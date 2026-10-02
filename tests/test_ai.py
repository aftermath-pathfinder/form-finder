import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from app import ai
from app.config import Settings
from app.llm import build_model
from app.models import FormField, FormSchema, SourceKind


def form(fid: str, title: str) -> FormSchema:
    return FormSchema(
        id=fid, title=title, kind=SourceKind.DOCX, source="x.docx", fields=[FormField(id="name", label="Name")]
    )


def scripted(*replies: str) -> tuple[FunctionModel, list[int]]:
    """A model that returns each reply in turn; counts calls."""
    calls = [0]

    def respond(messages, info):
        calls[0] += 1
        return ModelResponse(parts=[TextPart(replies[min(calls[0], len(replies)) - 1])])

    return FunctionModel(respond), calls


def test_match_retries_when_model_invents_a_form_id():
    model, calls = scripted('{"form_id": "nope", "reason": "?"}', '{"form_id": "b", "reason": "IT issue"}')
    form_id, reason = asyncio.run(ai.match_form(model, "laptop broke", [form("a", "Leave"), form("b", "IT ticket")]))
    assert (form_id, reason) == ("b", "IT issue") and calls[0] == 2


def test_extract_retries_on_malformed_reply():
    model, calls = scripted("sure! the name is Ana", '{"answers": {"name": "Ana"}, "skipped": []}')
    answers, skipped = asyncio.run(ai.extract_answers(model, form("a", "Leave"), form("a", "Leave").fields, "Ana"))
    assert answers == {"name": "Ana"} and skipped == [] and calls[0] == 2


def test_ai_down_enrich_degrades_and_extract_raises():
    def down(messages, info):
        raise ai.AgentRunError("connection refused")

    model = FunctionModel(down)
    f = form("a", "Leave")
    assert asyncio.run(ai.enrich_form(model, f)).fields[0].ask() == "Name"  # falls back to the label
    with pytest.raises(ai.AIError):
        asyncio.run(ai.extract_answers(model, f, f.fields, "hi"))


def test_build_model_from_settings(monkeypatch):
    nvidia = build_model(Settings(_env_file=None, llm_api_key="k", llm_model="z-ai/glm-5.3"))
    assert nvidia.model_name == "z-ai/glm-5.3" and "integrate.api.nvidia.com" in nvidia.base_url

    other = build_model(Settings(_env_file=None, llm_provider="anthropic", llm_model="claude-sonnet-5-5"))
    assert other == "anthropic:claude-sonnet-5-5"

    monkeypatch.setenv("OPENAI_API_KEY", "k")  # fallback models read their provider's usual key variable
    fb = build_model(Settings(_env_file=None, llm_api_key="k", llm_fallback_models="openai:gpt-5.2"))
    assert type(fb).__name__ == "FallbackModel"
