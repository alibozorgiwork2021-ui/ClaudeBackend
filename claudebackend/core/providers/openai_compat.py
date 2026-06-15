"""OpenAI-compatible provider — covers OpenRouter, OpenAI, NVIDIA, DeepSeek, and
Gemini (via its OpenAI-compatible endpoint) with a single code path.

Anthropic-specific features (thinking, effort, prompt caching, the 1M context
advantage) do not exist here, so these backends are weaker for large
dependency-aware development tasks — Claude stays the recommended default.
"""

from __future__ import annotations

import json
from typing import Any

from .base import RefusalError
from claudebackend.core.pricing import Usage


def _flatten(content: Any) -> str:
    """Collapse our internal content shape (str or list of text blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def _strip_fence(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class OpenAICompatProvider:
    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, sdk: Any = None, usage: Usage | None = None,
                 timeout: float | None = None, max_retries: int | None = None) -> None:
        self.model = model
        self.usage = usage
        if sdk is None:
            from openai import OpenAI

            opts: dict[str, Any] = {"api_key": api_key, "base_url": base_url}
            # Only forward when set so existing providers keep the SDK defaults;
            # local backends (Ollama) pass a generous timeout + retries for slow
            # model loads.
            if timeout is not None:
                opts["timeout"] = timeout
            if max_retries is not None:
                opts["max_retries"] = max_retries
            sdk = OpenAI(**opts)
        self._sdk = sdk

    def _tally_usage(self, u: Any) -> None:
        """Accumulate one compat response's tokens into the shared Usage (prompt→input,
        completion→output; no cache tokens); ``u is None`` records a call with no usage data."""
        if self.usage is None:
            return
        if u is None:
            self.usage.add(had_usage=False)
            return
        self.usage.add(
            input=getattr(u, "prompt_tokens", 0) or 0,
            output=getattr(u, "completion_tokens", 0) or 0,
        )

    def _to_openai_messages(self, messages: list[dict], system: Any = None) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": _flatten(system)})
        for m in messages:
            out.append({"role": m["role"], "content": _flatten(m["content"])})
        return out

    def stream_text(self, messages: list[dict], system: Any = None,
                    model: str | None = None) -> tuple[str, str]:
        base_kwargs = dict(
            model=model or self.model,
            messages=self._to_openai_messages(messages, system),
            stream=True,
        )
        try:
            stream = self._sdk.chat.completions.create(
                **base_kwargs, stream_options={"include_usage": True}
            )
        except Exception:
            # Some OpenAI-compatible providers reject stream_options; fall back
            # without it so the stream still works — usage simply won't be reported.
            stream = self._sdk.chat.completions.create(**base_kwargs)
        text = ""
        finish: str | None = None
        cu = None
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                cu = chunk_usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta and choice.delta.content:
                text += choice.delta.content
            if choice.finish_reason:
                finish = choice.finish_reason
        self._tally_usage(cu)
        if finish == "content_filter":
            raise RefusalError("provider content filter blocked the request")
        return text, ("max_tokens" if finish == "length" else "end_turn")

    def parse(self, messages: list[dict], output_model: Any, model: str | None = None) -> Any:
        """Portable structured output: instruct JSON, validate, retry once.

        Avoids relying on each provider's native structured-output support.
        """
        schema = json.dumps(output_model.model_json_schema())
        convo: list[dict] = [
            {
                "role": "system",
                "content": "Return ONLY a JSON object that conforms to this JSON "
                "Schema. No prose, no Markdown code fence.\n" + schema,
            },
            *self._to_openai_messages(messages),
        ]
        last_err: Exception | None = None
        for _ in range(2):
            resp = self._sdk.chat.completions.create(model=model or self.model, messages=convo)
            self._tally_usage(getattr(resp, "usage", None))
            choice = resp.choices[0]
            if choice.finish_reason == "content_filter":
                raise RefusalError("provider content filter blocked the request")
            content = choice.message.content or ""
            try:
                return output_model.model_validate_json(_strip_fence(content))
            except Exception as exc:  # noqa: BLE001 — any validation/JSON failure retries
                last_err = exc
                convo += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"That was not valid JSON for the schema "
                        f"({exc}). Return only valid JSON.",
                    },
                ]
        raise ValueError(f"could not parse structured output from provider: {last_err}")

    def estimate_tokens(self, messages: list[dict]) -> int:
        text = "".join(_flatten(m.get("content", "")) for m in messages)
        return max(1, len(text) // 4)
