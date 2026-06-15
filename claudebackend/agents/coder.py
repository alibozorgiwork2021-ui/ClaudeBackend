"""Coder agent: stream the implemented file as plain text.

One streaming call per execution-plan step. The model is instructed to emit only
the full new contents of the target file; we strip a single optional Markdown
fence. A ``max_tokens`` stop reason means the output was truncated (file too large
for one call) and is a failure, not a partial success.
"""

from __future__ import annotations

from claudebackend.models import FileResult, PlanStep


class CoderError(RuntimeError):
    """The Coder could not produce usable file contents for a step."""


def strip_code_fence(text: str) -> str:
    """Remove one optional leading ```/```python fence and its closing ```."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    lines = lines[1:]  # drop the opening fence line
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def implement(client, step: PlanStep, context: dict, model: str | None = None) -> FileResult:
    """Implement one plan step. Returns the full new contents of ``step.path``."""
    text, stop_reason = client.stream_text(
        context["messages"], system=context["system"], model=model
    )
    if stop_reason == "max_tokens":
        raise CoderError(
            f"{step.path}: response truncated (max_tokens) — file too large "
            "for a single call"
        )
    code = strip_code_fence(text)
    if not code:
        raise CoderError(f"{step.path}: model returned no code")
    return FileResult(path=step.path, code=code, notes="")
