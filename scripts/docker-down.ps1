Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

docker compose down
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
