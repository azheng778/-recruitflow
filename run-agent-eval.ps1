$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "agent\Scripts\python.exe"
$Backend = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $Python)) { throw "Missing agent Python environment: $Python" }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "Missing .env" }
$Lines = Get-Content -LiteralPath $EnvFile
function EnvValue([string]$Name) { $Line=$Lines|Where-Object{$_ -match "^$Name="}|Select-Object -First 1; if($Line){return (($Line -split '=',2)[1]).Trim()}; return "" }
$TestDb=EnvValue "TEST_DB_NAME"; $DevDb=EnvValue "DB_NAME"; $Key=EnvValue "LLM_API_KEY"
if($TestDb -ne "hr_recruitment_test" -or $TestDb -eq $DevDb -or $TestDb -eq "langchain_db"){throw "Unsafe TEST_DB_NAME"}
if(-not $Key -or $Key -match "replace|your-api-key"){throw "A real LLM_API_KEY is required"}
$env:APP_ENV="test"; $env:DB_NAME=$TestDb; $env:TEST_DB_NAME=$TestDb; $env:PYTHONPATH=$Backend; $env:RUN_REAL_LLM_TESTS="1"; $env:AGENT_LLM_ROUTER_ENABLED="true"
& $Python (Join-Path $Backend "scripts\run_agent_eval.py") --real-llm --reset-db @args
exit $LASTEXITCODE
