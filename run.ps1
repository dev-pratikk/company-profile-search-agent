# Creates the virtual env on first run, installs deps, and starts the server.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }

Write-Host "Open http://127.0.0.1:8000" -ForegroundColor Green
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-include .env
