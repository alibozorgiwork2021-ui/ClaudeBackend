from unittest.mock import MagicMock

import pytest

from claudebackend.agents.coder import CoderError, implement, strip_code_fence
from claudebackend.models import PlanStep


def _step(path="a.py", action="modify"):
    return PlanStep(path=path, action=action, instructions="do the thing")


def test_strip_code_fence_removes_python_fence():
    assert strip_code_fence("```python\nprint('x')\n```").strip() == "print('x')"


def test_strip_code_fence_removes_bare_fence():
    assert strip_code_fence("```\nx = 1\n```").strip() == "x = 1"


def test_strip_code_fence_passthrough_plain():
    assert strip_code_fence("x = 1\n").strip() == "x = 1"


def test_implement_returns_fileresult_and_passes_system():
    client = MagicMock()
    client.stream_text.return_value = ("```python\nprint('x')\n```", "end_turn")
    ctx = {"system": ["SYS"], "messages": ["MSGS"]}

    res = implement(client, _step("a.py"), ctx)

    assert res.path == "a.py"
    assert res.code.strip() == "print('x')"
    assert res.notes == ""
    args, kwargs = client.stream_text.call_args
    assert args[0] is ctx["messages"]
    assert kwargs["system"] is ctx["system"]


def test_implement_plain_text_no_fence():
    client = MagicMock()
    client.stream_text.return_value = ("y = 2\n", "end_turn")
    res = implement(client, _step("a.py"), {"system": [], "messages": []})
    assert res.code.strip() == "y = 2"


def test_implement_raises_on_truncation():
    client = MagicMock()
    client.stream_text.return_value = ("partial...", "max_tokens")
    with pytest.raises(CoderError):
        implement(client, _step("big.py"), {"system": [], "messages": []})
