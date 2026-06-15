"""Codebase dependency/topology graph for a source tree.

Python imports are extracted with the stdlib ``tokenize`` module, **not**
``ast``. ``ast.parse`` raises ``SyntaxError`` on legacy or partial source
(``print "x"``, ``except X, e:``, ``0777``, half-written files) — exactly the
files we may need to analyse. ``tokenize`` is lexical and tolerates that source;
it only raises ``TokenError`` at EOF inside an unterminated construct, by which
point any imports near the top of the file have already been emitted.

Beyond Python imports the builder also (lightly, by regex) recognises ORM model
relationships (Django / SQLAlchemy), Dockerfile ``COPY``/``ADD`` references, and
config-file references to repo paths or modules, so the Planner gets a richer map
of the project topology. Each node is tagged with a ``kind``.
"""

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from token import COMMENT, DEDENT, ENCODING, INDENT, NAME, NEWLINE, NL

_DYNAMIC_NAMES = {"__import__", "importlib"}
_SKIP_TOKENS = {NEWLINE, NL, INDENT, DEDENT, ENCODING}

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "graphify-out",
}
_CONFIG_EXTS = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".env"}

# ORM detection (heuristic). A class is treated as a model if one of its base
# tokens is an ORM base; relationships create edges to the referenced model file.
_CLASS_RE = re.compile(r"class\s+(\w+)\s*\(([^)]*)\)")
_ORM_BASES = {"Base", "db.Model", "models.Model", "DeclarativeBase"}
_DJANGO_REL_RE = re.compile(
    r"(?:ForeignKey|OneToOneField|ManyToManyField)\(\s*(?:['\"]([\w.]+)['\"]|(\w+))"
)
_SQLA_REL_RE = re.compile(r"relationship\(\s*['\"](\w+)['\"]")

