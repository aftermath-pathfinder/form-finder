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
from .ingest.apps_script_form import SIGN_IN_TO_SUBMIT
from .ingest.html_form import css_attr, hidden_inputs, pick_form
from .models import FormSchema, SourceKind

if TYPE_CHECKING:
    from playwright.async_api import Frame, Locator, Page

_FIELD_TIMEOUT_MS = 5_000
# Button labels that mean "send this form" (not "send me a copy" or "resend code").
_SUBMIT_TEXT = re.compile(r"^\W*(submit|send)\b(?!.*\b(copy|code|again|me)\b)", re.I)


class SubmitError(RuntimeError):
    """The form wasn't submitted. The message is shown to the user as-is."""


class PageHasValues(SubmitError):
    """The live page pre-fills fields the user wasn't asked about. Nothing was sent.

    `values` (field id -> value) go back to the review screen, held in memory only, so the user
    approves them explicitly instead of them being silently sent or wiped.
    """

    def __init__(self, values: dict[str, Any]):
        super().__init__("The form already had some answers filled in. Check them below and approve again.")
        self.values = values


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


# Fallback for controls a real click can't reach (visually hidden custom controls) and for
# clearing radios, which can't be "unclicked".
_SET_CHECKED_JS = """(el, on) => {
  if (el.checked === on) return;
  el.checked = on;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}"""
# Sets a text/select value without needing the control to be visible or editable.
_SET_VALUE_JS = """(el, v) => {
  if (el.value === v) return;
  el.value = v;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}"""
# Controls the browser itself considers invalid, limited to the form being submitted (the <form>
# around our fields, or just our fields when the page has no <form>).
_INVALID_JS = """(sels) => {
  const ours = sels.map((s) => document.querySelector(s)).filter(Boolean);
  const form = ours.length ? ours[0].closest("form") : null;
  const controls = form ? [...form.elements] : ours;
  return controls.filter((e) => e.willValidate && !e.checkValidity()).map((e) => e.name || e.id || "");
}"""
_PAGE_TEXT_JS = "() => document.body ? document.body.innerText : ''"
# Words that mean the submit failed, unless a success word is also there
# ("Request received. Manager approval is required." is a success).
_PROBLEM_TEXT = re.compile(r"\b(error|invalid|failed|is required|required field|could not|couldn't)\b", re.I)
_SUCCESS_TEXT = re.compile(r"\b(thank|received|submitted|success|recorded|sent|saved)", re.I)
# Live value of each field as the page has it now, including values page scripts set after load.
_LIVE_VALUES_JS = """([selectors, optionSelectors]) => {
  const out = {};
  for (const [id, sel] of Object.entries(selectors)) {
    const opts = optionSelectors[id];
    if (opts) {
      const on = Object.entries(opts).filter(([, s]) => document.querySelector(s)?.checked).map(([t]) => t);
      if (on.length) out[id] = on;
      continue;
    }
    const el = document.querySelector(sel);
    if (!el || el.readOnly || el.disabled) continue;
    if (el.tagName === "SELECT") {
      const o = el.selectedOptions[0];
      if (o && o.value) out[id] = o.textContent.trim();
    } else if (el.value) {
      out[id] = el.value;
    }
  }
  return out;
}"""


async def _set_checked(box: Locator, on: bool) -> None:
    from playwright.async_api import Error as PlaywrightError

    is_radio = await box.evaluate("el => el.type === 'radio'")
    if await box.is_visible() and (on or not is_radio):
        try:
            await box.set_checked(on, timeout=_FIELD_TIMEOUT_MS)  # a real click, so page scripts react
            return
        except PlaywrightError:
            pass
    await box.evaluate(_SET_CHECKED_JS, on)


async def fill_frame(frame: Frame, form: FormSchema, answers: dict[str, Any]) -> None:
    """Make every field on the page match the reviewed answers exactly.

    The review screen started from what the page pre-filled, so anything the user cleared or
    unticked there is cleared or unticked here too; nothing is sent that they didn't see.
    """
    from playwright.async_api import Error as PlaywrightError

    selectors: dict[str, str] = form.submit.get("selectors", {})
    option_selectors: dict[str, dict[str, str]] = form.submit.get("option_selectors", {})
    for f in form.fields:
        v = answers.get(f.id)
        values = [] if v is None or v is False else [str(x) for x in (v if isinstance(v, list) else [v])]
        field = frame.locator(selectors.get(f.id) or css_attr("name", f.id)).first
        try:
            if f.id in option_selectors:
                options = option_selectors[f.id]
                if any(text not in options for text in values):
                    raise SubmitError(
                        f"An answer for “{f.label}” no longer matches the form's options, so nothing was sent. "
                        "Edit it and approve again."
                    )
                for text, sel in options.items():
                    await _set_checked(frame.locator(sel).first, text in values)
            elif await field.evaluate("el => el.readOnly || el.disabled"):
                continue  # the page owns it (older schemas may still list such fields)
            elif f.type == "dropdown" and values:
                if await field.is_visible():
                    await field.select_option(label=values, timeout=_FIELD_TIMEOUT_MS)
                else:  # styled dropdowns (e.g. Materialize) hide the real <select>
                    value = form.submit.get("option_values", {}).get(f.id, {}).get(values[0], values[0])
                    await field.evaluate(_SET_VALUE_JS, value)
            elif not values:
                await field.evaluate(_SET_VALUE_JS, "")  # clearing never needs the field to be visible
            elif await field.is_visible() and await field.is_editable():
                await field.fill(", ".join(values), timeout=_FIELD_TIMEOUT_MS)
            else:
                await field.evaluate(_SET_VALUE_JS, ", ".join(values))
        except PlaywrightError as e:
            raise SubmitError(
                f"Couldn't fill “{f.label}” on the page, so nothing was sent. "
                "Open the form yourself and submit it there."
            ) from e


