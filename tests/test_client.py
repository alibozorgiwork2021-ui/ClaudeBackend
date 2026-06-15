from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from claudebackend.core.client import MODEL, Client, RefusalError


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


def _msg(stop_reason="end_turn", parsed_output=None):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output)


def test_parse_returns_parsed_output_with_right_params():
    sdk = MagicMock()
    sentinel = object()
    sdk.messages.parse.return_value = _msg(parsed_output=sentinel)
    model_cls = object()

    out = Client(sdk=sdk).parse([{"role": "user", "content": "hi"}], model_cls)

    assert out is sentinel
    kwargs = sdk.messages.parse.call_args.kwargs
    assert kwargs["model"] == MODEL
    assert kwargs["output_format"] is model_cls
    assert kwargs["max_tokens"] <= 16000


def test_parse_raises_on_refusal():
    sdk = MagicMock()
    sdk.messages.parse.return_value = _msg(stop_reason="refusal")
    with pytest.raises(RefusalError):
        Client(sdk=sdk).parse([], object())


def test_stream_text_accumulates_and_returns_stop_reason():
    sdk = MagicMock()
    sdk.messages.stream.return_value = _FakeStream(["mig", "rated"], _msg("end_turn"))

    text, stop = Client(sdk=sdk).stream_text([{"role": "user", "content": "x"}])

    assert text == "migrated"
    assert stop == "end_turn"
    kwargs = sdk.messages.stream.call_args.kwargs
    assert kwargs["model"] == MODEL
    assert kwargs["max_tokens"] == 64000


def test_stream_text_raises_on_refusal():
    sdk = MagicMock()
    sdk.messages.stream.return_value = _FakeStream([], _msg("refusal"))
    with pytest.raises(RefusalError):
        Client(sdk=sdk).stream_text([])


def test_estimate_tokens():
    sdk = MagicMock()
    sdk.messages.count_tokens.return_value = SimpleNamespace(input_tokens=42)
    assert Client(sdk=sdk).estimate_tokens([{"role": "user", "content": "x"}]) == 42
