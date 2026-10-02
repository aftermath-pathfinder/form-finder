from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import FormField, FormSchema, SourceKind
from .errors import IngestError

_SKIP = {"submit", "button", "reset", "image", "file", "password"}
_TYPES = {"email": "email", "number": "number", "date": "date", "time": "time", "range": "number"}


def _label_for(el: Tag, soup: BeautifulSoup) -> str:
    if el.get("id"):
        lab = soup.find("label", attrs={"for": el["id"]})
        if lab and lab.get_text(strip=True):
            return lab.get_text(" ", strip=True)
    parent = el.find_parent("label")
    if parent and parent.get_text(strip=True):
        return parent.get_text(" ", strip=True)
    return el.get("aria-label") or el.get("placeholder") or el.get("title") or el["name"]


def pick_form(soup: BeautifulSoup) -> Tag:
    forms = soup.find_all("form")
    if not forms:
        raise IngestError("No <form> found on that page.")
    return max(forms, key=lambda f: len(f.find_all(["input", "select", "textarea"])))


def hidden_inputs(form: Tag) -> dict[str, str]:
    return {
        el["name"]: el.get("value", "") for el in form.find_all("input", attrs={"type": "hidden"}) if el.get("name")
    }


def parse_html_form(html: str, url: str, form_id: str) -> FormSchema:
    soup = BeautifulSoup(html, "html.parser")
    form = pick_form(soup)

    fields: dict[str, FormField] = {}
    # visible option text -> submitted value, per field
    option_values: dict[str, dict[str, str]] = {}

    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name:
            continue
        required = el.has_attr("required")

        if el.name == "textarea":
            fields[name] = FormField(id=name, label=_label_for(el, soup), type="paragraph", required=required)
        elif el.name == "select":
            opts = {o.get_text(strip=True): o.get("value", o.get_text(strip=True)) for o in el.find_all("option")}
            opts = {k: v for k, v in opts.items() if k and v}
            option_values[name] = opts
            fields[name] = FormField(
                id=name, label=_label_for(el, soup), type="dropdown", required=required, options=list(opts)
            )
        else:
            itype = (el.get("type") or "text").lower()
            if itype == "hidden" or itype in _SKIP:
                continue
            if itype in ("radio", "checkbox"):
                value = el.get("value", "on")
                text = _label_for(el, soup) if el.get("id") or el.find_parent("label") else value
                group = fields.get(name)
                if group is None:
                    legend = el.find_parent("fieldset")
                    legend = legend.find("legend") if legend else None
                    group = fields[name] = FormField(
                        id=name,
                        label=legend.get_text(" ", strip=True) if legend else name,
                        type="choice" if itype == "radio" else "checkbox",
                    )
                group.required = group.required or required
                group.options.append(text)
                option_values.setdefault(name, {})[text] = value
            else:
                fields[name] = FormField(
                    id=name, label=_label_for(el, soup), type=_TYPES.get(itype, "text"), required=required
                )

    if not fields:
        raise IngestError("That form has no fields I can fill.")

    title = soup.title.get_text(strip=True) if soup.title else url
    return FormSchema(
        id=form_id,
        title=title or url,
        kind=SourceKind.HTML_FORM,
        source=url,
        fields=list(fields.values()),
        submit={
            "action": urljoin(url, form.get("action") or url),
            "method": (form.get("method") or "get").lower(),
            "option_values": option_values,
        },
    )
