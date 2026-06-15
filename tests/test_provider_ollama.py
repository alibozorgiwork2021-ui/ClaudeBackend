from types import SimpleNamespace

from claudebackend.core.providers.ollama import OllamaProvider, default_base_url


def _chunk(content=None, finish=None):
    choice = SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish)
    return SimpleNamespace(choices=[choice])


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _sdk(responses):
    comps = _Completions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=comps), _comps=comps)


def test_default_base_url_is_localhost(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert default_base_url() == "http://localhost:11434/v1"


def test_default_base_url_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    assert default_base_url() == "http://ollama:11434/v1"


def test_builds_openai_sdk_with_local_defaults(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("OLLAMA_MAX_RETRIES", raising=False)
    monkeypatch.setattr("openai.OpenAI", fake_openai)

    OllamaProvider(model="qwen2.5-coder")

    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"  # dummy placeholder; Ollama ignores it
    assert captured["timeout"] == 600.0
    assert captured["max_retries"] == 3


def test_timeout_and_retries_env_override(monkeypatch):
    captured = {}
    monkeypatch.setattr("openai.OpenAI", lambda **kw: captured.update(kw) or object())
    monkeypatch.setenv("OLLAMA_TIMEOUT", "30")
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "1")

    OllamaProvider(model="m")

    assert captured["timeout"] == 30.0
    assert captured["max_retries"] == 1


def test_stream_text_uses_model_and_override():
    sdk = _sdk([[_chunk("ok", "stop")]])
    p = OllamaProvider(model="base", sdk=sdk)
    text, stop = p.stream_text([{"role": "user", "content": "x"}])
    assert (text, stop) == ("ok", "end_turn")
    assert sdk._comps.calls[0]["model"] == "base"

    sdk2 = _sdk([[_chunk("ok", "stop")]])
    p2 = OllamaProvider(model="base", sdk=sdk2)
    p2.stream_text([{"role": "user", "content": "x"}], model="override")
    assert sdk2._comps.calls[0]["model"] == "override"
