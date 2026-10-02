"""Every prompt the app sends to the AI lives here."""

import json
from datetime import date
from typing import Any

from .llm import LLMError, LLMProvider, complete_json
from .models import FormField, FormSchema


def _field_brief(f: FormField) -> dict[str, Any]:
    brief: dict[str, Any] = {"id": f.id, "label": f.label, "type": f.type}
    if f.options:
        brief["options"] = f.options
    if f.help:
        brief["help"] = f.help
    if f.required:
        brief["required"] = True
    return brief


async def enrich_form(llm: LLMProvider, form: FormSchema) -> FormSchema:
    """Write a one-line purpose for matching, plus a friendly question per field.

    Runs once when a form is added. If the AI is unavailable the form still works
    with its raw labels.
    """
    system = (
        "You help people fill in forms. Given a form's title and fields, write:\n"
        '- "description": one sentence saying what requests this form is used for '
        "(include likely keywords people would say, e.g. 'leave, vacation, time off').\n"
        '- "questions": an object mapping each field id to a short, plain-English question '
        "that asks the user for that field. Keep cryptic field names understandable."
    )
    user = json.dumps(
        {"title": form.title, "description": form.description, "fields": [_field_brief(f) for f in form.fields]},
        ensure_ascii=False,
    )
    try:
        out = await complete_json(llm, system, user)
    except LLMError:
        return form
    if isinstance(out.get("description"), str):
        form.purpose = out["description"].strip()
    questions = out.get("questions") or {}
    for f in form.fields:
        q = questions.get(f.id)
        if isinstance(q, str) and q.strip():
            f.question = q.strip()
    return form


async def match_form(llm: LLMProvider, request: str, forms: list[FormSchema]) -> tuple[str | None, str]:
    """Pick the form that fits the user's request. Returns (form_id or None, reason)."""
    if not forms:
        return None, "Your knowledge base is empty. Add a form first."
    if len(forms) == 1:
        return forms[0].id, "It's the only form in your knowledge base."

    catalog = [
        {
            "id": f.id,
            "title": f.title,
            "purpose": f.purpose or f.description,
            "fields": [x.label for x in f.fields][:25],
        }
        for f in forms
    ]
    system = (
        "You route a user's request to the right form. Given a catalog of forms and the request, "
        'return {"form_id": <id or null>, "reason": <one short sentence>}. '
        "Use null only if no form plausibly fits."
    )
    user = json.dumps({"catalog": catalog, "request": request}, ensure_ascii=False)
    out = await complete_json(llm, system, user)
    form_id = out.get("form_id")
    if form_id not in {f.id for f in forms}:
        form_id = None
    return form_id, str(out.get("reason") or "")


async def extract_answers(
    llm: LLMProvider, form: FormSchema, fields: list[FormField], message: str, today: date | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Read the user's free-text message and pull out values for any of `fields`.

    Returns (answers by field id, ids the user explicitly declined/skipped).
    The user may answer several questions in one message, out of order, or
    volunteer info for questions not asked yet; all of it is captured.
    """
    today = today or date.today()
    system = (
        "You extract form answers from a user's message.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"
        "Rules:\n"
        "- Only use information the user actually gave. Never invent values.\n"
        "- Dates as YYYY-MM-DD (resolve 'next Friday' etc. using today). Times as HH:MM (24h).\n"
        "- For fields with options, answer with one of the options exactly; for checkbox fields, a list of options.\n"
        "- boolean fields: true or false.\n"
        "- If the user says to skip or leave something blank, list its id in \"skipped\".\n"
        'Return {"answers": {<field id>: <value>}, "skipped": [<field id>, ...]}.'
    )
    user = json.dumps(
        {"form": form.title, "fields": [_field_brief(f) for f in fields], "message": message},
        ensure_ascii=False,
    )
    out = await complete_json(llm, system, user)
    answers = out.get("answers") if isinstance(out.get("answers"), dict) else {}
    skipped = [s for s in out.get("skipped") or [] if isinstance(s, str)]
    return answers, skipped
