# Phase 5 · Stage 2 — `PHPDriver` + `--lang` (execution-ready plan)

> Status: **planned, not yet implemented.** Stage 1 (the `LanguageDriver` abstraction +
> `PythonDriver`) is landed and verified (266 offline tests pass, ruff clean). This document
> is the next shippable increment. Stages 3 (local SSE server) and 4 (React dashboard) remain
> as specified in `~/.claude/plans/read-plan-txt-and-go-mighty-stream.md` and are out of scope here.

## Context

`claudebackend` is a deterministic Planner → Coder → Verifier pipeline. Stage 1 pushed every
genuinely language-specific operation behind a `LanguageDriver` ABC
(`claudebackend/core/drivers/base.py`) and shipped `PythonDriver`. The orchestration,
git-safety model, pricing, and agents are already language-agnostic, and
`build_graph(driver=)`, `verify_project(driver=)` (which loops `driver.verify_steps`),
`build_context(driver=)`, and `develop_feature(lang=)` → `get_driver(lang)` all already thread
the driver through (verified at `orchestrator.py:485,489,397,432,425,258`).

**What Stage 1 deliberately left Python-specific:** the *per-step security gate* inside
`_apply_step` — the single-file syntax check, the SAST scan, and the review-marker injection —
plus the CLI/MCP `--lang` surface. Stage 2 generalizes exactly those, adds the `PHPDriver`, and
wires `--lang auto|python|php` with auto-detection. Everything is additive and default-Python;
the existing suite must stay byte-identical green for Python at every step.

**Outcome:** `claudebackend develop <php-repo> "<objective>" --lang php` (or auto-detected)
runs the same pipeline over PHP — regex dependency graph, `php -l`/phpstan|psalm/phpunit
verification (all degrading gracefully when the toolchain is absent), and a deterministic PHP
SAST that feeds the existing security gate so a raw `$_GET` SQL concat is blocked exactly like a
Python `pickle.loads`.

---

## Two design decisions resolved up front

The recon agents converged on the architecture and surfaced one real fork. Decisions:

### Decision A — SAST routing (the load-bearing one)

The per-step gate calls `scan_code(result.code)` at `orchestrator.py:283`, where `scan_code` is
`verifier.scan_code` imported into the orchestrator namespace (`orchestrator.py:31-36`).
`verifier.scan_code` (`verifier.py:174-184`) hardcodes `suffix=".py"` + bandit. `test_orchestrator.py:446-449`
monkeypatches **`orch.scan_code`** with a **1-arg** lambda. So we cannot just "have the driver do
SAST" — the patch target name in the orchestrator namespace must survive, and the Python path
must stay byte-identical.

**Chosen approach (least churn, preserves the test seam):**

- `verifier.scan_code(code, driver=None)` becomes the single seam and stays the orchestrator's
  imported patch target. When `driver is None` **or** `driver.name == "python"`, run the *current*
  body unchanged (temp `.py` + `_run_sast_check` → bandit) — byte-identical, so `test_verifier`
  and the Python orchestrator tests stay green. Otherwise `return driver.scan_candidate(code)`.
- Add `scan_candidate(self, code: str) -> list[SastFinding]` to the ABC with a default of `[]`
  (minimal drivers stay tiny; no per-candidate SAST = nothing blocks, acceptable). `PythonDriver`
  needs **no** override (handled inline by `verifier.scan_code`). `PHPDriver.scan_candidate` runs
  the deterministic `_PHP_SAST_RULES` regex over the code string — **tool-free**, so the gate fires
  in CI with no PHP toolchain installed and the `$_GET` SQL-concat e2e test is deterministic.
- Orchestrator call site → `sast = scan_code(result.code, driver)` (2-arg).
- **Mandatory lockstep test edit** (`test_orchestrator.py:446-449`): 1-arg → 2-arg lambda,
  same patch target, same return shape:
  ```python
  monkeypatch.setattr(
      orch, "scan_code",
      lambda code, driver=None: [SastFinding("B101", "LOW", "LOW", 1, "assert used")],
  )
  ```

