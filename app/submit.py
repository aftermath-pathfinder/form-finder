"""Submit answers to online forms."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from . import browser
from .ingest import BROWSER_HEADERS
from .ingest.apps_script_form import SIGN_IN_FIRST
from .ingest.html_form import css_attr, hidden_inputs, pick_form
from .models import FormSchema, SourceKind

if TYPE_CHECKING:
    from playwright.async_api import Frame, Locator, Page

_FIELD_TIMEOUT_MS = 5_000
_SUBMIT_TEXT = re.compile(r"submit|send", re.I)


class SubmitError(RuntimeError):
    """The form wasn't submitted. The message is shown to the user as-is."""


def google_form_payload(form: FormSchema, answers: dict[str, Any]) -> list[tuple[str, str]]:
    data: list[tuple[str, str]] = []
    for f in form.fields:
        v = answers.get(f.id)
        if v is None:
            continue
        if f.type == "date":
            y, m, d = str(v).split("-")
            data += [(f"{f.id}_year", y), (f"{f.id}_month", m), (f"{f.id}_day", d)]
        elif f.type == "time":
            h, mi = str(v).split(":")
            data += [(f"{f.id}_hour", h), (f"{f.id}_minute", mi)]
        elif isinstance(v, list):
            data += [(f.id, str(x)) for x in v]
        else:
            data.append((f.id, str(v)))
    pages = int(form.submit.get("pages", 1))
    data.append(("pageHistory", ",".join(str(i) for i in range(pages))))
    return data


def google_prefill_url(form: FormSchema, answers: dict[str, Any]) -> str:
    """A link that opens the Google Form with answers already filled in.

    The user submits it themselves in their own browser, so it works for forms that need
    Google sign-in without this app ever touching their account.
    """
    data: list[tuple[str, str]] = [("usp", "pp_url")]
    for f in form.fields:
        v = answers.get(f.id)
        if v is None:
            continue
        data += [(f.id, str(x)) for x in v] if isinstance(v, list) else [(f.id, str(v))]
    viewform = form.submit["action"].removesuffix("/formResponse") + "/viewform"
    return f"{viewform}?{urlencode(data)}"


def html_form_payload(form: FormSchema, answers: dict[str, Any], hidden: dict[str, str]) -> list[tuple[str, str]]:
    option_values = form.submit.get("option_values", {})
    data: list[tuple[str, str]] = list(hidden.items())
    for f in form.fields:
        v = answers.get(f.id)
        if v is None or v is False:
            continue
        values = v if isinstance(v, list) else [v]
        for x in values:
            x = str(x)
            data.append((f.id, option_values.get(f.id, {}).get(x, x)))
    return data


# ---- browser: Apps Script ------------------------------------------------


async def fill_frame(frame: Frame, form: FormSchema, answers: dict[str, Any]) -> None:
    """Type/select/tick each answered field, located the way the ingester recorded it."""
    from playwright.async_api import Error as PlaywrightError

    selectors: dict[str, str] = form.submit.get("selectors", {})
    option_selectors: dict[str, dict[str, str]] = form.submit.get("option_selectors", {})
    for f in form.fields:
        v = answers.get(f.id)
        if v is None or v is False:
            continue
        values = [str(x) for x in (v if isinstance(v, list) else [v])]
        field = frame.locator(selectors.get(f.id) or css_attr("name", f.id)).first
        try:
            if f.type in ("choice", "checkbox") and f.id in option_selectors:
                for text in values:
                    sel = option_selectors[f.id].get(text)
                    if sel is None:
                        raise SubmitError(f"“{text}” isn't an option for “{f.label}” any more. Edit it and retry.")
                    await frame.locator(sel).first.check(timeout=_FIELD_TIMEOUT_MS)
            elif f.type == "dropdown":
                await field.select_option(label=values, timeout=_FIELD_TIMEOUT_MS)
            else:
                await field.fill(", ".join(values), timeout=_FIELD_TIMEOUT_MS)
        except PlaywrightError as e:
            raise SubmitError(
                f"Couldn't fill “{f.label}” on the page, so nothing was sent. The form may have changed; "
                "remove it from the knowledge base and add the link again."
            ) from e


