# ClaudeBackend -- Windows install guide

ClaudeBackend is a universal multi-agent backend development system. This guide
gets it installed and running on Windows using PowerShell (Windows PowerShell
5.1 or PowerShell 7+).

## Prerequisites

- Windows 10 or 11.
- Windows PowerShell 5.1 (built in) or PowerShell 7+.
- Python 3.10 or newer (installed in step 1).
- Git, to clone the repo (or download the source as a ZIP).
- One way to authenticate (set up in step 4): an Anthropic API key, a Claude
  subscription login, or another provider's API key.

## 1. Install Python 3.10+

Check whether a suitable Python is already present:

```
py -3 --version
```

If that prints `Python 3.10` or higher, skip to step 2. Otherwise install it
with winget:

```
winget install Python.Python.3.12
```

Or download the installer from https://www.python.org/downloads/windows/ and,
during install, check "Add python.exe to PATH". Open a NEW terminal afterwards so
the updated PATH takes effect, then confirm:

```
py -3 --version
```

## 2. Get the code

Clone the repository and change into it:

```
git clone <repo-url> claudebackend
cd claudebackend
```

(If you downloaded a ZIP instead, extract it and `cd` into the extracted folder.)

## 3. Run the setup script

From the repo root, run the setup script. The reliable way (no execution-policy
prompt) is to bypass the policy for this one invocation:

```
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

To install the dev/test extras as well, add `--dev`:

```
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --dev
```

The script prints `=== ClaudeBackend setup ===` and runs four steps:
`[1/4] Python`, `[2/4] venv`, `[3/4] install`, `[4/4] verify`. It creates a
virtual environment at `.venv` in the repo root, installs `claudebackend`
editable into it, and verifies the console script runs. It is safe to re-run.

Execution-policy gotcha: if you run the script directly (for example
`.\scripts\setup.ps1`) and see "running scripts is disabled on this system",
either use the `-ExecutionPolicy Bypass` form above, or allow local scripts once
for your user:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

After a successful run, activate the virtual environment in your shell:

```
.\.venv\Scripts\Activate.ps1
```

If activation is blocked by the execution policy, run the
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` command above once, then
activate again.

## 4. Choose how to authenticate

Pick ONE of these three options.

Option 1 -- Anthropic API key. Set it for the current shell:

```
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Or persist it for future shells (open a new terminal afterwards):

```
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Option 2 -- Claude subscription login. Log in once, then pass
`--use-subscription` (Anthropic only):

```
claude
claudebackend develop ./service "Add a /health endpoint" --dry-run --use-subscription
```

(`ant auth login` works in place of `claude` if you have that CLI.)

Option 3 -- another provider (OpenRouter, OpenAI, NVIDIA, DeepSeek, or Gemini).
Set the provider's API key and select it with `--provider`/`--model`:

```
$env:DEEPSEEK_API_KEY = "..."
claudebackend develop ./service "Add a /health endpoint" --dry-run --provider deepseek --model deepseek-chat
```

See `docs\providers.md` for each provider's env var, base URL, and example model
ids. `--model` is required for every non-Anthropic provider.

## 5. First run (dry run)

Always start with `--dry-run`. It runs the full Plan -> Code -> Verify pipeline
and prints the diff and summary WITHOUT writing anything to disk:

```
claudebackend develop ./service "Add a /health endpoint" --dry-run
```

If you did not activate the venv, call the console script by its full path
instead:

```
.\.venv\Scripts\claudebackend.exe develop ./service "Add a /health endpoint" --dry-run
```

## 6. Everyday use

With the venv activated:

```
claudebackend develop ./service "Add a /health endpoint" --dry-run   # preview only, writes nothing
claudebackend develop ./service "Add a /health endpoint"             # work onto a new git branch
claudebackend develop ./service "Add a /health endpoint" --init      # if the path is not a git repo yet
claudebackend develop ./legacy "Migrate this codebase from Python 2 to Python 3"   # py2->3 is just one objective
claudebackend --help                                                 # all commands and options
```

The real run never touches your working tree or current branch; it writes the
result to a new branch (`claudebackend/feature-<timestamp>`) with a
`DEV_SUMMARY.md` and `DEV_GRAPH.md`. To update later, pull the latest code and
re-run `scripts\setup.ps1` (it reuses the existing `.venv`).

## Troubleshooting

- "running scripts is disabled on this system" (execution policy blocks the
  script or `Activate.ps1`). Run the script with
  `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`, or allow local
  scripts once for your user with
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

- "'py' is not recognized" or "'python' is not recognized" (Python not found or
  not on PATH). Install Python with `winget install Python.Python.3.12`, or
  reinstall from python.org with "Add python.exe to PATH" checked, then open a
  NEW terminal and verify with `py -3 --version`.

- pip SSL or proxy errors during `[3/4] install`. On a corporate network set the
  proxy first: `$env:HTTPS_PROXY = "http://user:pass@proxy:port"` (and
  `$env:HTTP_PROXY` likewise), then re-run the setup script. SSL-interception
  errors usually mean your company root CA must be trusted by Python; ask IT for
  the CA bundle, or set `$env:PIP_CERT = "C:\path\to\corp-ca.pem"`.

- venv activation blocked even after install. The `[4/4] verify` step proves the
  install works without activation. You can skip activation entirely and call the
  tool by full path: `.\.venv\Scripts\claudebackend.exe --help`. To enable
  activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

- "claudebackend is not recognized" after closing the terminal. The command is
  only on PATH while the venv is activated. Re-activate with
  `.\.venv\Scripts\Activate.ps1`, or use the full path
  `.\.venv\Scripts\claudebackend.exe`.
