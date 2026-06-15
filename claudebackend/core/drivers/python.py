"""The Python language driver — the existing pipeline behaviour, behind the driver
interface.

Each method delegates to the module-level functions in ``core/depgraph`` and
``core/verifier`` (kept there as the public, test-imported, monkeypatchable API).
Imports are lazy inside the methods to avoid an import cycle: ``verifier`` imports
``drivers`` (for the default driver), and this module is reached through that path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from claudebackend.core.drivers.base import (
    NO_TESTS,
    LanguageDriver,
    SyntaxCheck,
    VerifyStep,
)


class PythonDriver(LanguageDriver):
    name = "python"
    source_exts = (".py",)
    test_framework = "pytest"

    # --- dependency graph ---

    def extract_imports(self, src: bytes) -> set[str]:
        from claudebackend.core import depgraph

        return depgraph.extract_imports(src)

    def module_name(self, relpath: str) -> str:
        from claudebackend.core import depgraph

        return depgraph._module_name(relpath)

    def resolve(self, mod, importer, modmap, relset):
        from claudebackend.core import depgraph

        return depgraph._resolve(mod, importer, modmap)

    def has_dynamic_import(self, src: bytes) -> bool:
        from claudebackend.core import depgraph

        return depgraph._has_dynamic_import(src)

    def model_classes(self, text: str) -> list[str]:
        from claudebackend.core import depgraph

        return depgraph._model_classes(text)

    def model_refs(self, text: str) -> set[str]:
        from claudebackend.core import depgraph

        return depgraph._model_refs(text)

    # --- verification ---

    def syntax_check(self, path: Path) -> SyntaxCheck:
        from claudebackend.core import verifier

        err = verifier._compile_check(Path(path))
        return SyntaxCheck(ok=err is None, error=err)

    def verify_steps(self, root: Path, target_version: str | None) -> list[VerifyStep]:
        # Calls the verifier module's functions through the live module object so
        # tests that monkeypatch ``verifier.bandit_available`` / ``_run_sast_check``
        # still take effect, and the output stays byte-identical to the prior
        # inline ``verify_project``.
        from claudebackend.core import verifier

        root = Path(root)
        steps: list[VerifyStep] = []

        # 1. Syntax across the whole tree (in-process; writes nothing).
        syntax_errors = []
        for ext in self.source_exts:
            for p in root.rglob(f"*{ext}"):
                sc = self.syntax_check(p)
                if not sc.ok and sc.error:
                    syntax_errors.append(sc.error)
        compile_step = VerifyStep(
            key="compile", status="ok" if not syntax_errors else "FAILED"
        )
        if syntax_errors:
            compile_step.errors.append("compile:\n" + "\n".join(syntax_errors))
        steps.append(compile_step)

        # 2. Undefined names / syntax (real py2 leftovers like `xrange`, `unicode`).
        verifier.ensure_ruff()
        ruff_rc, ruff_out = verifier._run(
            [
                sys.executable, "-m", "ruff", "check",
                "--select", "E9,F",
                "--target-version", verifier._normalize_target(target_version),
                "--output-format", "concise",
                "--no-cache",
                str(root),
            ]
        )
        ruff_step = VerifyStep(key="ruff", status="ok" if ruff_rc == 0 else "FAILED")
        if ruff_rc != 0:
            ruff_step.errors.append(
                "ruff:\n" + (ruff_out.strip() or f"ruff exited {ruff_rc}")
            )
        steps.append(ruff_step)

        # 3. Runtime / cross-file gate via the project's own test suite, if any.
        pytest_rc, pytest_out = verifier.run_pytest(root)
        pytest_step = VerifyStep(key="pytest", status="")
        if pytest_rc == NO_TESTS:
            pytest_step.status = "skipped"
            pytest_step.notes.append(
                "pytest: no tests collected - runtime behaviour not verified"
            )
        elif pytest_rc != 0:
            pytest_step.status = "FAILED"
            pytest_step.errors.append("pytest:\n" + pytest_out.strip())
        else:
            pytest_step.status = verifier._parse_pytest_summary(pytest_out)
        steps.append(pytest_step)

        # 4. Advisory SAST (bandit). Never flips ``ok`` — surfaces findings for the
        #    report; the per-step gate is what blocks new code.
        sast_step = VerifyStep(key="bandit", status="")
        if verifier.bandit_available():
            findings = verifier._run_sast_check(root)
            sast_step.security_issues = verifier.format_sast(findings)
            sast_step.status = "ok" if not findings else f"{len(findings)} issue(s)"
        else:
            sast_step.status = "skipped"
            sast_step.notes.append(
                "bandit not installed - SAST skipped (pip install claudebackend[security])"
            )
        steps.append(sast_step)

        return steps

    # --- prompt hints ---

    def version_label(self) -> str:
        return "Target Python version"

    def vuln_patterns_hint(self) -> str:
        return "pickle/yaml.load/eval/exec"

    def default_version(self) -> str:
        return f"py{sys.version_info.major}{sys.version_info.minor}"
