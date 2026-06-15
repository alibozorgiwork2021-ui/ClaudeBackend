# Changelog

All notable changes to ClaudeBackend are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

"Multi-language + live dashboard" — ClaudeBackend stops being Python-only and gains an
optional, fully local web dashboard. Purely additive: every new parameter defaults to
the previous behaviour, so existing Python runs, the git safety model, pricing, and the
security gate are byte-for-byte unchanged.

### Added

- **PHP support via a `LanguageDriver` abstraction** (`core/drivers/`): `PythonDriver`
  (unchanged behaviour) and a new `PHPDriver` — regex dependency graph (`use`/`extends`/
  `implements`/`include`/`require`), PSR-4 resolution from `composer.json`, and
  verification via `php -l` / phpstan|psalm / phpunit, each **degrading gracefully when
  the toolchain is absent** (recorded note, never a failed build). A deterministic regex
  PHP SAST feeds the existing per-step security gate, so a raw `$_GET` SQL concat is
  blocked exactly like a Python `pickle.loads`.
- **`--lang auto|python|php`** on `develop` (and `lang` on the MCP tool): auto-detects
  from the repo's manifest (`composer.json` → php; `pyproject.toml`/`requirements.txt` →
  python). `--local`/Ollama composes unchanged — the driver only swaps verify commands
  and prompt hints, not the provider.
- **Local air-gapped dashboard server** (`claudebackend serve`, optional `[web]` extra):
  a loopback-only Starlette + uvicorn server that streams live pipeline events,
  token/cost, the dependency-topology graph, and diffs over Server-Sent Events, with a
  **human-in-the-loop review endpoint** (`POST /api/runs/{id}/review`) where a *reject*
  reverts the file on the isolated feature branch — never `main`/`master`. Binds
  `127.0.0.1` only unless `--allow-remote`; makes no outbound calls of its own; all run
  state is in-memory. The React UI is built and served separately and is never packaged
  into the wheel.

## [0.6.0] - 2026-06-14

"Continuous development" — ClaudeBackend becomes event-driven: a GitHub Action turns
a labeled issue into a verified pull request, and a local TDD watcher turns a failing
test green. Purely additive: the `develop`/`mcp` commands, the git safety model, and
the security gate are unchanged.

### Added

- **CI/CD GitHub Action** (`.github/workflows/claude-backend-agent.yml` + `cicd.py` +
  `claudebackend ci`): on an issue labeled **`ai-developer`** or **`ai-feature`**, the
  agent develops it on an isolated `claudebackend/issue-<id>` branch, then **opens a
  PR only if the run verified safely** (`project_ok` and nothing discarded by the
  security gate) — otherwise it **comments on the issue** explaining why. The PR body
  carries the `DEV_SUMMARY`, cost/tokens, verification steps, `CLAUDEBACKEND-REVIEW`
  markers, and any discarded-unsafe files. Tokens come from standard Actions secrets
  (`GITHUB_TOKEN` / `ANTHROPIC_API_KEY`) — never hardcoded.
- **Local TDD watcher** (`claudebackend watch --dir tests` + `watcher.py` + `tdd.py`):
  watches the test dir; when a save leaves a failing test, it feeds that test's pytest
  output to the Coder and implements the fix **in place** (no branch, no commit) for a
  fast red→green loop. Loop-safe: only test-dir saves trigger a run, runs are
  serialised, and a still-red test **halts and waits** for the next edit after
  `--max-retries`. Needs the optional `watch` extra (`pip install claudebackend[watch]`).
- **Git push + GitHub API**: `git.push_branch` (refuses `main`/`master`) and a stdlib
  `core/github.py` REST client (`create_pull_request`, `comment_on_issue`).
- **Orchestrator modes**: `develop_feature` gains `branch_name` (override the branch),
  `apply_in_place` (write to the working tree with no branch/commits, tolerating a
  dirty tree), and `task_context` (a failing-test block fed into `context_builder` /
  the Coder prompt from the first attempt).
- **Headless CI**: `CI=true` (or GitHub Actions) auto-skips the cost-confirmation
  prompt and TTY progress in `develop`.

## [0.5.0] - 2026-06-14

"DevSecOps / Red Team" — the Verifier now actively hunts for security
vulnerabilities (SQLi, IDOR, XSS, command injection, auth/authz, SSRF, path
traversal, unsafe deserialization, secrets) **while** developing, not just after.
A per-step blocking security gate runs after the deterministic checks pass and is
**on by default**. Purely additive: the deterministic checks (py_compile, ruff,
pytest) and the existing advisory `--security-review` pass are unchanged.

