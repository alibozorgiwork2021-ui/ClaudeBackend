"""Optional LLM security-review pass (advisory; never edits files).

Off by default; enabled with ``--security-review``. Routed to the configured
"verifier" model, which lets a stronger/deeper model audit the change while a
faster model handles planning and coding. It complements — it does not replace —
the deterministic Verifier (py_compile + ruff + pytest).
"""

from __future__ import annotations

from claudebackend import prompts
from claudebackend.models import SecurityReview


def review(client, files: dict[str, str], model: str | None = None) -> SecurityReview:
    """Review ``files`` (repo-relative path -> source) for security issues.

    Returns an empty ``ok=True`` review when there is nothing to look at, so the
    caller never needs to special-case "no changes".
    """
    files = {p: s for p, s in files.items() if s}
    if not files:
        return SecurityReview(ok=True, findings=[])
    message = {"role": "user", "content": prompts.security_review_prompt(files)}
    return client.parse([message], SecurityReview, model=model)
