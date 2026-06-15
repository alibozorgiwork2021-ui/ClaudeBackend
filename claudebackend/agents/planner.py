"""Planner agent: turn a user objective into an ordered ExecutionPlan.

The Planner is the driver of the pipeline. Given an arbitrary objective and a map
of the existing codebase (Python modules, ORM models, Dockerfiles, config — built
by ``depgraph``), it decides which files to create, modify, or delete and in what
order. It does not write code; the Coder implements each step.
"""

from __future__ import annotations

from claudebackend import prompts
from claudebackend.core.depgraph import Graph, graph_summary
from claudebackend.models import ExecutionPlan


def plan(client, objective: str, graph: Graph, model: str | None = None) -> ExecutionPlan:
    summary = graph_summary(graph)
    message = {
        "role": "user",
        "content": prompts.planner_prompt(objective, summary, graph.dynamic),
    }
    return client.parse([message], ExecutionPlan, model=model)
