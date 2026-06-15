"""Per-agent model routing configuration.

Lets you point each LLM agent at a different model — e.g. a fast model for the
Planner and a stronger one for the Coder/Verifier — which is most useful with the
local ``ollama`` provider. Nothing is hardcoded: the choice is resolved from, in
decreasing precedence:

1. CLI flags (``--planner-model`` / ``--coder-model`` / ``--verifier-model``),
2. environment (``CLAUDEBACKEND_MODEL_PLANNER`` / ``_CODER`` / ``_VERIFIER``),
3. the target project's ``pyproject.toml`` ``[tool.claudebackend.models]`` table,
4. the run-wide ``--model`` default.

The ``pyproject.toml`` source uses the stdlib ``tomllib`` (Python 3.11+); on 3.10
it is silently skipped (CLI/env still work), so no extra dependency is needed.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["ROLES", "resolve_models"]

ROLES = ("planner", "coder", "verifier")


def _load_pyproject_models(root) -> dict[str, str]:
    """Read ``[tool.claudebackend.models]`` from ``root/pyproject.toml`` if present."""
    if root is None:
        return {}
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        return {}
    pp = Path(root) / "pyproject.toml"
    if not pp.exists():
        return {}
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except Exception:
        return {}
    models = data.get("tool", {}).get("claudebackend", {}).get("models", {})
    return {r: models[r] for r in ROLES if isinstance(models.get(r), str)}


def resolve_models(
    default_model: str | None = None,
    cli_overrides: dict[str, str | None] | None = None,
    root=None,
) -> dict[str, str | None]:
    """Resolve the model for each agent role. A role with no specific setting
    falls back to ``default_model`` (which may be ``None`` → use the client's
    built-in default, e.g. Anthropic's ``MODEL``)."""
    cli_overrides = cli_overrides or {}
    pyproject = _load_pyproject_models(root)
    resolved: dict[str, str | None] = {}
    for role in ROLES:
        env_val = os.environ.get("CLAUDEBACKEND_MODEL_" + role.upper())
        resolved[role] = (
            cli_overrides.get(role)
            or env_val
            or pyproject.get(role)
            or default_model
        )
    return resolved
