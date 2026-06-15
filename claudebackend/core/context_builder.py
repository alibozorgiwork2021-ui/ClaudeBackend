"""Assemble the Coder's request for a single execution-plan step.

The system prompt (always stable) and the read-only related-file block (stable
across a step's retries) carry ``cache_control`` so repeated calls read from
cache instead of re-paying full input cost. The volatile step + prior errors go
last, uncached.
"""

from __future__ import annotations

from pathlib import Path

from claudebackend import prompts
from claudebackend.core.depgraph import Graph
from claudebackend.core.limits import ContextWindowExceededError
from claudebackend.models import PlanStep

_CACHE = {"type": "ephemeral"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _est_tokens(blocks: list[dict]) -> int:
    """Cheap, provider-agnostic estimate (~4 chars/token) over text blocks."""
    return sum(len(b.get("text", "")) for b in blocks) // 4


def build_context(
    objective: str,
    step: PlanStep,
    graph: Graph,
    root,
    target_version: str,
    extra_deps=(),
    prior_errors: list[str] | None = None,
    security_errors: list[str] | None = None,
    max_context_tokens: int | None = None,
    task_context: str | None = None,
    driver=None,
) -> dict:
    """Return ``{"system": [...blocks], "messages": [user message]}`` for a step.

    The target file's current contents are included when it exists (empty for a
    ``create`` step). ``extra_deps`` lets the orchestrator add extra read-only
    context paths beyond the graph's recorded dependencies.

    When ``max_context_tokens`` is set (local models, to avoid OOM) the assembled
    request must fit that input budget: the read-only dependency block is dropped
    first, and if the bare step still overflows a ``ContextWindowExceededError`` is
    raised. ``None`` (cloud/Anthropic) keeps the previous unbounded behaviour.
    """
    root = Path(root)
    target_file = root / step.path
    target_source = _read(target_file) if target_file.exists() else ""

    dep_paths = set(graph.edges.get(step.path, set())) | set(extra_deps)
    dep_paths.discard(step.path)
    dependencies = {
        d: _read(root / d) for d in sorted(dep_paths) if (root / d).exists()
    }

    system = [{"type": "text", "text": prompts.CODER_SYSTEM, "cache_control": _CACHE}]

    content = []
    deps_block = None
    if dependencies:
        deps_block = {
            "type": "text",
            "text": prompts.deps_block_text(dependencies),
            "cache_control": _CACHE,
        }
        content.append(deps_block)
    version_label = (
        driver.version_label() if driver is not None else "Target Python version"
    )
    content.append(
        {
            "type": "text",
            "text": prompts.step_block_text(
                objective, step, target_source, target_version, prior_errors,
                security_errors, task_context, version_label=version_label,
            ),
        }
    )

    if max_context_tokens is not None:
        total = _est_tokens(system) + _est_tokens(content)
        if total > max_context_tokens and deps_block is not None:
            content.remove(deps_block)  # drop read-only context first
            total = _est_tokens(system) + _est_tokens(content)
        if total > max_context_tokens:
            raise ContextWindowExceededError(
                f"step '{step.path}' needs ~{total} input tokens but the model's "
                f"context budget is {max_context_tokens}. Use a larger-context "
                f"model or raise CLAUDEBACKEND_CONTEXT_<MODEL>."
            )

    return {"system": system, "messages": [{"role": "user", "content": content}]}
