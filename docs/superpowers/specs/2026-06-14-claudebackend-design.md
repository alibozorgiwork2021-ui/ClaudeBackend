# ClaudeBackend — Universal Multi-Agent Backend Dev System (Design)

This supersedes the original `2026-06-13-claudemigrate-py2to3-design.md`, which
described the tool when it was a hardcoded Python 2 → 3 migrator. That document is
kept alongside this one for history; the pipeline mechanics it describes (the
isolated agents, the retry loop, the git safety model, prompt caching, the
provider layer) are preserved here unchanged.

## Goal

Generalize the deterministic `Planner → Coder → Verifier` pipeline from a single
hardcoded task (py2 → 3) into a continuous backend development assistant that
accepts an **arbitrary objective** (e.g. "Add JWT authentication", "Refactor the
SQLAlchemy models") and executes it through the same isolated, retry-guarded,
git-safe workflow.

## The key shift: graph-driven → objective-driven

Previously the **dependency graph drove everything**: it computed SCC units in
dependency order and the Coder rewrote every file in that order; the Planner only
annotated risk. Now the **Planner is the driver**:

- The dependency graph is *context* — a map of the codebase (Python imports + ORM
  models + Dockerfiles + config), summarized for the Planner.
- The Planner reads the objective + the map and emits an `ExecutionPlan`: an
  ordered list of `PlanStep`s, each a file to **create / modify / delete** with
  precise instructions, a risk level, and `depends_on` ordering.
- The Coder implements one step at a time against the objective, the step
  instructions, the target file, and its related files.
- The Verifier is unchanged: `py_compile` syntax gate per Python file, then a
  project-wide `compile + ruff(E9,F) + pytest` gate.

## Data models (`models.py`)

- `Action = Literal["create","modify","delete"]`
- `PlanStep`: `path`, `action`, `instructions`, `rationale`, `risk`, `depends_on`
- `ExecutionPlan`: `objective`, `summary`, `steps: list[PlanStep]`
- `FileResult`: `path`, `code`, `notes`
- `VerifyResult`: unchanged (`ok`, `errors`, `notes`, `steps`)
- `DevReport` (orchestrator dataclass): `objective`, `branch`, `created`,
  `modified`, `deleted`, `flagged`, `review`, `dynamic`, `project_ok`,
  `project_errors`, `project_notes`, `summary`, `dry_run`, `diff`, `cost`,
  `verify_steps`, `graph_path`; `to_dict()` is `schema_version: 2`.

## Pipeline (`orchestrator.develop_feature`)

1. Cost preflight (offline token estimate; abortable).
2. `build_graph(root)` → codebase map; emit `DepGraphDone`.
3. `plan(client, objective, graph)` → `ExecutionPlan`; order steps by `depends_on`;
   emit `PlanDone`.
4. Per step (emit `StepStart`): `create`/`modify` → build context → Coder
   `implement` → syntax gate (Python only) → retry up to `max_retries` (emit
   `FileRetry`); `delete` → remove the file. Emit `FileDone`.
5. `verify_project` → the real gate; emit `ProjectVerifyResult`.
6. Render `DEV_GRAPH.md` + `graph.html`; scan `CLAUDEBACKEND-REVIEW` markers; build
   `DEV_SUMMARY.md`.
7. Live run: commit per step on `claudebackend/feature-<timestamp>`, commit the
   graph, write the summary. Dry run: do it all on a throwaway copy and return a
   unified diff; write nothing to the user's repo.

The three agents remain in separate modules and separate LLM calls — they are
never merged.

## Expanded codebase map (`depgraph.py`)

`Graph` gains `kinds: dict[str,str]` (`python|orm|dockerfile|config`). Lightweight,
regex-based heuristics add, beyond Python imports:

- **ORM** (Django `class X(models.Model)` + `ForeignKey`/`OneToOne`/`ManyToMany`;
  SQLAlchemy `class X(Base)` + `relationship("Y")`) → mark files `orm`, add edges
  between model files. Pydantic `BaseModel` is deliberately *not* treated as ORM.
- **Dockerfiles** (`Dockerfile`, `*.Dockerfile`, `Dockerfile.*`) → edges from
  `COPY`/`ADD` source paths to referenced repo files.
- **Config** (`*.yml|yaml|toml|ini|cfg|env`, `.env`) → edges to repo paths /
  modules referenced in the file (bounded fan-out).

`graph_summary(graph)` renders this map for the Planner. `ordered_units` is kept
for graph layout but no longer drives the pipeline.

## Topology graph (`core/graphviz.py`)

`render_graph(graph, out_dir)` writes `DEV_GRAPH.md` + a self-contained
vis-network `graph.html`. Nodes are grouped/coloured by kind (Python module / ORM
model / Dockerfile / Config); edges are coloured by source kind (import /
model-rel / docker-copy / config-ref). The legend reflects standard project
topology.

## Interfaces

- **CLI**: `claudebackend develop <path> "<objective>" [flags]` and
  `claudebackend mcp`. Flags preserved: `--dry-run`, `--init`, `--max-retries`,
  `--target-version`, `--use-subscription`, `--provider/--model/--api-key`,
  `--yes`, `--verbose/--quiet`, `--json/--report-json`, `--no-cost`.
- **MCP**: tool `develop_backend_feature(path, objective, dry_run=True, provider,
  model, init, max_retries)` (replaces `migrate`). Dry run is the default.

## Preserved invariants (DON'Ts)

- Anthropic prompt caching (`cache_control`) on the stable system + related-file
  blocks in `context_builder.py`.
- Three strictly-isolated agents; no single merged LLM call.
- Git safety: abort on a dirty tree; all writes on a new `claudebackend/feature-*`
  branch.
- `--dry-run` emits a unified diff and writes nothing.
- The `CLAUDEBACKEND-REVIEW` human-in-the-loop marker, injected by the Coder on
  ambiguous architectural or security-sensitive changes.
- The OpenAI-compatible provider layer and the ≤`--max-retries=3` Coder↔Verifier
  loop.

## Python 2 → 3

Now one example objective driven through the generic pipeline — the bundled
`migrate-python-2-to-3` skill and the `tests/fixtures/py2_sample` e2e fixture — not
a hardcoded mode.
