"""Apps Script via a real (headless) Chromium, against in-memory pages. No network: every
request is answered by `page.route` from the fixtures below."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest

from app.ingest.apps_script_form import read_apps_script
from app.submit import PageHasValues, SubmitError, _confirmed, submit_apps_script_page

pytest.importorskip("playwright")
from playwright.async_api import Error as PlaywrightError  # noqa: E402
from playwright.async_api import Page, async_playwright  # noqa: E402

URL = "https://script.google.com/macros/s/ABC/exec"
SANDBOX = "https://n-abc-0lu-script.googleusercontent.com/sandbox"
USER_HTML = "https://n-abc-0lu-script.googleusercontent.com/userCodeAppPanel"

# Apps Script nests the user's page: outer page -> sandbox frame -> userHtmlFrame.
OUTER = f'<html><head><title>Leave App</title></head><body><iframe src="{SANDBOX}"></iframe></body></html>'
MIDDLE = f'<html><body><iframe id="userHtmlFrame" src="{USER_HTML}"></iframe></body></html>'
FORM = """<html><body>
  <form id="leave" onsubmit="event.preventDefault(); send(this)">
    <label for="fullName">Full name</label><input id="fullName" required>
    <label for="start">Start date</label><input id="start" type="date">
    <label for="kind">Leave type</label>
    <select id="kind"><option value="">Pick one</option><option value="v">Vacation</option>
      <option value="s">Sick</option></select>
    <fieldset><legend>Half day?</legend>
      <label><input type="radio" name="half" value="am"> Morning</label>
      <label><input type="radio" name="half" value="pm"> Afternoon</label></fieldset>
    <label><input type="checkbox" name="notify" value="mgr"> Manager</label>
    <label><input type="checkbox" name="notify" value="hr"> HR</label>
    <textarea name="notes"></textarea>
    <button type="submit">Send request</button>
  </form>
  <p id="done"></p>
  <script>
    // Stands in for google.script.run: record what would have been sent.
    function send(f) {
      window.__submitted = {
        fullName: f.fullName.value, start: f.start.value, kind: f.kind.value,
        half: (f.querySelector('[name=half]:checked') || {}).value || null,
        notify: [...f.querySelectorAll('[name=notify]:checked')].map((x) => x.value),
        notes: f.notes.value,
      };
      document.getElementById("done").textContent = "Thanks!";
    }
  </script>
