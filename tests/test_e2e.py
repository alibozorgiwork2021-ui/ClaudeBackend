"""End-to-end acceptance test: a real run on the py2 fixture.

Python 2 -> 3 modernisation is now just one example objective driven through the
generic pipeline. Skipped unless ANTHROPIC_API_KEY is set, so the default offline
suite stays free and network-free. Run with:  pytest -m e2e
"""

import os
import shutil
from pathlib import Path

import pytest

from claudebackend.core.verifier import verify_file

pytestmark = pytest.mark.e2e

FIXTURE = Path(__file__).parent / "fixtures" / "py2_sample"

OBJECTIVE = (
    "Migrate this Python 2 codebase to modern Python 3, preserving behaviour "
    "exactly (fix print statements, integer division, dict views, etc.)."
)


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="end-to-end run needs ANTHROPIC_API_KEY",
)
def test_end_to_end_py2_to_py3(tmp_path):
    from claudebackend.core.client import Client
    from claudebackend.orchestrator import develop_feature

    target = tmp_path / "py2_sample"
    shutil.copytree(FIXTURE, target)

    report = develop_feature(target, client=Client(), objective=OBJECTIVE, init=True)

    # (1) project verification passed: compile + ruff + the fixture's own pytest.
    assert report.project_ok, report.project_errors

    # (2) every file compiles under Python 3.
    for f in target.rglob("*.py"):
        assert verify_file(f).ok, f"{f} did not compile"

    # (3) no Python 2 print statements remain in the dependent file.
    assert 'print "' not in (target / "app.py").read_text(encoding="utf-8")

    # (4) a development summary and a topology graph were written.
    assert (target / "DEV_SUMMARY.md").exists()
    assert (target / "DEV_GRAPH.md").exists()
