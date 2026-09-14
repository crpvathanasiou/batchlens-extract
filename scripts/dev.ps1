Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
