Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
