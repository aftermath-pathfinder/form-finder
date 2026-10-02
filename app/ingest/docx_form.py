import re
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph

from ..models import FormField, FormSchema, SourceKind
from .errors import IngestError

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def iter_paragraphs(doc) -> Iterator[Paragraph]:
    """Every paragraph in the body, tables (nested) and headers/footers."""

    def walk(container):
        yield from container.paragraphs
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from walk(cell)

    yield from walk(doc)
    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from walk(part)


def parse_docx(data: bytes, filename: str, form_id: str) -> FormSchema:
    try:
        doc = Document(BytesIO(data))
    except Exception as e:
        raise IngestError(f"Couldn't read that Word file: {e}") from e

    names: list[str] = []
    for p in iter_paragraphs(doc):
        for name in PLACEHOLDER_RE.findall(p.text):
            if name not in names:
                names.append(name)

    if not names:
        raise IngestError(
            "No fields found. Mark the blanks in your Word template with double braces, "
            "e.g. {{Full name}} or {{Date of leave}}."
        )

    title = doc.core_properties.title or Path(filename).stem
    return FormSchema(
        id=form_id,
        title=title,
        kind=SourceKind.DOCX,
        source=filename,
        fields=[FormField(id=n, label=n, required=True) for n in names],
    )
