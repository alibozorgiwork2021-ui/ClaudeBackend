# LLM backends

ClaudeBackend runs on Claude by default. Other backends are OpenAI-compatible and
selected with `--provider <name> --model <id>`; the API key is read from the
provider's env var (or `--api-key`).

> **Claude is recommended.** Only Claude Opus 4.8 gives the 1M-token context +
> prompt caching that powers the dependency-aware ("orphan file") development
> pipeline. Non-Claude backends have smaller effective context and no caching, so
> they are weaker on large repos and cost more per pass. Use them when you must.

| `--provider` | API key env var | base URL | example `--model` (verify the current id at the provider) |
|---|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` or `--use-subscription` | default | `claude-opus-4-8` (default), `claude-sonnet-4-6` |
| `ollama` (fully local) | none (offline) | `http://localhost:11434/v1` (or `OLLAMA_BASE_URL`) | `qwen2.5-coder`, `deepseek-coder-v2`, `llama3.1` — any pulled model |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | `anthropic/claude-opus-4-8`, `deepseek/deepseek-chat` |
| `openai` | `OPENAI_API_KEY` | default | a current GPT/o-series id from platform.openai.com/docs/models |
| `nvidia` | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` | e.g. `deepseek-ai/deepseek-r1`, `meta/llama-3.3-70b-instruct` |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | `deepseek-chat`, `deepseek-reasoner` |
| `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-pro`, `gemini-2.5-flash` |

Model ids change frequently — the table lists **examples**. Confirm the current id
in the provider's own model list before relying on it. `--model` is required for
every non-anthropic provider.

## Examples

```bash
# Anthropic API key (default)
export ANTHROPIC_API_KEY=...
claudebackend develop ./service "Add JWT authentication" --dry-run

# Anthropic via your Claude subscription login (no API key)
claude   # log in once (or: ant auth login)
claudebackend develop ./service "Add JWT authentication" --dry-run --use-subscription

# DeepSeek
export DEEPSEEK_API_KEY=...
claudebackend develop ./service "Add caching" --dry-run --provider deepseek --model deepseek-chat

# OpenRouter (route to any model it hosts)
export OPENROUTER_API_KEY=...
claudebackend develop ./service "Add caching" --dry-run --provider openrouter --model anthropic/claude-opus-4-8

# Gemini
export GEMINI_API_KEY=...
claudebackend develop ./service "Add caching" --dry-run --provider gemini --model gemini-2.5-pro

# Ollama — fully local / offline (see docs/install/local_ai.md)
ollama pull qwen2.5-coder
claudebackend develop ./service "Add caching" --dry-run --local --model qwen2.5-coder
```

## Notes

- Non-anthropic backends use a portable JSON prompt for the Planner (their native
  structured-output support varies); the deterministic file order/grouping is
  unaffected.
- `thinking`, `effort`, and prompt caching apply to the anthropic backend only.
- **Fully local / air-gapped:** `--local` runs entirely offline against Ollama with
  zero external calls, per-agent model routing, and strict context-window limits.
  See **[docs/install/local_ai.md](install/local_ai.md)** for setup, Docker, and
  per-agent model configuration.
- **Cost reporting:** every backend reports token usage after a run, but a dollar
  `$` figure is computed **only for models in the built-in pricing table** (the
  Anthropic models). For any other model the report shows token counts with
  `pricing_known=false` and `cost_usd=null`, so automation can tell "unknown"
  apart from "free".
- **Price override:** supply (or override) a model's rate with the env var
  `CLAUDEBACKEND_PRICE_<MODEL>="input,output,cache_read,cache_write"` (USD per 1M
  tokens), e.g. `CLAUDEBACKEND_PRICE_DEEPSEEK_CHAT="0.27,1.10,0.07,0.27"`. The
  `<MODEL>` is the model id upper-cased with each `-` turned into `_`
  (`model.upper().replace("-", "_")`); a malformed value (not four
  comma-separated numbers) is ignored with a warning and falls back to the table.
