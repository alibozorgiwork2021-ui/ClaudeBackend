"""Ollama provider — fully local, offline LLM execution.

Ollama exposes an OpenAI-compatible API at ``/v1``, so this is a thin subclass of
``OpenAICompatProvider``: streaming, the portable instructed-JSON ``parse`` (which
works on local models without relying on native structured output), and
content-filter handling are all inherited. Anthropic-only features (thinking,
effort, prompt caching) are simply absent — ``cache_control`` metadata is stripped
by the compat message flattener, so caching disables itself with no error.

What this adds over the base provider:
- a localhost default endpoint (``OLLAMA_BASE_URL`` or ``http://localhost:11434/v1``),
- a dummy API key (the ``openai`` SDK requires a non-empty key; Ollama ignores it),
- a generous timeout + connection retries, because a cold local model can take a
  long time to load on first use (``OLLAMA_TIMEOUT`` / ``OLLAMA_MAX_RETRIES``).
"""

from __future__ import annotations

import os
from typing import Any

from claudebackend.core.pricing import Usage
from claudebackend.core.providers.openai_compat import OpenAICompatProvider

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_TIMEOUT = 600.0  # seconds; a cold model can take minutes to load
DEFAULT_MAX_RETRIES = 3


def default_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL


class OllamaProvider(OpenAICompatProvider):
    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        sdk: Any = None,
        usage: Usage | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        base_url = base_url or default_base_url()
        if timeout is None:
            timeout = float(os.environ.get("OLLAMA_TIMEOUT", DEFAULT_TIMEOUT))
        if max_retries is None:
            max_retries = int(os.environ.get("OLLAMA_MAX_RETRIES", DEFAULT_MAX_RETRIES))
        # "ollama" is an ignored placeholder key — Ollama needs none, but the
        # OpenAI SDK rejects an empty key.
        super().__init__(
            model=model,
            api_key="ollama",
            base_url=base_url,
            sdk=sdk,
            usage=usage,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.base_url = base_url
