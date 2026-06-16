# ClaudeBackend

A universal, strictly-verified multi-agent backend development system.

Give ClaudeBackend a repository and an objective in plain English — "Add JWT authentication", "Refactor the SQLAlchemy models", "Migrate this legacy code" — and it implements the change through an isolated **Planner → Coder → Verifier** pipeline.

Unlike standard AI chat assistants, ClaudeBackend understands semantic and cross-file dependencies. It maps your entire project (code, ORM models, Dockerfiles, and config), executes a verified step-by-step development plan, and outputs the result to a clean, reviewable git branch.

Your working tree is never touched. The generated code is strictly gated by syntax checkers, linters, SAST tools, and your own test suite.

> **New here?** Read [what ClaudeBackend is and why you'd use it](docs/overview.md).
> Available in [فارسی](docs/i18n/fa.md) · [日本語](docs/i18n/ja.md) · [中文](docs/i18n/zh.md) · [Русский](docs/i18n/ru.md) · [Français](docs/i18n/fr.md) · [Deutsch](docs/i18n/de.md).

---

## The Core Difference

| Feature | codemods / 2to3 | Linters (SonarQube) | AI Chat Assistants | ClaudeBackend |
| --- | --- | --- | --- | --- |
| **Implements arbitrary objectives** | ❌ Fixed rules | ❌ Read-only | ✅ Manual copy/paste | ✅ Automated |
| **Dependency-aware (ORM/Docker)** | ❌ | Partial | ❌ Relies on user context | ✅ Comprehensive graph |
| **Verification Gate** (`compile` + `ruff` + `pytest`) | ❌ | ❌ | ❌ | ✅ Strict |
| **Built-in Red Team / DevSecOps** | ❌ | ✅ SAST only | ❌ | ✅ SAST + AI Audit |
| **Final Output** | Edits in place | A report | Chat text | Reviewable git branch + Diff |

---

## Quick Start

Requires **Python 3.10+**. The quickest path is our per-OS bootstrap script:

| OS | Command (run from repo root) |
| --- | --- |
| **Windows** | `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` |
| **macOS** | `chmod +x scripts/setup-macos.sh && ./scripts/setup-macos.sh` |
| **Linux** | `chmod +x scripts/setup-linux.sh && ./scripts/setup-linux.sh` |

**Security Extra (Recommended):** For the Static Application Security Testing (SAST) gate, install the security extra:

```bash
pip install claudebackend[security]
```

Activate your `.venv`, authenticate (e.g., `export ANTHROPIC_API_KEY=...`), and start developing:

```bash
# Develop a feature safely on a new branch:
claudebackend develop ./service "Add JWT authentication"

# Preview only (no disk writes, no commits):
claudebackend develop ./service "Refactor the models" --dry-run
```

---

## How It Works: The Verifiable Pipeline

ClaudeBackend is built on a philosophy of **Trust, but Verify**. The AI writes the code, but strict deterministic gates ensure its safety.

1. **Context Mapping** — Builds a graph of your repo (Python imports, ORM relationships, Dockerfile refs).
2. **Planner** — Produces an `ExecutionPlan` detailing files to create, modify, or delete.
3. **Coder & Syntax Gate** — Builds a context window for each file, streams the code, and verifies it against a strict syntax gate (`py_compile`).
4. **DevSecOps Gate (Red Team)** — New code is scanned with `bandit` (SAST) and audited by a specialized Red Team Agent. Vulnerabilities (SQLi, IDOR, SSRF) reject the code and force a rewrite. Unfixable code is discarded.
5. **Project-Wide Verification** — Compiles every module + `ruff` + `pytest` + an advisory `bandit` scan.
6. **Git Isolation** — Creates `claudebackend/feature-<timestamp>`, commits the safe code, and writes a detailed `DEV_SUMMARY.md`.

---

## Local AI (Air-Gapped & Offline)

Run the entire pipeline on your own hardware via [Ollama](https://ollama.com) with zero outbound network calls.

> **Note:** The Planner agent requires high reasoning capabilities to output structured dependency JSON. We recommend using capable coder models (e.g., `qwen2.5-coder`, `llama3`).

```bash
ollama pull qwen2.5-coder
claudebackend develop ./service "Add a /health endpoint" --local --model qwen2.5-coder
```

See [`docs/install/local_ai.md`](docs/install/local_ai.md) for advanced per-agent model routing.

---

## Modular Ecosystem

ClaudeBackend's core is just the pipeline engine. We provide optional, opt-in tools for advanced workflows without bloating the core system:

- **Continuous CI/CD** — Drop `.github/workflows/claude-backend-agent.yml` into your repo. Label an issue `ai-developer` and the agent will open a fully verified PR.
- **Local TDD Watcher** — (`pip install "claudebackend[watch]"`). Write a failing test, save it, and the watcher automatically fixes the code in place to turn it green.
- **IDE / Agent Integration** — Exposes an MCP server (`claudebackend mcp`) and a Claude Code plugin for seamless IDE usage.

---

## Roadmap & Upcoming Features

- **PHP Support (`PHPDriver`)** — Bringing the pipeline to PHP with `composer.json` mapping. Security analysis will rely on true AST parsing (PHPStan/Psalm) rather than fragile regex, ensuring enterprise-grade safety.
- **Opt-in Live Dashboard** — An air-gapped, decoupled React UI to visualize pipeline token usage and dependency graphs in real-time.

---

## License

Released under the [MIT License](LICENSE).
