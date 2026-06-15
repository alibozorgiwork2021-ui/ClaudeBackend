# ClaudeMigrate — Python 2 → 3 Migration Agent (Design)

> **Historical / superseded.** This documents the original `claudemigrate` design,
> when the tool was a hardcoded Python 2 → 3 migrator. The project has since been
> generalized into **ClaudeBackend**, a universal backend development system — see
> [`2026-06-14-claudebackend-design.md`](2026-06-14-claudebackend-design.md). Kept
> here for history; the names/commands below are out of date.

- **Status:** Approved; revised after design review
- **Date:** 2026-06-13
- **Author:** Mohsen (with Claude)

## 0. Revisions after design review

Adversarial review (verified on Python 3.13) corrected the original draft. These
**supersede any conflicting text below**; the implementation follows them:

- **D1 — parser:** `depgraph` uses stdlib **`tokenize`**, not `ast`. Python 3's
  `ast.parse` raises `SyntaxError` on Python 2 input (`print "x"`, `except X, e:`,
  `0777`, …) — i.e. on the very files we migrate. `lib2to3` is removed in 3.13.
  `tokenize` is lexical and tolerates py2 source.
- **D2 — verification is a safety net, not a correctness proof:** `py_compile` is
  a **syntax** smoke-test only (it does *not* catch `xrange`, `unicode`,
  `has_key`, or integer division `5/2`). The **Coder (Opus 4.8) performs the
  semantic migration**; the **project-wide import check is the real gate**; and
  genuinely ambiguous semantic cases (integer `/`, str/bytes) are **flagged for
  human review** in `MIGRATION_SUMMARY.md`. `ruff` is a **runtime** dependency.
- **D3 — git safety:** require a clean working tree (abort otherwise); refuse a
  non-repo unless `--init` (then commit the original py2 tree as a baseline so the
  migration is diffable); branch from HEAD; per-module commits are created only
  after the project-wide verify passes (only HEAD is guaranteed green);
  `--dry-run` writes **nothing** to disk.
- **D4 — cost/scale:** prompt-cache the shared system prompt + dependency context
  (`cache_control`) to avoid an O(n²) re-send blowup, and run a `count_tokens`
  preflight with a confirmation gate for large repos. Add `--target-version`.
- **D5 — Coder I/O:** the Coder **streams plain text** (the migrated file,
  de-fenced) rather than JSON-structured output (avoids whole-file escaping and
  silent truncation); it guards `stop_reason` for `max_tokens`/`refusal`.

## 1. Goal & Context

ClaudeMigrate is a **CLI tool you actually run** on a real Python 2 codebase to
migrate it to Python 3. It is not a portfolio mock-up: the success bar is a
working tool that produces a Python 3 branch that compiles and passes tests.

It improves on the legacy `2to3` tool by understanding **semantic** and
**cross-file** changes (the "orphan file" problem): when one module changes, the
files that depend on it are updated in the same pass, because the Coder sees the
target file *and its dependencies together* inside Claude Opus 4.8's 1M context
window.

### Locked decisions

| Decision | Choice |
|---|---|
| Purpose | Real tool to use |
| Foundation | Anthropic **Python SDK** (`anthropic`), self-hosted tool-use surface |
| Migration | **Python 2 → 3** (only) |
| Tool language | **Python** |
| Orchestration | Deterministic Python pipeline: Planner → Coder → Verifier |
| Verifier (MVP) | **Static** (`py_compile` + `ruff` + run existing `pytest` if present) |
| Output | New git branch + `MIGRATION_SUMMARY.md` |

**Why the Anthropic SDK and not Managed Agents:** Managed Agents runs tools in
Anthropic's hosted container. We need file edits and `pytest` to run **locally**
against the user's repo, so we use the self-hosted "Claude API + tool use"
surface (the `anthropic` package), where our Python orchestrator owns the loop.

## 2. Architecture

A deterministic Python orchestrator drives the loop. No agent controls flow.

```
repo (py2)
   │
   ▼
[depgraph]  ──  AST import graph → topological file order
   │
   ▼
[Planner agent]  ──  structured output → MigrationPlan
   │                  (ordered units + per-file risk + py2→3 notes)
   ▼  for each unit, in dependency order:
[context_builder] → target file + direct dependencies (read-only) in 1M context
   │
   ▼
[Coder agent]  ──  structured output → { migrated_code, notes }
   │
   ▼
[Verifier]  ──  py_compile(py3) + ruff + (pytest if present)   ← deterministic, no LLM
   │            ├─ pass → write to branch + commit the module
   │            └─ fail → feed errors back to Coder (max 3 retries)
   ▼
[final project-wide Verifier]  ──  one pass over the whole repo
   │
   ▼
[git] → branch + per-module commits + MIGRATION_SUMMARY.md
```

