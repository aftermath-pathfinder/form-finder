import json
from collections.abc import Callable
from io import BytesIO

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from app.llm import LLMProvider


class FakeLLM(LLMProvider):
    """Answers prompts with canned JSON. `handler(system, user_json) -> dict`."""

    def __init__(self, handler: Callable[[str, dict], dict]):
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    async def complete(self, messages, *, temperature=None):
        system, user = messages[0]["content"], json.loads(messages[1]["content"])
        self.calls.append((system, user))
        return json.dumps(self.handler(system, user))


def make_pdf(fields: list[str], checkbox: str | None = None) -> bytes:
    """Build a tiny fillable PDF with text fields (and optionally one checkbox)."""
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    annots, acro_fields = ArrayObject(), ArrayObject()

    def add(field: DictionaryObject):
        ref = w._add_object(field)
        annots.append(ref)
        acro_fields.append(ref)

    for i, name in enumerate(fields):
        add(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Widget"),
                    NameObject("/FT"): NameObject("/Tx"),
                    NameObject("/T"): TextStringObject(name),
                    NameObject("/Rect"): ArrayObject(
                        [NumberObject(50), NumberObject(700 - i * 40), NumberObject(300), NumberObject(720 - i * 40)]
                    ),
                    NameObject("/Ff"): NumberObject(2 if i == 0 else 0),  # first field required
                }
            )
        )
    if checkbox:
        add(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Widget"),
                    NameObject("/FT"): NameObject("/Btn"),
                    NameObject("/T"): TextStringObject(checkbox),
                    NameObject("/Rect"): ArrayObject(
                        [NumberObject(50), NumberObject(100), NumberObject(70), NumberObject(120)]
                    ),
                    NameObject("/AP"): DictionaryObject(
                        {
                            NameObject("/N"): DictionaryObject(
                                {NameObject("/Yes"): DictionaryObject(), NameObject("/Off"): DictionaryObject()}
                            )
                        }
                    ),
                }
            )
        )
    page[NameObject("/Annots")] = annots
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): acro_fields})
    out = BytesIO()
    w.write(out)
    return out.getvalue()


def make_docx(*paragraphs: str) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
