import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from .. import browser
from ..models import FormSchema
from .apps_script_form import is_apps_script, read_apps_script
from .docx_form import parse_docx
from .errors import IngestError
from .google_form import is_google_form, parse_google_form, read_signed_in_google_form
from .html_form import parse_html_form
from .pdf_form import parse_pdf

__all__ = ["IngestError", "ingest_url", "ingest_file", "new_form_id", "BROWSER_HEADERS"]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
}


def new_form_id() -> str:
    return uuid.uuid4().hex[:12]


async def _in_browser(
    read: Callable[[Any, str, str], Awaitable[FormSchema]], url: str, profile: Path | None
) -> FormSchema:
    """Run `read(page, url, form_id)` in a headless browser carrying the saved Google login."""
    try:
        async with browser.browser_context(profile) as context:
            return await read(await context.new_page(), url, new_form_id())
    except browser.BrowserError as e:
        raise IngestError(str(e)) from e


async def ingest_url(url: str, browser_profile: Path | None = None) -> FormSchema:
    """`browser_profile` is the saved Google login used for browser-only forms (default: from settings)."""
    if is_apps_script(url):
        # Drawn inside sandboxed iframes, so a plain fetch sees no form.
        return await _in_browser(read_apps_script, url, browser_profile)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=BROWSER_HEADERS) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise IngestError(f"Couldn't open that link: {e}") from e

    final_url = str(resp.url)
    if browser.on_login_page(final_url):
        if not (is_google_form(url) or is_google_form(final_url)):
            raise IngestError("That page needs a sign-in Form Finder can't do. Public forms and Google Forms work.")
        return await _in_browser(read_signed_in_google_form, url, browser_profile)
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
