"""Write answers into PDF/DOCX templates. Output stays in memory, never on disk."""

from io import BytesIO
from typing import Any

from docx import Document
from pypdf import PdfReader, PdfWriter

from .ingest.docx_form import PLACEHOLDER_RE, iter_paragraphs
from .models import FormSchema


def fill_pdf(template: bytes, form: FormSchema, answers: dict[str, Any]) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(template)))
    on_values = form.submit.get("on_values", {})
    values: dict[str, Any] = {}
    for f in form.fields:
        if f.id not in answers:
            continue
        v = answers[f.id]
        if f.type == "boolean":
            values[f.id] = on_values.get(f.id, "/Yes") if v else "/Off"
        elif f.type == "choice":
            values[f.id] = "/" + str(v)  # radio buttons take their state name
        else:
            values[f.id] = str(v)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    writer.set_need_appearances_writer(True)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def fill_docx(template: bytes, form: FormSchema, answers: dict[str, Any]) -> bytes:
    doc = Document(BytesIO(template))

    def sub(m):
        v = answers.get(m.group(1))
        if v is None:
            return "____________"
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

    for p in iter_paragraphs(doc):
        if "{{" not in p.text:
            continue
        new = PLACEHOLDER_RE.sub(sub, p.text)
        if new != p.text and p.runs:
            # Word often splits "{{Name}}" across runs; collapse into the first run,
            # keeping its formatting.
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
