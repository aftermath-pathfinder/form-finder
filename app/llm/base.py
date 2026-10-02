from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    """The only thing the rest of the app knows about the AI.

    To add a provider, subclass this, implement `complete`, and register it
    in `app/llm/__init__.py`. Messages use the common chat format:
    [{"role": "system" | "user" | "assistant", "content": "..."}].
    """

    @abstractmethod
    async def complete(self, messages: list[dict[str, str]], *, temperature: float | None = None) -> str:
        """Return the assistant's reply text."""
