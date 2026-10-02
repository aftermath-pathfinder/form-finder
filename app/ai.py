"""Every prompt the app sends to the AI lives here, as Pydantic AI agents.

Each agent has a typed output. Pydantic AI validates the model's reply against it and asks the
model to try again when it doesn't fit, so callers always get a well-formed object.

Agents use prompted output (the schema is described in the prompt and the reply is parsed as
JSON) because it works on every provider, including ones without tool calling.
"""

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from .models import FormField, FormSchema

SETTINGS = ModelSettings(temperature=0.2)
RETRIES = 2


class AIError(RuntimeError):
    """The AI was unreachable or kept replying in the wrong shape. Message is user-facing."""


# ---- output shapes --------------------------------------------------------


class Enrichment(BaseModel):
    description: str = Field(
        description="One sentence on what requests this form is for, with keywords people would say."
    )
    questions: dict[str, str] = Field(
        default_factory=dict, description="Field id -> short plain-English question asking for that field."
    )


class Match(BaseModel):
    form_id: str | None = Field(description="Id of the best form from the catalog, or null if none plausibly fits.")
    reason: str = Field(description="One short sentence explaining the choice.")


class Extraction(BaseModel):
    answers: dict[str, Any] = Field(
        default_factory=dict, description="Field id -> value, only for fields the user actually answered."
    )
    skipped: list[str] = Field(default_factory=list, description="Ids of fields the user asked to skip/leave blank.")


# ---- agents ---------------------------------------------------------------

enrich_agent = Agent(
    output_type=PromptedOutput(Enrichment),
    instructions=(
        "You help people fill in forms. Given a form's title and fields, describe what the form is for "
        "and write one friendly question per field. Make cryptic field names understandable."
    ),
    model_settings=SETTINGS,
    retries=RETRIES,
)

match_agent = Agent(
    deps_type=set,  # valid form ids
    output_type=PromptedOutput(Match),
    instructions="You route a user's request to the right form from a catalog. Use null only if nothing fits.",
    model_settings=SETTINGS,
    retries=RETRIES,
)


@match_agent.output_validator
def _known_form(ctx: RunContext[set], out: Match) -> Match:
    if out.form_id is not None and out.form_id not in ctx.deps:
        raise ModelRetry(f"'{out.form_id}' is not in the catalog. Use one of: {', '.join(sorted(ctx.deps))}.")
    return out


extract_agent = Agent(
    deps_type=date,  # today
    output_type=PromptedOutput(Extraction),
    model_settings=SETTINGS,
    retries=RETRIES,
)


@extract_agent.instructions
def _extract_rules(ctx: RunContext[date]) -> str:
    today = ctx.deps
    return (
        "You extract form answers from a user's message.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"
        "Rules:\n"
        "- Only use information the user actually gave. Never invent values.\n"
        "- Dates as YYYY-MM-DD (resolve 'next Friday' etc. using today). Times as HH:MM (24h).\n"
        "- For fields with options, answer with one of the options exactly; for checkbox fields, a list of options.\n"
        "- boolean fields: true or false.\n"
        "- If the user says to skip or leave something blank, put its id in skipped."
    )


# ---- what the app calls ---------------------------------------------------


def _field_brief(f: FormField) -> dict[str, Any]:
    brief: dict[str, Any] = {"id": f.id, "label": f.label, "type": f.type}
    if f.options:
        brief["options"] = f.options
    if f.help:
        brief["help"] = f.help
    if f.required:
        brief["required"] = True
    return brief


def _prompt(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


async def enrich_form(model: Model | str, form: FormSchema) -> FormSchema:
    """Write a one-line purpose for matching, plus a friendly question per field.

    Runs once when a form is added. If the AI is unavailable the form still works with its raw labels.
    """
    prompt = _prompt(
        {"title": form.title, "description": form.description, "fields": [_field_brief(f) for f in form.fields]}
    )
    try:
        out = (await enrich_agent.run(prompt, model=model)).output
    except AgentRunError:
        return form
    form.purpose = out.description.strip()
    for f in form.fields:
        q = out.questions.get(f.id, "").strip()
        if q:
            f.question = q
    return form


async def match_form(model: Model | str, request: str, forms: list[FormSchema]) -> tuple[str | None, str]:
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
    try:
        out = (
            await match_agent.run(
                _prompt({"catalog": catalog, "request": request}), model=model, deps={f.id for f in forms}
            )
        ).output
    except AgentRunError as e:
        raise AIError(f"The AI couldn't pick a form: {e}") from e
    return out.form_id, out.reason


async def extract_answers(
    model: Model | str, form: FormSchema, fields: list[FormField], message: str, today: date | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Read the user's free-text message and pull out values for any of `fields`.

    Returns (answers by field id, ids the user explicitly skipped). The user may answer several
    questions in one message, out of order, or volunteer info for questions not asked yet.
    Values are checked against each field later, in `interview.normalize`.
    """
    prompt = _prompt({"form": form.title, "fields": [_field_brief(f) for f in fields], "message": message})
    try:
        out = (await extract_agent.run(prompt, model=model, deps=today or date.today())).output
    except AgentRunError as e:
        raise AIError(f"The AI couldn't read your answers: {e}") from e
    return out.answers, out.skipped