async def find_submit_button(frame: Frame, near: str | None = None) -> Locator | None:
    """The visible submit control, preferring one inside the same <form> as the field `near`."""
    scopes = []
    if near:
        scopes.append(frame.locator("form").filter(has=frame.locator(near)).first)
    scopes.append(frame.locator(":root"))
    for scope in scopes:
        for loc in (
            scope.locator("button[type=submit], input[type=submit]"),
            scope.get_by_role("button", name=_SUBMIT_TEXT),
        ):
            visible = loc.filter(visible=True)
            if await visible.count():
                return visible.first
    return None


async def _page_state(page: Page, frame: Frame) -> tuple[str, str | None]:
    """Page URL and the form frame's visible text (None once the frame is gone)."""
    from playwright.async_api import Error as PlaywrightError

    if frame.is_detached():
        return page.url, None
    try:
        return page.url, await frame.evaluate(_PAGE_TEXT_JS)
    except PlaywrightError:  # navigated away mid-read
        return page.url, None


def _confirmed(before: tuple[str, str | None], after: tuple[str, str | None]) -> bool:
    """Did the page react like a successful submit? Moved on, or showed new text that isn't an error."""
    if browser.on_login_page(after[0]):
        return False
    if after[0] != before[0] or after[1] is None:
        return True
    old = set((before[1] or "").splitlines())
    added = "\n".join(line for line in after[1].splitlines() if line.strip() and line not in old)
    if not added:
        return False
    return bool(_SUCCESS_TEXT.search(added)) or not _PROBLEM_TEXT.search(added)


async def submit_apps_script_page(
    page: Page, form: FormSchema, answers: dict[str, Any], *, page_values_reviewed: bool = False
) -> str:
    """Open the form in `page`, fill it, check the page accepts it, click submit, and confirm a reaction.

    Anything short of a clear success raises `SubmitError`, so the session (and the user's answers)
    is kept for another try. The first time, if the live page pre-fills fields the user wasn't asked
    about, `PageHasValues` sends them to the review screen instead of sending or wiping them.
    """
    await browser.goto(page, form.source)
    if browser.on_login_page(page.url):
        raise SubmitError(SIGN_IN_TO_SUBMIT)
    frame = await browser.find_form_frame(page)
    if frame is None:
        raise SubmitError(
            "Couldn't find the form on the Apps Script page, so nothing was sent. Check the link still "
            "opens in your browser."
        )
    if not page_values_reviewed:
        live = await frame.evaluate(
            _LIVE_VALUES_JS, [form.submit.get("selectors", {}), form.submit.get("option_selectors", {})]
        )
        unseen = {fid: v for fid, v in live.items() if fid not in answers}
        if unseen:
            raise PageHasValues(unseen)
    await fill_frame(frame, form, answers)

    ours = list(form.submit.get("selectors", {}).values())
    invalid = await frame.evaluate(_INVALID_JS, ours)
    if invalid:
        known = [f.label for i in dict.fromkeys(invalid) if (f := form.field(i))]
        if len(known) == len(set(invalid)):
            raise SubmitError(
                f"The form says these are missing or invalid: {', '.join(known)}. Nothing was sent; fix them on "
                "the review screen and approve again."
            )
        raise SubmitError(
            "The form wants something I can't fill from here, so nothing was sent. Open the form yourself and "
            "submit it there."
        )

    button = await find_submit_button(frame, near=ours[0] if ours else None)
    if button is None:
        raise SubmitError(
            "Couldn't find the form's Submit button, so nothing was sent. Open the form yourself and submit it there."
        )
    before = await _page_state(page, frame)
    await button.click(timeout=_FIELD_TIMEOUT_MS)
    await browser.settle(page)
    if not _confirmed(before, await _page_state(page, frame)):
        raise SubmitError(
            "I clicked Submit, but the page didn't confirm it went through. Check the form in your browser "
            "before trying again; your answers are still here."
        )
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
        raise SubmitError(
            f"The form rejected the submission (HTTP {resp.status}). Open the form yourself and submit it there."
        )
    return "Submitted."


async def _submit_in_browser(
    form: FormSchema, answers: dict[str, Any], profile: Path | None, page_values_reviewed: bool
) -> str:
    try:
        async with browser.browser_context(profile) as context:
            if form.kind == SourceKind.APPS_SCRIPT:
                return await submit_apps_script_page(
                    await context.new_page(), form, answers, page_values_reviewed=page_values_reviewed
                )
            return await post_signed_in_google_form(context.request, form, answers)
    except browser.BrowserError as e:
        raise SubmitError(str(e)) from e


# ---- dispatch ------------------------------------------------------------


async def submit_online(
    form: FormSchema,
    answers: dict[str, Any],
    browser_profile: Path | None = None,
    *,
    page_values_reviewed: bool = False,
) -> str:
    """Submit and return a short confirmation message.

    `browser_profile` is the saved Google login for browser-only forms (default: from settings).
    """
    if form.kind == SourceKind.APPS_SCRIPT or (
        form.kind == SourceKind.GOOGLE_FORM and form.submit.get("requires_login")
    ):
        return await _submit_in_browser(form, answers, browser_profile, page_values_reviewed)

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
