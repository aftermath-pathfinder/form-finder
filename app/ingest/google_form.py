from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .. import browser
from ..models import FormField, FormSchema, SourceKind
from .errors import IngestError

if TYPE_CHECKING:
    from playwright.async_api import Page

_DATA_RE = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);\s*</script>", re.S)

# Google's internal question type codes.
_TYPES = {0: "text", 1: "paragraph", 2: "choice", 3: "dropdown", 4: "checkbox", 5: "scale", 9: "date", 10: "time"}
_PAGE_BREAK = 8


def is_google_form(url: str) -> bool:
    return "docs.google.com/forms" in url or "forms.gle/" in url


def form_response_url(url: str) -> str:
    base = url.split("?")[0].split("#")[0]
    return re.sub(r"/(viewform|edit|formResponse)$", "", base.rstrip("/")) + "/formResponse"


def parse_google_form(html: str, url: str, form_id: str) -> FormSchema:
    m = _DATA_RE.search(html)
    if not m:
        raise IngestError("Couldn't find the form's questions on that page. Is it a public Google Form link?")
    data = json.loads(m.group(1))
    info = data[1]

    title = (len(info) > 8 and info[8]) or (len(data) > 3 and data[3]) or "Untitled Google Form"
    fields: list[FormField] = []
    pages = 1
    for item in info[1] or []:
        qtype = item[3]
        if qtype == _PAGE_BREAK:
            pages += 1
            continue
        if qtype not in _TYPES or not item[4]:
            continue  # titles, images, grids, file uploads: not supported yet
        for entry in item[4]:
            options = [o[0] for o in (entry[1] or []) if o and o[0]]
            fields.append(
                FormField(
                    id=f"entry.{entry[0]}",
                    label=item[1] or "Untitled question",
                    type=_TYPES[qtype],
                    required=bool(entry[2]),
                    options=options,
                    help=item[2] or "",
                )
            )
    if not fields:
        raise IngestError("That Google Form has no questions I can fill yet.")

    return FormSchema(
        id=form_id,
        title=title,
        description=info[0] or "",
        kind=SourceKind.GOOGLE_FORM,
        source=url,
        fields=fields,
        submit={"action": form_response_url(url), "pages": pages},
    )


async def read_signed_in_google_form(page: Page, url: str, form_id: str) -> FormSchema:
    """Open a sign-in-only Google Form in a browser that carries the saved Google login."""
    await browser.goto(page, url)
    if browser.on_login_page(page.url) or not is_google_form(page.url):
        raise IngestError(
            "That Google Form needs sign-in. Click “Sign in to Google” in the left panel, sign in, close that "
            "window, then add the link again. (Or open the form yourself and submit it there.)"
        )
    form = parse_google_form(await page.content(), page.url, form_id)
    form.submit["requires_login"] = True
    return form
