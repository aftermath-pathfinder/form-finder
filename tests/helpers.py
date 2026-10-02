import json
from collections.abc import Callable
from io import BytesIO

from docx import Document
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

Handler = Callable[[str, dict], dict]


def fake_model(handler: Handler) -> FunctionModel:
    """A Pydantic AI model that answers with canned JSON: `handler(instructions, prompt_json) -> dict`.

    Tests never call a real AI. The handler sees the agent's instructions (to tell agents apart)
    and the JSON prompt the app sent.
    """

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        return ModelResponse(parts=[TextPart(json.dumps(handler(info.instructions or "", json.loads(prompt))))])

    return FunctionModel(respond)


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