> Note the distinction the prior plan conflated: **phpstan/psalm is the project-wide static gate**
> inside `verify_steps` (parallels ruff E9,F — its findings go to `errors` and CAN flip `ok`),
> whereas **`php-sast` (regex) is the advisory/per-candidate SAST** (parallels bandit — never flips
> `ok`; its findings drive the per-step block / review marker). They are two different things.

### Decision B — the `lang` field lives in `orchestrator.py`, not `models.py`

`DevReport` and `to_dict()` are in `orchestrator.py:55-121`, not `models.py` (the recon corrected
the original plan here). Add `lang: str = ""` to `DevReport` (`orchestrator.py:55-77`) and
`"lang": self.lang` to `to_dict()` (after `target_version`, ~`:103`). **Keep `schema_version: 2`**
— additive keys do not bump the schema. Set `report.lang = lang` in `develop_feature`.
`models.VerifyResult` gets **no** change (its `steps` dict already varies per language; a `lang`
field there is dead data).

---

## New file — `claudebackend/core/drivers/php.py`

`PHPDriver(LanguageDriver)`. No PHP runtime needed for graph-building (pure regex). All
verification tools degrade gracefully when absent (run `--version`, catch `OSError`; missing →
recorded note, never fail the build — mirror `bandit_available` at `verifier.py:119-125`).

```
name = "php"
source_exts = (".php",)
test_framework = "phpunit"
```

### Dependency graph methods (consumed by `build_graph`, which fully delegates)

