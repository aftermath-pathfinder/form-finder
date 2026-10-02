import json
import re
from typing import Any

from ..config import Settings
from .base import LLMError, LLMProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["LLMError", "LLMProvider", "get_provider", "register_provider", "complete_json"]

_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai_compatible": OpenAICompatProvider,
}


def register_provider(name: str, cls: type[LLMProvider]) -> None:
    _REGISTRY[name] = cls


def get_provider(settings: Settings) -> LLMProvider:
    cls = _REGISTRY.get(settings.llm_provider)
    if cls is None:
        raise LLMError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Known: {', '.join(_REGISTRY)}")
    return cls(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
        temperature=settings.llm_temperature,
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> Any:
    """Pull a JSON object out of a model reply that may include fences or chatter."""
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise LLMError(f"AI reply contained no JSON: {text[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"AI reply had invalid JSON: {text[:200]}") from e


async def complete_json(provider: LLMProvider, system: str, user: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system + "\n\nRespond with a single JSON object and nothing else."},
        {"role": "user", "content": user},
    ]
    try:
        return parse_json(await provider.complete(messages))
    except LLMError:
        # One retry with a firmer nudge; small models sometimes ramble.
        messages.append({"role": "user", "content": "That was not valid JSON. Reply with only the JSON object."})
        return parse_json(await provider.complete(messages, temperature=0))
