Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

poetry run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

poetry run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

poetry run pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

poetry run pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
