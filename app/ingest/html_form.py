from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import FormField, FormSchema, SourceKind
from .errors import IngestError

_SKIP = {"submit", "button", "reset", "image", "file", "password"}
_TYPES = {"email": "email", "number": "number", "date": "date", "time": "time", "range": "number"}
_CONTROLS = ["input", "select", "textarea"]


def css_attr(attr: str, value: str) -> str:
    """A CSS attribute selector that is safe for any value (quotes, brackets, leading digits)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}="{escaped}"]'


def _label_for(el: Tag, soup: BeautifulSoup, fallback: str) -> str:
    if el.get("id"):
        lab = soup.find("label", attrs={"for": el["id"]})
        if lab and lab.get_text(strip=True):
            return lab.get_text(" ", strip=True)
    parent = el.find_parent("label")
    if parent and parent.get_text(strip=True):
        return parent.get_text(" ", strip=True)
    return el.get("aria-label") or el.get("placeholder") or el.get("title") or fallback


def pick_form(soup: BeautifulSoup) -> Tag:
    forms = soup.find_all("form")
    if not forms:
        raise IngestError("No <form> found on that page.")
    return max(forms, key=lambda f: len(f.find_all(_CONTROLS)))


def hidden_inputs(form: Tag) -> dict[str, str]:
    return {
        el["name"]: el.get("value", "") for el in form.find_all("input", attrs={"type": "hidden"}) if el.get("name")
    }


def parse_html_form(html: str, url: str, form_id: str, scripted: bool = False) -> FormSchema:
    """Read the biggest <form> on a page.

    `scripted=True` is for pages filled in a real browser (Apps Script): fields with only an `id`
    count too, and controls outside any <form> are read from the whole page. A plain HTTP submit
    only sends named fields, so those extras would be questions whose answers go nowhere.

    `submit["selectors"]` records how to find each field in the page (by name or by id), and
    `submit["option_selectors"]` the exact radio/checkbox to tick for each option.
    """
    soup = BeautifulSoup(html, "html.parser")
    if scripted and not soup.find("form"):
        form = soup.body or soup
        if not form.find(_CONTROLS):
            raise IngestError("No form fields found on that page.")
    else:
        form = pick_form(soup)

    fields: dict[str, FormField] = {}
    # visible option text -> submitted value, per field
    option_values: dict[str, dict[str, str]] = {}
    selectors: dict[str, str] = {}
    option_selectors: dict[str, dict[str, str]] = {}

    for el in form.find_all(_CONTROLS):
        if el.get("name"):
            fid, selector = el["name"], css_attr("name", el["name"])
        elif scripted and el.get("id"):
            fid, selector = el["id"], css_attr("id", el["id"])
        else:
            continue
        if scripted and (el.has_attr("disabled") or el.has_attr("readonly")):
            continue  # the page owns these; leave them exactly as it set them
        required = el.has_attr("required")

        if el.name == "textarea":
            fields[fid] = FormField(
                id=fid,
                label=_label_for(el, soup, fid),
                type="paragraph",
                required=required,
                default=el.get_text().strip() or None,
            )
        elif el.name == "select":
            opts = {o.get_text(strip=True): o.get("value", o.get_text(strip=True)) for o in el.find_all("option")}
            opts = {k: v for k, v in opts.items() if k and v}
            option_values[fid] = opts
            chosen = el.find("option", selected=True)
            chosen_text = chosen.get_text(strip=True) if chosen else ""
            fields[fid] = FormField(
                id=fid,
                label=_label_for(el, soup, fid),
                type="dropdown",
                required=required,
                options=list(opts),
                default=chosen_text if chosen_text in opts else None,
            )
        else:
            itype = (el.get("type") or "text").lower()
            if itype == "hidden" or itype in _SKIP:
                continue
            if itype in ("radio", "checkbox"):
                value = el.get("value", "on")
                text = _label_for(el, soup, fid) if el.get("id") or el.find_parent("label") else value
                group = fields.get(fid)
                if group is None:
                    legend = el.find_parent("fieldset")
                    legend = legend.find("legend") if legend else None
                    group = fields[fid] = FormField(
                        id=fid,
                        label=legend.get_text(" ", strip=True) if legend else fid,
                        type="choice" if itype == "radio" else "checkbox",
                    )
                group.required = group.required or required
                group.options.append(text)
                option_values.setdefault(fid, {})[text] = value
                if el.has_attr("checked"):
                    if itype == "radio":
                        group.default = text
                    else:
                        group.default = [*(group.default or []), text]
                own = css_attr("id", el["id"]) if el.get("id") else selector + css_attr("value", value)
                option_selectors.setdefault(fid, {})[text] = own
            else:
                fields[fid] = FormField(
                    id=fid,
                    label=_label_for(el, soup, fid),
                    type=_TYPES.get(itype, "text"),
                    required=required,
                    default=el.get("value") or None,
                )
        selectors.setdefault(fid, selector)

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
            "selectors": selectors,
            "option_selectors": option_selectors,
        },
    )
