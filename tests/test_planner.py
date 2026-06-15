from unittest.mock import MagicMock

from claudebackend.agents.planner import plan
from claudebackend.core.depgraph import Graph
from claudebackend.models import ExecutionPlan, PlanStep


def test_plan_calls_parse_with_execution_plan_and_returns_it():
    client = MagicMock()
    expected = ExecutionPlan(
        objective="Add a thing",
        steps=[PlanStep(path="a.py", action="modify", instructions="change it")],
    )
    client.parse.return_value = expected

    graph = Graph(
        edges={"a.py": set(), "b.py": {"a.py"}},
        kinds={"a.py": "python", "b.py": "python"},
    )
    out = plan(client, "Add a thing", graph)

    assert out is expected
    messages, output_model = client.parse.call_args.args
    assert output_model is ExecutionPlan
    content = messages[0]["content"]
    # the objective and the codebase map are both in the prompt
    assert "Add a thing" in content
    assert "a.py" in content and "b.py" in content


def test_plan_prompt_flags_dynamic_imports():
    client = MagicMock()
    client.parse.return_value = ExecutionPlan(objective="obj", steps=[])
    graph = Graph(edges={"d.py": set()}, dynamic={"d.py"}, kinds={"d.py": "python"})

    plan(client, "obj", graph)

    content = client.parse.call_args.args[0][0]["content"]
    assert "d.py" in content
    assert "dynamic" in content.lower()