</body></html>"""


@asynccontextmanager
async def routed_page(pages: dict[str, str]) -> AsyncIterator[Page]:
    """A headless Chromium page where `pages` (url -> html) is the whole internet."""
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except PlaywrightError as e:
            pytest.skip(f"Chromium can't launch here: {e}")
        try:
            page = await browser.new_page()

            async def serve(route):
                html = pages.get(route.request.url.split("?")[0])
                if html is None:
                    await route.abort()
                else:
                    await route.fulfill(status=200, content_type="text/html", body=html)

            await page.route("**/*", serve)
            yield page
        finally:
            await browser.close()


def run(pages: dict[str, str], fn: Callable[[Page], Awaitable]):
    async def go():
        async with routed_page(pages) as page:
            return await fn(page)

    return asyncio.run(go())


APP = {URL: OUTER, SANDBOX: MIDDLE, USER_HTML: FORM}


def test_apps_script_parse_reads_the_nested_frame():
    form = run(APP, lambda page: read_apps_script(page, URL, "a1"))
    assert form.kind == "apps_script" and form.title == "Leave App" and form.source == URL
    by_id = {f.id: f for f in form.fields}
    assert list(by_id) == ["fullName", "start", "kind", "half", "notify", "notes"]
    assert by_id["fullName"].required and by_id["start"].type == "date"
    assert by_id["kind"].options == ["Vacation", "Sick"]
    assert by_id["half"].type == "choice" and by_id["half"].options == ["Morning", "Afternoon"]
    assert by_id["notify"].type == "checkbox"
    assert form.submit["selectors"]["fullName"] == '[id="fullName"]'  # id fallback
    assert form.submit["selectors"]["notes"] == '[name="notes"]'
    assert "action" not in form.submit


def test_apps_script_submit_fills_and_clicks():
    answers = {
        "fullName": "Ana Cruz",
        "start": "2026-10-09",
        "kind": "Sick",
        "half": "Afternoon",
        "notify": ["Manager", "HR"],
        "notes": "Back Monday",
    }

    async def go(page: Page):
        form = await read_apps_script(page, URL, "a1")
        msg = await submit_apps_script_page(page, form, answers)
        frame = page.frame(url=USER_HTML)
        return msg, await frame.evaluate("window.__submitted"), await frame.inner_text("#done")

    msg, submitted, done = run(APP, go)
    assert msg == "Submitted." and done == "Thanks!"
    assert submitted == {
        "fullName": "Ana Cruz",
        "start": "2026-10-09",
        "kind": "s",
        "half": "pm",
        "notify": ["mgr", "hr"],
        "notes": "Back Monday",
    }


def test_apps_script_submit_without_a_button_sends_nothing():
    no_button = FORM.replace('<button type="submit">Send request</button>', "")

    async def go(page: Page):
        form = await read_apps_script(page, URL, "a1")
        with pytest.raises(SubmitError, match="Submit button"):
            await submit_apps_script_page(page, form, {"fullName": "Ana"})
        return json.dumps(await page.frame(url=USER_HTML).evaluate("window.__submitted ?? null"))

    assert run({**APP, USER_HTML: no_button}, go) == "null"


def submit_with(form_html: str, answers: dict, reviewed: bool = False):
    """Ingest + submit against `form_html`; returns (message or SubmitError, what the page recorded)."""

    async def go(page: Page):
        form = await read_apps_script(page, URL, "a1")
        try:
            msg = await submit_apps_script_page(page, form, answers, page_values_reviewed=reviewed)
        except SubmitError as e:
            msg = e
        return msg, await page.frame(url=USER_HTML).evaluate("window.__submitted ?? null")

    return run({**APP, USER_HTML: form_html}, go)


PRESET = (
    FORM.replace('value="mgr">', 'value="mgr" checked>')
    .replace('value="am">', 'value="am" checked>')
    .replace('<textarea name="notes"></textarea>', '<textarea name="notes">Subscribe me</textarea>')
)


def test_apps_script_page_prefills_go_back_to_review_first():
    # The page pre-ticks "Manager", pre-selects "Morning", pre-fills notes. The user was asked none of it.
    msg, submitted = submit_with(PRESET, {"fullName": "Ana", "notify": ["HR"]})
    assert isinstance(msg, PageHasValues) and submitted is None  # nothing sent
    assert msg.values == {"half": ["Morning"], "notes": "Subscribe me"}  # "notify" was answered: user wins


def test_apps_script_after_review_sends_exactly_the_approved_answers():
    # On review the user kept "Morning" and cleared the notes.
    msg, submitted = submit_with(PRESET, {"fullName": "Ana", "notify": ["HR"], "half": "Morning"}, reviewed=True)
    assert msg == "Submitted."
    assert submitted["notify"] == ["hr"] and submitted["half"] == "am" and submitted["notes"] == ""


def test_apps_script_sees_values_set_by_page_scripts():
    scripted = FORM.replace("<script>", '<script>document.getElementById("fullName").value = "ana@example.com";', 1)
    msg, _ = submit_with(scripted, {"notes": "hi"})
    assert isinstance(msg, PageHasValues) and msg.values == {"fullName": "ana@example.com"}


def test_apps_script_fills_hidden_styled_dropdowns():
    hidden = FORM.replace('<select id="kind">', '<select id="kind" style="display:none">')
    msg, submitted = submit_with(hidden, {"fullName": "Ana", "kind": "Sick"})
    assert msg == "Submitted." and submitted["kind"] == "s"


def test_apps_script_success_message_mentioning_required_is_still_success():
    note = FORM.replace('textContent = "Thanks!"', 'textContent = "Request received. Manager approval is required."')
    msg, _ = submit_with(note, {"fullName": "Ana"})
    assert msg == "Submitted."


def test_apps_script_submit_refuses_when_the_page_says_a_field_is_invalid():
    # Full name is required on the page; the user left it empty.
    msg, submitted = submit_with(FORM, {"notes": "hi"})
    assert isinstance(msg, SubmitError) and "Full name" in str(msg) and "Nothing was sent" in str(msg)
    assert submitted is None


def test_apps_script_submit_does_not_claim_success_without_a_reaction():
    silent = FORM.replace('document.getElementById("done").textContent = "Thanks!";', "")
    msg, submitted = submit_with(silent, {"fullName": "Ana"})
    assert isinstance(msg, SubmitError) and "didn't confirm" in str(msg)  # answers kept for another try


def test_apps_script_submit_treats_an_error_message_as_failure():
    failing = FORM.replace('textContent = "Thanks!"', 'textContent = "Error: quota exceeded"')
    msg, _ = submit_with(failing, {"fullName": "Ana"})
    assert isinstance(msg, SubmitError)


def test_apps_script_leaves_hidden_and_readonly_fields_workable():
    extra = (
        '<input name="other" style="display:none">'  # conditional "Other: please specify" box
        '<input name="ref" value="REF-7" readonly>'  # the page owns this one
        '<button type="submit">'
    )
    page_html = FORM.replace('<button type="submit">', extra, 1).replace(
        "notes: f.notes.value,", "notes: f.notes.value, other: f.other.value, ref: f.ref.value,"
    )

    async def go(page: Page):
        form = await read_apps_script(page, URL, "a1")
        assert "ref" not in {f.id for f in form.fields}  # readonly: not asked, not touched
        msg = await submit_apps_script_page(page, form, {"fullName": "Ana"})  # "other" left empty
        return msg, await page.frame(url=USER_HTML).evaluate("window.__submitted")

    msg, submitted = run({**APP, USER_HTML: page_html}, go)
    assert msg == "Submitted." and submitted["ref"] == "REF-7" and submitted["other"] == ""


def test_apps_script_ignores_required_controls_outside_the_form():
    with_search = FORM.replace("<body>", '<body><input type="search" name="q" required>', 1)
    msg, submitted = submit_with(with_search, {"fullName": "Ana"})
    assert msg == "Submitted." and submitted["fullName"] == "Ana"


@pytest.mark.parametrize(
    "text,ok",
    [
        ("Thanks! Your request was received.", True),
        ("Request received. Manager approval is required.", True),
        ("Error: your request could not be saved.", False),
        ("Submission failed: not sent.", False),
        ("Invalid date. Nothing was submitted.", False),
        ("Error: quota exceeded", False),
        ("Error: request couldn't be saved", False),
        ("Not seeing your email? Your request was received", True),
        ("Thanks! Do not reply; we have received it.", True),
        ("Your request has been submitted and cannot be edited", True),
    ],
)
def test_confirmed_reads_the_new_text(text, ok):
    before = ("https://x/exec", "Leave form")
    assert _confirmed(before, ("https://x/exec", "Leave form\n" + text)) is ok


def test_confirmed_is_cautious_when_the_form_just_vanishes():
    assert _confirmed(("https://x/exec", "Leave form"), ("https://x/exec", None)) is False
    assert _confirmed(("https://x/exec", "Leave form"), ("https://x/done", None)) is True
