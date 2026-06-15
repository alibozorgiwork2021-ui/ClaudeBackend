import pytest

from claudebackend.core.context_builder import build_context
from claudebackend.core.depgraph import Graph
from claudebackend.core.limits import ContextWindowExceededError
from claudebackend.models import PlanStep


def _step(path, action="modify", instructions="do the thing"):
    return PlanStep(path=path, action=action, instructions=instructions)


def _flatten(ctx):
    parts = [b["text"] for b in ctx["system"]]
    for msg in ctx["messages"]:
        parts += [b["text"] for b in msg["content"]]
    return "\n".join(parts)


def test_context_includes_target_objective_and_readonly_deps(tmp_path):
    (tmp_path / "mathutils.py").write_text(
        "def keys_of(d):\n    return d.keys()\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text(
        "from mathutils import keys_of\nx = keys_of({})\n", encoding="utf-8"
    )
    graph = Graph(edges={"app.py": {"mathutils.py"}, "mathutils.py": set()})

    ctx = build_context("Refactor utils", _step("app.py"), graph, tmp_path, "py310")
    blob = _flatten(ctx)

    assert "from mathutils import keys_of" in blob  # target source
    assert "def keys_of" in blob  # dependency source
    assert "READ-ONLY" in blob
    assert "py310" in blob
    assert "Refactor utils" in blob  # objective present


def test_context_marks_system_and_deps_cacheable(tmp_path):
    (tmp_path / "dep.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("from dep import VALUE\n", encoding="utf-8")
    graph = Graph(edges={"main.py": {"dep.py"}, "dep.py": set()})

    ctx = build_context("obj", _step("main.py"), graph, tmp_path, "py310")

    assert any(b.get("cache_control") for b in ctx["system"])
    user_blocks = ctx["messages"][0]["content"]
    assert any(b.get("cache_control") and "dep.py" in b["text"] for b in user_blocks)


def test_context_with_no_deps_has_no_dep_block(tmp_path):
    (tmp_path / "solo.py").write_text("x = 1\n", encoding="utf-8")
    graph = Graph(edges={"solo.py": set()})

    ctx = build_context("obj", _step("solo.py"), graph, tmp_path, "py310")

    # exactly one user content block (the step), no read-only dep block
    blocks = ctx["messages"][0]["content"]
    assert len(blocks) == 1
    assert "READ-ONLY" not in blocks[0]["text"]


def test_context_retry_appends_prior_errors(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    graph = Graph(edges={"m.py": set()})

    ctx = build_context(
        "obj", _step("m.py"), graph, tmp_path, "py310", prior_errors=["BOOM-42"]
    )

    assert "BOOM-42" in _flatten(ctx)


def test_context_includes_extra_deps(tmp_path):
    (tmp_path / "a.py").write_text("import b\nA = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\nB = 2\n", encoding="utf-8")
    graph = Graph(edges={"a.py": {"b.py"}, "b.py": {"a.py"}})

    ctx = build_context("obj", _step("a.py"), graph, tmp_path, "py310", extra_deps=["b.py"])
    blob = _flatten(ctx)

    assert "B = 2" in blob  # extra dependency provided as read-only context


def test_context_create_step_has_no_target_source(tmp_path):
    graph = Graph(edges={})

    ctx = build_context(
        "obj", _step("new/module.py", action="create"), graph, tmp_path, "py310"
    )
    blob = _flatten(ctx)

    assert "FILE TO CREATE" in blob
    assert "new file" in blob.lower()


def test_max_context_drops_dep_block_to_fit(tmp_path):
    # A large read-only dependency is dropped first so the step still fits.
    (tmp_path / "dep.py").write_text("x = 1\n" * 2000, encoding="utf-8")
    (tmp_path / "app.py").write_text("import dep\n", encoding="utf-8")
    graph = Graph(edges={"app.py": {"dep.py"}, "dep.py": set()})

    ctx = build_context(
        "obj", _step("app.py"), graph, tmp_path, "py310", max_context_tokens=400
    )
    blob = _flatten(ctx)

    assert "--- dep.py ---" not in blob  # dependency block dropped to fit the window
    assert "app.py" in blob  # the step itself is still present


def test_max_context_raises_when_step_too_big(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n" * 5000, encoding="utf-8")  # huge target
    graph = Graph(edges={"app.py": set()})

    with pytest.raises(ContextWindowExceededError):
        build_context(
            "obj", _step("app.py"), graph, tmp_path, "py310", max_context_tokens=50
        )


def test_task_context_block_present_from_first_attempt(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    graph = Graph(edges={"app.py": set()})

    ctx = build_context(
        "obj", _step("app.py"), graph, tmp_path, "py310",
        task_context="E   AssertionError: expected 42",
    )
    blob = _flatten(ctx)

    assert "FAILING TEST OUTPUT" in blob
    assert "AssertionError: expected 42" in blob


def test_no_enforcement_when_budget_none(tmp_path):
    # max_context_tokens=None keeps the previous unbounded behaviour.
    (tmp_path / "dep.py").write_text("x = 1\n" * 2000, encoding="utf-8")
    (tmp_path / "app.py").write_text("import dep\n", encoding="utf-8")
    graph = Graph(edges={"app.py": {"dep.py"}, "dep.py": set()})

    ctx = build_context("obj", _step("app.py"), graph, tmp_path, "py310")
    assert "--- dep.py ---" in _flatten(ctx)  # deps retained, nothing dropped
