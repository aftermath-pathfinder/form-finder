"""Builds the AI model from settings. The only place that knows about providers.

Switching providers is config-only (`.env`):

- LLM_PROVIDER=openai_compatible (default): any `/chat/completions` API at LLM_BASE_URL
  (NVIDIA build, OpenAI, OpenRouter, Groq, Ollama, ...).
- Any other LLM_PROVIDER is passed to Pydantic AI as "<provider>:<model>", e.g.
  LLM_PROVIDER=anthropic + LLM_MODEL=claude-sonnet-5-5. That provider's own key variable
  (ANTHROPIC_API_KEY, GEMINI_API_KEY, ...) must be set; install its extra
  (`pip install "pydantic-ai-slim[anthropic]"`).
- LLM_JSON_MODE=false: for OpenAI-compatible APIs that reject `response_format` (400 errors).
- LLM_FALLBACK_MODELS: optional comma-separated "<provider>:<model>" list tried in order when
  the main model errors (e.g. the free tier is rate-limited).
"""

import os

from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from .config import Settings

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def build_model(settings: Settings) -> Model | str:
    if settings.llm_provider == "openai_compatible":
        primary: Model | str = OpenAIChatModel(
            settings.llm_model,
            provider=OpenAIProvider(base_url=settings.llm_base_url, api_key=settings.llm_api_key or "none"),
            profile=None if settings.llm_json_mode else OpenAIModelProfile(supports_json_object_output=False),
        )
    else:
        primary = f"{settings.llm_provider}:{settings.llm_model}"

    fallbacks = [m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()]
    return FallbackModel(primary, *fallbacks) if fallbacks else primary
