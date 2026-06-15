# ClaudeBackend

A **universal multi-agent backend development system**. Give it a repo and an
objective in plain English — *"Add JWT authentication"*, *"Refactor the SQLAlchemy
models"*, *"Migrate this Python 2 code to Python 3"* — and it implements the change
through an isolated, deterministic `Planner → Coder → Verifier` pipeline. Default
backend is Claude Opus 4.8 (1M context).

ClaudeBackend understands **semantic** and **cross-file** changes. It first builds
a map of your codebase (Python imports **and** ORM models, Dockerfiles, and config
files), so the Planner can decide *which files to create, modify, or delete* to
achieve the objective, and the Coder sees each target file *together with its
dependencies* inside a large context window.

It runs as a **deterministic Python pipeline** and writes the result to a **new
git branch** with a `DEV_SUMMARY.md` and a `DEV_GRAPH.md` topology graph. Your
working tree and current branch are never touched.

**New here?** Read [*what ClaudeBackend is and why you'd use it*](docs/about/en.md) —
also in [فارسی](docs/about/fa.md), [日本語](docs/about/ja.md), [中文](docs/about/zh.md),
[Русский](docs/about/ru.md), [Français](docs/about/fr.md), and [Deutsch](docs/about/de.md).

## Why it's different

| | codemods / `2to3` | linters (SonarQube) | AI chat assistants | ClaudeBackend |
|---|---|---|---|---|
| Implements an arbitrary objective | ❌ fixed rules | ❌ read-only | ✅ | ✅ |
| Dependency-aware (ORM/Docker/config too) | ❌ | partial | ❌ | ✅ |
| Deterministic verify gate (compile + ruff + pytest) | ❌ | ❌ | ❌ | ✅ |
| Flags ambiguous / security-sensitive choices | ❌ | ❌ | ❌ | ✅ (`CLAUDEBACKEND-REVIEW`) |
| Output | edits in place | a report | chat text | a reviewable git branch + summary + graph |

## Install

Requires **Python 3.10+**. The quickest path is the per-OS bootstrap script — it
detects Python, creates a `.venv`, installs ClaudeBackend into it, and verifies
the `claudebackend` command works (idempotent, safe to re-run):

| OS | One-time setup (from the repo root) | Guide |
|---|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` | [docs/install/windows.md](docs/install/windows.md) |
| macOS | `chmod +x scripts/setup-macos.sh && ./scripts/setup-macos.sh` | [docs/install/macos.md](docs/install/macos.md) |
| Linux | `chmod +x scripts/setup-linux.sh && ./scripts/setup-linux.sh` | [docs/install/linux.md](docs/install/linux.md) |

Pass `--dev` to also install the test extras. Prefer to do it by hand? Just
`pip install -e .[dev]`. For the SAST half of the security gate, add the optional
`security` extra (`pip install claudebackend[security]`) to pull in **bandit**;
without it the gate's static scan degrades to a note and the Red Team LLM audit
still runs.

## Usage

First time? Run the per-OS setup script above, then **activate the venv** so
`claudebackend` is on your PATH — `.\.venv\Scripts\Activate.ps1` on Windows,
`source .venv/bin/activate` on macOS/Linux.

```bash
# Authenticate one of four ways (pick one):
export ANTHROPIC_API_KEY=...                 # 1) pay-per-token Anthropic key
#   Windows PowerShell:  $env:ANTHROPIC_API_KEY = "..."   (use setx to persist)
claude   # or: ant auth login                # 2) log in, then add --use-subscription
#            3) another provider — see "Other LLM backends" below
#            4) fully local, no key — see "Local AI" below

# develop <path> "<objective>"
claudebackend develop ./service "Add a /health endpoint" --dry-run   # preview only
claudebackend develop ./service "Add JWT authentication"             # onto a new branch
claudebackend develop ./service "Add rate limiting" --init           # ...if it's not a git repo yet
claudebackend develop ./service "Refactor the models" --use-subscription

# Fully local / offline (Ollama) — no API key, air-gapped:
ollama pull qwen2.5-coder
claudebackend develop ./service "Add a /health endpoint" --dry-run --local --model qwen2.5-coder
```

**Local AI (offline / air-gapped):** `--local` runs the whole pipeline against
[Ollama](https://ollama.com) on your own hardware with **zero external calls**,
per-agent model routing, and strict context-window limits. A Docker stack is
included. See **[docs/install/local_ai.md](docs/install/local_ai.md)**.

Always start with `--dry-run`: it runs the full Plan → Code → Verify on a
throwaway copy and prints the diff and summary **without writing anything**.

### `develop` options

| Option | Default | Purpose |
|---|---|---|
| `--dry-run` | off | Preview only; no disk writes, no commits. |
| `--init` | off | If the path is not a git repo, commit the current tree as a baseline first. |
| `--max-retries` | `3` | Coder attempts per step before it's flagged. |
| `--target-version` | this interpreter | Target Python (e.g. `py311`) for the verifier/lint. |
| `--use-subscription` | off | Use a Claude Code / `ant auth login` session instead of `ANTHROPIC_API_KEY` (Anthropic only). |
| `--provider` | `anthropic` | LLM backend (see below). |
| `--local` | off | Run fully offline against local Ollama — air-gapped, no external calls ([guide](docs/install/local_ai.md)). |
| `--ollama-base-url` | `http://localhost:11434/v1` | Ollama endpoint (or set `OLLAMA_BASE_URL`). |
| `--model` | — | Default model id (required for non-Anthropic providers, incl. Ollama). |
| `--planner-model` / `--coder-model` / `--verifier-model` | — | Per-agent model routing (most useful with `--local`). |
| `--security-gate` / `--no-security-gate` | on | Per-step blocking security gate (bandit SAST + Red Team LLM audit) on the Coder's new code; unfixable vulns are discarded. |
| `--security-review` | off | Extra advisory LLM security review of the changed files (routed to `--verifier-model`). |
| `--api-key` | from env | API key for the chosen provider. |
| `--yes` / `-y` | off | Skip the cost-confirmation prompt on large repos. |
| `--verbose` / `-v` | off | Verbose DEBUG logging to stderr. |
| `--quiet` / `-q` | off | Suppress live progress; still print the summary and cost line. |
| `--json` | off | Print the run report as JSON to stdout (implies `--quiet`). |
| `--report-json PATH` | — | Also write the JSON run report to PATH (works in human mode too). |
| `--no-cost` | off | Do not print the final token/cost line. |

## How it works

1. **Codebase map** — a graph of the repo: Python imports (via the stdlib
   `tokenize` module, which tolerates legacy/partial source), plus ORM model
   relationships (Django / SQLAlchemy), Dockerfile `COPY`/`ADD` references, and
   config-file references. This is *context*, not a script.
2. **Planner** reads the objective and the map and produces an `ExecutionPlan`: an
   ordered list of steps, each one a file to **create**, **modify**, or **delete**
   with precise instructions, a risk level, and dependencies.
3. For each step, in dependency order: a **context** is built (the objective, the
   step instructions, the target file, and its related files — with prompt caching
   on the stable parts), the **Coder** streams the full new file, and a **syntax
   gate** (`py_compile`) checks Python files; failures feed back to the Coder (up
   to `--max-retries`).
4. **Security gate** (on by default) — once the syntax gate passes, the new file is
   scanned with **bandit** (SAST) and audited by a **Red Team** agent with an
   attacker's mindset (SQLi, IDOR, XSS, injection, auth/authz, SSRF, path traversal,
   unsafe deserialization, secrets). A blocking finding feeds the *vulnerability*
   back to the Coder and consumes a retry; if it can't be fixed within
   `--max-retries`, the unsafe file is **discarded** (never written, never
   committed). The deterministic checks always run first — the Red Team is an
   addition to the safety net, not a replacement.
