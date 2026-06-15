#Requires -Version 5.1
<#
.SYNOPSIS
    ClaudeBackend setup script for Windows (PowerShell 5.1 and 7+).

.DESCRIPTION
    Finds a Python 3.10+ interpreter, creates a .venv at the repo root,
    installs the project editable into it, and verifies the claudebackend
    console script runs. Idempotent and safe to re-run.

.PARAMETER dev
    Install the dev/test extras (pip install -e .[dev]) instead of plain install.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --dev
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Argument parsing (must work under Windows PowerShell 5.1 AND PowerShell 7).
# We parse $args by hand so that POSIX-style flags (--dev, -h, --help) work
# without PowerShell trying to bind them to named parameters.
# ---------------------------------------------------------------------------
$Dev = $false
$ShowHelp = $false

foreach ($arg in $args) {
    switch ($arg) {
        '--dev'  { $Dev = $true }
        '-h'     { $ShowHelp = $true }
        '--help' { $ShowHelp = $true }
        '/?'     { $ShowHelp = $true }
        default {
            Write-Host ("ERROR: unknown argument: {0}" -f $arg)
            Write-Host "Run with -h for usage."
            exit 2
        }
    }
}

function Show-Usage {
    Write-Host "=== ClaudeBackend setup ==="
    Write-Host ""
    Write-Host "Usage: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [--dev] [-h|--help]"
    Write-Host ""
    Write-Host "  --dev        Install dev/test extras (pip install -e .[dev])."
    Write-Host "  -h, --help   Show this help and exit."
    Write-Host ""
    Write-Host "Creates a .venv at the repo root, installs claudebackend editable,"
    Write-Host "and verifies it. Safe to re-run."
}

if ($ShowHelp) {
    Show-Usage
    exit 0
}

# ---------------------------------------------------------------------------
# Banner + repo root. The repo root is the PARENT of this script's directory.
# ---------------------------------------------------------------------------
Write-Host "=== ClaudeBackend setup ==="

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot
Write-Host ("Repo root: {0}" -f $RepoRoot)

$VenvDir    = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvCli    = Join-Path $VenvDir 'Scripts\claudebackend.exe'

# ---------------------------------------------------------------------------
# [1/4] Python: find an interpreter that is >= 3.10 and actually runs.
# Try the launcher 'py -3' first, then 'python', then 'python3'.
# Each candidate is a token array so we can pass leading args (e.g. -3).
# ---------------------------------------------------------------------------
Write-Host "[1/4] Python: locating an interpreter (>= 3.10)..."

$Candidates = @(
    @('py', '-3'),
    @('python'),
    @('python3')
)

function Test-PyVersion {
    param([string[]]$Cmd)

    $exe = $Cmd[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        return $false
    }

    $rest = @()
    if ($Cmd.Length -gt 1) { $rest = $Cmd[1..($Cmd.Length - 1)] }

    # Probe the version. We do NOT use 'assert' (it is a no-op under -O); we
    # print a sentinel and exit non-zero ourselves when the version is too old.
    $probe = 'import sys; sys.exit(0) if sys.version_info >= (3, 10) else sys.exit(1)'
    try {
        & $exe @rest '-c' $probe 2>$null
    } catch {
        return $false
    }
    return ($LASTEXITCODE -eq 0)
}

function Get-PyVersionString {
    param([string[]]$Cmd)

    $exe  = $Cmd[0]
    $rest = @()
    if ($Cmd.Length -gt 1) { $rest = $Cmd[1..($Cmd.Length - 1)] }

    # No quotes inside the snippet: Windows PowerShell 5.1 mangles embedded
    # double quotes when passing args to a native exe. split() with no args
    # splits on whitespace, so "3.12.1" comes out clean and quote-free.
    $code = 'import sys; print(sys.version.split()[0])'
    $out  = & $exe @rest '-c' $code 2>$null
    return ($out | Select-Object -First 1)
}

$PyCmd = $null
foreach ($cand in $Candidates) {
    if (Test-PyVersion -Cmd $cand) {
        $PyCmd = $cand
        break
    }
}

