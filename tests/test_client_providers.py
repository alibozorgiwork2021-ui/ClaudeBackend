import pytest

from claudebackend.core.client import Client, ProviderConfigError


def test_anthropic_is_default_and_uses_injected_sdk():
    c = Client(sdk=object())
    assert c.provider == "anthropic"
    assert c._compat is None


def test_openai_provider_requires_model():
    with pytest.raises(ProviderConfigError):
        Client(provider="openai")  # no model, no sdk


def test_openai_provider_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError):
        Client(provider="openai", model="gpt-x")  # no key, no injected sdk


def test_compat_provider_builds_with_injected_sdk():
    c = Client(provider="deepseek", model="deepseek-chat", sdk=object())
    assert c.provider == "deepseek"
    assert c._compat is not None


def test_ollama_provider_builds_without_api_key():
    c = Client(provider="ollama", model="qwen2.5-coder", sdk=object())
    assert c.provider == "ollama"
    assert c._compat is not None  # no API key required for local


def test_ollama_requires_model():
    with pytest.raises(ProviderConfigError):
        Client(provider="ollama", sdk=object())  # no model


def test_ollama_in_supported_providers():
    from claudebackend.core.client import SUPPORTED_PROVIDERS

    assert "ollama" in SUPPORTED_PROVIDERS


def test_local_rejects_non_ollama_provider():
    with pytest.raises(ProviderConfigError):
        Client(provider="anthropic", local=True, sdk=object())


def test_local_rejects_remote_base_url():
    with pytest.raises(ProviderConfigError):
        Client(provider="ollama", model="m", local=True,
               base_url="https://api.example.com/v1")


def test_local_allows_loopback_and_avoids_anthropic(monkeypatch):
    import sys

    # If the local path ever tried to construct the Anthropic SDK, importing it
    # would raise — proving the air-gap path never touches Anthropic.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    c = Client(provider="ollama", model="m", local=True,
               base_url="http://localhost:11434/v1", sdk=object())
    assert c.local is True
    assert c.provider == "ollama"


def test_subscription_only_allowed_with_anthropic():
    with pytest.raises(ProviderConfigError):
        Client(provider="openrouter", model="x", use_subscription=True, sdk=object())


def test_unknown_provider_errors():
    with pytest.raises(ProviderConfigError):
        Client(provider="bogus", model="x", sdk=object())


def test_compat_provider_uses_preset_base_url_and_env_key(monkeypatch):
    captured = {}

    def fake_openai(api_key=None, base_url=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return object()

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    monkeypatch.setenv("NVIDIA_API_KEY", "k-123")

    Client(provider="nvidia", model="m")

    assert captured["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert captured["api_key"] == "k-123"


def test_client_delegates_to_compat_provider():
    class FakeCompat:
        def parse(self, messages, output_model, model=None):
            return "PARSED"

        def stream_text(self, messages, system=None, model=None):
            return ("TEXT", "end_turn")

        def estimate_tokens(self, messages):
            return 7

    c = Client(provider="openai", model="x", sdk=object())
    c._compat = FakeCompat()
    assert c.parse([], None) == "PARSED"
    assert c.stream_text([]) == ("TEXT", "end_turn")
    assert c.estimate_tokens([]) == 7