5. A **project-wide verify** runs after all steps: compile every module + `ruff`
   (undefined names / syntax) + the repo's own `pytest` suite if it collects + an
   advisory bandit scan. This is the real cross-file gate.
6. **git** creates `claudebackend/feature-<timestamp>`, commits per step, renders
   the `DEV_GRAPH.md` / `graph.html` topology graph, and writes `DEV_SUMMARY.md`
   (files created/modified/deleted, discarded-as-unsafe files, flagged files, SAST
   findings, and items marked for review).

**Honest about verification (by design):** the Coder (the LLM) writes the code;
the static checks are a *safety net*, not a correctness proof. `py_compile` catches
syntax only. The Coder adds a `CLAUDEBACKEND-REVIEW` comment wherever it makes an
ambiguous architectural decision or a security-sensitive change (raw SQL, auth,
crypto, deserialization, subprocess) so you can confirm it. The surest guarantee is
the repo's own test suite passing afterwards.

## Continuous development (CI/CD + TDD watcher)

Beyond the manual `develop` command, ClaudeBackend runs as an event-driven agent.

**GitHub Action — issue → PR.** Drop
[`.github/workflows/claude-backend-agent.yml`](.github/workflows/claude-backend-agent.yml)
into a repo and add the `ANTHROPIC_API_KEY` secret. Label an issue **`ai-developer`**
(or **`ai-feature`**) and the agent develops it on an isolated
`claudebackend/issue-<id>` branch, then **opens a PR only if it verifies safely**
(deterministic checks + Red Team gate) — otherwise it **comments on the issue**
explaining why. The PR body includes the `DEV_SUMMARY`, cost/tokens, verification
steps, and any `CLAUDEBACKEND-REVIEW` markers. It never pushes to `main`/`master`,
and tokens come from standard Actions secrets (no hardcoding). `CI=true` makes runs
non-interactive automatically.

