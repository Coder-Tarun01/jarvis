# JARVIS - one-command local start (Windows PowerShell)
#
#   .\run.ps1
#
# Creates .venv, installs backend deps, installs frontend deps, then starts
# the API on :8000 (new window) and Vite on :5173 (this window).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

if (-not (Test-Path ".env")) {
    Write-Host "No .env found - copying .env.example. Fill in OPENAI_API_KEY and JARVIS_AUTH_TOKEN." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

$python = Join-Path $root ".venv\Scripts\python.exe"
Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r (Join-Path $root "backend\requirements.txt")

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location "frontend"
    npm install --no-audit --no-fund
    Pop-Location
}

Write-Host "Starting backend on http://127.0.0.1:8000 (separate window)..." -ForegroundColor Green
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend")

Start-Sleep -Seconds 2
Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Green
Push-Location "frontend"
try {
    npm run dev
} finally {
    Pop-Location
    Write-Host "Frontend stopped. Close the backend window when you are done." -ForegroundColor Yellow
}
