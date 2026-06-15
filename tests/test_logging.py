"""Tests for side-effect-free library logging and CLI log configuration.

CliRunner in the installed Click (8.4.1) has NO ``mix_stderr`` parameter; it
already captures stdout and stderr separately, exposed as ``res.stdout`` and
``res.stderr``.  We use those directly.
"""

import logging

import pytest
from typer.testing import CliRunner

import claudebackend.cli as cli_mod
from claudebackend.models import ExecutionPlan, PlanStep, SecurityReview

runner = CliRunner()


class FakeClient:
    def __init__(self, outputs):
        self.outputs = outputs

    def estimate_tokens(self, messages):
        return 10

    def parse(self, messages, output_model, model=None):
        if output_model is SecurityReview:
            return SecurityReview(ok=True)
        return ExecutionPlan(
            objective="obj",
            steps=[
                PlanStep(path=p, action="modify", instructions="touch")
                for p in self.outputs
            ],
        )

    def stream_text(self, messages, system=None, model=None):
        text = "\n".join(b["text"] for b in messages[0]["content"])
        for path, code in self.outputs.items():
            if f"=== {path} ===" in text:
                return code, "end_turn"
        raise AssertionError("no canned output")


@pytest.fixture(autouse=True)
def _restore_logger():
    """Reset the ``claudebackend`` logger to its clean import state per test.

    ``_configure_logging`` mutates a module-global logger; other test files
    (e.g. test_cli.py) may have leaked a CLI StreamHandler into this process
    before us.  Strip any CLI-attached handlers and restore the default level
    both before AND after each test so ordering never matters.
    """
    logger = logging.getLogger("claudebackend")

    def _clean():
        for h in list(logger.handlers):
            if getattr(h, "_claudebackend_cli", False):
                logger.removeHandler(h)
        logger.setLevel(logging.NOTSET)

    _clean()
    try:
        yield
    finally:
        _clean()


def _cli_stream_handlers():
    logger = logging.getLogger("claudebackend")
    return [h for h in logger.handlers if getattr(h, "_claudebackend_cli", False)]


def test_import_only_attaches_null_handler(capsys):
    import claudebackend  # noqa: F401  (importing for its side effects)

    logger = logging.getLogger("claudebackend")
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)
    # No StreamHandler attached merely by importing the library.
    assert not any(type(h) is logging.StreamHandler for h in logger.handlers)

    # Emitting a record produces no output (NullHandler swallows it).
    logger.warning("should-not-appear")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_verbose_sets_debug_and_logs_to_stderr_only(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print "a"\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('a')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "-v"])

    assert res.exit_code == 0, res.output
    # The CLI attached exactly one stderr StreamHandler at DEBUG level.
    handlers = _cli_stream_handlers()
    assert len(handlers) == 1
    assert logging.getLogger("claudebackend").level == logging.DEBUG
    # Logs are actually EMITTED to stderr (INFO phase boundaries + DEBUG detail),
    # not merely enabled.  These are call sites the orchestrator/verifier emit.
    assert "INFO claudebackend.orchestrator: graph" in res.stderr
    assert "INFO claudebackend.orchestrator: project verify" in res.stderr
    assert "DEBUG claudebackend.core.verifier" in res.stderr
    # ...and logs never leak onto stdout (reserved for progress + JSON).
    assert "DEBUG claudebackend" not in res.stdout
    assert "INFO claudebackend" not in res.stdout


def test_default_run_emits_no_logs_to_stderr(tmp_path, monkeypatch):
    """No -v/-q: level is WARNING and we only emit INFO/DEBUG, so stderr is silent."""
    (tmp_path / "a.py").write_text('print "a"\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('a')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run"])

    assert res.exit_code == 0, res.output
    assert logging.getLogger("claudebackend").getEffectiveLevel() == logging.WARNING
    # No claudebackend log records reach stderr in default mode.
    assert "claudebackend" not in res.stderr


def test_quiet_sets_error_level(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print "a"\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('a')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "-q"])

    assert res.exit_code == 0, res.output
    assert logging.getLogger("claudebackend").getEffectiveLevel() == logging.ERROR


def test_configure_logging_does_not_duplicate_handlers():
    cli_mod._configure_logging(verbose=False, quiet=False)
    cli_mod._configure_logging(verbose=True, quiet=False)
    cli_mod._configure_logging(verbose=False, quiet=True)
    assert len(_cli_stream_handlers()) == 1  # repeated calls don't stack handlers


def test_json_stdout_is_pure_json_no_log_text(tmp_path, monkeypatch):
    import json

    (tmp_path / "a.py").write_text('print "a"\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('a')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "--json"])

    assert res.exit_code == 0, res.output
    # stdout must parse as JSON with no log lines mixed in.
    json.loads(res.stdout)
