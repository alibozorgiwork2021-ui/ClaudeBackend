# ClaudeBackend — what it is, and why you'd use it

**English** · [فارسی](fa.md) · [日本語](ja.md) · [中文](zh.md) · [Русский](ru.md) · [Français](fr.md) · [Deutsch](de.md)

> A universal, multi-agent **backend development system**: hand it a repository
> and a plain-language objective, and it implements the change on a reviewable
> git branch — dependency-aware, verified, and never touching your working tree.

## What is ClaudeBackend?

ClaudeBackend is a command-line agent that takes a code repository plus an
arbitrary objective written in plain language — "Add JWT authentication",
"Refactor the SQLAlchemy models", "Add a `/health` endpoint", or even "Migrate
this from Python 2 to 3" — and implements it. It is powered by a large language
model (Claude Opus 4.8 by default, with a 1M-token context window) wrapped in a
**deterministic, isolated three-agent pipeline**: a **Planner** decides which
files to create, modify, or delete; a **Coder** implements each step; and a
**Verifier** runs syntax checks, `ruff`, and the project's own `pytest` suite as
a safety net (with up to 3 retries). The model does the actual coding; the
surrounding program decides *what* to change, *in what order*, and *checks the
result*. The output is written to a **new git branch** — your working tree and
current branch are never touched.

## The problem it solves

Real backend work rarely fits in a single file. Adding an endpoint, swapping an
auth scheme, reshaping a data model, or modernizing a legacy codebase all ripple
across modules, ORM models, configuration, and tests. Doing it by hand is slow
and error-prone; doing it with a naive code assistant is risky, because the
assistant edits one file at a time and can't see how a change in one place breaks
another.

The dangerous bugs are the ones that cross file boundaries:

> A helper returns `d.keys()`. In Python 2 that's a `list`, so another module
> safely writes `keys()[0]`. In Python 3 `keys()` is a *view* — `keys()[0]`
> raises `TypeError`. A purely local tool "fixes" both files and leaves the
> codebase broken, because the bug only shows up when you look at the two files
> *together*. The same trap hides in countless backend changes — rename a model
> field, and every query and serializer that touched it can break silently.

## Why ClaudeBackend is different

| | naive code assistants | linters (e.g. SonarQube) | ClaudeBackend |
|---|---|---|---|
| Implements a change (not just edits/reports) | one file at a time | read-only | end-to-end across the repo |
| Cross-file / dependency-aware fixes | no | no | yes — maps imports, ORM, config |
| Flags ambiguous / risky choices | no | no | yes (`CLAUDEBACKEND-REVIEW`) |
| Output | edits in place | a report | a reviewable git branch + summary |

The core idea: ClaudeBackend builds a **dependency graph** of your code — it maps
Python imports *and* ORM models (Django / SQLAlchemy), Dockerfiles, and config
files — and gives the Planner that real context. Each file is shown to the model
*together with its dependencies* inside a very large context window. That is why
it can implement changes that ripple across files, instead of the broken,
file-at-a-time edits that purely local tools produce.

## Who needs it

- **Teams shipping backend features** who want a reviewable branch, not a
  black-box bulk edit.
- **Maintainers** modernizing services, reshaping data models, or paying down
  technical debt across many files.
- **Consultants and contractors** doing large refactors or migrations who want a
  reviewable diff, not a black box.
- **Anyone** with a legacy codebase — including a Python 2 utility that "still
  works" but no longer installs on a modern machine — that needs a careful,
  dependency-aware update.

## Key features

- **Dependency-aware, cross-file development** — the headline capability: it maps
  imports, ORM models, Dockerfiles, and config so the Planner sees real context.
- **Three-agent pipeline** — Planner, Coder, and Verifier run as isolated,
  deterministic stages so every objective follows the same disciplined path.
- **Honest, layered verification** — a syntax gate per file, then a project-wide
  pass (compile + `ruff` + your own `pytest` suite, if it collects), with up to
  3 retries as a safety net.
- **Safe by construction** — it refuses a dirty working tree, writes only to a
  new branch (`claudebackend/feature-<timestamp>`), and has a `--dry-run` mode
  (the default for agents) that writes nothing.
- **Flags what it isn't sure about** — ambiguous or security-sensitive changes
  are implemented *and* marked with a `CLAUDEBACKEND-REVIEW` comment for a human
  to confirm.
- **Use your own LLM** — Claude by default; also other OpenAI-compatible
  providers (OpenRouter, OpenAI, NVIDIA, DeepSeek, and Gemini).
- **Use it from your tools** — it ships as an MCP server, an Agent Skill, and a
  Claude Code plugin, so Cursor, Codex, Google Antigravity, and Claude
  Code/Desktop can call it.

## How it works (at a glance)

1. **Graph** — map the repository's dependencies: Python imports (via the stdlib
   `tokenize`, so it can parse even Python 2 source that `ast` rejects), ORM
   models (Django / SQLAlchemy), Dockerfiles, and config files. Import cycles
   collapse into a single unit.
2. **Plan** — the Planner turns your objective into a concrete list of files to
   create, modify, or delete, annotated with per-file risk and notes.
3. **Develop** — for each step, the Coder builds context (the file plus its
   dependencies, with prompt caching), streams the change, syntax-checks it, and
   retries on failure.
4. **Verify** — a project-wide compile + lint + test pass: the real cross-file
   gate (up to 3 retries).
5. **Commit** — create the branch, commit per module, and write a `DEV_SUMMARY.md`
   plus an interactive `DEV_GRAPH.md` topology graph.

## Honest about its limits

The static checks are a **safety net, not a correctness proof**. Syntax checks
and `ruff` catch a class of mistakes — but behaviour-preserving-yet-ambiguous
choices are decided by the model and *flagged* for you, not proven correct. The
surest guarantee is your **own test suite passing** after the change.
ClaudeBackend is built to make that review fast and honest, not to pretend
backend work is fully automatable.

## Getting started

```bash
# 1. Install (per-OS bootstrap script — see the install guides):
#    Windows: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#    macOS:   ./scripts/setup-macos.sh
#    Linux:   ./scripts/setup-linux.sh

# 2. Authenticate (e.g. with an Anthropic API key) and preview the work first:
export ANTHROPIC_API_KEY=...
claudebackend develop path/to/repo "Add a /health endpoint" --dry-run  # writes nothing
```

**Learn more:** [Project README](../../README.md) ·
[LLM backends](../providers.md) · [IDE / agent integrations](../integrations.md)
· install guides for [Windows](../install/windows.md),
[macOS](../install/macos.md), and [Linux](../install/linux.md).
