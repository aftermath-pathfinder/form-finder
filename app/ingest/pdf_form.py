import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from ..models import FormField, FormSchema, SourceKind
from .errors import IngestError

_RADIO_FLAG = 1 << 15
_REQUIRED_FLAG = 1 << 1


def _pretty(name: str) -> str:
    name = name.split(".")[-1]
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return name.strip().capitalize() or "Field"


def parse_pdf(data: bytes, filename: str, form_id: str) -> FormSchema:
    try:
        reader = PdfReader(BytesIO(data))
        raw_fields = reader.get_fields() or {}
    except Exception as e:
        raise IngestError(f"Couldn't read that PDF: {e}") from e

    fields: list[FormField] = []
    on_values: dict[str, str] = {}
    for name, f in raw_fields.items():
        ftype = f.get("/FT")
        if ftype is None or ftype == "/Sig":
            continue  # parent containers and signature boxes
        flags = int(f.get("/Ff", 0) or 0)
        label = str(f.get("/TU") or _pretty(name))
        required = bool(flags & _REQUIRED_FLAG)

        if ftype == "/Btn":
            states = [str(s) for s in f.get("/_States_", []) if str(s) != "/Off"]
            if flags & _RADIO_FLAG:
                fields.append(
                    FormField(
                        id=name, label=label, type="choice", required=required, options=[s.lstrip("/") for s in states]
                    )
                )
            else:
                on_values[name] = states[0] if states else "/Yes"
                fields.append(FormField(id=name, label=label, type="boolean", required=required))
        elif ftype == "/Ch":
            opts = [o[-1] if isinstance(o, list) else o for o in f.get("/Opt", [])]
            fields.append(
                FormField(id=name, label=label, type="dropdown", required=required, options=[str(o) for o in opts])
            )
        else:
            fields.append(FormField(id=name, label=label, type="text", required=required))

    if not fields:
        raise IngestError(
            "This PDF has no fillable fields. Scanned/flat PDFs aren't supported yet; "
            "try a fillable version of the form."
        )

    title = (reader.metadata.title if reader.metadata and reader.metadata.title else None) or Path(filename).stem
    return FormSchema(
        id=form_id,
        title=str(title),
        kind=SourceKind.PDF,
        source=filename,
        fields=fields,
        submit={"on_values": on_values},
    )
