"""The PHP language driver.

Dependency-graph building is pure regex (no PHP runtime needed): ``use`` imports,
``extends``/``implements``, literal ``include``/``require`` paths, PSR-4 autoload
from ``composer.json``. Verification shells out to ``php -l`` (syntax),
``phpstan``/``psalm`` (static analysis), and ``phpunit`` (tests) — every tool
**degrades gracefully when absent** (records a note, never fails the build), exactly
like the optional ``bandit`` SAST on the Python side.

The per-step security gate is fed by a deterministic regex SAST table
(``_PHP_SAST_RULES``) exposed via :meth:`PHPDriver.scan_candidate`, so it fires even
in environments with no PHP toolchain installed and produces the same
``SastFinding`` objects the orchestrator's security gate already understands.
"""

from __future__ import annotations

import json
import posixpath
import re
import subprocess
from pathlib import Path

from claudebackend.core.drivers.base import (
    LanguageDriver,
    SastFinding,
    SyntaxCheck,
    VerifyStep,
)

# --- regexes for dependency extraction ---

_USE_RE = re.compile(
    r"^\s*use\s+(?:function\s+|const\s+)?([A-Za-z_\\][\w\\]*)(?:\s+as\s+\w+)?\s*;",
    re.MULTILINE,
)
_GROUP_USE_RE = re.compile(r"\buse\s+([\w\\]+)\\\{([^}]+)\}", re.MULTILINE)
_CLASS_RE = re.compile(
    r"\b(?:class|interface|trait)\s+\w+"
    r"(?:\s+extends\s+([\w\\]+))?(?:\s+implements\s+([\w\\,\s]+))?"
)
_INCLUDE_RE = re.compile(
    r"""\b(?:include|include_once|require|require_once)\b\s*\(?\s*['"]([^'"]+)['"]"""
)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w\\]+)\s*;", re.MULTILINE)
_DYNAMIC_RE = re.compile(
    r"\beval\s*\(|\bcall_user_func(?:_array)?\s*\(|\$\$"
    r"|(?:include|require)(?:_once)?\s*\(?\s*\$"
)

# ORM detection (light, optional): Eloquent ``extends Model`` and Doctrine ``#[ORM\Entity]``.
_ELOQUENT_RE = re.compile(r"\bclass\s+(\w+)\s+extends\s+(?:[\\\w]*\\)?Model\b")
_DOCTRINE_RE = re.compile(r"#\[\s*ORM\\Entity[^\]]*\][\s\S]{0,200}?\bclass\s+(\w+)")

# --- deterministic PHP SAST rule table ---
# Request-controlled superglobals (the taint sources we care about for the gate).
_SG = r"\$_(?:GET|POST|REQUEST|COOKIE)"

# Each rule: (test_id, compiled regex, severity, confidence, text). HIGH/MEDIUM rules
# BLOCK via the orchestrator's _classify_security; lower ones fall to review markers.
_PHP_SAST_RULES = [
    (
        "PHP-SQLI",
        re.compile(
            # scan is line-by-line, so ``.*`` is bounded to the line (and tolerates a
            # ``;`` inside a string literal, unlike a ``[^;]*`` class).
            r"(?i)(?:->\s*(?:query|exec|prepare)\s*\(.*" + _SG + r"|"
            r"""["'][^"']*\b(?:select|insert|update|delete)\b[^"']*["']\s*\.\s*\$)"""
        ),
        "HIGH",
        "MEDIUM",
        "Possible SQL injection: query built from request data",
    ),
    (
        "PHP-OPEN-REDIRECT",
        re.compile(r"""(?i)header\s*\(\s*["']\s*location\s*:[^"']*["']?\s*\.?\s*""" + _SG),
        "MEDIUM",
        "MEDIUM",
        "Unvalidated redirect: Location header built from request data",
    ),
    (
        "PHP-LFI-RFI",
        re.compile(r"\b(?:include|include_once|require|require_once)\b[^;]*" + _SG),
        "HIGH",
        "MEDIUM",
        "Local/remote file inclusion: include path from request data",
    ),
    (
        "PHP-CMD-INJECT",
        re.compile(
            r"\b(?:exec|system|shell_exec|passthru|popen|proc_open)\s*\([^;]*\$"
        ),
        "HIGH",
        "MEDIUM",
        "Command injection: shell command built from a variable",
    ),
    (
        "PHP-UNSERIALIZE",
        # Any variable argument — object-injection gadgets are often base64/decoded
        # first (``unserialize(base64_decode($_POST['x']))``), so a direct-superglobal
        # match alone misses the common case.
        re.compile(r"\bunserialize\s*\([^)]*\$"),
        "HIGH",
        "MEDIUM",
        "Unsafe deserialization of untrusted input (unserialize)",
    ),
    (
        "PHP-EVAL",
        re.compile(r"\beval\s*\("),
        "HIGH",
        "MEDIUM",
        "Use of eval() - arbitrary code execution risk",
    ),
]
# Reflected XSS needs a negative guard a single regex cannot express.
_XSS_RE = re.compile(r"(?i)\b(?:echo|print)\b[^;]*" + _SG)
_XSS_SAFE_RE = re.compile(r"(?i)htmlspecialchars|htmlentities|intval|\(\s*int\s*\)")