## 3. Components

Each unit has one clear purpose, a typed interface, and is independently testable.

### `core/depgraph.py`
- **Does:** Extracts imports from every `.py` file with the stdlib **`tokenize`**
  module (D1 — lexical, tolerates py2 source), builds the intra-repo import graph,
  and returns a dependency-ordered list of files. Cyclic dependencies are
  collapsed into a strongly-connected component (SCC) and emitted as one group
  (migrated together, all files mutable).
- **In:** repo root path. **Out:** ordered list of files + dependency map.
- **Deps:** stdlib only (`tokenize`). No LLM.

### `agents/planner.py`
- **Does:** One `client.messages.parse()` call (structured output). Reviews the
  dependency graph and a summary of each file, and produces a `MigrationPlan`:
  ordered units, a risk level per file, and per-file py2→3 notes (e.g. `print`
  statements, `except X, e`, integer division, `dict` iterator methods,
  `unicode`/`str`/`bytes`, relative imports).
- **In:** dependency graph + file summaries. **Out:** `MigrationPlan`.
- **Deps:** `core.client`, `models.MigrationPlan`.

### `core/context_builder.py`
- **Does:** For a unit, assembles the target file (to be rewritten) plus the full
  text of its direct dependencies as **read-only context**. This is the
  orphan-file mechanism: the Coder sees both the file being changed and the
  signatures of the modules it depends on.
- **In:** target unit + dependency map + repo files. **Out:** prompt context.
- **Deps:** `core.depgraph`.

### `agents/coder.py`
- **Does:** One streaming SDK call per unit. Rewrites the target file (or all files
  of an SCC group); dependencies outside the group are context only. Returns the
  migrated file as **plain streamed text** (D5), de-fenced — not JSON-structured.
  Guards `stop_reason` for `max_tokens` (truncation ⇒ failure) and `refusal`.
- **In:** context from `context_builder` + (on retry) prior verifier errors.
- **Out:** `FileResult { path, migrated_code, notes="" }`.
- **Deps:** `core.client`, `models.FileResult`, `prompts`.

