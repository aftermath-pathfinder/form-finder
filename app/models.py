from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    GOOGLE_FORM = "google_form"
    HTML_FORM = "html_form"
    APPS_SCRIPT = "apps_script"
    PDF = "pdf"
    DOCX = "docx"


ONLINE_KINDS = {SourceKind.GOOGLE_FORM, SourceKind.HTML_FORM, SourceKind.APPS_SCRIPT}

FieldType = Literal[
    "text",
    "paragraph",
    "email",
    "number",
    "date",
    "time",
    "choice",
    "dropdown",
    "checkbox",
    "boolean",
    "scale",
]


class FormField(BaseModel):
    id: str  # key used when filling/submitting (e.g. "entry.123", PDF field name)
    label: str
    type: FieldType = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    help: str = ""
    question: str = ""  # natural-language question written by the AI at ingest time
    # What the page itself pre-fills (text, pre-selected option, pre-ticked boxes). Starts as the
    # answer, so the review screen shows it and nothing is silently kept or wiped.
    default: str | list[str] | None = None

    def ask(self) -> str:
        return self.question or self.label


class FormSchema(BaseModel):
    id: str
    title: str
    description: str = ""
    purpose: str = ""  # AI-written "what is this form for", used to match requests
    kind: SourceKind
    source: str  # URL for online forms, original filename for uploads
    fields: list[FormField]
    # Kind-specific details needed to submit/fill (action URL, hidden inputs, ...).
    submit: dict[str, Any] = Field(default_factory=dict)

    @property
    def online(self) -> bool:
        return self.kind in ONLINE_KINDS

    def field(self, field_id: str) -> FormField | None:
        return next((f for f in self.fields if f.id == field_id), None)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.purpose or self.description,
            "kind": self.kind.value,
            "source": self.source,
            "field_count": len(self.fields),
        }
