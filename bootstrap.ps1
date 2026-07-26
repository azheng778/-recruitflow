$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "agent\Scripts\python.exe"
$Backend = Join-Path $ProjectRoot "backend"

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $ProjectRoot ".env")
    throw "Created .env. Configure DB_PASSWORD, SECRET_KEY, and optional LLM_API_KEY, then run again."
}

$EnvContent = Get-Content -LiteralPath (Join-Path $ProjectRoot ".env")
$DbUser = (($EnvContent | Where-Object { $_ -match '^DB_USERNAME=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
$DbPassword = (($EnvContent | Where-Object { $_ -match '^DB_PASSWORD=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
if (-not $DbUser -or $DbUser -eq "recruitflow_app" -or -not $DbPassword -or $DbPassword -match "replace|your") {
    throw "DB_USERNAME and DB_PASSWORD in .env must contain valid MySQL credentials."
}

$env:PYTHONPATH = $Backend
& $Python -m pip install -r (Join-Path $Backend "requirements.txt")
& $Python (Join-Path $Backend "scripts\create_databases.py")
& $Python -m alembic -c (Join-Path $Backend "alembic.ini") upgrade head
& $Python (Join-Path $Backend "scripts\seed.py")
Write-Host "RecruitFlow initialized. Run .\run.ps1 and open http://127.0.0.1:8000"
