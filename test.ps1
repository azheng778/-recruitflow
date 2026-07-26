$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "agent\Scripts\python.exe"
$Backend = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing agent Python environment: $Python"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing .env. Copy .env.example to .env and configure MySQL credentials."
}

$EnvContent = Get-Content -LiteralPath $EnvFile
$FileDbUser = (($EnvContent | Where-Object { $_ -match '^DB_USERNAME=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
$FileDbPassword = (($EnvContent | Where-Object { $_ -match '^DB_PASSWORD=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
$FileTestDb = (($EnvContent | Where-Object { $_ -match '^TEST_DB_NAME=' } | Select-Object -First 1) -split '=', 2)[1].Trim()
$DbUser = if ($env:DB_USERNAME) { $env:DB_USERNAME } else { $FileDbUser }
$DbPassword = if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { $FileDbPassword }
$TestDb = if ($env:TEST_DB_NAME) { $env:TEST_DB_NAME } else { $FileTestDb }

if (-not $DbUser -or $DbUser -eq "recruitflow_app" -or -not $DbPassword -or $DbPassword -match "replace|your") {
    throw "Database credentials are placeholders. Configure DB_USERNAME and DB_PASSWORD in .env."
}
if (-not $TestDb -or $TestDb -eq "langchain_db") {
    throw "TEST_DB_NAME must be an independent test database, such as hr_recruitment_test."
}

$env:APP_ENV = "test"
$env:DB_NAME = $TestDb
$env:TEST_DB_NAME = $TestDb
$env:DB_USERNAME = $DbUser
$env:DB_PASSWORD = $DbPassword
$env:PYTHONPATH = $Backend
# Unit and API tests use deterministic local routing and do not consume LLM quota.
$env:LLM_API_KEY = "replace-me"
$env:DEEPSEEK_API_KEY = "replace-me"
$env:RESPONSE_LLM_ENABLED = "false"

& $Python (Join-Path $Backend "scripts\reset_test_database.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m alembic -c (Join-Path $Backend "alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $Backend "scripts\seed.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest (Join-Path $Backend "tests") -q
exit $LASTEXITCODE