if ($null -eq $PyCmd) {
    Write-Host "ERROR: no Python 3.10+ interpreter found (tried: py -3, python, python3)."
    Write-Host ""
    Write-Host "Install Python 3.10 or newer, then re-run this script:"
    Write-Host "  winget install Python.Python.3.12"
    Write-Host "or download from https://www.python.org/downloads/windows/ and, in"
    Write-Host 'the installer, check "Add python.exe to PATH". Then open a NEW terminal.'
    exit 1
}

$PyVersion = Get-PyVersionString -Cmd $PyCmd
Write-Host ("[1/4] Python: using '{0}' (Python {1})." -f ($PyCmd -join ' '), $PyVersion)

# ---------------------------------------------------------------------------
# [2/4] venv: create .venv at the repo root if missing; reuse if present.
# ---------------------------------------------------------------------------
Write-Host "[2/4] venv: ensuring .venv exists..."

if (Test-Path -LiteralPath $VenvPython) {
    Write-Host ("[2/4] venv: reusing existing venv at {0}" -f $VenvDir)
} else {
    $exe  = $PyCmd[0]
    $rest = @()
    if ($PyCmd.Length -gt 1) { $rest = $PyCmd[1..($PyCmd.Length - 1)] }

    & $exe @rest '-m' 'venv' $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: failed to create virtual environment."
        exit 1
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host ("ERROR: venv created but {0} is missing." -f $VenvPython)
        exit 1
    }
    Write-Host ("[2/4] venv: created {0}" -f $VenvDir)
}

# ---------------------------------------------------------------------------
# [3/4] install: upgrade pip, then editable-install the project using the
# VENV's python (never the system one).
# ---------------------------------------------------------------------------
Write-Host "[3/4] install: upgrading pip..."

& $VenvPython '-m' 'pip' 'install' '--upgrade' 'pip'
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: failed to upgrade pip in the venv."
    exit 1
}

if ($Dev) {
    $Target = '.[dev]'
    Write-Host "[3/4] install: installing project editable with dev extras (-e .[dev])..."
} else {
    $Target = '.'
    Write-Host "[3/4] install: installing project editable (-e .)..."
}

& $VenvPython '-m' 'pip' 'install' '-e' $Target
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: editable install failed."
    exit 1
}

# ---------------------------------------------------------------------------
# [4/4] verify: run 'claudebackend --help' via the venv; fail loudly on error.
# ---------------------------------------------------------------------------
Write-Host "[4/4] verify: running 'claudebackend --help'..."

if (-not (Test-Path -LiteralPath $VenvCli)) {
    Write-Host ("ERROR: console script not found at {0}" -f $VenvCli)
    exit 1
}

& $VenvCli '--help' | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 'claudebackend --help' returned a non-zero exit code."
    exit 1
}
Write-Host "[4/4] verify: OK."

# ---------------------------------------------------------------------------
# Next steps (ASCII only, copy-pasteable).
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Setup complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host ""
Write-Host "1) Activate the venv in this shell:"
Write-Host "     .\.venv\Scripts\Activate.ps1"
Write-Host "   (If activation is blocked, run once:"
Write-Host "      Set-ExecutionPolicy -Scope CurrentUser RemoteSigned )"
Write-Host ""
Write-Host "2) Authenticate (pick ONE):"
Write-Host "   a) Anthropic API key (this shell):"
Write-Host '        $env:ANTHROPIC_API_KEY = "sk-ant-..."'
Write-Host "      ...or persist it for future shells:"
Write-Host '        setx ANTHROPIC_API_KEY "sk-ant-..."'
Write-Host "   b) Claude subscription login, then pass --use-subscription (Anthropic only):"
Write-Host "        claude        (or: ant auth login)"
Write-Host '        claudebackend develop ./service "Add a /health endpoint" --dry-run --use-subscription'
Write-Host "   c) Another provider (OpenRouter/OpenAI/NVIDIA/DeepSeek/Gemini):"
Write-Host '        claudebackend develop ./service "Add a /health endpoint" --dry-run --provider <name> --model <id>'
Write-Host "      See docs\providers.md for env vars and example model ids."
Write-Host ""
Write-Host "3) First safe run (writes NOTHING):"
Write-Host '     claudebackend develop ./service "Add a /health endpoint" --dry-run'
Write-Host ""
