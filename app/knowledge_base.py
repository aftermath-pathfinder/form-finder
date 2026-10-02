from pathlib import Path

from .models import FormSchema


class KnowledgeBase:
    """Forms the assistant knows about, stored as JSON next to their template files.

    Only blank templates and their parsed questions are stored here, never answers.
    """

    def __init__(self, data_dir: Path):
        self.forms_dir = data_dir / "forms"
        self.files_dir = data_dir / "files"
        self.forms_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def save(self, form: FormSchema, template: bytes | None = None) -> None:
        (self.forms_dir / f"{form.id}.json").write_text(form.model_dump_json(indent=2))
        if template is not None:
            (self.files_dir / form.id).write_bytes(template)

    def get(self, form_id: str) -> FormSchema | None:
        if not form_id.isalnum():
            return None
        path = self.forms_dir / f"{form_id}.json"
        if not path.is_file():
            return None
        return FormSchema.model_validate_json(path.read_text())

    def template(self, form_id: str) -> bytes:
        return (self.files_dir / form_id).read_bytes()

    def all(self) -> list[FormSchema]:
        return [FormSchema.model_validate_json(p.read_text()) for p in sorted(self.forms_dir.glob("*.json"))]

    def delete(self, form_id: str) -> bool:
        if not form_id.isalnum():
            return False
        existed = False
        for path in (self.forms_dir / f"{form_id}.json", self.files_dir / form_id):
            if path.is_file():
                path.unlink()
                existed = True
        return existed
