# ClaudeBackend -- macOS install guide

ClaudeBackend is a universal multi-agent backend development system. This guide
gets it running on macOS.

## Prerequisites

- macOS with Terminal (the default shell is zsh).
- Python 3.10 or newer (installed in step 1).
- A clone of this repository.
- One way to authenticate (step 4): an Anthropic API key, a Claude Code login,
  or another provider's key.

## 1. Install Python 3.10+

Check whether a suitable Python is already present:

```bash
python3 --version
```

If it prints 3.10.x or newer, skip ahead. Otherwise install via Homebrew:

```bash
# If Homebrew is missing, install it first (see https://brew.sh):
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12
```

Alternatively, download the official installer from
https://www.python.org/downloads/macos/ and run it.

If you later hit compiler errors during install, add Apple's Command Line Tools:

```bash
xcode-select --install
```

## 2. Get the code

```bash
git clone <repo-url> claudebackend
cd claudebackend
```

If you already have the repository, just `cd` into its root.

## 3. Run the setup script

From the repo root, make the script executable and run it:

```bash
chmod +x scripts/setup-macos.sh
./scripts/setup-macos.sh
```

To install the dev/test extras instead of the plain install:

```bash
./scripts/setup-macos.sh --dev
```

The script finds Python 3.10+, creates `.venv` at the repo root, installs the
project editable into it, and verifies the `claudebackend` command works. It is
idempotent -- safe to run again.

Gotcha: if macOS Gatekeeper quarantined the file (e.g. downloaded as a zip
rather than cloned), clear the flag before running:

```bash
xattr -d com.apple.quarantine scripts/setup-macos.sh
```

## 4. Choose how to authenticate

Pick ONE of the following.

Option 1 -- Anthropic API key in an environment variable (zsh):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Persist it across shells by adding it to `~/.zshrc`:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
```

Option 2 -- Use an existing Claude Code / `ant auth login` session (Anthropic
only). Log in once, then pass `--use-subscription` on each command:

```bash
ant auth login
claudebackend develop ./service "Add a /health endpoint" --dry-run --use-subscription
```

Option 3 -- Use another provider (OpenRouter, OpenAI, NVIDIA, DeepSeek, or
Gemini) via `--provider` / `--model`. See `docs/providers.md` for the exact
provider names, model ids, and the API key env var each one expects.

## 5. First run (dry run)

Activate the virtualenv, then do a dry run. A dry run previews the work and
writes NOTHING to disk -- always start here:

```bash
source .venv/bin/activate
claudebackend develop ./service "Add a /health endpoint" --dry-run
```

Replace `./service` with the path to your project and the quoted text with the
objective you want done (for example, "Migrate this codebase from Python 2 to
Python 3").

## 6. Everyday use

```bash
# Activate the venv in each new terminal session:
source .venv/bin/activate

# Preview the work (no changes written):
claudebackend develop ./service "Add a /health endpoint" --dry-run

# See all options:
claudebackend --help

# Leave the venv when done:
deactivate
```

To pull updates later, `git pull` then re-run `./scripts/setup-macos.sh`. The
editable install picks up code changes automatically, but re-running keeps
dependencies in sync.

## Troubleshooting

- `command not found: python3`
  No system Python is installed. Install it with Homebrew:
  `brew install python@3.12`, then re-run the setup script.

- `permission denied: ./scripts/setup-macos.sh`
  The script is not executable. Run `chmod +x scripts/setup-macos.sh` first, or
  invoke it explicitly with `bash scripts/setup-macos.sh`.

- `zsh: no matches found: .[dev]`
  zsh treats `[dev]` as a glob pattern. Always quote the extras:
  `pip install -e '.[dev]'`. (The setup script already quotes this for you;
  this only bites you when typing pip commands by hand.)

- `error: externally-managed-environment` (PEP 668)
  This happens when installing into a Homebrew/system Python directly. The
  setup script installs into the project's `.venv`, which avoids this entirely.
  If you see it, make sure you are inside the venv (`source .venv/bin/activate`)
  and not running a system `pip`.

- `"setup-macos.sh" cannot be opened because it is from an unidentified
  developer` (Gatekeeper)
  This only occurs if the file was downloaded and quarantined. Clear the flag:
  `xattr -d com.apple.quarantine scripts/setup-macos.sh`, then re-run.