### Added

- **Per-step security gate** (on by default; `--no-security-gate` to disable): after
  the syntax gate passes, each new Python file is scanned with **bandit** (SAST) and
  audited by a new **Red Team** agent (`agents/security_auditor.py`) with an
  attacker's mindset. A blocking finding rejects the file, feeds the vulnerability
  back to the Coder as a distinct *SECURITY AUDIT FAILURE* block, and consumes a
  retry. If still unsafe at `--max-retries`, the candidate is **discarded** (nothing
  written/committed) and listed under `unsafe` — never an infinite loop, never
  unsafe code committed. Low-confidence SAST warnings the Red Team cannot confirm
  get a `CLAUDEBACKEND-REVIEW` marker instead of a block.
- **SAST in the Verifier** (`core/verifier.py`): `_run_sast_check` / `scan_code` run
  bandit (static, AST-based — never executes the code). `verify_project` runs it
  **alongside ruff** as an advisory project-wide scan; findings surface in
  `VerifyResult.security_issues` and a `bandit` step status, but never flip `ok`.
- **`bandit` optional extra**: `pip install claudebackend[security]`. When bandit is
  absent the SAST step degrades to a recorded note; the Red Team LLM audit still runs.
- **Report/MCP surfaces**: `DevReport` gains `unsafe` and `security_issues`; the
  `develop_backend_feature` MCP tool returns both; `DEV_SUMMARY.md` gains prominent
  "discarded unsafe files" and "SAST findings" sections; the CLI prints security
  rejections live (`! SECURITY: …`) and a discarded/SAST summary.
- **`SecurityReject` event** for live progress + a `--security-gate/--no-security-gate`
  CLI flag and a `security_gate` MCP parameter.

### Notes

- The Coder's *initial* prompt stays security-free — security feedback only appears
  on a retry — so business logic and the security audit remain separate concerns.
- Anthropic prompt caching, agent isolation, the git safety model, `--dry-run`, and
  the retry loop are all preserved.

## [0.4.0] - 2026-06-14

"Local AI execution" — run the whole `Planner → Coder → Verifier` pipeline fully
offline against local [Ollama](https://ollama.com), with per-agent model routing
and an absolute air-gap. Purely additive: the Anthropic and OpenAI-compatible
backends are unchanged.

### Added

- **Ollama provider** (`core/providers/ollama.py`): native local execution via
  Ollama's OpenAI-compatible endpoint (`http://localhost:11434/v1` or
  `OLLAMA_BASE_URL`), with a generous timeout and connection retries for slow
  cold-model loads (`OLLAMA_TIMEOUT` / `OLLAMA_MAX_RETRIES`). Streaming and the
  portable instructed-JSON output path are inherited; Anthropic-only prompt
  caching is simply absent (gracefully, no error).
- **`--local` air-gap mode**: runs offline against Ollama only — the Anthropic SDK
  is never constructed, no credential discovery or telemetry runs, and a
  non-loopback/non-private endpoint is refused. `CLAUDEBACKEND_LOCAL=1` forces it
  for both the CLI and the MCP server (used by the Docker stack).
- **Per-agent model routing**: `--planner-model` / `--coder-model` /
  `--verifier-model` (or `CLAUDEBACKEND_MODEL_PLANNER|CODER|VERIFIER`, or
  `[tool.claudebackend.models]` in the target `pyproject.toml`). Nothing is
  hardcoded; CLI > env > pyproject > `--model`.
- **Context-window enforcement** (`core/limits.py`): local runs respect a per-model
  context budget (built-in table + `CLAUDEBACKEND_CONTEXT_<MODEL>` override) — the
  builder drops read-only dependency context first and only then refuses a step, so
  an oversized file is flagged instead of OOM-ing the machine.
- **Optional LLM security review** (`--security-review`, off by default): an
  advisory pass that routes the changed files to the verifier model for a security
  audit; surfaced in the report, `--json`, and the MCP result under `security`.
- **Docker stack**: `docker/Dockerfile` + `docker-compose.yml` run Ollama and
  ClaudeBackend on an isolated network with **no published ports**.
- **Docs**: `docs/install/local_ai.md` (setup, models, Docker, air-gap, routing).

## [0.3.0] - 2026-06-14

"ClaudeBackend" — generalize the tool from a hardcoded Python 2→3 migrator into a
universal, objective-driven backend development system. The deterministic
`Planner → Coder → Verifier` pipeline, the ≤`--max-retries` retry loop, the git
safety model, prompt caching, and the OpenAI-compatible provider layer are all
preserved.