# Dockerfile / config helpers.
_COPY_RE = re.compile(r"^\s*(?:COPY|ADD)\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_TOKEN_RE = re.compile(r"[A-Za-z_][\w./-]*")


@dataclass
class Graph:
    """Intra-repo topology graph keyed by POSIX-relative path.

    ``edges`` maps a path to the set of repo paths it depends on / references.
    ``dynamic`` is the set of files using dynamic imports. ``kinds`` maps each
    node to its kind: ``"python"``, ``"orm"``, ``"dockerfile"``, or ``"config"``.
    """

    edges: dict[str, set[str]] = field(default_factory=dict)
    dynamic: set[str] = field(default_factory=set)
    kinds: dict[str, str] = field(default_factory=dict)


def _safe_tokens(src: bytes) -> list[tokenize.TokenInfo]:
    """Tokenize best-effort; keep whatever was emitted before any lexical error."""
    toks: list[tokenize.TokenInfo] = []
    try:
        for tok in tokenize.tokenize(io.BytesIO(src).readline):
            toks.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return toks


def _is_dots(s: str) -> bool:
    return bool(s) and all(c == "." for c in s)


def _read_dotted(toks: list, i: int, n: int) -> tuple[str, int]:
    """Read a dotted (or relative) module name starting at ``i`` until ``import``
    or end of statement. Returns (module, index_positioned_at_stop_token)."""
    parts: list[str] = []
    while i < n:
        t = toks[i]
        if t.type == NAME and t.string == "import":
            break
        if t.type in (NEWLINE, NL):
            break
        if t.type == NAME:
            parts.append(t.string)
        elif _is_dots(t.string):
            parts.append(t.string)
        i += 1
    return "".join(parts), i


def _read_import_list(toks: list, i: int, n: int) -> tuple[set[str], int]:
    """Parse ``import a.b as c, d`` -> {"a.b", "d"}; stops at end of statement."""
    names: set[str] = set()
    cur: list[str] = []
    skipping = False  # inside an `as <alias>` tail
    while i < n:
        t = toks[i]
        if t.type in (NEWLINE, NL):
            break
        if t.type == NAME and t.string == "as":
            if cur:
                names.add("".join(cur))
                cur = []
            skipping = True
        elif t.string == ",":
            if cur:
                names.add("".join(cur))
                cur = []
            skipping = False
        elif not skipping and (t.type == NAME or _is_dots(t.string)):
            cur.append(t.string)
        i += 1
    if cur:
        names.add("".join(cur))
    return names, i


def extract_imports(src: bytes) -> set[str]:
    """Return the set of imported module names (dotted; relative kept with dots)."""
    toks = _safe_tokens(src)
    n = len(toks)
    mods: set[str] = set()
    i = 0
    at_start = True
    while i < n:
        t = toks[i]
        if t.type in _SKIP_TOKENS:
            at_start = True
            i += 1
            continue
        if t.type == COMMENT:
            i += 1
            continue
        if at_start and t.type == NAME and t.string == "from":
            mod, i = _read_dotted(toks, i + 1, n)
            if mod:
                mods.add(mod)
            at_start = False
            continue
        if at_start and t.type == NAME and t.string == "import":
            found, i = _read_import_list(toks, i + 1, n)
            mods.update(found)
            at_start = False
            continue
        at_start = False
        i += 1
    return mods


def _has_dynamic_import(src: bytes) -> bool:
    return any(
        t.type == NAME and t.string in _DYNAMIC_NAMES for t in _safe_tokens(src)
    )


def _module_name(relpath: str) -> str:
    stem = relpath[:-3] if relpath.endswith(".py") else relpath
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def _resolve(mod: str, importer: str, modmap: dict[str, str]) -> str | None:
    """Resolve an imported module to a repo-relative path, or None if external."""
    if mod.startswith("."):
        dots = len(mod) - len(mod.lstrip("."))
        rest = mod.lstrip(".")
        base = list(Path(importer).parent.parts)
        up = dots - 1
        if up > 0:
            base = base[: len(base) - up] if up <= len(base) else []
        target_parts = base + (rest.split(".") if rest else [])
        cand = ".".join(p for p in target_parts if p)
        return modmap.get(cand)
    parts = mod.split(".")
    for k in range(len(parts), 0, -1):
        cand = ".".join(parts[:k])
        if cand in modmap:
            return modmap[cand]
    return None


# --- ORM / Dockerfile / config heuristics ---

def _model_classes(text: str) -> list[str]:
    """Names of classes that look like ORM models (Django / SQLAlchemy)."""
    out: list[str] = []
    for m in _CLASS_RE.finditer(text):
        name, bases = m.group(1), m.group(2)
        toks = [b.strip() for b in bases.split(",")]
        if any(t in _ORM_BASES or t.endswith(".Model") for t in toks):
            out.append(name)
    return out


def _model_refs(text: str) -> set[str]:
    """Model names referenced via Django FK/O2O/M2M or SQLAlchemy relationship()."""
    refs: set[str] = set()
    for m in _DJANGO_REL_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name and name != "self":
            refs.add(name.split(".")[-1])
    for m in _SQLA_REL_RE.finditer(text):
        refs.add(m.group(1))
    return refs


def _is_dockerfile(name: str) -> bool:
    return (
        name == "Dockerfile"
        or name.endswith(".Dockerfile")
        or name.startswith("Dockerfile.")
    )


def _docker_copy_srcs(text: str) -> list[str]:
    """Source paths from ``COPY``/``ADD`` lines (last token is the destination)."""
    srcs: list[str] = []
    for m in _COPY_RE.finditer(text):
        args = [a for a in m.group(1).split() if not a.startswith("--")]
        if len(args) >= 2:
            srcs.extend(args[:-1])
    return srcs


def _is_config(p: Path) -> bool:
    return p.suffix.lower() in _CONFIG_EXTS or p.name == ".env"


def _iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        yield p


def build_graph(root, driver=None) -> Graph:
    """Build the intra-repo topology graph for ``root``.

    Source-file detection, import extraction/resolution, dynamic-import flagging,
    and ORM model detection are delegated to the language ``driver`` (defaults to
    the Python driver, preserving the previous behaviour). Dockerfile and config
    references are language-neutral and handled here directly.
    """
    if driver is None:
        from claudebackend.core.drivers import get_driver

        driver = get_driver("python")

    root = Path(root)
    files = list(_iter_files(root))
    rels = {p: p.relative_to(root).as_posix() for p in files}
    relset = set(rels.values())
    source_files = [p for p in files if driver.is_source_file(rels[p])]
    modmap = driver.build_modmap([rels[p] for p in source_files], root)

    graph = Graph()

    # Source files: imports, dynamic imports, and ORM model definitions.
    src_text: dict[str, str] = {}
    model_def: dict[str, str] = {}  # ModelClassName -> defining file
    for p in source_files:
        rel = rels[p]
        src = p.read_bytes()
        src_text[rel] = src.decode("utf-8", "replace")
        deps: set[str] = set()
        for mod in driver.extract_imports(src):
            target = driver.resolve(mod, rel, modmap, relset)
            if target and target != rel:
                deps.add(target)
        graph.edges[rel] = deps
        graph.kinds[rel] = driver.name
        if driver.has_dynamic_import(src):
            graph.dynamic.add(rel)
        for name in driver.model_classes(src_text[rel]):
            model_def.setdefault(name, rel)

    # Mark ORM files and add model-relationship edges.
    model_files = set(model_def.values())
    for rel, text in src_text.items():
        is_orm = rel in model_files
        for name in driver.model_refs(text):
            target = model_def.get(name)
            if target and target != rel:
                graph.edges[rel].add(target)
                is_orm = True
        if is_orm:
            graph.kinds[rel] = "orm"

    # Dockerfiles.
    for p in files:
        rel = rels[p]
        if not _is_dockerfile(p.name):
            continue
        graph.kinds[rel] = "dockerfile"
        graph.edges.setdefault(rel, set())
        text = p.read_text(encoding="utf-8", errors="replace")
        for src in _docker_copy_srcs(text):
            cand = src.strip().lstrip("./").rstrip("/")
            if cand in relset and cand != rel:
                graph.edges[rel].add(cand)

    # Config files (anything not already classified).
    for p in files:
        rel = rels[p]
        if rel in graph.kinds or not _is_config(p):
            continue
        graph.kinds[rel] = "config"
        deps = graph.edges.setdefault(rel, set())
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in _TOKEN_RE.finditer(text):
            if len(deps) >= 50:  # keep config fan-out bounded
                break
            tok = m.group(0)
            cand = tok.lstrip("./")
            if cand in relset and cand != rel:
                deps.add(cand)
            elif tok in modmap and modmap[tok] != rel:
                deps.add(modmap[tok])

    return graph


def graph_summary(graph: Graph, max_edges_per_node: int = 8) -> str:
    """A compact, human/LLM-readable map of the codebase grouped by node kind."""
    by_kind: dict[str, list[str]] = {}
    for path, kind in graph.kinds.items():
        by_kind.setdefault(kind, []).append(path)

    labels = {
        "python": "Python modules",
        "php": "PHP modules",
        "orm": "ORM models",
        "dockerfile": "Dockerfiles",
        "config": "Config files",
    }
    order = ["python", "php", "orm", "dockerfile", "config"]
    lines: list[str] = []
    for kind in order + [k for k in sorted(by_kind) if k not in order]:
        paths = sorted(by_kind.get(kind, []))
        if not paths:
            continue
        lines.append(f"{labels.get(kind, kind)}:")
        for path in paths:
            deps = sorted(graph.edges.get(path, ()))
            if deps:
                shown = ", ".join(deps[:max_edges_per_node])
                extra = len(deps) - max_edges_per_node
                more = f", +{extra} more" if extra > 0 else ""
                lines.append(f"  - {path} -> {shown}{more}")
            else:
                lines.append(f"  - {path}")
    return "\n".join(lines)


def ordered_units(graph: Graph) -> list[list[str]]:
    """Dependency-ordered SCC groups (a group's dependencies come before it).

    Iterative Tarjan: SCCs are finalised in reverse-topological order, which —
    with edges pointing dependent -> dependency — yields dependencies first.
    Files within a group are sorted for determinism. Retained for graph layout;
    it no longer drives the development pipeline (the Planner does).
    """
    edges = graph.edges
    nodes = list(edges)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for start in nodes:
        if start in index:
            continue
        # work stack of (node, iterator-position)
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            children = sorted(edges.get(node, ()))
            recurse = False
            while child_i < len(children):
                child = children[child_i]
                if child not in edges:  # external/unknown — skip
                    child_i += 1
                    continue
                if child not in index:
                    work[-1] = (node, child_i + 1)
                    work.append((child, 0))
                    recurse = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
                child_i += 1
            if recurse:
                continue
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                result.append(sorted(comp))
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return result
