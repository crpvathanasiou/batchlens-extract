Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run ruff format .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
