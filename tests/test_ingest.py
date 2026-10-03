import asyncio
import json
import sys
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qsl

import pytest
from docx import Document
from pypdf import PdfReader

from app.fill import fill_docx, fill_pdf
from app.ingest import IngestError, ingest_file, ingest_url
from app.ingest.google_form import form_response_url, parse_google_form
from app.ingest.html_form import parse_html_form
from app.submit import (
    SubmitError,
    google_form_payload,
    google_prefill_url,
    html_form_payload,
    post_signed_in_google_form,
    submit_online,
)
from tests.helpers import make_docx, make_pdf


def google_form_html() -> str:
    items = [
        [1, "Full name", None, 0, [[111, None, 1]]],
        [2, "Leave type", "Pick one", 2, [[222, [["Vacation"], ["Sick"], ["Emergency"]], 1]]],
        [3, None, None, 8, None],  # page break
        [4, "Start date", None, 9, [[333, None, 1]]],
        [5, "Notes", None, 1, [[444, None, 0]]],
        [6, "Section title", None, 6, None],
    ]
    data = [
        None,
        ["Fill this in to request leave", items, None, None, None, None, None, None, "Leave Request"],
        "/forms",
        "Leave Request (file)",
    ]
    return f"<html><script>var FB_PUBLIC_LOAD_DATA_ = {json.dumps(data)};</script></html>"


def test_google_form_parse_and_payload():
    url = "https://docs.google.com/forms/d/e/ABC/viewform?usp=sf_link"
    form = parse_google_form(google_form_html(), url, "f1")
    assert form.title == "Leave Request"
    assert [f.id for f in form.fields] == ["entry.111", "entry.222", "entry.333", "entry.444"]
    assert form.fields[1].options == ["Vacation", "Sick", "Emergency"]
    assert form.fields[2].type == "date" and form.fields[2].required
    assert form.submit == {"action": "https://docs.google.com/forms/d/e/ABC/formResponse", "pages": 2}

    payload = google_form_payload(form, {"entry.111": "Ana", "entry.222": "Sick", "entry.333": "2026-10-09"})
    assert ("entry.333_year", "2026") in payload and ("entry.333_day", "09") in payload
    assert ("pageHistory", "0,1") in payload

    url = google_prefill_url(form, {"entry.111": "Ana Cruz", "entry.222": "Sick", "entry.333": "2026-10-09"})
    assert url == (
        "https://docs.google.com/forms/d/e/ABC/viewform?usp=pp_url"
        "&entry.111=Ana+Cruz&entry.222=Sick&entry.333=2026-10-09"
    )
    # Checkbox answers repeat the entry key, one per ticked option.
    form.fields[3].type = "checkbox"
    assert "entry.444=A&entry.444=B" in google_prefill_url(form, {"entry.444": ["A", "B"]})


def test_form_response_url_variants():
    assert (
        form_response_url("https://docs.google.com/forms/d/e/X/viewform")
        == "https://docs.google.com/forms/d/e/X/formResponse"
    )


def test_html_form_parse_and_payload():
    html = """<html><head><title>IT Ticket</title></head><body>
      <form action="/submit" method="post">
        <input type="hidden" name="csrf" value="t0k">
        <label for="n">Your name</label><input id="n" name="name" required>
        <input name="email" type="email" placeholder="Work email">
        <select name="dept">
          <option value="">--</option><option value="it">IT</option><option value="hr">HR</option>
        </select>
        <fieldset><legend>Urgency</legend>
          <label><input type="radio" name="urg" value="1"> Low</label>
          <label><input type="radio" name="urg" value="3"> High</label>
        </fieldset>
        <textarea name="details"></textarea>
        <input type="submit" value="Send">
      </form></body></html>"""
    form = parse_html_form(html, "https://example.com/ticket", "f2")
    by_id = {f.id: f for f in form.fields}
    assert form.title == "IT Ticket"
    assert by_id["name"].label == "Your name" and by_id["name"].required
    assert by_id["email"].type == "email" and by_id["email"].label == "Work email"
    assert by_id["dept"].options == ["IT", "HR"]  # empty placeholder option dropped
    assert by_id["urg"].label == "Urgency" and by_id["urg"].options == ["Low", "High"]
    assert form.submit["action"] == "https://example.com/submit"

    payload = html_form_payload(form, {"name": "Ana", "urg": "High", "dept": "HR"}, {"csrf": "t0k"})
    assert payload == [("csrf", "t0k"), ("name", "Ana"), ("dept", "hr"), ("urg", "3")]


