"""Submit answers to online forms."""

from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from .ingest import BROWSER_HEADERS
from .ingest.html_form import hidden_inputs, pick_form
from .models import FormSchema, SourceKind


class SubmitError(RuntimeError):
    pass


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


async def submit_online(form: FormSchema, answers: dict[str, Any]) -> str:
    """Submit and return a short confirmation message."""
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
