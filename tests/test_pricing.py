"""Tests for claudebackend.core.pricing — token accounting + USD cost table."""

from __future__ import annotations

import pytest

from claudebackend.core.pricing import Usage, price


# ---------------------------------------------------------------------------
# Usage.add
# ---------------------------------------------------------------------------


def test_usage_add_accumulates_across_calls():
    u = Usage()
    u.add(input=100, output=200)
    u.add(input=50, output=75, cache_read=10, cache_write=5)

    assert u.input_tokens == 150
    assert u.output_tokens == 275
    assert u.cache_read_tokens == 10
    assert u.cache_write_tokens == 5
    assert u.calls == 2
    assert u.calls_without_usage == 0


def test_usage_add_had_usage_false_increments_calls_without_usage():
    u = Usage()
    u.add(had_usage=False)

    assert u.calls == 1
    assert u.calls_without_usage == 1
    # no tokens accumulated
    assert u.input_tokens == 0
    assert u.output_tokens == 0


def test_usage_add_had_usage_false_adds_zero_tokens():
    u = Usage()
    u.add(input=100)
    u.add(input=999, output=999, had_usage=False)

    # had_usage=False means we don't know the real counts; only calls_without_usage
    # increments — the spec says: "adds zero tokens … had_usage=False"
    assert u.input_tokens == 100
    assert u.output_tokens == 0
    assert u.calls == 2
    assert u.calls_without_usage == 1


def test_usage_defaults_all_zero():
    u = Usage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_read_tokens == 0
    assert u.cache_write_tokens == 0
    assert u.calls == 0
    assert u.calls_without_usage == 0


# ---------------------------------------------------------------------------
# price() — known model math
# ---------------------------------------------------------------------------


def test_price_known_model_basic():
    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    r = price("claude-opus-4-8", u)

    assert r.pricing_known is True
    assert r.cost_usd == pytest.approx(30.00)  # 5.00 + 25.00
    assert r.model == "claude-opus-4-8"
    assert r.usage is u


def test_price_known_model_with_cache_tokens():
    u = Usage()
    # 1M of each token type
    u.add(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000)

    r = price("claude-opus-4-8", u)

    # 5.00 + 25.00 + 0.50 + 6.25 = 36.75
    assert r.cost_usd == pytest.approx(36.75)
    assert r.pricing_known is True


def test_price_sonnet_rates():
    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    r = price("claude-sonnet-4-6", u)

    # 3.00 + 15.00 = 18.00
    assert r.cost_usd == pytest.approx(18.00)


def test_price_haiku_rates():
    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    r = price("claude-haiku-4-5", u)

    # 1.00 + 5.00 = 6.00
    assert r.cost_usd == pytest.approx(6.00)


# ---------------------------------------------------------------------------
# price() — unknown model
# ---------------------------------------------------------------------------


def test_price_unknown_model_returns_pricing_unknown():
    u = Usage()
    u.add(input=500, output=300)

    r = price("unknown-model-xyz", u)

    assert r.pricing_known is False
    assert r.cost_usd is None
    assert r.usage.input_tokens == 500
    assert r.usage.output_tokens == 300


# ---------------------------------------------------------------------------
# cache_hit_ratio
# ---------------------------------------------------------------------------


def test_cache_hit_ratio_zero_denominator_no_exception():
    u = Usage()  # all zeros
    r = price("claude-opus-4-8", u)

    assert r.cache_hit_ratio == 0.0


def test_cache_hit_ratio_with_cache_reads():
    u = Usage()
    u.add(input=1_000_000, cache_read=1_000_000)

    r = price("claude-opus-4-8", u)

    # cache_read / (cache_read + input + cache_write) = 1M / 2M = 0.5
    assert r.cache_hit_ratio == pytest.approx(0.5)


def test_cache_hit_ratio_full_cache():
    u = Usage()
    u.add(cache_read=1_000_000)

    r = price("claude-opus-4-8", u)

    assert r.cache_hit_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# partial flag
# ---------------------------------------------------------------------------


def test_partial_flag_set_when_calls_without_usage():
    u = Usage()
    u.add(input=100)
    u.add(had_usage=False)

    r = price("claude-opus-4-8", u)

    assert r.partial is True


def test_partial_flag_false_when_all_calls_have_usage():
    u = Usage()
    u.add(input=100)
    u.add(input=200)

    r = price("claude-opus-4-8", u)

    assert r.partial is False


# ---------------------------------------------------------------------------
# Env-var price override
# ---------------------------------------------------------------------------


def test_env_override_applies(monkeypatch):
    monkeypatch.setenv("CLAUDEBACKEND_PRICE_CLAUDE_OPUS_4_8", "10.00,50.00,1.00,12.50")

    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    r = price("claude-opus-4-8", u)

    # 10.00 + 50.00 = 60.00 (overridden rates)
    assert r.cost_usd == pytest.approx(60.00)
    assert r.pricing_known is True


def test_env_override_malformed_warns_and_falls_back_to_table(monkeypatch):
    monkeypatch.setenv("CLAUDEBACKEND_PRICE_CLAUDE_OPUS_4_8", "bad,data,here")

    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    with pytest.warns(UserWarning, match="malformed price override"):
        r = price("claude-opus-4-8", u)

    # falls back to table: 5.00 + 25.00 = 30.00
    assert r.cost_usd == pytest.approx(30.00)


def test_env_override_wrong_count_warns_and_falls_back(monkeypatch):
    # three valid floats — parses but is not 4 values, so still falls back
    monkeypatch.setenv("CLAUDEBACKEND_PRICE_CLAUDE_OPUS_4_8", "10.0,50.0,1.0")

    u = Usage()
    u.add(input=1_000_000, output=1_000_000)

    with pytest.warns(UserWarning, match="malformed price override"):
        r = price("claude-opus-4-8", u)

    assert r.cost_usd == pytest.approx(30.00)


def test_env_override_does_not_leak(monkeypatch):
    """monkeypatch auto-restores the env; this test just confirms isolation."""
    monkeypatch.setenv("CLAUDEBACKEND_PRICE_CLAUDE_HAIKU_4_5", "99.0,99.0,9.9,12.375")

    u = Usage()
    u.add(input=1_000_000)

    r = price("claude-haiku-4-5", u)
    assert r.cost_usd == pytest.approx(99.0)


def test_env_override_unknown_model_unknown_env_stays_none():
    """No env set for this model, and it's not in the table → None."""
    u = Usage()
    u.add(input=1_000_000)

    r = price("some-future-model", u)

    assert r.pricing_known is False
    assert r.cost_usd is None
