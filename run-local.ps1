# Run FuckinDownloader natively on Windows (no Docker), for local testing.
# Usage:  .\run-local.ps1            (port 8090)
#         .\run-local.ps1 -Port 9000
# Needs Python 3.11+ and ffmpeg on PATH. Settings and downloads go to .\data
param([int]$Port = 8090)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "!! ffmpeg not found on PATH. Install it: winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host ">> Creating .venv and installing dependencies (one-time, takes a minute)..."
    py -3 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt deno
}
if (-not (Test-Path ".venv-spotdl\Scripts\spotdl.exe")) {
    Write-Host ">> Installing spotdl in its own venv..."
    py -3 -m venv .venv-spotdl
    .\.venv-spotdl\Scripts\python.exe -m pip install -q spotdl
}

# load .env (KEY=VALUE lines) into this process
if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), "Process")
        }
    }
}

$env:PATH = "$PSScriptRoot\.venv\Scripts;$env:PATH"
$env:FDL_DATA_DIR = "$PSScriptRoot\data"
$env:FDL_SPOTDL = "$PSScriptRoot\.venv-spotdl\Scripts\spotdl.exe"
$env:FDL_SPOTDL_PIP = "$PSScriptRoot\.venv-spotdl\Scripts\pip.exe"

$admin = if ($env:ADMIN_PATH) { $env:ADMIN_PATH.Trim("/") } else { "admin" }
Write-Host ">> FuckinDownloader:  http://localhost:$Port" -ForegroundColor Green
Write-Host ">> Admin panel:       http://localhost:$Port/$admin  (password = ADMIN_PASSWORD in .env)" -ForegroundColor Green
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-access-log