**Local TDD watcher — red → green.** Install the extra and watch your tests:

```bash
pip install "claudebackend[watch]"
claudebackend watch --dir tests        # watches ./tests for saves
```

Write a failing test and save — the watcher feeds the pytest failure to the Coder
and implements the code to make it pass, **in place** (no branch, no commit) so you
review and commit. If a test stays red after `--max-retries`, it halts and waits for
your next edit (no infinite loops; it only reacts to test-file saves, never its own
source writes).

## Progress & cost

A run prints live `[1/4]..[4/4]` progress and a final token/cost line:

```
$ claudebackend develop ./service "Add a /health endpoint"
[1/4] graph: 37 files (python 30, orm 2, config 5), 1 dynamic
[2/4] plan: 4 steps (1 high-risk)
[3/4] develop  ####------  step 2/4  create health.py
[4/4] verify: compile OK | ruff OK | pytest 18 passed

Branch: claudebackend/feature-20260614-...
Project verification: PASSED
Created 1, modified 2, deleted 0 file(s)
Cost  in 1.24M  out 412k  ~$23.10  (cache hit 71%)
```

Progress goes to **stdout** (redrawn in place on a TTY; one line per phase when
piped); logs go to **stderr**. `--quiet` drops the progress bar but keeps the
summary and the `Cost` line. The `$` figure only appears for models in the
built-in pricing table (the Anthropic models) — others report tokens with
`pricing_known=false` (see [docs/providers.md](docs/providers.md)).

`--json` emits a versioned machine-readable report (`schema_version: 2`) with the
full unified `diff`, so you can apply or inspect a dry run programmatically:

```bash
claudebackend develop ./service "Add caching" --dry-run --json | jq -r .diff | git apply
```

## Other LLM backends

Claude is the default and **recommended** backend — its 1M context + prompt
caching are what power the dependency-aware development. You can also use
OpenRouter, OpenAI, NVIDIA, DeepSeek, or Gemini (all OpenAI-compatible):

```bash
claudebackend develop ./service "Add logging" --dry-run --provider deepseek --model deepseek-chat
```

