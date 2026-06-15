from claudebackend.core.limits import (
    DEFAULT_LOCAL_CONTEXT,
    context_window_for,
    input_budget_for,
)


def test_known_model_window():
    assert context_window_for("qwen2.5-coder") == 32768


def test_ollama_tag_is_stripped():
    assert context_window_for("qwen2.5-coder:7b") == 32768


def test_cloud_and_unknown_non_local_are_unbounded():
    assert context_window_for("claude-opus-4-8") is None
    assert context_window_for("some-unknown-model") is None
    assert context_window_for(None) is None


def test_unknown_local_uses_conservative_default(monkeypatch):
    monkeypatch.delenv("CLAUDEBACKEND_DEFAULT_CONTEXT", raising=False)
    assert context_window_for("totally-unknown", local=True) == DEFAULT_LOCAL_CONTEXT


def test_default_local_context_env_override(monkeypatch):
    monkeypatch.setenv("CLAUDEBACKEND_DEFAULT_CONTEXT", "1234")
    assert context_window_for("totally-unknown", local=True) == 1234


def test_per_model_env_override(monkeypatch):
    monkeypatch.setenv("CLAUDEBACKEND_CONTEXT_QWEN2_5_CODER", "4096")
    assert context_window_for("qwen2.5-coder") == 4096


def test_input_budget_reserves_output(monkeypatch):
    monkeypatch.delenv("CLAUDEBACKEND_OUTPUT_RESERVE", raising=False)
    assert input_budget_for("qwen2.5-coder") == 32768 - 2048


def test_input_budget_none_for_cloud():
    assert input_budget_for("claude-opus-4-8") is None


def test_input_budget_output_reserve_env(monkeypatch):
    monkeypatch.setenv("CLAUDEBACKEND_OUTPUT_RESERVE", "1000")
    assert input_budget_for("qwen2.5-coder") == 32768 - 1000
