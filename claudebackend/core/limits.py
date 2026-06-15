"""Per-model context-window limits.

Anthropic/cloud models are left unbounded here (``None`` → no enforcement), which
preserves existing behaviour. Local models, where exceeding the window means an
OOM/abort on the user's own hardware, get a concrete limit so the context builder
can trim or refuse before the call.

Resolution order for ``context_window_for``:
1. ``CLAUDEBACKEND_CONTEXT_<MODEL>`` env override (mirrors the pricing override in
   ``pricing.py``).
2. a small built-in table of common local models.
3. ``CLAUDEBACKEND_DEFAULT_CONTEXT`` (a conservative fallback) for any *local*
   model not otherwise known.
"""

from __future__ import annotations

import os

__all__ = [
    "ContextWindowExceededError",
    "context_window_for",
    "input_budget_for",
    "DEFAULT_LOCAL_CONTEXT",
]

# Conservative default for an unknown local model when no override is set.
DEFAULT_LOCAL_CONTEXT = 8192

# Known native context windows (input+output) for common local coding models.
# Values are deliberately conservative; override per-model via env if your build
# of a model supports a larger window.
_CONTEXT_WINDOWS: dict[str, int] = {
    "qwen2.5-coder": 32768,
    "deepseek-coder-v2": 32768,
    "deepseek-coder": 16384,
    "llama3.1": 131072,
    "llama3": 8192,
    "codellama": 16384,
    "mistral": 32768,
    "mixtral": 32768,
    "phi3": 4096,
}


class ContextWindowExceededError(RuntimeError):
    """The assembled request does not fit in the active model's context window."""


def _model_key(model: str) -> str:
    """Strip an Ollama ``:tag`` so ``qwen2.5-coder:7b`` matches ``qwen2.5-coder``."""
    return model.split(":", 1)[0].strip().lower()


def context_window_for(model: str | None, *, local: bool = False) -> int | None:
    """Return the input context budget for ``model`` in tokens, or ``None`` for no
    enforcement (cloud/Anthropic models, or an unknown model when not ``local``).

    ``local=True`` applies the conservative ``DEFAULT_LOCAL_CONTEXT`` fallback (or
    ``CLAUDEBACKEND_DEFAULT_CONTEXT``) so local runs are never silently unbounded.
    """
    if not model:
        return None
    key = _model_key(model)

    env_key = "CLAUDEBACKEND_CONTEXT_" + key.upper().replace("-", "_").replace(".", "_")
    raw = os.environ.get(env_key)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass

    if key in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[key]

    if local:
        raw_default = os.environ.get("CLAUDEBACKEND_DEFAULT_CONTEXT")
        if raw_default:
            try:
                return int(raw_default)
            except ValueError:
                pass
        return DEFAULT_LOCAL_CONTEXT

    return None


def input_budget_for(model: str | None, *, local: bool = False) -> int | None:
    """The input-token budget for ``model`` — its context window minus an output
    reserve (``CLAUDEBACKEND_OUTPUT_RESERVE``, default 2048). ``None`` when the
    window is unenforced (cloud/Anthropic)."""
    window = context_window_for(model, local=local)
    if window is None:
        return None
    reserve = 2048
    raw = os.environ.get("CLAUDEBACKEND_OUTPUT_RESERVE")
    if raw:
        try:
            reserve = int(raw)
        except ValueError:
            pass
    return max(512, window - reserve)
