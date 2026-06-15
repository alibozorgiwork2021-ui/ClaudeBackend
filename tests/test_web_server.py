"""Tests for the optional local dashboard server (the [web] extra).

Skipped entirely when Starlette is not installed. A FakeClient drives a full pipeline
run through the real server (HTTP + SSE) with no LLM and no network.
"""

import json
import time
import types

import pytest

pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from claudebackend.core import git  # noqa: E402
from claudebackend.core.pricing import Usage, price  # noqa: E402
from claudebackend.models import (  # noqa: E402
    ExecutionPlan,
    PlanStep,
    SecurityReview,
)
from claudebackend.web import _is_loopback, run_server  # noqa: E402
from claudebackend.web.app import create_app  # noqa: E402
from claudebackend.web.runs import RunRegistry  # noqa: E402


class FakeClient:
    def __init__(self, outputs, plan, security=None):
        self.outputs = outputs
        self.plan = plan
        self.security = security

    def estimate_tokens(self, messages):
        return 10

    def parse(self, messages, output_model, model=None):
        if output_model is SecurityReview:
            return self.security or SecurityReview(ok=True)
        return self.plan

    def stream_text(self, messages, system=None, model=None):
        text = "\n".join(b["text"] for b in messages[0]["content"])
        for path, code in self.outputs.items():
            if f"=== {path} ===" in text:
                return code, "end_turn"
        raise AssertionError("no canned output")


class CostFakeClient(FakeClient):
    def __init__(self, outputs, plan, model="claude-opus-4-8"):
        super().__init__(outputs, plan)
        self.model = model
        self.usage = Usage(input_tokens=1000, output_tokens=200, calls=2)

    def cost_report(self):
        return price(self.model, self.usage)


_PLAN = ExecutionPlan(
    objective="o",
    steps=[PlanStep(path="a.py", action="modify", instructions="touch")],
)
_OUTPUTS = {"a.py": "VALUE = 2\n"}


def _client(factory):
    return TestClient(create_app(registry=RunRegistry(), client_factory=factory))


def _make_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo


def _wait_done(client, rid, tries=300):
    for _ in range(tries):
        status = client.get(f"/api/runs/{rid}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError(f"run {rid} did not finish")


def _collect_frames(client, rid):
    frames = []
    with client.stream("GET", f"/api/runs/{rid}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                fr = json.loads(line[len("data: "):])
                frames.append(fr)
                if fr["type"] in ("done", "error"):
                    break
    return frames


# --- air-gap / lazy-extra guards -------------------------------------------------


def test_is_loopback():
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("localhost")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback("")  # empty host == bind-all, not loopback


def test_run_server_refuses_non_loopback_without_allow_remote():
    with pytest.raises(RuntimeError, match="non-loopback"):
        run_server(host="0.0.0.0", allow_remote=False)


def test_health_is_air_gapped():
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "air_gapped": True, "allow_remote": False}


# --- run lifecycle + SSE ---------------------------------------------------------


def test_dry_run_streams_events_and_done_carries_report(tmp_path):
    repo = _make_repo(tmp_path)
    git.init_baseline(repo)
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))

    created = client.post("/api/runs", json={"path": str(repo), "objective": "o"})
    assert created.status_code == 201
    rid = created.json()["id"]
    assert created.json()["dry_run"] is True

    _wait_done(client, rid)
    frames = _collect_frames(client, rid)

    types = [f["type"] for f in frames]
    assert types[0] == "hello"
    assert "depgraph" in types and "plan" in types and "verify" in types
    assert types.index("depgraph") < types.index("plan") < types.index("verify")
    assert types[-1] == "done"

    done = frames[-1]
    assert done["data"]["dry_run"] is True
    assert done["data"]["lang"] == "python"
    assert "VALUE = 2" in done["data"]["diff"]  # dry-run preview diff in the report


