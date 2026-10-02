import re

import httpx

from .base import LLMError, LLMProvider

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


class OpenAICompatProvider(LLMProvider):
    """Any `/chat/completions` API: NVIDIA build, OpenAI, OpenRouter, Groq, Ollama, ..."""

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 120.0, temperature: float = 0.2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    async def complete(self, messages: list[dict[str, str]], *, temperature: float | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": 4096,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach the AI provider: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(f"AI provider returned {resp.status_code}: {resp.text[:300]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"Unexpected AI response: {resp.text[:300]}") from e
        # Reasoning models (GLM, DeepSeek, ...) may inline their thinking.
        return _THINK_RE.sub("", content).strip()
