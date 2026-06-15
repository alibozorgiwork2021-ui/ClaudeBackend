# Local AI execution (Ollama) — fully offline, air-gapped

ClaudeBackend can run its `Planner → Coder → Verifier` pipeline **entirely on your
own hardware** against [Ollama](https://ollama.com), with **zero external calls**.
This is for air-gapped / enterprise environments and for working without API keys.

What you get:

- `--local` runs offline against Ollama (no Anthropic SDK, no credential
  discovery, no telemetry, no remote endpoint — the air-gap is enforced in code).
- **Per-agent model routing**: point the Planner, Coder, and (optional) security
  reviewer at different local models. Nothing is hardcoded.
- **Strict context-window limits** so a large file can't blow past a local model's
  window and OOM your machine.
- A **Docker stack** that runs Ollama + ClaudeBackend on an isolated network with
  no published ports.

> **Models are your choice.** The examples below use mainstream coding models
> (`qwen2.5-coder`, `deepseek-coder-v2`, `llama3.1`). **Any** model you can
> `ollama pull` works — just use its name wherever a model id appears. Nothing in
> the code is tied to a specific model.

---

## 1. Install Ollama and pull models

Native install (macOS / Linux / Windows): see <https://ollama.com/download>. Then
pull whatever models you want to use:

```bash
ollama pull qwen2.5-coder        # fast — good for planning/coding
ollama pull deepseek-coder-v2    # stronger — good for coding/review
ollama pull llama3.1             # general-purpose, large context
```

Ollama serves an OpenAI-compatible API at `http://localhost:11434/v1`, which is
exactly what ClaudeBackend talks to.

## 2. Run fully local

```bash
# One model for everything:
claudebackend develop ./service "Add a /health endpoint" --dry-run \
  --local --model qwen2.5-coder

# Per-agent routing (fast planner, stronger coder):
claudebackend develop ./service "Add JWT auth" --dry-run --local \
  --planner-model qwen2.5-coder \
  --coder-model deepseek-coder-v2
```

`--local` implies `--provider ollama` and turns on the air-gap guard. Start with
`--dry-run` (writes nothing; prints the diff), then drop it to write to a branch.

## 3. Configure model routing

A model is resolved per agent from, in **decreasing** precedence:

1. **CLI flags** — `--planner-model`, `--coder-model`, `--verifier-model`
   (falling back to `--model`).
2. **Environment** — `CLAUDEBACKEND_MODEL_PLANNER`, `CLAUDEBACKEND_MODEL_CODER`,
   `CLAUDEBACKEND_MODEL_VERIFIER`.
3. **`pyproject.toml`** of the target project (Python 3.11+; uses stdlib `tomllib`):

   ```toml
   [tool.claudebackend.models]
   planner  = "qwen2.5-coder"
   coder    = "deepseek-coder-v2"
   verifier = "deepseek-coder-v2"
   ```

4. The run-wide `--model` default.

Other local knobs (all optional):

| Env var | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint (also `--ollama-base-url`). |
| `OLLAMA_TIMEOUT` | `600` | Request timeout in seconds (cold model loads are slow). |
| `OLLAMA_MAX_RETRIES` | `3` | Connection retries for the local endpoint. |
| `CLAUDEBACKEND_CONTEXT_<MODEL>` | built-in table | Override a model's context window (tokens). `<MODEL>` is the name upper-cased with `-`/`.` → `_`. |
| `CLAUDEBACKEND_DEFAULT_CONTEXT` | `8192` | Window assumed for an unknown local model. |
| `CLAUDEBACKEND_OUTPUT_RESERVE` | `2048` | Tokens reserved for the model's response when checking the input budget. |

## 4. Optional LLM security review

`--security-review` adds an advisory pass that asks the **verifier** model to audit
the changed files for security issues (injection, authn/z, crypto, secret
handling, unsafe deserialization, SSRF, path traversal, subprocess use). It never
edits files and is **off by default**; it complements the deterministic Verifier
(`py_compile` + `ruff` + `pytest`).

```bash
claudebackend develop ./service "Add file upload" --dry-run --local \
  --coder-model deepseek-coder-v2 \
  --verifier-model deepseek-coder-v2 \
  --security-review
```

Findings are printed after the run and appear under a `security` key in `--json`
output and the MCP result.

## 5. Docker (isolated, no published ports)

`docker-compose.yml` runs Ollama + ClaudeBackend on an internal network. Ollama's
port is **not** published to the host, and `CLAUDEBACKEND_LOCAL=1` forces offline
mode for both the CLI and the MCP server.

```bash
# 1) Pull models (first time needs network access to Ollama's registry):
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5-coder
docker compose exec ollama ollama pull deepseek-coder-v2

# 2) Run a development task — air-gapped, no external calls:
mkdir -p workspace && cp -r /path/to/your/project/* workspace/
docker compose run --rm claudebackend develop /work "Add a /health endpoint" --dry-run
```

Edit the `CLAUDEBACKEND_MODEL_*` values (and the `ollama pull` names) in
`docker-compose.yml` to match the models you pulled. For a true air-gap, do the
model pull once, then disconnect the host from the network — inference needs no
outside access.

## 6. Air-gap guarantees

When `--local` (or `CLAUDEBACKEND_LOCAL=1`) is active:

- the Anthropic SDK is **never imported or constructed**, and no credential
  discovery runs;
- only the `ollama` provider is allowed — a non-local provider or a non-loopback /
  non-private base URL is rejected with a clear error;
- there is **no telemetry, version ping, or pricing fetch** — pricing is a static
  local table and local models simply report `pricing_known=false`;
- the MCP server is stdio-only and opens **no network ports**.

## 7. Troubleshooting

- **First call hangs / times out** — a cold model loads into memory on first use;
  raise `OLLAMA_TIMEOUT`. Make sure the model is pulled (`ollama list`).
- **A file is "flagged" with a context-window error** — the file plus its context
  exceeds the model's window. Use a larger-context model, or raise the limit with
  `CLAUDEBACKEND_CONTEXT_<MODEL>`. ClaudeBackend drops read-only dependency context
  first and only then refuses, so it never silently truncates or OOMs.
- **`--model is required for provider 'ollama'`** — give a default `--model` or at
  least one per-agent model (e.g. `--coder-model`).
- **`--local requires a loopback/private Ollama endpoint`** — your
  `OLLAMA_BASE_URL` points at a public host; use localhost, a private IP, or a
  Docker service name.
