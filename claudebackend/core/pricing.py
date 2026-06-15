"""Token-usage accounting and USD pricing table.

Provides :class:`Usage` (a mutable accumulator for token counts across LLM
calls) and :func:`price` (which looks up per-model rates and returns a
:class:`CostReport`).  No external dependencies.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

__all__ = ["Usage", "CostReport", "price"]

# USD per 1,000,000 tokens: (input, output, cache_read, cache_write)
_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4-8":   (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-7":   (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "claude-haiku-4-5":  (1.00,  5.00, 0.10, 1.25),
}


def _resolve(model: str) -> tuple[float, float, float, float] | None:
    """Return price tuple for *model*, honouring env-var overrides."""
    env_key = "CLAUDEBACKEND_PRICE_" + model.upper().replace("-", "_")
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            parts = [float(x) for x in raw.split(",")]
            if len(parts) == 4:
                return (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            pass  # malformed value below
        warnings.warn(
            f"Ignoring malformed price override {env_key}={raw!r}; "
            'expected "input,output,cache_read,cache_write". '
            "Falling back to the built-in price table.",
            stacklevel=2,
        )
    return _PRICES.get(model)


@dataclass
class Usage:
    """Mutable accumulator for token counts across multiple LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    calls_without_usage: int = 0

    def add(
        self,
        *,
        input: int = 0,
        output: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        had_usage: bool = True,
    ) -> None:
        """Accumulate token counts from one LLM response.

        When *had_usage* is ``False`` the response carried no usage data; we
        increment :attr:`calls` and :attr:`calls_without_usage` but add zero
        tokens so the totals remain accurate (if partial).
        """
        self.calls += 1
        if not had_usage:
            self.calls_without_usage += 1
            return
        self.input_tokens += input
        self.output_tokens += output
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write


@dataclass
class CostReport:
    """Cost summary for a completed (or partial) run."""

    usage: Usage
    model: str
    cost_usd: float | None
    pricing_known: bool
    partial: bool
    cache_hit_ratio: float


def price(model: str, usage: Usage) -> CostReport:
    """Compute a :class:`CostReport` for *usage* against *model* rates."""
    partial = usage.calls_without_usage > 0

    denom = usage.cache_read_tokens + usage.input_tokens + usage.cache_write_tokens
    cache_hit_ratio = usage.cache_read_tokens / denom if denom else 0.0

    rates = _resolve(model)
    if rates is None:
        return CostReport(
            usage=usage,
            model=model,
            cost_usd=None,
            pricing_known=False,
            partial=partial,
            cache_hit_ratio=cache_hit_ratio,
        )

    pi, po, pr, pw = rates
    cost_usd = round(
        (
            usage.input_tokens * pi
            + usage.output_tokens * po
            + usage.cache_read_tokens * pr
            + usage.cache_write_tokens * pw
        )
        / 1_000_000,
        6,
    )
    return CostReport(
        usage=usage,
        model=model,
        cost_usd=cost_usd,
        pricing_known=True,
        partial=partial,
        cache_hit_ratio=cache_hit_ratio,
    )
