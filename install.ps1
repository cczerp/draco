# Draco install script for Windows
# Run in PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Or one-liner (downloads and runs):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/cczerp/draco/main/install.ps1 | iex"

$ErrorActionPreference = 'Stop'
$RAW = 'https://raw.githubusercontent.com/cczerp/draco/main/draco.py'

function Write-Step($msg)  { Write-Host "  $msg" -ForegroundColor DarkGray }
function Write-Ok($msg)    { Write-Host "      OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "      !   $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "      X   $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  ╔═══════════════════════════════╗" -ForegroundColor Magenta
Write-Host "  ║  🐉  Draco  ·  Windows install ║" -ForegroundColor Magenta
Write-Host "  ╚═══════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

# ── Locate or download draco.py ───────────────────────────────────────────────
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
$dracoSrc  = Join-Path $scriptDir 'draco.py'

if (-not (Test-Path $dracoSrc)) {
    Write-Step '[0/3] Downloading draco.py from GitHub...'
    $dracoSrc = Join-Path $env:TEMP 'draco.py'
    try {
        Invoke-WebRequest -Uri $RAW -OutFile $dracoSrc -UseBasicParsing
        Write-Ok 'downloaded draco.py'
    } catch {
        Write-Fail "Download failed: $_"
        Write-Host "      Check your internet connection or download manually from:"
        Write-Host "      https://github.com/cczerp/draco"
        exit 1
    }
}

# ── Check Python ──────────────────────────────────────────────────────────────
Write-Step '[1/3] Checking Python...'
$pyCmd = $null
foreach ($cmd in @('python', 'python3', 'py')) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match 'Python 3') { $pyCmd = $cmd; break }
    } catch {}
}

if (-not $pyCmd) {
    Write-Fail 'Python 3 not found.'
    Write-Host ""
    Write-Host "  Download Python from: https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "  IMPORTANT: check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Then re-run this script."
    exit 1
}
$pyVer = (& $pyCmd --version 2>&1).ToString().Trim()
Write-Ok $pyVer

# Install requests
try {
    & $pyCmd -c 'import requests' 2>$null
} catch {
    Write-Step '      installing requests...'
    & $pyCmd -m pip install --quiet requests
}
Write-Ok 'requests'

# ── Install draco ─────────────────────────────────────────────────────────────
Write-Step '[2/3] Installing draco...'

$installDir = Join-Path $env:USERPROFILE '.draco'
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

Copy-Item $dracoSrc (Join-Path $installDir 'draco.py') -Force

# Create draco.bat wrapper so "draco" works from any terminal
$pyPath = (Get-Command $pyCmd).Source
$batPath = Join-Path $installDir 'draco.bat'
Set-Content -Path $batPath -Value "@echo off`n`"$pyPath`" `"$installDir\draco.py`" %*"

Write-Ok "installed → $installDir\draco.bat"

# Add to user PATH if needed
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable('PATH', "$userPath;$installDir", 'User')
    Write-Warn 'Added to PATH — open a new terminal window for it to take effect.'
} else {
    Write-Ok 'already in PATH'
}

# ── Check Ollama ──────────────────────────────────────────────────────────────
Write-Step '[3/3] Checking Ollama...'
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    $models = ($resp.Content | ConvertFrom-Json).models
    Write-Ok "Ollama running  ($($models.Count) model(s) installed)"
} catch {
    Write-Warn 'Ollama not detected — draco will walk you through setup on first run.'
    Write-Host ""
    Write-Host "  To install Ollama for Windows:" -ForegroundColor DarkGray
    Write-Host "  https://ollama.com/download/windows" -ForegroundColor Cyan
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Done!" -ForegroundColor Green
Write-Host ""
Write-Host "  Open a new terminal, then type: draco"
Write-Host ""
Write-Host "  Quick usage:" -ForegroundColor DarkGray
Write-Host "    draco                                 # interactive session"
Write-Host "    draco `"what's on my desktop?`"        # single prompt"
Write-Host "    draco --dangerously-skip-permissions  # auto-approve all tools"
Write-Host "    draco --model <name>                  # pick a model"
Write-Host ""
