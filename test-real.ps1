$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "agent\Scripts\python.exe"
$Backend = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing agent Python environment: $Python"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing .env. Configure real MySQL and LLM credentials first."
}

$EnvContent = Get-Content -LiteralPath $EnvFile
function Get-EnvFileValue([string]$Name) {
    $Line = $EnvContent | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if (-not $Line) { return "" }
    return (($Line -split '=', 2)[1]).Trim()
}

$DbUser = Get-EnvFileValue "DB_USERNAME"
$DbPassword = Get-EnvFileValue "DB_PASSWORD"
$TestDb = Get-EnvFileValue "TEST_DB_NAME"
$LlmKey = Get-EnvFileValue "LLM_API_KEY"

if (-not $DbUser -or $DbUser -eq "recruitflow_app" -or -not $DbPassword -or $DbPassword -match "replace|your") {
    throw "Configure real DB_USERNAME and DB_PASSWORD values in .env."
}
if (-not $LlmKey -or $LlmKey -match "replace|your-api-key") {
    throw "Configure a real LLM_API_KEY in .env."
}
if (-not $TestDb -or $TestDb -eq "langchain_db" -or $TestDb -eq (Get-EnvFileValue "DB_NAME")) {
    throw "TEST_DB_NAME must be independent from the development database and langchain_db."
}

$env:APP_ENV = "test"
$env:DB_NAME = $TestDb
$env:TEST_DB_NAME = $TestDb
$env:PYTHONPATH = $Backend
$env:RUN_REAL_LLM_TESTS = "1"
$env:AGENT_LLM_ROUTER_ENABLED = "true"

& $Python -m alembic -c (Join-Path $Backend "alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $Backend "scripts\seed.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest (Join-Path $Backend "tests\test_real_integration.py") -q -s
exit $LASTEXITCODE
