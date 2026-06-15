# ClaudeBackend — DevSecOps / Red-Team Security Gate (Design)

Builds on `2026-06-14-claudebackend-design.md`. The pipeline mechanics it
describes (isolated agents, the retry loop, the git safety model, prompt caching,
the provider layer, `--dry-run`) are preserved unchanged; this adds a security
dimension to the Verifier.

## Goal

Make the Verifier actively hunt for security vulnerabilities — SQLi, IDOR, XSS,
OS/template-command injection, broken access control, SSRF, path traversal, unsafe
deserialization, weak crypto, hard-coded secrets — **while** the Coder is writing
code, not only afterward. If the Coder introduces a vulnerability, block the
change, explain the exploit, and send it back through the existing retry loop.

## Two layers, kept separate

1. **Deterministic checks (unchanged):** `py_compile` syntax gate per file;
   project-wide `compile + ruff(E9,F) + pytest`. The real correctness net.
2. **Security gate (new, on by default):** runs *after* the deterministic syntax
   gate passes, per step, on the Coder's new Python file:
   - **SAST** — `bandit` (static, AST-based; it never executes the code). Optional
     extra `claudebackend[security]`; degrades to a note when absent.
   - **Red Team** — `agents/security_auditor.audit`, a 4th strictly-isolated agent
     with its own LLM call and an attacker's-mindset prompt, returning a
     `SecurityReview` for that one file.

The existing advisory `--security-review` (a whole-change-set pass, off by default)
is unchanged and complementary.

## Per-step gate flow (`orchestrator._apply_step`)

For each attempt, after the syntax gate passes (Python files only; skipped for
non-`.py` and when `security_gate=False`):

1. `sast = verifier.scan_code(code)`; `audit = security_auditor.audit(client, step,
   code, format_sast(sast), model=verifier_model)`.
2. `_classify_security(sast, audit)` → `(blocking, review_only)`:
   - **blocking** = Red Team findings rated medium/high + SAST findings that are
     high severity AND ≥ medium confidence (a low-confidence SAST finding the Red
     Team confirms re-surfaces as a medium/high audit finding, so it blocks too).
   - **review_only** = leftover low-confidence / low-severity SAST warnings the Red
     Team did not confirm.
3. **Blocking** → reject: emit `SecurityReject(path, attempt, issues)`, set
   `security_errors`, retry. The next `build_context` adds a distinct **SECURITY
   AUDIT FAILURE** block (`prompts.step_block_text(..., security_errors=...)`) so
   the Coder fixes the specific vulnerability. The shared retry counter decrements.
4. **Not blocking** → accept: inject `# CLAUDEBACKEND-REVIEW:` markers for any
   review_only warnings (so they never block forever, but a human is pointed at the
   line), then write the file.
5. **Retries exhausted while still blocking** → **discard**: write nothing (a
   `modify` step keeps its safe original; a `create` step file is never created),
   record under `DevReport.unsafe`, do not commit. Bounded — never an infinite loop.

`verify_project` also runs `_run_sast_check(root)` alongside ruff, but project-level
SAST is **advisory**: it fills `VerifyResult.security_issues` + a `bandit` step and
never flips `ok` (pre-existing repo code must not fail the build).

## Separation of concerns (deliberate)

- The Coder's **initial** prompt carries no security instructions — it focuses on
  business logic. Security text reaches it **only on a retry**, as the SECURITY
  AUDIT FAILURE block. The Security Verifier catches and corrects.
- Static analysis only: no generated code is executed outside the `pytest` gate.

## Surfaces

- `DevReport`: `unsafe: list[str]`, `security_issues: list[str]`; both in
  `to_dict()` (schema_version stays 2 — additive). MCP `develop_backend_feature`
  returns both. `DEV_SUMMARY.md` gains "discarded unsafe files" + "SAST findings"
  sections.
- CLI: `--security-gate/--no-security-gate`; live `! SECURITY: <path> rejected …`
  lines (`SecurityReject` event) and a discarded/SAST summary. MCP: `security_gate`
  parameter.

## Preserved invariants

Deterministic checks intact; agents isolated (Red Team is a separate module/call);
retries bounded (discard at the cap); `cache_control` unchanged; git safety,
`--dry-run`, and the provider layer untouched.
