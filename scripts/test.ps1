Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
