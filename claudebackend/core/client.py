"""LLM client facade.

Default backend is Anthropic (Claude Opus 4.8) with native structured output,
streaming, thinking/effort, prompt caching, and subscription auth. Other backends
(OpenRouter, OpenAI, NVIDIA, DeepSeek, Gemini) are OpenAI-compatible and routed
through ``OpenAICompatProvider``. The orchestrator only sees this facade.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claudebackend.core.providers.openai_compat import OpenAICompatProvider

from claudebackend.core.pricing import CostReport, Usage, price
from claudebackend.core.providers.base import RefusalError  # re-exported

__all__ = [
    "Client",
    "RefusalError",
    "SubscriptionAuthError",
    "ProviderConfigError",
    "MODEL",
    "SUPPORTED_PROVIDERS",
]

MODEL = "claude-opus-4-8"
PLAN_MAX_TOKENS = 16000  # messages.parse is non-streaming; keep <= ~16000
CODE_MAX_TOKENS = 64000  # streamed; source files can be large
THINKING = {"type": "adaptive"}
OUTPUT_CONFIG = {"effort": "high"}

Message = dict[str, Any]

# OpenAI-compatible providers: name -> (base_url or None for default, env var).
_OPENAI_COMPAT = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": (None, "OPENAI_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
}
SUPPORTED_PROVIDERS = ("anthropic", "ollama", *_OPENAI_COMPAT)


class SubscriptionAuthError(RuntimeError):
    """``--use-subscription`` was requested but no Claude login is available."""


class ProviderConfigError(RuntimeError):
    """A backend was misconfigured (unknown provider, missing model/key, ...)."""


def _subscription_available() -> bool:
    """True if a Claude subscription login (auth token or logged-in profile) is
    usable by the SDK's credential chain."""
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:
        from anthropic.lib.credentials._constants import (
            _has_auto_discoverable_credentials,
        )

        return bool(_has_auto_discoverable_credentials())
    except Exception:
        return False


def _guard_refusal(response: Any) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        raise RefusalError(f"model refused the request (stop_details={details})")


def _build_compat_provider(
    provider: str, model: str | None, api_key: str | None, sdk: Any, usage: Usage
) -> "OpenAICompatProvider":
    base_url, env = _OPENAI_COMPAT[provider]
    if not model:
        raise ProviderConfigError(
            f"--model is required for provider '{provider}'. "
            "See docs/providers.md for example model ids."
        )
    key = api_key or os.environ.get(env)
    if not key and sdk is None:
        raise ProviderConfigError(
            f"No API key found for provider '{provider}'. Set {env} or pass --api-key."
        )
    from claudebackend.core.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        model=model, api_key=key, base_url=base_url, sdk=sdk, usage=usage
    )


def _is_local_endpoint(base_url: str) -> bool:
    """True if ``base_url``'s host is loopback, a private IP, or a bare hostname
    (a container/service name on a private Docker network)."""
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "0.0.0.0"}:
        return True
    if "." not in host:  # bare hostname, e.g. the Docker service name "ollama"
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _build_ollama_provider(
    model: str | None, base_url: str | None, sdk: Any, usage: Usage, local: bool
):
    """Build a local Ollama provider. No API key is needed; under ``local`` the
    endpoint must be loopback/private so an air-gapped run cannot reach out."""
    if not model:
        raise ProviderConfigError(
            "--model is required for provider 'ollama' (the local model name, e.g. "
            "'qwen2.5-coder'). See docs/install/local_ai.md."
        )
    from claudebackend.core.providers.ollama import OllamaProvider, default_base_url

    resolved = base_url or default_base_url()
    if local and sdk is None and not _is_local_endpoint(resolved):
        raise ProviderConfigError(
            f"--local requires a loopback/private Ollama endpoint; refusing the "
            f"non-local base_url '{resolved}'."
        )
    return OllamaProvider(model=model, base_url=resolved, sdk=sdk, usage=usage)


