---
description: Develop a backend feature with ClaudeBackend (dry-run first)
argument-hint: <path-to-repo> "<objective>" [--provider X --model Y]
---

Run a **dry-run** ClaudeBackend pass first, show me the preview (diff + summary),
and wait for my confirmation before writing anything. `$ARGUMENTS` is the repo
path followed by the objective in quotes (e.g. `./service "Add JWT authentication"`):

```bash
claudebackend develop $ARGUMENTS --dry-run
```

If I confirm the preview looks right, run it for real. It creates a new git branch
and requires a clean working tree; add `--init` if the path is not a git
repository:

```bash
claudebackend develop $ARGUMENTS
```

A per-step security gate (bandit SAST + a Red Team LLM audit) runs by default;
unfixable vulnerabilities are **discarded** rather than committed (pass
`--no-security-gate` to disable it).

Then report the project verification status (PASSED/FAILED), the files
created/modified/deleted, any **discarded-as-unsafe** files, any flagged files
(failed verification after retries), and any files marked for human review
(`CLAUDEBACKEND-REVIEW` — ambiguous or security-sensitive changes). Full details
land in `DEV_SUMMARY.md` and the `DEV_GRAPH.md` topology graph on the new branch.
