"""Provider-neutral types shared by every LLM backend."""

from __future__ import annotations

from typing import Any, Protocol


class RefusalError(RuntimeError):
    """The model declined the request (Anthropic refusal / OpenAI content_filter)."""


class Provider(Protocol):
    """The interface the orchestrator uses, regardless of backend."""

    def parse(self, messages: list[dict], output_model: Any) -> Any: ...

    def stream_text(
        self, messages: list[dict], system: Any = None
    ) -> tuple[str, str]: ...

    def estimate_tokens(self, messages: list[dict]) -> int: ...
