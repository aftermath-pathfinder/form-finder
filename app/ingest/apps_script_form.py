"""Google Apps Script web apps (script.google.com/macros/...).

The page is drawn two sandboxed iframes deep and usually submits through JavaScript
(`google.script.run`), so it is read, and later submitted, in a real browser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import browser
from ..models import FormSchema, SourceKind
from .errors import IngestError
from .html_form import parse_html_form

if TYPE_CHECKING:
    from playwright.async_api import Page

SIGN_IN_FIRST = (
    "This form needs a Google sign-in. Click “Sign in to Google” in the left panel, sign in, close that "
    "window, then add the link again."
)


def is_apps_script(url: str) -> bool:
    return "script.google.com/macros" in url or "script.googleusercontent.com" in url


def parse_apps_script(html: str, url: str, form_id: str, title: str = "") -> FormSchema:
    """Parse the HTML of the frame that holds the form. `title` is the outer page's title."""
    form = parse_html_form(html, url, form_id, scripted=True)
    return form.model_copy(
        update={
            "kind": SourceKind.APPS_SCRIPT,
            "title": title or (form.title if form.title != url else "Apps Script form"),
            # The frame's form action is meaningless (submits go through JavaScript); keep how to find things.
            "submit": {k: form.submit[k] for k in ("selectors", "option_selectors", "option_values")},
        }
    )


async def read_apps_script(page: Page, url: str, form_id: str) -> FormSchema:
    """Open `url` in `page` and parse the frame with the most form controls."""
    await browser.goto(page, url)
    if browser.on_login_page(page.url):
        raise IngestError(SIGN_IN_FIRST)
    frame = await browser.find_form_frame(page)
    if frame is None:
        raise IngestError(
            "That Apps Script page loaded but has no form fields I can see. Check the link opens a form "
            "in your browser (and that it's shared with you)."
        )
    return parse_apps_script(await frame.content(), url, form_id, title=await page.title())