async def find_submit_button(frame: Frame) -> Locator | None:
    candidates = (
        frame.locator("button[type=submit], input[type=submit]"),
        frame.get_by_role("button", name=_SUBMIT_TEXT),
    )
    for loc in candidates:
        visible = loc.filter(visible=True)
        if await visible.count():
            return visible.first
    return None


async def submit_apps_script_page(page: Page, form: FormSchema, answers: dict[str, Any]) -> str:
    """Open the form in `page`, fill it, click its submit control and wait for the page to settle."""
    await browser.goto(page, form.source)
    if browser.on_login_page(page.url):
        raise SubmitError(SIGN_IN_FIRST.replace("add the link again", "approve again"))
    frame = await browser.find_form_frame(page)
    if frame is None:
        raise SubmitError(
            "Couldn't find the form on the Apps Script page, so nothing was sent. Check the link still "
            "opens in your browser."
        )
    await fill_frame(frame, form, answers)
    button = await find_submit_button(frame)
    if button is None:
        raise SubmitError(
            "Couldn't find the form's Submit button, so nothing was sent. Open the form yourself and submit it there."
        )
    await button.click()
    await browser.settle(page)
    return "Submitted."


# ---- browser: sign-in Google Forms ---------------------------------------


class _Poster(Protocol):
    async def post(self, url: str, **kwargs: Any) -> Any: ...


async def post_signed_in_google_form(request: _Poster, form: FormSchema, answers: dict[str, Any]) -> str:
    """POST through a browser context's request API, which carries the Google login cookies."""
    resp = await request.post(
        form.submit["action"],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode(google_form_payload(form, answers)),
    )
    if browser.on_login_page(resp.url):
        raise SubmitError(
            "Your Google sign-in has expired, so the form wasn't submitted. Click “Sign in to Google”, "
            "then approve again."
        )
    if resp.status >= 400:
        raise SubmitError(f"The form rejected the submission (HTTP {resp.status}).")
    return "Submitted."


async def _submit_in_browser(form: FormSchema, answers: dict[str, Any], profile: Path | None) -> str:
    try:
        async with browser.browser_context(profile) as context:
            if form.kind == SourceKind.APPS_SCRIPT:
                return await submit_apps_script_page(await context.new_page(), form, answers)
            return await post_signed_in_google_form(context.request, form, answers)
    except browser.BrowserError as e:
        raise SubmitError(str(e)) from e


# ---- dispatch ------------------------------------------------------------


async def submit_online(form: FormSchema, answers: dict[str, Any], browser_profile: Path | None = None) -> str:
    """Submit and return a short confirmation message.

    `browser_profile` is the saved Google login for browser-only forms (default: from settings).
    """
    if form.kind == SourceKind.APPS_SCRIPT or (
        form.kind == SourceKind.GOOGLE_FORM and form.submit.get("requires_login")
    ):
        return await _submit_in_browser(form, answers, browser_profile)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=BROWSER_HEADERS) as client:
        if form.kind == SourceKind.GOOGLE_FORM:
            resp = await client.post(form.submit["action"], data=google_form_payload(form, answers))
        elif form.kind == SourceKind.HTML_FORM:
            # Reload the page for fresh hidden inputs (CSRF tokens) and cookies.
            page = await client.get(form.source)
            hidden = hidden_inputs(pick_form(BeautifulSoup(page.text, "html.parser")))
            data = html_form_payload(form, answers, hidden)
            if form.submit.get("method") == "post":
                resp = await client.post(form.submit["action"], data=data)
            else:
                resp = await client.get(form.submit["action"], params=data)
        else:
            raise SubmitError(f"Submitting {form.kind.value} forms isn't supported yet.")

    if "accounts.google.com" in str(resp.url):
        raise SubmitError("The form asked for Google sign-in, so it wasn't submitted.")
    if resp.status_code >= 400:
        raise SubmitError(f"The form rejected the submission (HTTP {resp.status_code}).")
    return "Submitted."
