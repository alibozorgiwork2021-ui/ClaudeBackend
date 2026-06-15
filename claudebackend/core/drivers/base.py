"""Language-driver abstraction: the language-specific half of the pipeline.

The Planner, Coder, git safety model, pricing, and orchestration are
language-agnostic. Everything that genuinely differs per language — how to find
source files, extract and resolve their dependencies for the topology graph, and
how to verify them (syntax, static analysis, tests, SAST) — lives behind a
``LanguageDriver``. ``PythonDriver`` keeps the existing behaviour; new languages
(PHP, ...) implement the same contract.

This is orthogonal to ``core/providers`` (the LLM-backend abstraction): any
provider runs with any language driver — they compose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# pytest's "no tests collected" exit code. Other test runners map their
# "nothing to run" outcome onto this so the orchestration can stay generic.
NO_TESTS = 5


@dataclass(frozen=True)
class SastFinding:
    """One static-analysis security finding.

    ``severity``/``confidence`` are LOW | MEDIUM | HIGH. Produced by a deterministic
    SAST tool (e.g. ``bandit`` for Python); the orchestrator's security gate
    classifies these without caring which language produced them.
    """

    test_id: str
    severity: str
    confidence: str
    line: int
    text: str

    def __str__(self) -> str:
        return (
            f"{self.test_id} [{self.severity}/{self.confidence}] "
            f"line {self.line}: {self.text}"
        )


@dataclass(frozen=True)
class SyntaxCheck:
    """Outcome of a single-file syntax gate. ``error`` is a human-readable string."""

    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class TestRun:
    """Outcome of running a project's test suite.

    ``returncode == NO_TESTS`` means nothing was collected; ``0`` means pass;
    anything else is a failure whose ``output`` carries the traceback to feed back
    to the Coder.
    """

    returncode: int
    output: str
    summary: str = ""


@dataclass
class VerifyStep:
    """One project-verification step, assembled into a ``VerifyResult`` by the caller.

    ``key`` is the step name shown in reports (``"compile"``, ``"php -l"``, ...);
    ``status`` is its short status (``"ok"``, ``"FAILED"``, ``"skipped"``, or a
    summary like ``"18 passed"``). ``errors`` flip the overall result; ``notes`` and
    ``security_issues`` are advisory.
    """

    key: str
    status: str
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    security_issues: list[str] = field(default_factory=list)


class LanguageDriver(ABC):
    """The language-specific operations the pipeline needs.

    Subclasses set ``name``/``source_exts``/``test_framework`` and implement the
    abstract methods. Defaults cover the common case (no dynamic imports, no ORM
    models, ``#`` comments) so a minimal driver stays small.
    """

    name: str = ""
    source_exts: tuple[str, ...] = ()
    test_framework: str = ""

    # --- source identification ---

    def is_source_file(self, path: str) -> bool:
        """True if ``path`` (a repo-relative POSIX path) is one of this language's
        source files."""
        return any(path.endswith(ext) for ext in self.source_exts)

    # --- dependency graph ---

    @abstractmethod
    def extract_imports(self, src: bytes) -> set[str]:
        """Imported module/namespace/dependency names found in ``src``."""

    @abstractmethod
    def module_name(self, relpath: str) -> str:
        """Map a source file path to its module/namespace identifier."""

    def build_modmap(self, source_rels: list[str], root: Path) -> dict[str, str]:
        """Map module/namespace identifiers to repo-relative file paths.

        Default: ``{module_name(rel): rel}``. Languages with a package manifest
        (PHP PSR-4) override this to use the autoload map.
        """
        return {self.module_name(rel): rel for rel in source_rels}

    @abstractmethod
    def resolve(
        self, mod: str, importer: str, modmap: dict[str, str], relset: set[str]
    ) -> str | None:
        """Resolve an imported name to a repo-relative path, or None if external."""

    def has_dynamic_import(self, src: bytes) -> bool:
        """True if ``src`` uses dynamic imports (so the dep map may be incomplete)."""
        return False

    def model_classes(self, text: str) -> list[str]:
        """Names of ORM model classes defined in ``text`` (empty by default)."""
        return []

    def model_refs(self, text: str) -> set[str]:
        """Names of ORM models referenced from ``text`` (empty by default)."""
        return set()

    def package_manifest(self, root: Path) -> dict:
        """Package dependencies + autoload map from the project's manifest.

        Returns ``{"deps": [...], "autoload": {...}}``. Empty by default.
        """
        return {"deps": [], "autoload": {}}

    # --- verification ---

    @abstractmethod
    def verify_steps(self, root: Path, target_version: str | None) -> list[VerifyStep]:
        """The ordered project-wide verification steps for this language."""

    @abstractmethod
    def syntax_check(self, path: Path) -> SyntaxCheck:
        """Syntax-check a single file."""

    def sast_tmp_suffix(self) -> str:
        """File suffix for a temp file written for single-candidate SAST/syntax."""
        return self.source_exts[0] if self.source_exts else ""

    def scan_candidate(self, code: str) -> list[SastFinding]:
        """Deterministic SAST of a single candidate file given as a string.

        The per-step security gate calls this on the Coder's new code before it is
        written. The default does nothing (no findings); languages with a
        deterministic SAST (Python via ``bandit``, PHP via a regex rule table)
        return real findings. ``bandit``-based Python scanning is handled inline by
        ``verifier.scan_code`` for byte-identical legacy behaviour, so
        ``PythonDriver`` does not override this.
        """
        return []

    # --- prompt hints ---

    def version_label(self) -> str:
        """Label for the Coder's target-version line, e.g. ``"Target Python version"``."""
        return f"Target {self.name} version"

    def vuln_patterns_hint(self) -> str:
        """Language-specific examples of dangerous constructs for the Red Team prompt.

        Empty by default; drivers override with concrete sinks (e.g. Python's
        ``pickle/yaml.load/eval/exec``) so the audit prompt names the right hazards.
        """
        return ""

    @abstractmethod
    def default_version(self) -> str:
        """Default target version string when the caller does not supply one."""

    def comment_prefix(self) -> str:
        """Single-line comment prefix for this language (``#`` by default)."""
        return "#"

    def review_marker_line(self, marker: str, text: str) -> str:
        """A single review-marker comment line in this language's comment syntax."""
        return f"{self.comment_prefix()} {marker}: {text}"
