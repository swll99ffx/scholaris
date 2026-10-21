# One-time setup: Python virtualenv + backend deps + frontend deps.
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Creating Python virtual environment" -ForegroundColor Cyan
if (-not (Test-Path "backend\.venv")) {
    python -m venv backend\.venv
}

Write-Host "==> Installing backend dependencies" -ForegroundColor Cyan
& "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt

Write-Host "==> Installing frontend dependencies" -ForegroundColor Cyan
Push-Location frontend
npm install
Pop-Location

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example (add your free API keys when you have them)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Start everything with: scripts\dev.ps1" -ForegroundColor Green
