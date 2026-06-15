from typer.testing import CliRunner

import claudebackend.cli as cli_mod
from claudebackend.models import (
    ExecutionPlan,
    PlanStep,
    SecurityFinding,
    SecurityReview,
)

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


def test_help_lists_develop():
    res = runner.invoke(cli_mod.app, ["--help"])
    assert res.exit_code == 0
    assert "develop" in res.output


def test_help_lists_watch_and_ci():
    res = runner.invoke(cli_mod.app, ["--help"])
    assert "watch" in res.output
    assert "ci" in res.output


def test_is_ci_detects_env(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("CI", "true")
    assert cli_mod._is_ci() is True
    monkeypatch.delenv("CI", raising=False)
    assert cli_mod._is_ci() is False
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cli_mod._is_ci() is True


def test_ci_env_forces_non_interactive(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("CI", "true")
    captured = {}

    def fake_develop_feature(path, **kw):
        captured.update(kw)
        return cli_mod.DevReport(objective="o", dry_run=True)

    monkeypatch.setattr(cli_mod, "develop_feature", fake_develop_feature)
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: object())

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run"])

    assert res.exit_code == 0, res.output
    assert captured["assume_yes"] is True  # CI auto-skips the cost prompt


def test_develop_help_lists_options():
    res = runner.invoke(cli_mod.app, ["develop", "--help"])
    assert res.exit_code == 0
    assert "--dry-run" in res.output
    assert "--init" in res.output
    assert "--local" in res.output


def test_develop_help_lists_security_gate():
    res = runner.invoke(cli_mod.app, ["develop", "--help"])
    assert res.exit_code == 0
    assert "security-gate" in res.output  # --security-gate / --no-security-gate


class BlockingClient(FakeClient):
    """Like FakeClient but the Red Team audit always reports a blocking vuln."""

    def parse(self, messages, output_model, model=None):
        if output_model is SecurityReview:
            return SecurityReview(
                ok=False,
                findings=[SecurityFinding(file="a.py", severity="high",
                                          issue="SQL injection")],
            )
        return super().parse(messages, output_model, model)


def test_security_rejection_and_discard_shown(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: BlockingClient({"a.py": "print('A')\n"})
    )

    res = runner.invoke(
        cli_mod.app,
        ["develop", str(tmp_path), "obj", "--dry-run", "--max-retries", "1"],
    )

    assert res.exit_code == 0, res.output
    assert "! SECURITY:" in res.stdout  # prominent live rejection line
    assert "Discarded (unsafe" in res.stdout  # report lists the discarded file


def test_local_flag_routes_to_ollama(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    monkeypatch.delenv("CLAUDEBACKEND_LOCAL", raising=False)
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return FakeClient({"a.py": "print('A')\n"})

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(
        cli_mod.app,
        ["develop", str(tmp_path), "obj", "--dry-run", "--local",
         "--model", "qwen2.5-coder"],
    )

    assert res.exit_code == 0, res.output
    assert seen["provider"] == "ollama"
    assert seen["local"] is True


def test_develop_dry_run_writes_nothing(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('A')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run"])

    assert res.exit_code == 0, res.output
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == 'print("a")\n'  # untouched


def test_develop_non_repo_without_init_exits_nonzero(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('A')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj"])  # no --init

    assert res.exit_code == 1
    assert "not a git repository" in res.output.lower()


def test_use_subscription_flag_passed_to_client(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return FakeClient({"a.py": "print('A')\n"})

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(
        cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "--use-subscription"]
    )

    assert res.exit_code == 0, res.output
    assert seen.get("use_subscription") is True


def test_subscription_auth_error_exits_nonzero(tmp_path, monkeypatch):
    from claudebackend.core.client import SubscriptionAuthError

    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    def factory(**kw):
        raise SubscriptionAuthError("No Claude subscription login found.")

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--use-subscription"])

    assert res.exit_code == 1
    assert "subscription login" in res.output.lower()


def test_provider_and_model_passed_to_client(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return FakeClient({"a.py": "print('A')\n"})

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(
        cli_mod.app,
        ["develop", str(tmp_path), "obj", "--dry-run", "--provider", "openai",
         "--model", "gpt-x"],
    )

    assert res.exit_code == 0, res.output
    assert seen.get("provider") == "openai"
    assert seen.get("model") == "gpt-x"


def test_provider_config_error_exits_nonzero(tmp_path, monkeypatch):
    from claudebackend.core.client import ProviderConfigError

    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    def factory(**kw):
        raise ProviderConfigError("--model is required for provider 'openai'.")

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--provider", "openai"])

    assert res.exit_code == 1
    assert "model is required" in res.output.lower()


# ---------------------------------------------------------------------------
# progress reporter, cost line, --json / --report-json
# ---------------------------------------------------------------------------

import json  # noqa: E402
import sys  # noqa: E402

from claudebackend.core.pricing import Usage, price  # noqa: E402
from claudebackend.orchestrator import DevReport  # noqa: E402


class CostFakeClient(FakeClient):
    """FakeClient that also reports token usage / cost (like the real Client)."""

    def __init__(self, outputs, *, model="claude-opus-4-8"):
        super().__init__(outputs)
        self.model = model
        self.usage = Usage(
            input_tokens=1_500_000,
            output_tokens=2_300,
            cache_read_tokens=500_000,
            cache_write_tokens=0,
            calls=4,
        )

    def cost_report(self):
        return price(self.model, self.usage)


def _src(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")


def test_develop_help_lists_new_flags():
    res = runner.invoke(cli_mod.app, ["develop", "--help"])
    assert res.exit_code == 0
    out = res.output
    for flag in ("--verbose", "--quiet", "--json", "--report-json", "--no-cost"):
        assert flag in out, flag


def test_verbose_and_quiet_mutually_exclusive(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('A')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "-v", "-q"])

    assert res.exit_code != 0


def test_non_tty_progress_lines(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(cli_mod, "Client", lambda **kw: FakeClient({"a.py": "print('A')\n"}))

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run"])

    assert res.exit_code == 0, res.output
    out = res.stdout
    assert "[1/4]" in out
    assert "[2/4]" in out
    assert "[4/4]" in out
    assert "[3/4] develop:" in out  # single non-TTY line
    assert "\r" not in out  # no in-place carriage returns when piped


def test_cost_line_printed_by_default(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: CostFakeClient({"a.py": "print('A')\n"})
    )

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run"])

    assert res.exit_code == 0, res.output
    out = res.stdout
    assert "Cost  in " in out
    assert "~$" in out
    assert "(cache hit" in out


def test_quiet_suppresses_progress_but_keeps_summary_and_cost(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: CostFakeClient({"a.py": "print('A')\n"})
    )

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "--quiet"])

    assert res.exit_code == 0, res.output
    out = res.stdout
    assert "[1/4]" not in out  # no progress
    assert "Created" in out  # _print_report body present
    assert "Cost  in " in out  # cost line present


def test_no_cost_suppresses_cost_line(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: CostFakeClient({"a.py": "print('A')\n"})
    )

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "--no-cost"])

    assert res.exit_code == 0, res.output
    out = res.stdout
    assert "Created" in out
    assert "Cost  in " not in out


def test_json_output_is_pure_json(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: CostFakeClient({"a.py": "print('A')\n"})
    )

    res = runner.invoke(cli_mod.app, ["develop", str(tmp_path), "obj", "--dry-run", "--json"])

    assert res.exit_code == 0, res.output
    data = json.loads(res.stdout)
    assert data["schema_version"] == 2
    assert "ok" in data
    assert "cost" in data
    assert "diff" in data
    assert "[1/4]" not in res.stdout
    assert "Cost" not in res.stdout


def test_json_on_error_emits_json(tmp_path, monkeypatch):
    from claudebackend.core.client import ProviderConfigError

    _src(tmp_path)

    def factory(**kw):
        raise ProviderConfigError("--model is required for provider 'openai'.")

    monkeypatch.setattr(cli_mod, "Client", factory)

    res = runner.invoke(
        cli_mod.app, ["develop", str(tmp_path), "obj", "--provider", "openai", "--json"]
    )

    assert res.exit_code == 1
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert "error" in data


def test_report_json_written_and_human_report_printed(tmp_path, monkeypatch):
    _src(tmp_path)
    monkeypatch.setattr(
        cli_mod, "Client", lambda **kw: CostFakeClient({"a.py": "print('A')\n"})
    )
    out_path = tmp_path / "report.json"

    res = runner.invoke(
        cli_mod.app,
        ["develop", str(tmp_path), "obj", "--dry-run", "--report-json", str(out_path)],
    )

    assert res.exit_code == 0, res.output
    assert "Created" in res.stdout  # human report still printed
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert "cost" in data


def test_cp1252_safety(monkeypatch):
    """The cost line for a non-cp1252 model must not raise on a legacy console."""
    monkeypatch.setattr(sys, "stdout", _Cp1252Stdout(sys.stdout))

    report = DevReport(cost=price("modèl—λ", Usage(input_tokens=5, output_tokens=2)))
    line = cli_mod._cost_line(report)
    assert "cost unavailable" in line

    safe = cli_mod._safe(line)
    safe.encode("cp1252")  # would raise UnicodeEncodeError if _safe failed
    assert "modèl—λ" not in safe  # the offending chars were replaced


class _Cp1252Stdout:
    """Wrap a stream so ``.encoding`` reports cp1252 (exercises ``_safe``)."""

    encoding = "cp1252"

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def test_tty_verify_starts_on_fresh_line_after_retry(capsys):
    """On a TTY, a retry on the last step must not glue [4/4] onto the in-place line."""
    from claudebackend.core import events

    reporter = cli_mod._ConsoleReporter(quiet=False)
    reporter._tty = True  # force the in-place rendering path

    reporter(events.StepStart(index=2, total=2, path="b.py", action="modify"))
    reporter(events.FileRetry(path="b.py", attempt=1))
    reporter(events.ProjectVerifyResult(
        steps={"compile": "ok", "ruff": "ok", "pytest": "3 passed"}, ok=True
    ))

    out = capsys.readouterr().out
    assert any(line.startswith("[4/4] verify:") for line in out.splitlines())
    assert "pytest 3 passed" in out


def test_humantok_rounds_just_below_million_to_M():
    assert cli_mod.humantok(999_999) == "1.00M"
    assert cli_mod.humantok(1_500_000) == "1.50M"
    assert cli_mod.humantok(2_300) == "2k"
    assert cli_mod.humantok(999) == "999"
