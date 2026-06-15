# ClaudeBackend -- Linux install guide

ClaudeBackend is a universal multi-agent backend development system. This guide
gets it running on Linux.

## Prerequisites

- A Linux distribution with a terminal (bash is assumed).
- Python 3.10 or newer (installed in step 1).
- A clone of this repository.
- One way to authenticate (step 4): an Anthropic API key, a Claude Code login,
  or another provider's key.

## 1. Install Python 3.10+

Check whether a suitable Python is already present:

```bash
python3 --version
```

If it prints 3.10.x or newer, skip ahead. Otherwise install Python (with venv
and pip) using your distro's package manager:

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y python3 python3-venv python3-pip

# Fedora / RHEL / CentOS
sudo dnf install -y python3 python3-pip

# Arch / Manjaro
sudo pacman -S --needed python python-pip
```

On Debian/Ubuntu the `python3-venv` package is required for `python3 -m venv` to
work -- install it now to avoid the "ensurepip is not available" error later.

If your distro ships an older python3 (run `python3 --version` to check), install
a newer one. On Ubuntu the deadsnakes PPA provides modern versions:

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update && sudo apt install -y python3.12 python3.12-venv
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
chmod +x scripts/setup-linux.sh
./scripts/setup-linux.sh
```

To install the dev/test extras instead of the plain install:

```bash
./scripts/setup-linux.sh --dev
```

The script finds Python 3.10+, creates `.venv` at the repo root, installs the
project editable into it, and verifies the `claudebackend` command works. It is
idempotent -- safe to run again.

Gotcha: the script must be executable. If you get `permission denied`, run the
`chmod +x` above first, or invoke it explicitly with
`bash scripts/setup-linux.sh`.

## 4. Choose how to authenticate

Pick ONE of the following.

Option 1 -- Anthropic API key in an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Persist it across shells by adding it to `~/.bashrc`:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
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

To pull updates later, `git pull` then re-run `./scripts/setup-linux.sh`. The
editable install picks up code changes automatically, but re-running keeps
dependencies in sync.

## Troubleshooting

- `ensurepip is not available`
  Seen when creating the venv on Debian/Ubuntu without the venv package. Install
  it and re-run:
  `sudo apt update && sudo apt install -y python3-venv python3-pip`, then
  `rm -rf .venv && ./scripts/setup-linux.sh`.

- `python3: command not found`
  No system Python is installed. Install it for your distro, then re-run the
  setup script:
  - Debian/Ubuntu: `sudo apt update && sudo apt install -y python3 python3-venv python3-pip`
  - Fedora/RHEL: `sudo dnf install -y python3 python3-pip`
  - Arch: `sudo pacman -S --needed python python-pip`

- `error: externally-managed-environment` (PEP 668)
  Recent distros block `pip install` into the system Python. The setup script
  installs into the project's `.venv`, which avoids this entirely. If you hit it,
  make sure you are inside the venv (`source .venv/bin/activate`) and not using a
  system `pip`.

- `permission denied: ./scripts/setup-linux.sh`
  The script is not executable. Run `chmod +x scripts/setup-linux.sh` first, or
  invoke it explicitly with `bash scripts/setup-linux.sh`.

- pip times out or fails behind a proxy
  Point pip at your proxy and re-run the setup script. Either export the proxy
  vars or pass `--proxy`:
  ```bash
  export HTTPS_PROXY="http://user:pass@proxy.example.com:8080"
  export HTTP_PROXY="http://user:pass@proxy.example.com:8080"
  ./scripts/setup-linux.sh
  ```
  For a one-off manual install inside the venv:
  `.venv/bin/python -m pip install --proxy "$HTTPS_PROXY" -e .`
