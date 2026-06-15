"""Deterministic verification — a safety net, not a correctness proof.

The Coder (Opus 4.8) writes the code. This module only catches obvious breakage:

- ``verify_file``  -> in-process ``compile()``: a **syntax** gate. It does NOT
  detect semantic bugs (a wrong return value, an off-by-one, ``5/2`` vs ``5//2``).
- ``verify_project`` -> compile every file + ``ruff check --select E9,F``
  (undefined names / syntax) + ``pytest`` when a suite collects + an advisory
  ``bandit`` SAST scan. The test suite is the real cross-file / orphan-file gate;
  when there is none, that is recorded as a non-silent note, not a silent pass.

``bandit`` (static, AST-based — it never *executes* the scanned code) is the
deterministic half of the security gate. It is an optional extra
(``pip install claudebackend[security]``); when it is not installed the SAST step
degrades to a recorded note. At the project level its findings are advisory and
never flip ``ok``; the blocking security gate runs per step on the Coder's new
code (see the orchestrator). No LLM calls live here.

Syntax checks run in-process and subprocesses set ``PYTHONDONTWRITEBYTECODE`` so
verification never litters the target repo with ``__pycache__`` (which would
leave the working tree unclean).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from claudebackend.core.drivers.base import SastFinding
from claudebackend.models import VerifyResult

logger = logging.getLogger(__name__)

_NO_BYTECODE_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def ensure_ruff() -> None:
    """Raise a clear error if ``ruff`` is not importable (it is a runtime dep)."""
    rc, out = _run([sys.executable, "-m", "ruff", "--version"])
    if rc != 0:
        raise RuntimeError(
            "ruff is required but not installed. Install it with: pip install ruff\n"
            + out
        )


def _run(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=_NO_BYTECODE_ENV
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _normalize_target(target_version: str | None) -> str:
    """Return a ruff ``--target-version`` like ``py38``."""
    if not target_version:
        return f"py{sys.version_info.major}{sys.version_info.minor}"
    tv = target_version.lower().strip()
    return tv if tv.startswith("py") else "py" + tv.replace(".", "")


def _compile_check(path: Path) -> str | None:
    """Syntax-check one file in-process. Returns an error string or None."""
    try:
        compile(path.read_bytes(), str(path), "exec")
        return None
    except SyntaxError as exc:
        return f"{path}: {exc}"


def verify_file(path: str | Path) -> VerifyResult:
    """Syntax gate: compile a single file (no bytecode written)."""
    err = _compile_check(Path(path))
    return VerifyResult(ok=err is None, errors=[] if err is None else [err])


_PYTEST_SUMMARY_RE = re.compile(
    r"(\d+ (?:passed|failed|skipped|error)[\w ,]*?)(?: in [\d.]+s.*)?$"
)


def run_pytest(root: str | Path) -> tuple[int, str]:
    """Run the project's pytest suite (no cache, no bytecode) and return
    ``(returncode, combined_output)``. ``returncode == 5`` means no tests were
    collected. Shared by ``verify_project`` and the TDD watcher."""
    return _run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(root),
    )


def _parse_pytest_summary(out: str) -> str:
    """Extract a short pass summary from pytest -q output, e.g. ``'18 passed'``.

    Falls back to ``'passed'`` if no recognisable summary line is found.
    """
    last = next(
        (line for line in reversed(out.splitlines()) if line.strip()),
        "",
    )
    m = _PYTEST_SUMMARY_RE.search(last)
    return m.group(1) if m else "passed"


# --- SAST (bandit) -----------------------------------------------------------
#
# Static, AST-based security scanning. bandit parses the source and never runs
# it, so this is safe to point at untrusted generated code. ``SastFinding`` is
# defined in (and re-exported from) the driver base so every language's SAST
# produces the same shape.


def bandit_available() -> bool:
    """True if ``bandit`` can be invoked. Soft (never raises) — it is optional."""
    try:
        rc, _ = _run([sys.executable, "-m", "bandit", "--version"])
    except OSError:
        return False
    return rc == 0


def _parse_bandit_json(out: str) -> list[SastFinding]:
    """Parse a ``bandit -f json`` report into findings; tolerant of junk."""
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return []
    findings = []
    for r in data.get("results", []):
        findings.append(
            SastFinding(
                test_id=str(r.get("test_id", "B000")),
                severity=str(r.get("issue_severity", "LOW")).upper(),
                confidence=str(r.get("issue_confidence", "LOW")).upper(),
                line=int(r.get("line_number", 0) or 0),
                text=str(r.get("issue_text", "")).strip(),
            )
        )
    return findings


def _run_sast_check(target: str | Path) -> list[SastFinding]:
    """Run bandit over ``target`` (a file or a directory). Returns findings.

    Static analysis only: bandit reads the AST and never executes the code, so
    this is safe on untrusted generated code. Degrades to ``[]`` (a recorded note
    is left by the caller) when bandit is not installed; never raises.
    """
    target = Path(target)
    if not bandit_available():
        logger.debug("bandit not installed; SAST skipped for %s", target)
        return []
    cmd = [sys.executable, "-m", "bandit", "-q", "-f", "json"]
    if target.is_dir():
        cmd.append("-r")
    cmd.append(str(target))
    try:
        # stdout carries the JSON report; bandit exits 1 when it finds issues.
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=_NO_BYTECODE_ENV
        )
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("bandit invocation failed: %s", exc)
        return []
    return _parse_bandit_json(proc.stdout)


def scan_code(code: str, driver=None) -> list[SastFinding]:
    """SAST a single candidate file given as a string (no real file touched).

    Python (the default, or an explicit Python driver) runs bandit on a temp file —
    byte-identical to the previous behaviour. Any other language supplies its own
    deterministic SAST through ``driver.scan_candidate`` (e.g. PHP's regex rule
    table), which needs neither a temp file nor an external tool.
    """
    if driver is not None and driver.name != "python":
        return driver.scan_candidate(code)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(code)
        tmp = Path(fh.name)
    try:
        return _run_sast_check(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def format_sast(findings: list[SastFinding]) -> list[str]:
    """Render findings as short strings for reports and Coder feedback."""
    return [str(f) for f in findings]


def verify_project(
    root: str | Path, target_version: str | None = None, driver=None
) -> VerifyResult:
    """Project-wide gate, driven by the selected language driver.

    For Python this is compile every file + ruff(E9,F) + pytest (if it collects) +
    an advisory ``bandit`` SAST scan (its findings populate ``security_issues`` and
    a ``bandit`` step status but never flip ``ok``). Other languages supply their
    own ordered steps (e.g. ``php -l`` / phpstan / phpunit). ``driver`` defaults to
    the Python driver, preserving the previous behaviour and signature.
    """
    if driver is None:
        from claudebackend.core.drivers import get_driver

        driver = get_driver("python")

    root = Path(root)
    errors: list[str] = []
    notes: list[str] = []
    steps: dict[str, str] = {}
    security_issues: list[str] = []

    for step in driver.verify_steps(root, target_version):
        steps[step.key] = step.status
        errors.extend(step.errors)
        notes.extend(step.notes)
        security_issues.extend(step.security_issues)
        logger.debug("%s: %s", step.key, step.status)

    return VerifyResult(
        ok=not errors,
        errors=errors,
        notes=notes,
        steps=steps,
        security_issues=security_issues,
    )
