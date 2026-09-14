Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
