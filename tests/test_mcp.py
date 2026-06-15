from claudebackend.core.pricing import Usage, price
from claudebackend.mcp_server import _run, mcp
from claudebackend.models import ExecutionPlan, PlanStep, SecurityReview

_EXPECTED_KEYS = {
    "objective", "dry_run", "branch", "lang", "project_ok", "project_errors",
    "created", "modified", "deleted", "flagged", "unsafe", "review", "summary",
    "graph", "diff", "cost", "security_issues",
}


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


class CostFakeClient(FakeClient):
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


def test_run_dry_run_returns_report_and_writes_nothing(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    report = _run(
        str(tmp_path), "obj", dry_run=True, client=FakeClient({"a.py": "print('A')\n"})
    )

    assert report["dry_run"] is True
    assert report["objective"] == "obj"
    assert "project_ok" in report
    assert "summary" in report
    # the real repo is untouched in dry-run
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == 'print("a")\n'
    assert report["diff"] is not None  # preview present for dry-run


def test_mcp_server_name():
    assert mcp.name == "claudebackend"


def test_security_key_present_and_none_by_default(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    result = _run(
        str(tmp_path), "obj", dry_run=True, client=FakeClient({"a.py": "print('A')\n"})
    )
    assert "security" in result
    assert result["security"] is None  # security review off by default


def test_local_env_builds_ollama_client(tmp_path, monkeypatch):
    import claudebackend.mcp_server as mcp_mod

    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")
    monkeypatch.setenv("CLAUDEBACKEND_LOCAL", "1")
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return FakeClient({"a.py": "print('A')\n"})

    monkeypatch.setattr(mcp_mod, "Client", factory)

    _run(str(tmp_path), "obj", dry_run=True, model="qwen2.5-coder")

    assert seen["provider"] == "ollama"  # CLAUDEBACKEND_LOCAL forced local mode
    assert seen["local"] is True


def test_cost_key_present_with_known_model(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    result = _run(
        str(tmp_path),
        "obj",
        dry_run=True,
        client=CostFakeClient({"a.py": "print('A')\n"}, model="claude-opus-4-8"),
    )

    cost = result["cost"]
    assert isinstance(cost, dict), "cost should be a dict for a known model"
    assert set(cost.keys()) == {
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
        "cost_usd", "pricing_known", "cache_hit_ratio", "calls",
    }
    assert cost["pricing_known"] is True
    assert isinstance(cost["cost_usd"], float) and cost["cost_usd"] > 0


def test_cost_key_none_when_no_cost_report(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    result = _run(
        str(tmp_path),
        "obj",
        dry_run=True,
        client=FakeClient({"a.py": "print('A')\n"}),
    )

    assert result["cost"] is None


def test_result_has_expected_keys(tmp_path):
    (tmp_path / "a.py").write_text('print("a")\n', encoding="utf-8")

    result = _run(
        str(tmp_path),
        "obj",
        dry_run=True,
        client=FakeClient({"a.py": "print('A')\n"}),
    )

    assert _EXPECTED_KEYS.issubset(result.keys())