### `core/verifier.py`
- **Does:** Deterministic, **no LLM** — a *safety net*, not a correctness proof
  (D2). The Coder performs the semantic migration; this catches obvious breakage:
  1. `verify_file`: `py_compile` each migrated file under Python 3 — **syntax**
     gate only (py2-only syntax surfaces as `SyntaxError`; semantic py2→3 bugs do
     **not**).
  2. `verify_project` — the **real gate**: `compileall` + an import smoke-test of
     every migrated module (catches cross-file/orphan breakage a per-file compile
     can't), then `ruff check --select E9,F,UP --target-version <tv>`.
  3. If the repo has a `pytest` suite that collects cleanly in this env, run it;
     otherwise record a **non-silent skip**.
  Ambiguous semantic cases (integer `/`, str/bytes) are surfaced for human review.
- **In:** migrated file(s) + repo + target version. **Out:** `VerifyResult { ok, errors }`.
- **Deps:** subprocess (`py_compile`, `ruff`, `pytest`). `ruff` is a runtime dep. No LLM.

### `core/git.py`
- **Does:** `git init` if the target isn't a repo; create branch
  `claudemigrate/py2to3-<timestamp>`; commit **one commit per migrated module**;
  generate `MIGRATION_SUMMARY.md` (files changed, notes, flagged files, skipped
  tests) as a final commit.
- **In:** repo path, per-module results. **Out:** branch + commits + summary.
- **Deps:** `git` CLI via subprocess.

### `core/client.py`
- **Does:** Thin wrapper around `anthropic.Anthropic()`: default model, streaming
  helper, structured-output helper. (The SDK already retries 429/5xx.)
- **In:** request params. **Out:** parsed responses.
- **Deps:** `anthropic`.

### `cli.py`
- **Does:** Entry point using **Typer**: `claudemigrate run <path> [--dry-run]
  [--max-retries 3]`. `--dry-run` runs Plan + Code + Verify and writes the
  summary but makes **no** git commits (changes shown as a diff only).
- **Deps:** `typer`, `orchestrator`.

### `orchestrator.py`
- **Does:** Wires the deterministic loop: depgraph → planner → per-unit
  (context → coder → verifier → retry → commit) → final verify → summary.
- **Deps:** all of the above.

## 4. Models & SDK

- Package: `anthropic` (`pip install anthropic`).
- **Planner & Coder model:** `claude-opus-4-8` (1M context — the basis of the
  dependency-aware pitch), with `thinking={"type": "adaptive"}` and
  `output_config={"effort": "high"}`.
- **Coder** uses **streaming** (`client.messages.stream`, `max_tokens` up to
  `64000`) because source files can be large.
- **Structured output** via `client.messages.parse(...)` with Pydantic models
  (`MigrationPlan`, `FileResult`).
- **Verifier** makes **no** LLM calls — cheap, deterministic, unit-testable.
- Cheaper option (phase 2, not now): run the Coder on `claude-sonnet-4-6` for
  low-risk files.

## 5. Retry loop

Per file: Coder → Verifier. On failure, the verifier error text
(`py_compile` / `ruff` / `pytest` output) is fed back to the Coder as a user
message; **max 3 attempts**. After 3 failures the file is **flagged** and recorded
in the summary — never silently skipped.

## 6. Error handling & edge cases

- Requires a **Python 3** interpreter (the one running the tool).
- Existing tests run **only** if they import cleanly and dependencies are
  installed; otherwise they are skipped with a clear message recorded in the
  summary (no silent skip).
- Dynamic / conditional imports (`__import__`, runtime imports) that the AST can't
  see are flagged for **manual review** in the summary.
- Cyclic imports are handled by the SCC grouping in `depgraph`.

## 7. Testing & success criteria

A small **real Python 2 fixture** lives at `tests/fixtures/py2_sample/`,
containing: a `print` statement, `except X, e:` syntax, integer division, and a
helper module that another file depends on (to prove the orphan-file scenario).

**Verifiable MVP goal:** running `claudemigrate run tests/fixtures/py2_sample`
produces a branch where (1) every file passes `py_compile` under Python 3,
(2) the fixture's bundled `pytest` suite passes, and (3) the dependent file whose
helper signature changed is correctly updated.

Unit tests cover `depgraph` (ordering, cycles), `verifier` (pass/fail on known
inputs), and `git` (branch + commit) without LLM calls. Agent calls are exercised
in the end-to-end fixture run.

## 8. Directory structure

```
claudemigrate/
├── claudemigrate/
│   ├── cli.py            orchestrator.py   models.py   prompts.py
│   ├── agents/           planner.py        coder.py
│   └── core/  client.py  depgraph.py  context_builder.py  verifier.py  git.py
├── tests/  fixtures/py2_sample/  test_depgraph.py  test_verifier.py  ...
├── pyproject.toml   CLAUDE.md   README.md
```

## 9. Scope (YAGNI)

**MVP:** Python 2→3 only; deterministic pipeline; static verify; branch +
per-module commits + summary; dependency-aware context; retry loop; fixture-based
validation.

**Phase 2 (not now):** characterization tests (need a Python 2 interpreter for the
baseline); real GitHub PR creation via `gh`; other migration types; parallel file
processing; Sonnet-for-low-risk-files routing.

## 10. Resolved choices

- **ruff vs pyright for verify:** ruff in MVP (fast, near-zero-config, strong
  py2→3 `UP` rules). `py_compile` is the hard gate. pyright is phase 2.
- **Commit granularity:** one commit per migrated module (reviewable history that
  feeds the PR summary), plus a final summary commit.

## 11. v0.2 — Usability & transparency (addendum)

v0.2 makes a run observable and accountable **without changing migration
behaviour**. Everything here is additive and backward-compatible — return
contracts, the `Provider` protocol, and the existing fixtures are unchanged.

- **Reporter (`on_event`):** the orchestrator takes an optional `on_event`
  callback and emits frozen event dataclasses from `core/events.py`
  (`DepGraphDone`, `PlanDone`, `UnitStart`, `FileRetry`, `FileDone`,
  `ProjectVerifyResult`, `Commit`). This mirrors the existing `cost_confirm`
  callback pattern and defaults to a no-op, so library and MCP behaviour is
  byte-identical when no reporter is passed. The CLI's `_ConsoleReporter` renders
  the `[1/4]..[4/4]` progress from these events.
- **Token/cost accounting:** `core/client.py` accumulates token usage as a side
  effect over both backends (a `Usage` accumulator), and `core/pricing.py` holds
  the per-model rate table. `price(model, usage)` returns a `CostReport`; an
  unknown model yields `pricing_known=false` and `cost_usd=null` (so callers
  distinguish "unknown" from "free"). A per-model env override
  `CLAUDEMIGRATE_PRICE_<MODEL>` is honoured.
- **Per-step verify:** `verify_steps` (compile / ruff / pytest) is added to the
  verify result and surfaced both live (`[4/4]`) and in the report — additive to
  the existing `VerifyResult { ok, errors }`.
- **Structured logging:** all logs go through the `claudemigrate` logger to
  **stderr** (stdout is reserved for progress and JSON), with levels driven by
  `--verbose`/`--quiet`.
- **Versioned report:** `MigrationReport.to_dict()` produces a stable
  `schema_version: 1` JSON view (no I/O) consumed by both `--json`/`--report-json`
  and the MCP tool's `cost` key. Dry-run reports carry the full unified `diff`.