def test_pdf_roundtrip():
    template = make_pdf(["full_name", "employeeID"], checkbox="agree")
    form = ingest_file("leave.pdf", template)
    by_id = {f.id: f for f in form.fields}
    assert by_id["full_name"].label == "Full name" and by_id["full_name"].required
    assert by_id["employeeID"].label == "Employee id"
    assert by_id["agree"].type == "boolean"

    filled = fill_pdf(template, form, {"full_name": "Ana Cruz", "employeeID": "E-42", "agree": True})
    values = {k: v.get("/V") for k, v in PdfReader(BytesIO(filled)).get_fields().items()}
    assert values["full_name"] == "Ana Cruz" and values["employeeID"] == "E-42"
    assert values["agree"] == "/Yes"


def test_docx_roundtrip():
    template = make_docx("Name: {{Full name}}", "Leave from {{ Start date }} to {{End date}}", "Again {{Full name}}")
    form = ingest_file("leave.docx", template)
    assert [f.id for f in form.fields] == ["Full name", "Start date", "End date"]

    filled = fill_docx(template, form, {"Full name": "Ana", "Start date": "2026-10-09"})
    text = [p.text for p in Document(BytesIO(filled)).paragraphs]
    assert text == ["Name: Ana", "Leave from 2026-10-09 to ____________", "Again Ana"]


def test_html_form_falls_back_to_id_only_for_scripted_pages():
    html = """<html><body>
      <label for="fullName">Full name</label><input id="fullName" required>
      <input name="email" id="em" type="email" placeholder="Email">
      <select id="team"><option>Ops</option><option>Sales</option></select>
      <label><input type="radio" name="shift" value="am"> Morning</label>
      <input type="checkbox" id="agree"><label for="agree">I agree</label>
      <button onclick="go()">Submit</button></body></html>"""
    form = parse_html_form(html, "https://example.com/app", "f3", scripted=True)  # no <form> tag at all
    by_id = {f.id: f for f in form.fields}
    assert list(by_id) == ["fullName", "email", "team", "shift", "agree"]
    assert by_id["fullName"].label == "Full name" and by_id["fullName"].required
    assert form.submit["selectors"] == {
        "fullName": '[id="fullName"]',
        "email": '[name="email"]',  # name wins over id
        "team": '[id="team"]',
        "shift": '[name="shift"]',
        "agree": '[id="agree"]',
    }
    assert form.submit["option_selectors"] == {
        "shift": {"Morning": '[name="shift"][value="am"]'},
        "agree": {"I agree": '[id="agree"]'},
    }

    # A plain HTTP submit only sends named fields, so id-only ones aren't asked for there.
    plain = parse_html_form(f"<form>{html}</form>", "https://example.com/app", "f4")
    assert [f.id for f in plain.fields] == ["email", "shift"]


def test_signed_in_google_form_posts_through_browser_request():
    form = parse_google_form(google_form_html(), "https://docs.google.com/forms/d/e/ABC/viewform", "f5")
    form.submit["requires_login"] = True

    class FakeRequest:  # stands in for Playwright's BrowserContext.request (shares login cookies)
        def __init__(self):
            self.calls = []

        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return SimpleNamespace(url=url.replace("formResponse", "formResponse?ok"), status=200)

    req = FakeRequest()
    assert asyncio.run(post_signed_in_google_form(req, form, {"entry.111": "Ana Cruz"})) == "Submitted."
    url, kwargs = req.calls[0]
    assert url == "https://docs.google.com/forms/d/e/ABC/formResponse"
    assert parse_qsl(kwargs["data"]) == [("entry.111", "Ana Cruz"), ("pageHistory", "0,1")]

    async def expired(url, **kwargs):
        return SimpleNamespace(url="https://accounts.google.com/v3/signin", status=200)

    req.post = expired
    with pytest.raises(SubmitError, match="sign-in has expired"):
        asyncio.run(post_signed_in_google_form(req, form, {"entry.111": "Ana"}))


def test_browser_sources_without_the_addon_say_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)  # behaves as if not installed
    with pytest.raises(IngestError, match="pip install playwright"):
        asyncio.run(ingest_url("https://script.google.com/macros/s/ABC/exec", browser_profile=tmp_path / "p"))
    form = parse_google_form(google_form_html(), "https://docs.google.com/forms/d/e/ABC/viewform", "f6")
    form.submit["requires_login"] = True
    with pytest.raises(SubmitError, match="playwright install chromium"):
        asyncio.run(submit_online(form, {"entry.111": "Ana"}, browser_profile=tmp_path / "p"))
