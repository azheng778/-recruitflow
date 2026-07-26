$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "agent\Scripts\python.exe"

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    throw "Missing .env. Copy .env.example to .env and configure the database password."
}


$EnvContent = Get-Content -LiteralPath (Join-Path $ProjectRoot ".env")
$DbUser = (($EnvContent | Where-Object { $_ -match '^DB_USERNAME=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
$DbPassword = (($EnvContent | Where-Object { $_ -match '^DB_PASSWORD=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
if (-not $DbUser -or $DbUser -eq "recruitflow_app" -or -not $DbPassword -or $DbPassword -match "replace|your") {
    throw "DB_USERNAME and DB_PASSWORD in .env must contain valid MySQL credentials."
}

$env:PYTHONPATH = Join-Path $ProjectRoot "backend"
& $Python -m alembic -c (Join-Path $ProjectRoot "backend\alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m uvicorn app.main:app --app-dir (Join-Path $ProjectRoot "backend") --host 127.0.0.1 --port 8000 --reload