- **`extract_imports(src: bytes) -> set[str]`** — decode `.decode("utf-8","replace")`; return the union of:
  - FQCN from `use App\Models\User;` / `use App\Foo as Bar;` / grouped `use App\{Foo, Bar};`
    (emit the left-side namespace path, not the alias).
  - `extends`/`implements` targets from `class X extends Y implements Z, W`.
  - Literal `include`/`include_once`/`require`/`require_once` **string-literal** paths only (a path
    is recognized by `resolve` via "contains `/` or ends `.php`"). Do **not** emit dynamic
    `require $x` here (that is `has_dynamic_import`'s job).
  - The `namespace App\Foo;` declaration is parsed for `module_name`/`build_modmap`, **not** returned.
- **`module_name(relpath) -> str`** — `src/Models/User.php` → `src\Models\User` (strip `.php`, `/`→`\`).
  The PSR-4 prefix substitution happens in `build_modmap`, keeping this method total/pure.
- **`build_modmap(source_rels, root) -> dict[str,str]`** (override) — parse `composer.json`
  `autoload.psr-4` + `autoload-dev.psr-4` into `{FQCN: relpath}` (prefix `"App\\"`, dir `"src/"`,
  file `src/Models/User.php` → `App\Models\User`). Files under no PSR-4 dir fall back to
  `{module_name(rel): rel}`. Tolerate missing file/keys; normalize string-or-list dir values,
  trailing slashes, leading-backslash on prefixes.
- **`resolve(mod, importer, modmap, relset) -> str|None`** — **uses `relset`** (Python's driver
  drops it). If `mod` looks like a path → relative include: `(Path(importer).parent / mod)`
  normalized; return it iff in `relset`, else `None`. Else FQCN → **longest-prefix match** against
  `modmap` (split on `\`, try `parts[:k]` for k from len→1). External (vendor/stdlib) → `None`.
- **`has_dynamic_import(src) -> bool`** (override) — `eval`, `call_user_func[_array]`, `$$`, or a
  variable include/require `(?:include|require)(?:_once)?\s*\(?\s*\$`. Marks the file into `graph.dynamic`.
- **`model_classes` / `model_refs`** (optional) — light Eloquent (`extends Model`) + Doctrine
  (`#[ORM\Entity]`) detection so PHP ORM files get kind `"orm"`; safe to no-op → kind stays `"php"`
  (`build_graph` tolerates empty sets). `model_refs` may return `set()` for v1.
- **`package_manifest(root) -> dict`** (override) — `{"deps":[...], "autoload":{...}}` from
  `composer.json` (`require` + `require-dev`; merged psr-4). Tolerate missing file.

### Verification — `verify_steps(root, target_version) -> list[VerifyStep]`

Mirror the structure of `python.py:68-140`. Keys in order: `["php -l", "phpstan"|"psalm", "phpunit", "php-sast"]`.
`verify_project` (`verifier.py:214-219`) collects these verbatim into `report.verify_steps`.

1. **`php -l`** — whole-tree syntax: loop `root.rglob("*.php")` → `self.syntax_check(p)`; collect
   parse errors. `php` binary absent → status `"skipped"` + note `"php not installed - syntax check skipped"`.
2. **`phpstan` else `psalm` else skipped** — the cross-file static gate (parallels ruff, CAN flip `ok`).
   `vendor/bin/phpstan` or PATH → `phpstan analyse --error-format=json --no-progress <paths>`; parse
   JSON; non-empty → `"FAILED"` + `errors`. Else psalm (`--output-format=json`, key `"psalm"`). Else
   `"skipped"` + note. **Soft** — never `ensure_ruff`-style raise.
3. **`phpunit`** — prefer `vendor/bin/phpunit` then `phpunit`, `--no-coverage`. No tests / nothing-to-run
   → `"skipped"` + note `"phpunit: no tests collected - runtime behaviour not verified"` (NO_TESTS
   semantics, `base.py:22`). rc 0 → parsed summary (e.g. `"OK (12 tests)"`). rc != 0 → `"FAILED"` +
   `errors.append("phpunit:\n" + out.strip())` (this is the failing-traceback channel). phpunit absent → `"skipped"` + note.
4. **`php-sast`** — advisory; run `_PHP_SAST_RULES` over each `.php` file → `list[SastFinding]`;
   `step.security_issues = format_sast(findings)` (reuse `verifier.format_sast`); status
   `"ok"`/`f"{n} issue(s)"`. **Never** populates `errors` (parallels bandit, `python.py:126-138`).

### Single-file methods

- **`syntax_check(path) -> SyntaxCheck`** — `php -l <path>`; parse `PHP Parse error:` →
  `SyntaxCheck(ok=False, error=...)`; `php` absent → **`SyntaxCheck(ok=True)`** (never spuriously fail).
- **`scan_candidate(code) -> list[SastFinding]`** (Decision A) — run `_PHP_SAST_RULES` over the
  code string, tool-free.

### `_PHP_SAST_RULES` — deterministic table → `SastFinding`

Module-level list of `(test_id, regex, severity, confidence, text)`. Scan decoded source
line-by-line so `SastFinding.line` is the real line number. These are the **same** `SastFinding`
(`base.py:25`) the orchestrator's `_classify_security`/`_inject_review_markers` consume — reuse is
automatic. Set RCE-class rules to **HIGH/MEDIUM** so they BLOCK via `_classify_security:194`
(`severity=="HIGH" and confidence in ("MEDIUM","HIGH")`); noisy heuristics at LOW confidence fall to
review-markers (won't infinite-loop).

| test_id | what | severity/conf |
|---|---|---|
| `PHP-SQLI` | `->query/exec/prepare("..." . $ / $_GET…)` + string-interp variant | HIGH / MEDIUM |
| `PHP-OPEN-REDIRECT` | `header("Location:" . $_GET/$_REQUEST…)` | MEDIUM / MEDIUM |
| `PHP-LFI-RFI` | `include/require … $_GET/$_POST/$_REQUEST/$_COOKIE` | HIGH / MEDIUM |
| `PHP-CMD-INJECT` | `exec/system/shell_exec/passthru/popen/proc_open(… $ …)` + backticks | HIGH / MEDIUM |
| `PHP-UNSERIALIZE` | `unserialize($ / $_…)` | HIGH / MEDIUM |
| `PHP-XSS` | `echo/print … $_GET/$_POST/$_REQUEST/$_COOKIE` **and** no `htmlspecialchars`/`htmlentities`/`intval`/`(int)` on the line (post-filter in code, not regex) | MEDIUM / LOW |
| `PHP-EVAL` | `eval(` | HIGH / MEDIUM |

Factor the superglobal alternation `\$_(?:GET|POST|REQUEST|COOKIE|SERVER|FILES)` into a shared fragment.

### Prompt-hint overrides

- `comment_prefix()` → `"//"`; `version_label()` → `"Target PHP version"`; `default_version()` →
  `"php8.1"` (a constant — no `sys.version_info` analogue).
- `vuln_patterns_hint()` → PHP sinks string (unserialize gadget chains, LFI/RFI on request data,
  command exec sinks, `eval`/`call_user_func` with request data).
- `review_marker_line`/`sast_tmp_suffix` inherit defaults (correct once the orchestrator call sites
  below are wired).

---

## Integration edit list (verified file:line)

### 1. `core/drivers/base.py` — ABC additions
- Add non-abstract `vuln_patterns_hint(self) -> str` (default `""`), after the `version_label` block (~`:166`).
- Add non-abstract `scan_candidate(self, code: str) -> list[SastFinding]` (default `[]`).
- No new abstract methods — PHP SAST surfaces via `verify_steps` + `scan_candidate`.

### 2. `core/drivers/python.py`
- Override `vuln_patterns_hint()` → `"pickle/yaml.load/eval/exec"` (preserves the exact wording
  inlined today at `prompts.py:166-168`, so prompt output is byte-identical after parameterization).
- No `scan_candidate` override (the Python path stays inline in `verifier.scan_code`).

### 3. `core/drivers/__init__.py`
- Import `PHPDriver`; add `"php": PHPDriver` to `_DRIVERS` (`:31-33`); add `"PHPDriver"`,
  `"detect_lang"` to `__all__` (`:20-29`).
- Add `detect_lang(root) -> str`: `composer.json` → `"php"`; `pyproject.toml`/`requirements.txt`
  → `"python"`; else source-extension majority over registered drivers; **tie → `"python"`**.

### 4. `core/verifier.py`
- `scan_code(code, driver=None)`: keep the current bandit body when `driver is None or
  driver.name == "python"` (byte-identical); else `return driver.scan_candidate(code)` (Decision A).
- `SastFinding` re-export unchanged (`:35`). No other change.

### 5. `orchestrator.py` — generalize the per-step gate (in lockstep with tests)
- **`_verify_code(code, driver)`** (`:139-149`, call `:274`): temp file with
  `driver.sast_tmp_suffix()`, `sc = driver.syntax_check(tmp)`, return
  `VerifyResult(ok=sc.ok, errors=[sc.error] if sc.error else [])`. Drop the now-unused `verify_file`
  import (`:35`).
- **`scan_code` call** (`:283`) → `scan_code(result.code, driver)`. Edit the
  `test_orchestrator.py:446-449` monkeypatch to 2-arg in the same commit (Decision A).
- **`_inject_review_markers(code, review, driver)`** (`:203-213`, call `:298`): use
  `driver.review_marker_line(REVIEW_MARKER, f"{s.test_id} (low confidence) line {s.line}: {s.text}")`
  and a header built from `driver.comment_prefix()`. Drop the literal `bandit`/`#`.
- **`_classify_security(sast, audit, driver)`** (`:177-200`, call `:287`): drop the hardcoded
  `"bandit "` prefix at `:196` (use `str(s)` — `SastFinding.__str__` already renders cleanly).
- **`audit` call** (`:284-286`): pass `vuln_patterns_hint=driver.vuln_patterns_hint()`.
- **`DevReport.lang` + `to_dict`** (Decision B); set `report.lang = lang` in `develop_feature`.
- `develop_feature(lang=)`/`get_driver`/threading already in place (`:485,489,397,432,425,258`) —
  no change beyond the above.

### 6. `prompts.py` / `core/context_builder.py` / `agents/security_auditor.py`
- `red_team_prompt(step, code, sast_findings=None, vuln_patterns_hint=None)` (`:151-190`):
  interpolate `vuln_patterns_hint` in place of the hardcoded `pickle/yaml.load/eval/exec` (`:166-168`);
  change `"A static analyzer (bandit) flagged…"` (`:177`) → `"A static analyzer flagged…"`.
- `security_auditor.audit(..., vuln_patterns_hint=None)` (`:21-39`): forward it to `red_team_prompt` (`:37`).
- `version_label` is already wired through `context_builder.py:75-77` → `step_block_text`; PHPDriver's
  override flows automatically (confirm only).
- **Failing-PHPUnit traceback → Coder** needs no new plumbing: it reaches the Coder via the existing
  `task_context` (first attempt) / `prior_errors` (retry) channels
  (`develop_feature(task_context=)` → `_run_pipeline` → `_apply_step` → `build_context` →
  `step_block_text` `:118-124`/`:131-136`). PHPDriver's `phpunit` VerifyStep just needs to put the
  output in `errors` (mirror `python.py:121`).
- `CODER_SYSTEM` marker example (`prompts.py:69`) is cosmetic (`_scan_review_markers` greps the
  marker text, not the comment char) — leave static, low priority.

### 7. `cli.py`
- Add `--lang auto|python|php` Typer option near `target_version` (`:255`). After `path` is known
  (~`:355`): `if lang == "auto": lang = detect_lang(path) else: get_driver(lang)` (validate early);
  thread `lang=lang` into `develop_feature` (`:375-401`); map `ValueError` to a friendly exit (`:402`).
- Generalize `_ConsoleReporter._verify` (`:173-185`) to iterate `event.steps.items()` instead of
  hardcoding `compile | ruff | pytest`, so PHP shows `php -l | phpstan | phpunit`. `test_cli.py`
  asserts no verify-line text (only help strings `:80-91`) — safe.

### 8. `mcp_server.py` + `tests/test_mcp.py` (same commit)
- Add `lang: str | None = None` to the tool signature (`:107-121`), `_run` (`:27-43`), and tool body
  forward (`:155-169`). In `_run`, resolve `lang = detect_lang(path) if not lang or lang=="auto" else lang`
  before the `develop_feature` call (`:71-84`); add `"lang": report.lang` to the result dict (`:85-103`).
- Add `"lang"` to `_EXPECTED_KEYS` (`test_mcp.py:5-9`) in the same edit.

### 9. `core/graphviz.py` (cosmetic) + `models.py`
- Add a `"php"` entry (label "PHP module", color `#777bb3`) to the kind maps (`:17-35`) so PHP nodes
  render distinctly. Non-blocking.
- `models.py`: **no change** (Decision B).

---

## New tests + fixtures

- **`tests/test_drivers.py`** (NEW — does not exist today): `get_driver("php")` → `PHPDriver`;
  unknown raises `ValueError`; `detect_lang` matrix (composer→php, pyproject/requirements→python,
  3×`.php`+1×`.py`→php, tie→python, empty→python); `vuln_patterns_hint` defaults/overrides;
  `comment_prefix` "#" vs "//"; `review_marker_line` formatting.
- **`tests/test_php_driver.py`** (NEW): `extract_imports` (use/require/include), `has_dynamic_import`,
  PSR-4 `build_modmap`/`resolve`, `syntax_check` (soft-skip when `php` absent — mirror
  `test_verifier.py:175-177`), `verify_steps` ordered keys + a phpstan step populating
  `security_issues` (monkeypatch the driver's SAST runner like `test_verifier.py:182-185`),
  `default_version`/`version_label`.
- **`tests/test_orchestrator_php.py`** (NEW): reuse the `FakeClient` pattern from
  `test_orchestrator.py:15-51`. (a) safe `.php` edit → `report.project_ok`, file in `report.modified`,
  `report.lang == "php"`; (b) **required**: Coder emits `$q = "SELECT * FROM u WHERE id=" . $_GET['id'];`
  with the gate on + a `SecurityReview(ok=False, high)` from FakeClient (mirror `_block()`
  `:381-385`) → after retries the file lands in **`report.unsafe`** and is NOT written (shape of
  `:409-425`, over `.php`); (c) 2-arg `orch.scan_code` monkeypatch injecting a PHP finding → assert
  the review marker uses `//`.
- **`tests/fixtures/php_sample/`** (NEW): `composer.json` (PSR-4 `{"Acme\\":"src/"}`), `src/Foo.php`
  (`namespace Acme; class Foo {}`), `src/Bar.php` (`use Acme\Foo;`), `src/Unsafe.php` (the `$_GET`
  concat), optional `tests/FooTest.php`. Ensure it's excluded from lint/collection.

---

## Migration order (suite green at every step)

1. `base.py` + `python.py`: add `vuln_patterns_hint` (+ `scan_candidate` default). Pure-additive → green. Add `test_drivers.py` assertions for the new methods.
2. `php.py` + register `"php"` + `detect_lang`. No call site uses it yet → green. Add `test_php_driver.py`, `test_drivers.py` detect cases, `fixtures/php_sample/`.
3. `prompts.py` + `security_auditor.py`: optional `vuln_patterns_hint` param (defaults preserve text) → green.
4. `orchestrator.py` per-step gate: thread `driver` into `_verify_code`/`scan_code` call/`_inject_review_markers`/`_classify_security`/`audit`; **simultaneously** edit `verifier.scan_code(code, driver=None)` and the `test_orchestrator.py:446-449` monkeypatch → run `test_orchestrator.py`, must stay green for Python.
5. `DevReport.lang` + `to_dict` + set `report.lang`. Additive → green.
6. `mcp_server.py` + `test_mcp.py` (`lang` param/result + `_EXPECTED_KEYS`) in one commit → green.
7. `cli.py`: `--lang` + generalized `_verify` → green.
8. `test_orchestrator_php.py`: end-to-end PHP incl. the `$_GET` → `report.unsafe` case → green.
9. Full offline suite + ruff as the final gate.

---

## Verification (end-to-end)

- `pip install -e .[dev,security]` then `pytest -m "not e2e"` — full offline suite stays green
  (Python `verify_steps` byte-identical; new driver/PHP/orchestrator-PHP tests pass).
- `claudebackend develop <py-repo> "<obj>" --dry-run` — unchanged Python output.
- `claudebackend develop <php-repo> "<obj>" --dry-run` (auto-detect via `composer.json`) and with
  explicit `--lang php`: confirm `php -l | phpstan | phpunit | php-sast` steps render, and that they
  degrade to `skipped` + notes when the PHP toolchain is absent (gate still functions; the regex
  `php-sast` + `scan_candidate` fire without any PHP installed).
- MCP smoke: the `develop_backend_feature` tool accepts `lang` and returns it; Python behaviour unchanged.

## Critical files

Refactor: `orchestrator.py`, `core/verifier.py`, `core/drivers/{base,python,__init__}.py`,
`prompts.py`, `core/context_builder.py`, `agents/security_auditor.py`, `cli.py`, `mcp_server.py`,
`core/graphviz.py` (cosmetic). New: `core/drivers/php.py`, `tests/{test_drivers,test_php_driver,test_orchestrator_php}.py`,
`tests/fixtures/php_sample/`. Lockstep test edit: `tests/test_orchestrator.py:446-449`; `tests/test_mcp.py:5-9`.

## Hard constraints carried from `plan.txt`

No Python-specific commands hardcoded in the orchestrator/prompts (the driver supplies them);
PHP tools optional and graceful when absent; existing Python verification, git branching, and
pricing tables stay unbroken; `--local`/Ollama composes for free (the driver only changes verify
commands + prompt hints, not the provider).