### Changed

- **Renamed** the project from `claudemigrate` to `claudebackend` throughout
  (package, CLI entry point, MCP server, plugin, docs).
- **Objective-driven Planner**: the Planner now takes an arbitrary objective (e.g.
  "Add JWT authentication") plus a codebase map and produces an `ExecutionPlan` of
  ordered steps that **create / modify / delete** files. The Coder implements one
  step at a time; the dependency graph is now *context*, not the driver.
- **Pydantic models renamed/added**: `MigrationPlan` → `ExecutionPlan`,
  `PlanUnit` → `PlanStep` (with `action`, `instructions`, `depends_on`),
  `MigrationReport` → `DevReport` (with `created`/`modified`/`deleted` lists);
  `FileResult.migrated_code` → `code`. Report `schema_version` is now `2`.
- **CLI**: `run` → `develop <path> "<objective>"`; output reports
  created/modified/deleted counts and writes `DEV_SUMMARY.md`.
- **MCP**: the `migrate` tool is replaced by **`develop_backend_feature(path,
  objective, ...)`**.
- **Branch naming**: `claudebackend/feature-<timestamp>`; review marker is now
  `CLAUDEBACKEND-REVIEW` (injected by the Coder on ambiguous or security-sensitive
  changes).

### Added

- **Expanded codebase map** (`depgraph`): besides Python imports, it now
  recognises ORM model relationships (Django / SQLAlchemy), Dockerfile
  `COPY`/`ADD` references, and config-file references, each tagged by node kind.
- **Topology graph generator** (`core/graphviz.py`): every run writes
  `DEV_GRAPH.md` and an interactive vis-network `graph.html` of the project
  topology (modules, ORM models, Dockerfiles, config).

### Note

Python 2 → 3 migration is now one **example objective** driven through the generic
pipeline (the bundled `migrate-python-2-to-3` skill and the e2e fixture), not a
hardcoded mode.

## [0.2.0] - 2026-06-13

"Usability & Transparency" — make a run observable and accountable without
changing migration behaviour.

### Added

- **Live `[1/4]..[4/4]` progress** printed during a run by a console reporter
  (depgraph -> plan -> migrate -> verify). On a TTY the migrate phase redraws in
  place; when piped it prints one compact line per phase.
- **Real token + cost accounting**: token usage is accumulated across every LLM
  call and a final `Cost` line is printed (input/output tokens, dollar estimate,
  and cache-hit ratio).
- **New CLI flags** on `run`: `--verbose`/`-v` (DEBUG logging to stderr),
  `--quiet`/`-q` (suppress live progress, keep the summary + cost line),
  `--json` (print the report as JSON to stdout; implies `--quiet`),
  `--report-json PATH` (also write the JSON report to a file), and `--no-cost`
  (omit the final token/cost line).
- **Machine-readable report** via a stable, versioned `MigrationReport.to_dict()`
  schema (`schema_version: 1`), reused by both the CLI (`--json`/`--report-json`)
  and the MCP server. Dry-run reports include the full unified `diff`.
- **Per-step verify detail** in the report (`verify_steps`: compile / ruff /
  pytest), surfaced live in the `[4/4]` line.
- **MCP `migrate` tool** now returns an additive `cost` key alongside the existing
  result fields.
- **Pricing table** for the Anthropic models, with a per-model env override
  `CLAUDEBACKEND_PRICE_<MODEL>="input,output,cache_read,cache_write"` (USD per 1M
  tokens). A `$` figure is computed only for models in the table; other models
  report token counts with `pricing_known=false` and `cost_usd=null`.

### Changed

- Logging now goes through the `claudebackend` logger to **stderr** (stdout is
  reserved for progress and JSON), controlled by `--verbose`/`--quiet`.

All of the above is additive and backward-compatible: return contracts, the
provider protocol, and existing test fixtures are unchanged.

## [0.1.0] - 2026-06-13

### Added

- Initial release: deterministic Python 2 -> 3 migration pipeline
  (Planner -> Coder -> Verifier) that writes the result to a new git branch with
  a `MIGRATION_SUMMARY.md`.
- `claudebackend` CLI (`run`, `mcp`) and an MCP server for IDE/agent integration.
- Six LLM backends (Anthropic plus five OpenAI-compatible providers: OpenRouter,
  OpenAI, NVIDIA, DeepSeek, Gemini).
- Agent Skill and Claude Code plugin packaging.
