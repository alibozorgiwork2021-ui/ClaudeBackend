"""Red Team agent: a per-step, blocking security audit of the Coder's new code.

This is the LLM half of the security gate. After the deterministic syntax gate
passes, the orchestrator calls :func:`audit` on the candidate file (optionally
with the deterministic SAST findings). It adopts an attacker's mindset and returns
a :class:`SecurityReview`; the orchestrator decides whether the findings block the
file and feed back to the Coder.

It is a strictly isolated agent (its own module and its own LLM call) — separate
from the Planner, the Coder, the deterministic Verifier, and the advisory
whole-change-set ``security_reviewer``. The audit is static: it reviews the source
text and never executes it.
"""

from __future__ import annotations

from claudebackend import prompts
from claudebackend.models import PlanStep, SecurityReview


def audit(
    client,
    step: PlanStep,
    code: str,
    sast_findings: list[str] | None = None,
    model: str | None = None,
    vuln_patterns_hint: str | None = None,
) -> SecurityReview:
    """Audit one Coder-produced file for security flaws.

    Returns an empty ``ok=True`` review when there is nothing to look at, so the
    caller never needs to special-case empty code. ``vuln_patterns_hint`` (from the
    language driver) names the dangerous constructs the prompt should emphasise.
    """
    if not code.strip():
        return SecurityReview(ok=True, findings=[])
    message = {
        "role": "user",
        "content": prompts.red_team_prompt(
            step, code, sast_findings, vuln_patterns_hint=vuln_patterns_hint
        ),
    }
    return client.parse([message], SecurityReview, model=model)