class Client:
    def __init__(
        self,
        sdk: Any = None,
        use_subscription: bool = False,
        provider: str = "anthropic",
        model: str | None = None,
        api_key: str | None = None,
        local: bool = False,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self.local = local
        self._compat = None
        self._sdk = None
        self.usage = Usage()
        self.model_id: str | None = MODEL if provider == "anthropic" else model

        # Air-gap: --local runs offline against Ollama only. This guarantees we
        # never construct the Anthropic SDK, run credential discovery, or build a
        # remote OpenAI-compatible client — no external endpoint is ever reached.
        if local and provider != "ollama":
            raise ProviderConfigError(
                f"--local runs offline against Ollama only; use --provider ollama "
                f"(or drop --local). Got provider '{provider}'."
            )

        if provider == "anthropic":
            if sdk is None:
                import anthropic

                if use_subscription:
                    # See SubscriptionAuthError / the chain: a set ANTHROPIC_API_KEY
                    # shadows the login, so drop it for this process.
                    os.environ.pop("ANTHROPIC_API_KEY", None)
                    if not _subscription_available():
                        raise SubscriptionAuthError(
                            "No Claude subscription login found. Log in first with "
                            "`claude` (Claude Code) or `ant auth login`, or omit "
                            "--use-subscription to use ANTHROPIC_API_KEY."
                        )
                sdk = anthropic.Anthropic()
            self._sdk = sdk
        elif provider == "ollama":
            if use_subscription:
                raise ProviderConfigError(
                    "--use-subscription only works with the anthropic provider."
                )
            self._compat = _build_ollama_provider(
                model, base_url, sdk, self.usage, local
            )
        elif provider in _OPENAI_COMPAT:
            if use_subscription:
                raise ProviderConfigError(
                    "--use-subscription only works with the anthropic provider."
                )
            self._compat = _build_compat_provider(
                provider, model, api_key, sdk, self.usage
            )
        else:
            raise ProviderConfigError(
                f"unknown provider '{provider}'. Supported: "
                + ", ".join(SUPPORTED_PROVIDERS)
                + "."
            )

    def _tally(self, response: Any) -> None:
        """Maps an Anthropic response's ``.usage`` into the shared Usage; missing usage
        records a call with no usage data."""
        u = getattr(response, "usage", None)
        if u is None:
            self.usage.add(had_usage=False)
            return
        self.usage.add(
            input=getattr(u, "input_tokens", 0) or 0,
            output=getattr(u, "output_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )

    def cost_report(self) -> CostReport:
        """Return a CostReport for this session. ``pricing_known`` will be False
        (and ``cost_usd`` None) for models not in the pricing table — e.g. most non-Anthropic backends."""
        return price(self.model_id, self.usage)

    def parse(self, messages: list[Message], output_model: Any,
              model: str | None = None) -> Any:
        # ``model`` lets the orchestrator route a specific model per agent. For
        # cost, ``model_id`` stays the run default; local pricing is unknown anyway.
        if self._compat is not None:
            return self._compat.parse(messages, output_model, model=model)
        response = self._sdk.messages.parse(
            model=model or MODEL,
            max_tokens=PLAN_MAX_TOKENS,
            thinking=THINKING,
            output_config=OUTPUT_CONFIG,
            messages=messages,
            output_format=output_model,
        )
        self._tally(response)
        _guard_refusal(response)
        return response.parsed_output

    def stream_text(self, messages: list[Message], system: Any = None,
                    model: str | None = None) -> tuple[str, str]:
        if self._compat is not None:
            return self._compat.stream_text(messages, system, model=model)
        kwargs: dict[str, Any] = dict(
            model=model or MODEL,
            max_tokens=CODE_MAX_TOKENS,
            thinking=THINKING,
            output_config=OUTPUT_CONFIG,
            messages=messages,
        )
        if system is not None:
            kwargs["system"] = system
        with self._sdk.messages.stream(**kwargs) as stream:
            text = "".join(stream.text_stream)
            final = stream.get_final_message()
        self._tally(final)
        _guard_refusal(final)
        return text, getattr(final, "stop_reason", "end_turn")

    def estimate_tokens(self, messages: list[Message], model: str | None = None) -> int:
        if self._compat is not None:
            return self._compat.estimate_tokens(messages)
        return self._sdk.messages.count_tokens(
            model=model or MODEL, messages=messages
        ).input_tokens
