"""TDD glue: turn a failing test into an objective for the pipeline.

The watcher runs the project's own pytest suite, isolates the first failing test,
and hands its nodeid + output to the Coder so it implements the code that makes the
test pass.
"""

from __future__ import annotations

import re

from claudebackend.core.verifier import run_pytest

# pytest -q "short test summary info" lines look like:
#   FAILED tests/test_x.py::test_y - AssertionError: ...
#   ERROR  tests/test_x.py::test_z - ...
_SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)
# A verbose/other format where the verdict trails the nodeid.
_TRAILING_RE = re.compile(r"^(\S+::\S+)\s+(?:FAILED|ERROR)\b", re.MULTILINE)


def first_failing_nodeid(pytest_output: str) -> str | None:
    """Extract the first failing test's nodeid from pytest output, or None."""
    m = _SUMMARY_RE.search(pytest_output)
    if m:
        return m.group(1)
    m = _TRAILING_RE.search(pytest_output)
    if m:
        return m.group(1)
    return None


def find_first_failure(root) -> tuple[str, str] | None:
    """Run the suite; return ``(nodeid, pytest_output)`` for the first failing test,
    or ``None`` when the suite passes or collects nothing (rc 0 / 5)."""
    rc, out = run_pytest(root)
    if rc in (0, 5):
        return None
    nodeid = first_failing_nodeid(out) or "(unidentified test)"
    return nodeid, out.strip()


def tdd_objective(nodeid: str, pytest_output: str) -> str:
    """Phrase the failing test as an objective for the Planner/Coder."""
    return (
        f"A test is failing: `{nodeid}`. Implement or fix the backend/source code so "
        f"this test passes. Do NOT modify the test file and do NOT weaken the test; "
        f"make the smallest correct change that satisfies it.\n\n"
        f"pytest output:\n{pytest_output}"
    )
