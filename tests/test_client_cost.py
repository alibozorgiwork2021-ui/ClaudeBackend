"""Real token/cost accounting in Client and the OpenAI-compatible provider.

All sdks here are fakes; no network. Anthropic-path usage is read off the
response/final-message ``.usage``; compat-path usage is read off the per-call
``resp.usage`` (parse) and the final usage-bearing stream chunk (stream_text).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from claudebackend.core.client import Client
from claudebackend.core.pricing import CostReport
from claudebackend.core.providers.openai_compat import OpenAICompatProvider
from claudebackend.models import ExecutionPlan


# --- anthropic-path helpers -------------------------------------------------

class _FakeStream:
    def __init__(self, chunks, final):
        self.text_stream = iter(chunks)
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


def _anthropic_usage(input_tokens=10, output_tokens=2, cache_read=5, cache_write=1):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def _msg(stop_reason="end_turn", parsed_output=None, usage=None):
    ns = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output)
    if usage is not None:
        ns.usage = usage
    return ns


# --- anthropic parse --------------------------------------------------------

def test_parse_tallies_usage():
    sdk = MagicMock()
    sdk.messages.parse.return_value = _msg(parsed_output=object(), usage=_anthropic_usage())

    client = Client(sdk=sdk)
    client.parse([{"role": "user", "content": "hi"}], ExecutionPlan)

    assert client.usage.input_tokens == 10
    assert client.usage.output_tokens == 2
    assert client.usage.cache_read_tokens == 5
    assert client.usage.cache_write_tokens == 1
    assert client.usage.calls == 1
    assert client.usage.calls_without_usage == 0


def test_parse_no_usage_increments_calls_without_usage():
    sdk = MagicMock()
    sdk.messages.parse.return_value = _msg(parsed_output=object())  # no .usage

    client = Client(sdk=sdk)
    client.parse([], object())

    assert client.usage.calls == 1
    assert client.usage.calls_without_usage == 1
    assert client.usage.input_tokens == 0


# --- anthropic stream_text --------------------------------------------------

def test_stream_text_tallies_usage_and_return_unchanged():
    sdk = MagicMock()
    final = _msg("end_turn", usage=_anthropic_usage(input_tokens=7, output_tokens=3))
    sdk.messages.stream.return_value = _FakeStream(["mig", "rated"], final)

    client = Client(sdk=sdk)
    text, stop = client.stream_text([{"role": "user", "content": "x"}])

    assert (text, stop) == ("migrated", "end_turn")
    assert client.usage.input_tokens == 7
    assert client.usage.output_tokens == 3
    assert client.usage.calls == 1


def test_stream_text_no_usage_increments_calls_without_usage():
    sdk = MagicMock()
    sdk.messages.stream.return_value = _FakeStream(["x"], _msg("end_turn"))  # no .usage

    client = Client(sdk=sdk)
    client.stream_text([])

    assert client.usage.calls == 1
    assert client.usage.calls_without_usage == 1


# --- accumulation + cost report ---------------------------------------------

def test_usage_accumulates_across_calls():
    sdk = MagicMock()
    sdk.messages.parse.return_value = _msg(parsed_output=object(), usage=_anthropic_usage())
    final = _msg("end_turn", usage=_anthropic_usage())
    sdk.messages.stream.return_value = _FakeStream(["y"], final)

    client = Client(sdk=sdk)
    client.parse([], object())
    client.stream_text([])

    assert client.usage.calls == 2
    assert client.usage.input_tokens == 20  # 10 + 10
    assert client.usage.output_tokens == 4  # 2 + 2


def test_cost_report_priced_for_opus_on_anthropic_path():
    sdk = MagicMock()
    sdk.messages.parse.return_value = _msg(parsed_output=object(), usage=_anthropic_usage())

    client = Client(sdk=sdk)
    client.parse([], object())
    report = client.cost_report()

    assert isinstance(report, CostReport)
    assert report.model == "claude-opus-4-8"
    assert report.pricing_known is True
    assert report.cost_usd is not None and report.cost_usd > 0


# --- compat-path fakes ------------------------------------------------------

def _chunk(content=None, finish=None, usage=None):
    choice = SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish)
    ns = SimpleNamespace(choices=[choice])
    if usage is not None:
        ns.usage = usage
    return ns


def _usage_chunk(prompt_tokens, completion_tokens):
    # Final usage-bearing chunk: empty choices, carries .usage.
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


def _completion(content, finish="stop", usage=None):
    choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)
    ns = SimpleNamespace(choices=[choice])
    if usage is not None:
        ns.usage = usage
    return ns


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _provider(responses, usage):
    comps = _Completions(responses)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=comps))
    sdk._comps = comps
    return OpenAICompatProvider(model="m", sdk=sdk, usage=usage)


# --- compat stream_text -----------------------------------------------------

def test_compat_stream_passes_include_usage_and_tallies():
    from claudebackend.core.pricing import Usage

    usage = Usage()
    chunks = [_chunk("mig"), _chunk("rated"), _chunk(None, "stop"), _usage_chunk(11, 4)]
    p = _provider([chunks], usage)

    text, stop = p.stream_text([{"role": "user", "content": "x"}])

    assert (text, stop) == ("migrated", "end_turn")
    assert p._sdk._comps.calls[0]["stream_options"] == {"include_usage": True}
    assert usage.input_tokens == 11
    assert usage.output_tokens == 4
    assert usage.calls == 1


def test_compat_stream_no_usage_increments_calls_without_usage():
    from claudebackend.core.pricing import Usage

    usage = Usage()
    p = _provider([[_chunk("ok"), _chunk(None, "stop")]], usage)  # no usage chunk

    p.stream_text([{"role": "user", "content": "x"}])

    assert usage.calls == 1
    assert usage.calls_without_usage == 1


# --- compat parse -----------------------------------------------------------

def test_compat_parse_tallies_each_create():
    from claudebackend.core.pricing import Usage

    usage = Usage()
    bad = _completion("not json", usage=SimpleNamespace(prompt_tokens=8, completion_tokens=1))
    good = _completion(
        '{"objective": "o", "steps": []}',
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2),
    )
    p = _provider([bad, good], usage)

    out = p.parse([{"role": "user", "content": "plan"}], ExecutionPlan)

    assert out.steps == []
    assert usage.calls == 2  # both billed create() calls counted
    assert usage.input_tokens == 17  # 8 + 9
    assert usage.output_tokens == 3  # 1 + 2


# --- compat cost_report ---------------------------------------------------------

def _compat_client(model: str, responses: list) -> Client:
    """Build a compat-path Client with a fake SDK (no network/key needed)."""
    from types import SimpleNamespace

    comps = _Completions(responses)
    fake_sdk = SimpleNamespace(chat=SimpleNamespace(completions=comps))
    # provider="openrouter" uses the base_url preset; sdk= bypasses real OpenAI init
    return Client(provider="openrouter", model=model, sdk=fake_sdk)


def test_compat_cost_report_known_model():
    """claude-opus-4-8 is in the pricing table → pricing_known=True."""
    # stream_text needs at least one chunk; parse isn't called here
    chunks = [_chunk("hi"), _chunk(None, "stop"), _usage_chunk(5, 2)]
    client = _compat_client("claude-opus-4-8", [chunks])
    client.stream_text([{"role": "user", "content": "x"}])

    report = client.cost_report()
    assert report.pricing_known is True
    assert report.cost_usd is not None


def test_compat_cost_report_unknown_model():
    """An unknown model (not in pricing table) → pricing_known=False, cost_usd is None."""
    chunks = [_chunk("hi"), _chunk(None, "stop")]
    client = _compat_client("some/unknown-model", [chunks])
    client.stream_text([{"role": "user", "content": "x"}])

    report = client.cost_report()
    assert report.pricing_known is False
    assert report.cost_usd is None


# --- compat stream_text fallback when stream_options is rejected -----------------

def test_compat_stream_text_falls_back_when_stream_options_rejected():
    """If create() raises when stream_options is present, fall back without it."""
    from claudebackend.core.pricing import Usage
    from types import SimpleNamespace

    chunks = [_chunk("hello"), _chunk(None, "stop")]

    class _RejectStreamOptions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if "stream_options" in kwargs:
                raise ValueError("stream_options not supported by this provider")
            return iter(chunks)

    comps = _RejectStreamOptions()
    fake_sdk = SimpleNamespace(chat=SimpleNamespace(completions=comps))
    usage = Usage()
    p = OpenAICompatProvider(model="m", sdk=fake_sdk, usage=usage)

    text, stop = p.stream_text([{"role": "user", "content": "x"}])

    assert text == "hello"
    assert stop == "end_turn"
    # Two create() calls: first with stream_options (rejected), second without
    assert len(comps.calls) == 2
    assert "stream_options" in comps.calls[0]
    assert "stream_options" not in comps.calls[1]
    # No usage data from fallback path → calls_without_usage incremented
    assert usage.calls_without_usage == 1
