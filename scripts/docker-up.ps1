Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

docker compose up --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