def test_graph_endpoint_serves_vis_network_payload(tmp_path):
    repo = _make_repo(tmp_path)
    git.init_baseline(repo)
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))

    rid = client.post("/api/runs", json={"path": str(repo), "objective": "o"}).json()["id"]
    _wait_done(client, rid)

    graph = client.get(f"/api/runs/{rid}/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert "nodes" in payload and "edges" in payload
    assert any(n["id"] == "a.py" for n in payload["nodes"])


def test_live_cost_counters_present(tmp_path):
    repo = _make_repo(tmp_path)
    git.init_baseline(repo)
    client = _client(lambda body: CostFakeClient(_OUTPUTS, _PLAN))

    rid = client.post(
        "/api/runs", json={"path": str(repo), "objective": "o"}
    ).json()["id"]
    _wait_done(client, rid)
    frames = _collect_frames(client, rid)

    costed = [f for f in frames if f["cost"] is not None]
    assert costed, "expected at least one frame with a live cost snapshot"
    cost = costed[-1]["cost"]
    assert set(cost) == {
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
        "cost_usd", "pricing_known", "cache_hit_ratio", "calls",
    }


def test_unknown_run_404(tmp_path):
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/graph").status_code == 404


# --- human-in-the-loop review (git safety) ---------------------------------------


def test_review_reject_reverts_on_feature_branch_main_untouched(tmp_path):
    repo = _make_repo(tmp_path)
    git.init_baseline(repo)
    default_branch = git.current_branch(repo)
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))

    rid = client.post(
        "/api/runs", json={"path": str(repo), "objective": "o", "dry_run": False}
    ).json()["id"]
    _wait_done(client, rid)

    # The live run committed the change on an isolated feature branch.
    feature = git.current_branch(repo)
    assert feature.startswith("claudebackend/")
    assert (repo / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    resp = client.post(
        f"/api/runs/{rid}/review",
        json={"decisions": [{"path": "a.py", "decision": "reject"}]},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["reverted"] == ["a.py"]
    assert result["main_untouched"] is True

    # File restored to its baseline, the revert landed on the feature branch, and the
    # protected default branch was never checked out.
    assert (repo / "a.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert git.current_branch(repo) == feature
    assert feature != default_branch


def test_review_on_dry_run_is_409(tmp_path):
    repo = _make_repo(tmp_path)
    git.init_baseline(repo)
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))

    rid = client.post("/api/runs", json={"path": str(repo), "objective": "o"}).json()["id"]
    _wait_done(client, rid)

    resp = client.post(
        f"/api/runs/{rid}/review",
        json={"decisions": [{"path": "a.py", "decision": "reject"}]},
    )
    assert resp.status_code == 409


def test_live_run_init_on_non_repo_is_reviewable(tmp_path):
    # A live run that initialises a brand-new repo must still capture a revert
    # baseline (the worker creates it), so reject works (regression for the review fix).
    repo = _make_repo(tmp_path)  # NOT a git repo yet
    client = _client(lambda body: FakeClient(_OUTPUTS, _PLAN))

    rid = client.post(
        "/api/runs",
        json={"path": str(repo), "objective": "o", "dry_run": False, "init": True},
    ).json()["id"]
    _wait_done(client, rid)

    feature = git.current_branch(repo)
    assert feature.startswith("claudebackend/")
    assert (repo / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    resp = client.post(
        f"/api/runs/{rid}/review",
        json={"decisions": [{"path": "a.py", "decision": "reject"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["reverted"] == ["a.py"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "VALUE = 1\n"


# --- review guards (unit) --------------------------------------------------------


def test_apply_review_refuses_while_running():
    from claudebackend.web.review import ReviewError, apply_review

    handle = types.SimpleNamespace(
        dry_run=False, status="running", baseline_sha="abc", root="."
    )
    with pytest.raises(ReviewError, match="in progress"):
        apply_review(handle, [{"path": "a.py", "decision": "reject"}])


def test_apply_review_rejects_path_traversal():
    from claudebackend.web.review import ReviewError, apply_review

    handle = types.SimpleNamespace(
        dry_run=False, status="done", baseline_sha="abc", root="."
    )
    for bad in ("../escape.py", "/etc/passwd"):
        with pytest.raises(ReviewError):
            apply_review(handle, [{"path": bad, "decision": "reject"}])


def test_registry_has_active_run(tmp_path):
    reg = RunRegistry()
    h = reg.create(str(tmp_path), objective="o", dry_run=False, lang="python")
    assert reg.has_active_run(str(tmp_path)) is True
    h.status = "done"
    assert reg.has_active_run(str(tmp_path)) is False
    assert reg.has_active_run(str(tmp_path / "other")) is False


# --- serialize unit tests --------------------------------------------------------


def test_serialize_event_frame_and_cost_snapshot():
    from claudebackend.core import events
    from claudebackend.web import serialize

    ev = events.DepGraphDone(files=3, dynamic=0, kinds={"python": 3},
                             graph={"nodes": [], "edges": []})
    fr = serialize.event_frame(ev, run_id="r1", seq=0, ts=1.0)
    assert fr["type"] == "depgraph"
    assert fr["run_id"] == "r1" and fr["seq"] == 0
    assert fr["data"]["files"] == 3 and fr["data"]["graph"] == {"nodes": [], "edges": []}
    assert fr["cost"] is None

    assert serialize.cost_snapshot(None) is None
    snap = serialize.cost_snapshot(CostFakeClient(_OUTPUTS, _PLAN))
    assert snap["input_tokens"] == 1000 and snap["calls"] == 2
