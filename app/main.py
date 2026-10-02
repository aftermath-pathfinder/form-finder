import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai
from .config import get_settings
from .fill import fill_docx, fill_pdf
from .ingest import IngestError, ingest_file, ingest_url
from .interview import Session, SessionStore
from .knowledge_base import KnowledgeBase
from .llm import LLMError, LLMProvider, get_provider
from .models import FormField, SourceKind
from .submit import SubmitError, submit_online

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class UrlIn(BaseModel):
    url: str


class MessageIn(BaseModel):
    message: str


class AnswersIn(BaseModel):
    answers: dict[str, Any]


def _question(f: FormField) -> dict[str, Any]:
    return {"id": f.id, "question": f.ask(), "type": f.type, "options": f.options, "required": f.required}


def _turn(s: Session, reply: str) -> dict[str, Any]:
    """What the chat UI needs after each step: either the next batch, or the review screen."""
    batch = s.next_batch()
    base = {"session_id": s.id, "form": s.form.summary()}
    if batch:
        return {**base, "stage": "asking", "reply": reply, "questions": [_question(f) for f in batch]}
    return {**base, "stage": "review", "reply": reply, **_review(s)}


def _review(s: Session) -> dict[str, Any]:
    return {
        "fields": [{**_question(f), "label": f.label, "value": s.answers.get(f.id)} for f in s.form.fields],
        "missing_required": [f.id for f in s.missing_required()],
        "action": "submit" if s.form.online else "download",
    }


def create_app(llm: LLMProvider | None = None, data_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Form Finder")
    app.state.llm = llm or get_provider(settings)
    app.state.kb = KnowledgeBase(data_dir or settings.data_dir)
    app.state.sessions = SessionStore()

    def kb(request: Request) -> KnowledgeBase:
        return request.app.state.kb

    def session(request: Request, sid: str) -> Session:
        s = request.app.state.sessions.get(sid)
        if s is None:
            raise HTTPException(404, "This request expired. Start again.")
        return s

    # ---- knowledge base -------------------------------------------------

    @app.get("/api/forms")
    def list_forms(request: Request):
        return [f.summary() for f in kb(request).all()]

    @app.get("/api/forms/{form_id}")
    def get_form(request: Request, form_id: str):
        form = kb(request).get(form_id)
        if form is None:
            raise HTTPException(404, "Form not found.")
        return form.model_dump()

    @app.post("/api/forms/url")
    async def add_form_url(request: Request, body: UrlIn):
        try:
            form = await ingest_url(body.url.strip())
        except IngestError as e:
            raise HTTPException(422, str(e)) from e
        form = await ai.enrich_form(request.app.state.llm, form)
        kb(request).save(form)
        return form.summary()

    @app.post("/api/forms/upload")
    async def add_form_file(request: Request, file: UploadFile = File(...)):
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File is larger than 20 MB.")
        try:
            form = ingest_file(file.filename or "upload", data)
        except IngestError as e:
            raise HTTPException(422, str(e)) from e
        form = await ai.enrich_form(request.app.state.llm, form)
        kb(request).save(form, template=data)
        return form.summary()

    @app.delete("/api/forms/{form_id}")
    def delete_form(request: Request, form_id: str):
        if not kb(request).delete(form_id):
            raise HTTPException(404, "Form not found.")
        return {"ok": True}

    # ---- chat -----------------------------------------------------------

    @app.post("/api/chat")
    async def start(request: Request, body: MessageIn):
        llm = request.app.state.llm
        forms = kb(request).all()
        try:
            form_id, reason = await ai.match_form(llm, body.message, forms)
        except LLMError as e:
            raise HTTPException(502, str(e)) from e
        if form_id is None:
            return {"stage": "no_match", "reply": reason or "I couldn't find a form for that request."}

        s = request.app.state.sessions.add(Session(form=kb(request).get(form_id)))
        # Grab anything already in the request ("leave next Friday") so we don't ask for it.
        try:
            answers, skipped = await ai.extract_answers(llm, s.form, s.form.fields, body.message)
            s.apply(answers, skipped)
        except LLMError:
            pass
        reply = f"This looks like **{s.form.title}**. {reason}".strip()
        return _turn(s, reply)

    @app.post("/api/chat/{sid}")
    async def answer(request: Request, sid: str, body: MessageIn):
        s = session(request, sid)
        # Let the user answer anything still open, not just the current batch.
        try:
            answers, skipped = await ai.extract_answers(request.app.state.llm, s.form, s.unanswered(), body.message)
        except LLMError as e:
            raise HTTPException(502, str(e)) from e
        rejected = s.apply(answers, skipped)
        reply = "Got it."
        if rejected:
            labels = ", ".join(s.form.field(r).label for r in rejected)
            reply = f"Got it, but these didn't match what the form accepts: {labels}."
        return _turn(s, reply)

    @app.get("/api/chat/{sid}/review")
    def review(request: Request, sid: str):
        s = session(request, sid)
        return {"session_id": s.id, "form": s.form.summary(), "stage": "review", **_review(s)}

    @app.put("/api/chat/{sid}/answers")
    def edit_answers(request: Request, sid: str, body: AnswersIn):
        s = session(request, sid)
        for fid, value in body.answers.items():
            if value in (None, "", []):
                s.answers.pop(fid, None)
        rejected = s.apply({k: v for k, v in body.answers.items() if v not in (None, "", [])}, [])
        return {"session_id": s.id, "form": s.form.summary(), "stage": "review", "rejected": rejected, **_review(s)}

    @app.post("/api/chat/{sid}/submit")
    async def submit(request: Request, sid: str):
        """The user's approval. Online forms are submitted; files are filled and downloaded."""
        s = session(request, sid)
        missing = s.missing_required()
        if missing:
            raise HTTPException(422, "Still missing: " + ", ".join(f.label for f in missing))

        if s.form.online:
            try:
                msg = await submit_online(s.form, s.answers)
            except SubmitError as e:
                raise HTTPException(502, str(e)) from e
            request.app.state.sessions.drop(s.id)
            return {"stage": "done", "reply": msg}

        template = kb(request).template(s.form.id)
        if s.form.kind == SourceKind.PDF:
            content, media, ext = fill_pdf(template, s.form, s.answers), "application/pdf", ".pdf"
        else:
            content = fill_docx(template, s.form, s.answers)
            media, ext = "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
        request.app.state.sessions.drop(s.id)
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(s.form.source).stem) + "-filled" + ext
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ---- frontend -------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