# Per-rule negative guards: a match is suppressed when the same line also shows a
# recognised sanitiser, so the gate does not hard-block the recommended-safe pattern
# (e.g. ``exec(escapeshellarg($cmd))``).
_CMD_SAFE_RE = re.compile(r"escapeshellarg|escapeshellcmd")
_SAFE_GUARDS = {"PHP-CMD-INJECT": _CMD_SAFE_RE}


def _run(cmd: list[str], cwd: str | None = None) -> tuple[int | None, str]:
    """Run ``cmd``; return ``(returncode, combined_output)``.

    Returns ``(None, "")`` when the binary is missing (``OSError``) so callers can
    degrade gracefully instead of crashing on a toolchain that is not installed.
    """
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None, ""
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class PHPDriver(LanguageDriver):
    name = "php"
    source_exts = (".php",)
    test_framework = "phpunit"

    # --- dependency graph ---

    def extract_imports(self, src: bytes) -> set[str]:
        text = src.decode("utf-8", "replace")
        names: set[str] = set()
        for m in _USE_RE.finditer(text):
            names.add(m.group(1).lstrip("\\"))
        for m in _GROUP_USE_RE.finditer(text):
            prefix = m.group(1).lstrip("\\")
            for member in m.group(2).split(","):
                member = member.strip().split(" as ")[0].strip()
                member = member.removeprefix("function ").removeprefix("const ").strip()
                if member:
                    names.add(prefix + "\\" + member)
        for m in _CLASS_RE.finditer(text):
            if m.group(1):
                names.add(m.group(1).lstrip("\\"))
            if m.group(2):
                for impl in m.group(2).split(","):
                    impl = impl.strip()
                    if impl:
                        names.add(impl.lstrip("\\"))
        for m in _INCLUDE_RE.finditer(text):
            names.add(m.group(1))
        return names

    def module_name(self, relpath: str) -> str:
        stem = relpath[:-4] if relpath.endswith(".php") else relpath
        return stem.replace("/", "\\")

    def build_modmap(self, source_rels: list[str], root: Path) -> dict[str, str]:
        manifest = self.package_manifest(Path(root))
        psr4 = manifest.get("autoload", {})
        # Flatten to (prefix, dir) pairs sorted by LONGEST directory first, so a
        # specific mapping (e.g. "src/Api/") wins over a broader or root ("") one —
        # PSR-4 semantics. A plain first-match loop would let a root prefix shadow
        # every file and drop real dependency edges.
        pairs: list[tuple[str, str]] = []
        for prefix, dirs in psr4.items():
            if isinstance(dirs, str):
                dirs = [dirs]
            for d in dirs:
                pairs.append((prefix, d.strip("/").replace("\\", "/")))
        pairs.sort(key=lambda pd: len(pd[1]), reverse=True)

        modmap: dict[str, str] = {}
        for rel in source_rels:
            if not rel.endswith(".php"):
                modmap[self.module_name(rel)] = rel
                continue
            matched = False
            for prefix, d in pairs:
                pre = (d + "/") if d else ""
                if rel.startswith(pre):
                    sub = rel[len(pre):-4]  # strip dir + ".php"
                    fqcn = prefix + sub.replace("/", "\\")
                    modmap[fqcn] = rel
                    matched = True
                    break
            if not matched:
                modmap[self.module_name(rel)] = rel
        return modmap

    def resolve(self, mod, importer, modmap, relset):
        # Relative include/require of a literal path -> resolve against importer dir.
        if "/" in mod or mod.endswith(".php"):
            base = Path(importer).parent.as_posix()
            cand = posixpath.normpath(f"{base}/{mod}" if base != "." else mod)
            return cand if cand in relset else None
        # FQCN -> longest-namespace-prefix match against the PSR-4 module map.
        name = mod.lstrip("\\")
        parts = name.split("\\")
        for k in range(len(parts), 0, -1):
            cand = "\\".join(parts[:k])
            if cand in modmap:
                return modmap[cand]
        return None

    def has_dynamic_import(self, src: bytes) -> bool:
        return bool(_DYNAMIC_RE.search(src.decode("utf-8", "replace")))

    def model_classes(self, text: str) -> list[str]:
        out: list[str] = []
        for m in _ELOQUENT_RE.finditer(text):
            out.append(m.group(1))
        for m in _DOCTRINE_RE.finditer(text):
            out.append(m.group(1))
        return out

    def model_refs(self, text: str) -> set[str]:
        return set()

    def package_manifest(self, root: Path) -> dict:
        cj = Path(root) / "composer.json"
        deps: list[str] = []
        autoload: dict = {}
        if cj.exists():
            try:
                data = json.loads(cj.read_text(encoding="utf-8", errors="replace"))
            except (ValueError, OSError):
                data = {}
            if isinstance(data, dict):
                for key in ("require", "require-dev"):
                    section = data.get(key)
                    if isinstance(section, dict):
                        deps.extend(section.keys())
                al = data.get("autoload") or {}
                ald = data.get("autoload-dev") or {}
                autoload = {
                    **((al.get("psr-4") if isinstance(al, dict) else None) or {}),
                    **((ald.get("psr-4") if isinstance(ald, dict) else None) or {}),
                }
        return {"deps": deps, "autoload": autoload}

    # --- verification ---

    def _find_tool(self, root: Path, name: str) -> list[str] | None:
        """Prefer a project-local ``vendor/bin/<name>``, else the tool on PATH."""
        vendor = Path(root) / "vendor" / "bin" / name
        if vendor.exists():
            return [str(vendor)]
        if _run([name, "--version"])[0] == 0:
            return [name]
        return None

    def syntax_check(self, path: Path) -> SyntaxCheck:
        rc, out = _run(["php", "-l", str(path)])
        if rc is None:  # php not installed -> never fail the build
            return SyntaxCheck(ok=True)
        if rc != 0 and "Parse error" in out:
            msg = next(
                (ln.strip() for ln in out.splitlines() if "Parse error" in ln),
                out.strip(),
            )
            return SyntaxCheck(ok=False, error=f"{path}: {msg}")
        return SyntaxCheck(ok=True)

    def scan_candidate(self, code: str) -> list[SastFinding]:
        findings: list[SastFinding] = []
        for i, line in enumerate(code.splitlines(), 1):
            for test_id, rx, sev, conf, text in _PHP_SAST_RULES:
                if rx.search(line):
                    guard = _SAFE_GUARDS.get(test_id)
                    if guard and guard.search(line):
                        continue
                    findings.append(SastFinding(test_id, sev, conf, i, text))
            if _XSS_RE.search(line) and not _XSS_SAFE_RE.search(line):
                findings.append(
                    SastFinding(
                        "PHP-XSS", "MEDIUM", "LOW", i,
                        "Reflected XSS: request data echoed without htmlspecialchars",
                    )
                )
        return findings

    def _parse_phpstan(self, out: str) -> list[str]:
        try:
            data = json.loads(out)
        except (ValueError, TypeError):
            return []
        msgs: list[str] = []
        for finfo in (data.get("files") or {}).values():
            for m in finfo.get("messages", []):
                line = m.get("line")
                text = m.get("message", "")
                msgs.append(f"line {line}: {text}" if line else text)
        return msgs

    def _parse_phpunit_summary(self, out: str) -> str:
        for ln in reversed(out.splitlines()):
            s = ln.strip()
            if s.startswith("OK"):
                return s
        return "passed"

    def verify_steps(self, root: Path, target_version: str | None) -> list[VerifyStep]:
        from claudebackend.core.verifier import format_sast

        root = Path(root)
        php_files = list(root.rglob("*.php"))
        steps: list[VerifyStep] = []

        # 1. php -l syntax across the tree.
        php_ok = _run(["php", "--version"])[0] == 0
        lint = VerifyStep(key="php -l", status="ok")
        if not php_ok:
            lint.status = "skipped"
            lint.notes.append("php not installed - syntax check skipped")
        else:
            errs = []
            for p in php_files:
                sc = self.syntax_check(p)
                if not sc.ok and sc.error:
                    errs.append(sc.error)
            if errs:
                lint.status = "FAILED"
                lint.errors.append("php -l:\n" + "\n".join(errs))
        steps.append(lint)

        # 2. Static analysis: phpstan, else psalm, else skipped (parallels ruff E9,F;
        #    can flip ``ok``). Soft — never raise when the tool is absent.
        phpstan = self._find_tool(root, "phpstan")
        psalm = None if phpstan else self._find_tool(root, "psalm")
        if phpstan:
            rc, out = _run(
                phpstan + ["analyse", "--error-format=json", "--no-progress", str(root)],
                cwd=str(root),
            )
            step = VerifyStep(key="phpstan", status="ok")
            errs = self._parse_phpstan(out)
            if errs:
                step.status = "FAILED"
                step.errors.append("phpstan:\n" + "\n".join(errs))
            steps.append(step)
        elif psalm:
            rc, out = _run(
                psalm + ["--output-format=json", "--no-progress"], cwd=str(root)
            )
            if rc is None:
                step = VerifyStep(key="psalm", status="skipped")
                step.notes.append("psalm not installed - static analysis skipped")
            else:
                step = VerifyStep(key="psalm", status="ok" if rc == 0 else "FAILED")
                if rc != 0:
                    step.errors.append("psalm:\n" + out.strip())
            steps.append(step)
        else:
            step = VerifyStep(key="phpstan", status="skipped")
            step.notes.append("phpstan/psalm not installed - static analysis skipped")
            steps.append(step)

        # 3. Tests via phpunit, if a runner is available.
        phpunit = self._find_tool(root, "phpunit")
        test_step = VerifyStep(key="phpunit", status="")
        if not phpunit:
            test_step.status = "skipped"
            test_step.notes.append("phpunit not installed - tests skipped")
        else:
            rc, out = _run(phpunit + ["--no-coverage"], cwd=str(root))
            if rc is None:
                test_step.status = "skipped"
                test_step.notes.append("phpunit not installed - tests skipped")
            elif "No tests executed" in out or "no tests" in out.lower():
                test_step.status = "skipped"
                test_step.notes.append(
                    "phpunit: no tests collected - runtime behaviour not verified"
                )
            elif rc != 0:
                test_step.status = "FAILED"
                test_step.errors.append("phpunit:\n" + out.strip())
            else:
                test_step.status = self._parse_phpunit_summary(out)
        steps.append(test_step)

        # 4. Advisory deterministic regex SAST (parallels bandit; never flips ``ok``).
        findings: list[SastFinding] = []
        for p in php_files:
            findings.extend(
                self.scan_candidate(p.read_text(encoding="utf-8", errors="replace"))
            )
        sast = VerifyStep(key="php-sast", status="ok" if not findings else f"{len(findings)} issue(s)")
        sast.security_issues = format_sast(findings)
        steps.append(sast)

        return steps

    # --- prompt hints ---

    def comment_prefix(self) -> str:
        return "//"

    def version_label(self) -> str:
        return "Target PHP version"

    def vuln_patterns_hint(self) -> str:
        return (
            "unserialize() of untrusted input (object-injection gadget chains), "
            "local/remote file inclusion (include/require on request data), command "
            "execution (exec/system/shell_exec/passthru/popen/proc_open), and code "
            "execution via eval()/call_user_func with request data"
        )

    def default_version(self) -> str:
        return "php8.1"
