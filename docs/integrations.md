# Using ClaudeBackend from IDEs and agents

ClaudeBackend exposes itself as an **MCP server** (`claudebackend mcp`), a
**skill**, and a **Claude Code plugin**. That is how Cursor, Google Antigravity,
Codex, Claude Code/Desktop, and other agents use it — they call its
`develop_backend_feature` tool. (None of those tools can lend their subscription
to an external program; they consume ClaudeBackend, they are not LLM backends for
it.)

The `develop_backend_feature` tool defaults to `dry_run=true`, so an agent never
mutates a repo without explicitly opting in.

### The `develop_backend_feature` result's `cost` key

The dict returned by the `develop_backend_feature` tool includes a **`cost`** key.
It is an object with `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `cost_usd` (null when the model's pricing is unknown),
`pricing_known`, `cache_hit_ratio`, and `calls` — or `null` when no token usage
was recorded for the run. The full result also includes `objective`, `branch`,
`project_ok`, the `created`/`modified`/`deleted` lists, `flagged`, `review`,
`summary`, `graph`, and `diff` (in dry-run).

## Prerequisite

Install the CLI so `claudebackend` is on PATH, and set a backend key (see
`docs/providers.md`):

```bash
pip install -e .
export ANTHROPIC_API_KEY=...        # or use --provider/--model, or --use-subscription
```

## Claude Code / Claude Desktop

This repo ships a project `.mcp.json`, so opening it in Claude Code auto-offers
the server. To add it anywhere:

```bash
claude mcp add --scope project --transport stdio claudebackend claudebackend mcp
```

Claude Desktop — add to `claude_desktop_config.json`:

```json
{ "mcpServers": { "claudebackend": { "command": "claudebackend", "args": ["mcp"] } } }
```

As a **plugin** (bundles the MCP server + `/develop` command + skill): the repo is
a valid Claude Code plugin (`.claude-plugin/plugin.json`). Add it as a local
plugin / via your plugin marketplace per Claude Code's plugin docs.

## Cursor

Add to `~/.cursor/mcp.json` (or the project `.cursor/mcp.json`):

```json
{ "mcpServers": { "claudebackend": { "command": "claudebackend", "args": ["mcp"] } } }
```

## Google Antigravity

Add the MCP server in Antigravity's MCP settings (same stdio shape):

```json
{ "mcpServers": { "claudebackend": { "command": "claudebackend", "args": ["mcp"] } } }
```

## Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.claudebackend]
command = "claudebackend"
args = ["mcp"]
```

## As a skill

The bundled skill is auto-discovered by Claude Code (as a plugin/personal skill)
and by the Agent SDK. Point any skill-aware tool at the `skills/` directory.

> Config file locations and exact MCP-registration UI differ per tool and
> version — check each tool's current MCP docs if a path above has moved. The
> stdio command (`claudebackend mcp`) is the same everywhere.