Non-Claude backends have smaller effective context and no caching, so they're
weaker on large repos. See **[docs/providers.md](docs/providers.md)** for env
vars, base URLs, example model ids, and trade-offs.

## Use from IDEs / agents (MCP, skill, plugin)

ClaudeBackend exposes itself as an **MCP server** (`claudebackend mcp`), an
**Agent Skill** (`skills/migrate-python-2-to-3/` — the bundled py2→3 example), and
a **Claude Code plugin** (`.claude-plugin/plugin.json`). That's how Cursor, Google
Antigravity, Codex, and Claude Code/Desktop use it — they call its
`develop_backend_feature` tool, which defaults to a dry run so an agent never
mutates a repo unprompted. See **[docs/integrations.md](docs/integrations.md)**.

## Roadmap

ClaudeBackend's codebase mapping and verification run through a **pluggable
language-driver layer** (`core/drivers/`): the language-specific logic — source
detection, dependency parsing, syntax/test/SAST commands, and prompt hints — lives
behind one interface, with **Python** as the current driver. (This is orthogonal to
the LLM-backend layer in `core/providers/`, so any provider composes with any
language.) Built on that foundation, **in progress — not yet shipped**:

- **PHP support** — a `PHPDriver`: `composer.json` / PSR-4 dependency mapping,
  `php -l` + phpstan/psalm + phpunit verification, and PHP-specific security
  analysis (raw-PDO SQLi, unvalidated redirects, insecure includes), selectable via
  a new `--lang python|php` flag with auto-detection from the repo.
- **Live dashboard** — a local, **air-gapped** streaming server (SSE) plus a
  decoupled **React** UI that shows the `Planner → Coder → Verifier` pipeline in
  real time: live token/cost counters, the dependency-topology graph, unified diffs,
  and a human-in-the-loop screen to approve/reject `CLAUDEBACKEND-REVIEW` changes —
  every change still flowing through the same git feature-branch safety model.

## Safety

- Refuses a **dirty working tree**; refuses a non-repo unless you pass `--init`.
- All changes land on a **new branch** — your current branch is untouched.
- `--dry-run` and the MCP tool's default dry run write **nothing** to disk.
- Verification runs in-process / with `PYTHONDONTWRITEBYTECODE`, so it never
  litters the target repo with `__pycache__`.
- The **security gate** is static-only (bandit reads the AST; the Red Team reviews
  source text) — generated code is never executed outside the `pytest` gate. Code
  it deems unfixably unsafe is **discarded**, not committed.

## Project layout

```
claudebackend/
  cli.py  orchestrator.py  models.py  prompts.py  mcp_server.py
  agents/   planner.py  coder.py  security_auditor.py  security_reviewer.py
  core/     client.py  depgraph.py  context_builder.py  graphviz.py  verifier.py  git.py
            drivers/    base.py  python.py            (pluggable language drivers)
            providers/  base.py  openai_compat.py     (pluggable LLM backends)
skills/migrate-python-2-to-3/SKILL.md   .claude-plugin/plugin.json   .mcp.json
commands/develop.md
scripts/  setup.ps1  setup-macos.sh  setup-linux.sh     (per-OS bootstrap)
docs/     providers.md  integrations.md  install/{windows,macos,linux}.md
tests/    (offline tests + an e2e acceptance test)
```

## Develop

```bash
pip install -e .[dev]
pytest -m "not e2e"     # fast offline suite — no API key, no network, no cost
pytest -m e2e           # real end-to-end run on the bundled Py2 fixture
                        #   (needs ANTHROPIC_API_KEY; skipped otherwise)
ruff check claudebackend --select E9,F
```

The offline suite is fully mocked (no provider calls). The `e2e` test drives the
generic pipeline with the objective *"migrate this Python 2 code to Python 3"* on
`tests/fixtures/py2_sample/` and asserts the result compiles and its tests pass.

## Design

See `docs/superpowers/specs/2026-06-14-claudebackend-design.md` for the design of
the generalized system (and the original py2→3 spec alongside it for history).

## License

MIT.
