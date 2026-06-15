#!/usr/bin/env bash
set -euo pipefail

# === ClaudeBackend setup ===
# Linux bootstrap: find Python 3.10+, create .venv, install editable, verify.

echo "=== ClaudeBackend setup ==="

# --- Resolve paths: repo root is the parent of this script's directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- Defaults / flags ---
DEV=0

usage() {
    cat <<'USAGE'
Usage: ./scripts/setup-linux.sh [--dev] [-h|--help]

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

# --- Distro-aware install hints (shared by Python and venv steps) ---
print_python_install_hint() {
    cat >&2 <<'HINT'

Install Python 3.10 or newer (with venv + pip), then re-run this script:

  Debian / Ubuntu:
    sudo apt update && sudo apt install -y python3 python3-venv python3-pip

  Fedora / RHEL / CentOS:
    sudo dnf install -y python3 python3-pip

  Arch / Manjaro:
    sudo pacman -S --needed python python-pip

If your distro ships an older python3, install a newer version (e.g. the
deadsnakes PPA on Ubuntu provides python3.12) and re-run.
HINT
}

print_venv_package_hint() {
    cat >&2 <<'HINT'

Creating the virtualenv failed because the standard-library 'venv'/'ensurepip'
support is not installed. On Debian/Ubuntu this lives in a separate package:

  Debian / Ubuntu:
    sudo apt update && sudo apt install -y python3-venv python3-pip

  Fedora / RHEL / CentOS:
    sudo dnf install -y python3 python3-pip

  Arch / Manjaro:
    sudo pacman -S --needed python python-pip

Then delete any partial .venv and re-run this script:
  rm -rf .venv && ./scripts/setup-linux.sh
HINT
}

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
    print_python_install_hint
    exit 1
fi

PY_VERSION="$("${PYTHON}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
echo "[1/4] Python: using '${PYTHON}' (${PY_VERSION})."

# --- [2/4] venv: create .venv at repo root if missing; reuse otherwise ---
if [ -x "${VENV_PY}" ]; then
    echo "[2/4] venv: reusing existing ${VENV_DIR}"
else
    echo "[2/4] venv: creating ${VENV_DIR}"
    # Capture output so we can detect the Debian/Ubuntu "ensurepip is not
    # available" failure and point the user at the python3-venv package.
    VENV_LOG="$(mktemp)"
    if ! "${PYTHON}" -m venv "${VENV_DIR}" >"${VENV_LOG}" 2>&1; then
        cat "${VENV_LOG}" >&2
        echo "ERROR: failed to create virtualenv at ${VENV_DIR}" >&2
        if grep -qi 'ensurepip is not available' "${VENV_LOG}"; then
            print_venv_package_hint
        else
            print_python_install_hint
        fi
        rm -f "${VENV_LOG}"
        # Remove the half-created venv so a re-run starts clean.
        rm -rf "${VENV_DIR}"
        exit 1
    fi
    rm -f "${VENV_LOG}"
fi

if [ ! -x "${VENV_PY}" ]; then
    echo "ERROR: venv python not found at ${VENV_PY}" >&2
    print_venv_package_hint
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

  1. Activate the virtualenv (bash) from the repo root:
       source .venv/bin/activate

  2. Authenticate using ONE of these options:

     a) Anthropic API key:
          export ANTHROPIC_API_KEY="sk-ant-..."
        Persist it for future shells:
          echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc

     b) Use an existing Claude Code / 'ant auth login' session (Anthropic only),
        then pass --use-subscription on the command line:
          ant auth login
          claudebackend develop ./service "Add a /health endpoint" --dry-run --use-subscription

     c) Use another provider (OpenRouter/OpenAI/NVIDIA/DeepSeek/Gemini) via
        --provider / --model. See docs/providers.md for details.

  3. First safe run (writes NOTHING -- preview only):
       claudebackend develop ./service "Add a /health endpoint" --dry-run

NEXT
