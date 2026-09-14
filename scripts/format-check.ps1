Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
