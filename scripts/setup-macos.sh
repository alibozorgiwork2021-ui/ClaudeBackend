#!/usr/bin/env bash
set -euo pipefail

# === ClaudeBackend setup ===
# macOS bootstrap: find Python 3.10+, create .venv, install editable, verify.

echo "=== ClaudeBackend setup ==="

# --- Resolve paths: repo root is the parent of this script's directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- Defaults / flags ---
DEV=0

usage() {
    cat <<'USAGE'
Usage: ./scripts/setup-macos.sh [--dev] [-h|--help]

  --dev        Install the dev/test extras ( -e '.[dev]' ) instead of plain install.
  -h, --help   Show this help and exit.

Creates a virtualenv at <repo-root>/.venv, installs ClaudeBackend editable into
it, and verifies the 'claudebackend' console script works. Safe to re-run.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dev)
            DEV=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

cd "${REPO_ROOT}"

VENV_DIR="${REPO_ROOT}/.venv"
VENV_PY="${VENV_DIR}/bin/python"
VENV_CLI="${VENV_DIR}/bin/claudebackend"

# --- [1/4] Python: discover an interpreter and verify it is >= 3.10 ---
echo "[1/4] Python: locating an interpreter (>= 3.10)..."

# Returns 0 if the given interpreter exists and reports version >= 3.10.
python_ok() {
    local candidate="$1"
    command -v "${candidate}" >/dev/null 2>&1 || return 1
    "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' >/dev/null 2>&1
}

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if python_ok "${candidate}"; then
        PYTHON="${candidate}"
        break
    fi
done

if [ -z "${PYTHON}" ]; then
    echo "ERROR: no Python 3.10+ interpreter found." >&2
    cat >&2 <<'HINT'

Install Python 3.10 or newer, then re-run this script. Options:

  Homebrew (recommended):
    # If Homebrew is not installed, install it first from https://brew.sh :
    #   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install python@3.12

  Or download the official installer from:
    https://www.python.org/downloads/macos/

  If you hit compiler errors during install, install the Command Line Tools:
    xcode-select --install
HINT
    exit 1
fi

PY_VERSION="$("${PYTHON}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
echo "[1/4] Python: using '${PYTHON}' (${PY_VERSION})."

# --- [2/4] venv: create .venv at repo root if missing; reuse otherwise ---
if [ -x "${VENV_PY}" ]; then
    echo "[2/4] venv: reusing existing ${VENV_DIR}"
else
    echo "[2/4] venv: creating ${VENV_DIR}"
    "${PYTHON}" -m venv "${VENV_DIR}"
fi

if [ ! -x "${VENV_PY}" ]; then
    echo "ERROR: venv python not found at ${VENV_PY}" >&2
    exit 1
fi

# --- [3/4] install: upgrade pip, then editable install using the VENV python ---
echo "[3/4] install: upgrading pip..."
"${VENV_PY}" -m pip install --upgrade pip

if [ "${DEV}" -eq 1 ]; then
    echo "[3/4] install: installing editable with dev extras ( -e '.[dev]' )..."
    "${VENV_PY}" -m pip install -e '.[dev]'
else
    echo "[3/4] install: installing editable ( -e . )..."
    "${VENV_PY}" -m pip install -e .
fi

# --- [4/4] verify: run the console script via the venv ---
echo "[4/4] verify: running 'claudebackend --help'..."
if [ ! -x "${VENV_CLI}" ]; then
    echo "ERROR: console script not found at ${VENV_CLI}" >&2
    exit 1
fi
if ! "${VENV_CLI}" --help >/dev/null; then
    echo "ERROR: 'claudebackend --help' failed." >&2
    exit 1
fi
echo "[4/4] verify: OK."

# --- Next steps ---
cat <<'NEXT'

Next steps:

  1. Activate the virtualenv (zsh/bash) from the repo root:
       source .venv/bin/activate

  2. Authenticate using ONE of these options:

     a) Anthropic API key (zsh -- the default macOS shell):
          export ANTHROPIC_API_KEY="sk-ant-..."
        Persist it for future shells:
          echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc

     b) Use an existing Claude Code / 'ant auth login' session (Anthropic only),
        then pass --use-subscription on the command line:
          ant auth login
          claudebackend develop ./service "Add a /health endpoint" --dry-run --use-subscription

     c) Use another provider (OpenRouter/OpenAI/NVIDIA/DeepSeek/Gemini) via
        --provider / --model. See docs/providers.md for details.

  3. First safe run (writes NOTHING -- preview only):
       claudebackend develop ./service "Add a /health endpoint" --dry-run

NEXT