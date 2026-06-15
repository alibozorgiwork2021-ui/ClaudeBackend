---
name: migrate-python-2-to-3
description: Migrate a Python 2 codebase to Python 3 using the `claudebackend` tool. Use when the user wants to upgrade, port, or modernize Python 2 code, run a py2->3 migration, or fix Python 2 syntax and semantics (print statements, except-comma, integer division, dict views, unicode/bytes) across a repository. Drives the generic ClaudeBackend pipeline with a py2->3 objective; understands cross-file ("orphan file") changes by passing a file together with its dependencies.
---

# Migrate Python 2 to 3

`claudebackend` is a universal backend development tool (a deterministic
Planner -> Coder -> Verifier pipeline). Python 2 -> 3 migration is one example
objective: you run the generic `develop` command with a migration objective and it
plans the per-file changes, implements them, and verifies the result. Unlike
`2to3`, it understands semantic and cross-file changes.

Its analysis and verification run through a pluggable language-driver layer
(`core/drivers/`); **Python** is the current driver (this skill), and **PHP**
support plus a local streaming dashboard are in progress — see the project README
roadmap.

## When to use
The user asks to migrate / port / upgrade / modernize a Python 2 project or fix
py2-only syntax across a repo.

## How to invoke
Always preview first (writes nothing), then confirm before the real run. Pass the
migration as the objective string:

```bash
# 1. Preview (no writes, no git changes) — show the diff and the summary
claudebackend develop <path-to-py2-repo> "Migrate this Python 2 codebase to modern Python 3, preserving behaviour exactly (fix print statements, except-comma syntax, integer division, dict views, unicode/bytes, xrange)." --dry-run

# 2. Real run onto a new git branch (requires a clean working tree;
#    add --init if <path> is not yet a git repo)
claudebackend develop <path-to-py2-repo> "Migrate this Python 2 codebase to modern Python 3, preserving behaviour exactly." 
```

## Backends (optional)
Default is Claude Opus 4.8 (recommended — 1M context powers the dependency-aware
work). Other backends: `--provider {anthropic|openrouter|openai|nvidia|deepseek|gemini} --model <id>`
with the matching API key in the environment. See `docs/providers.md`.
`--use-subscription` uses a Claude Code / `ant auth login` session instead of an
API key (anthropic only).

## What to report back
After a run, report: project verification PASSED/FAILED, files
created/modified/deleted, any files **discarded as unsafe** by the security gate,
any flagged files (failed verification after retries), and files marked
`CLAUDEBACKEND-REVIEW` (ambiguous choices like integer division). Details land in
`DEV_SUMMARY.md` (and the `DEV_GRAPH.md` topology graph) on the new branch.

## Safety
- The real run refuses a dirty working tree and never touches the user's current
  branch — all changes land on a new `claudebackend/feature-*` branch.
- Prefer `--dry-run` until the user confirms.
