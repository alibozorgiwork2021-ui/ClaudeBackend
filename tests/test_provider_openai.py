from types import SimpleNamespace

import pytest

from claudebackend.core.providers.base import RefusalError
from claudebackend.core.providers.openai_compat import OpenAICompatProvider
from claudebackend.models import ExecutionPlan


def _chunk(content=None, finish=None):
    choice = SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish)
    return SimpleNamespace(choices=[choice])


def _completion(content, finish="stop"):
    choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)
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
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=comps))
    sdk._comps = comps
    return sdk


def _provider(responses, model="m"):
    return OpenAICompatProvider(model=model, sdk=_sdk(responses))


def test_stream_text_accumulates_and_marks_end_turn():
    p = _provider([[_chunk("mig"), _chunk("rated"), _chunk(None, "stop")]])
    text, stop = p.stream_text([{"role": "user", "content": "x"}])
    assert text == "migrated"
    assert stop == "end_turn"
    assert p._sdk._comps.calls[0]["stream"] is True
    assert p._sdk._comps.calls[0]["model"] == "m"


def test_stream_text_length_finish_maps_to_max_tokens():
    p = _provider([[_chunk("partial"), _chunk(None, "length")]])
    _, stop = p.stream_text([{"role": "user", "content": "x"}])
    assert stop == "max_tokens"


def test_stream_text_content_filter_raises_refusal():
    p = _provider([[_chunk(None, "content_filter")]])
    with pytest.raises(RefusalError):
        p.stream_text([{"role": "user", "content": "x"}])


def test_flattens_system_and_block_content():
    p = _provider([[_chunk("ok", "stop")]])
    p.stream_text(
        [{"role": "user", "content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}],
        system=[{"type": "text", "text": "SYS"}],
    )
    sent = p._sdk._comps.calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "SYS"}
    assert sent[1] == {"role": "user", "content": "A\nB"}


def test_parse_validates_json():
    p = _provider([_completion('{"objective": "o", "steps": []}')])
    out = p.parse([{"role": "user", "content": "plan it"}], ExecutionPlan)
    assert isinstance(out, ExecutionPlan)
    assert out.steps == []


def test_parse_strips_code_fence():
    p = _provider([_completion('```json\n{"objective": "o", "steps": []}\n```')])
    out = p.parse([{"role": "user", "content": "plan"}], ExecutionPlan)
    assert out.steps == []


def test_parse_retries_on_invalid_then_succeeds():
    p = _provider(
        [_completion("not json at all"), _completion('{"objective": "o", "steps": []}')]
    )
    out = p.parse([{"role": "user", "content": "plan"}], ExecutionPlan)
    assert out.steps == []
    assert len(p._sdk._comps.calls) == 2


def test_estimate_tokens_heuristic():
    p = _provider([])
    assert p.estimate_tokens([{"role": "user", "content": "abcd" * 10}]) == 10
