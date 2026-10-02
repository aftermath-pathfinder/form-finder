import uuid
from pathlib import Path

import httpx

from ..models import FormSchema
from .docx_form import parse_docx
from .errors import IngestError
from .google_form import is_google_form, parse_google_form
from .html_form import parse_html_form
from .pdf_form import parse_pdf

__all__ = ["IngestError", "ingest_url", "ingest_file", "new_form_id", "BROWSER_HEADERS"]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
}


def new_form_id() -> str:
    return uuid.uuid4().hex[:12]


def _is_apps_script(url: str) -> bool:
    return "script.google.com/macros" in url or "script.googleusercontent.com" in url


async def ingest_url(url: str) -> FormSchema:
    if _is_apps_script(url):
        # These render inside a sandboxed iframe, so a plain fetch sees no form.
        raise IngestError(
            "Google Apps Script web apps need a real browser to read. That's on the roadmap "
            "(Playwright); for now, add Google Forms, regular web forms, PDFs or Word files."
        )
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=BROWSER_HEADERS) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise IngestError(f"Couldn't open that link: {e}") from e

    final_url = str(resp.url)
    if "accounts.google.com" in final_url:
        raise IngestError(
            "That form requires Google sign-in. Sign-in support is on the roadmap; public forms work today."
        )
    if resp.status_code >= 400:
        raise IngestError(f"That link returned HTTP {resp.status_code}.")

    if is_google_form(final_url):
        return parse_google_form(resp.text, final_url, new_form_id())
    return parse_html_form(resp.text, final_url, new_form_id())


def ingest_file(filename: str, data: bytes) -> FormSchema:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(data, filename, new_form_id())
    if ext == ".docx":
        return parse_docx(data, filename, new_form_id())
    raise IngestError("Only .pdf and .docx uploads are supported.")
