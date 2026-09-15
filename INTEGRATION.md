# Integrating this delivery

This ZIP is the supplied BatchLens project with the authorized document feature integrated. It is not a different application scaffold. Preserve your actual checkout and unpack into a separate review directory first.

```powershell
Expand-Archive .\batchlens-extract.zip -DestinationPath .\batchlens-review
Set-Location .\batchlens-review\batchlens-extract
poetry env use 3.11
poetry install
poetry run python -m app.document_conversion offline examples/document_conversion/synthetic-table.json --output out/table
```

Start with `src/app/document_conversion/README.md`, then `infra/document_conversion/AWS_SETUP.md`. The latter includes exact Windows commands for the missing Docker/live deployment gates. `VERIFICATION.md` records what actually ran.

`INTEGRATION.patch` contains text changes relative to the uploaded source archive, including added files. It does not include itself. From a compatible **clean destination checkout** (after preserving your own working-tree edits), review it and use:

```powershell
git status --short
git apply --stat C:/PATH/TO/batchlens-review/batchlens-extract/INTEGRATION.patch
git apply --check C:/PATH/TO/batchlens-review/batchlens-extract/INTEGRATION.patch
```

If the check succeeds and you have reviewed the exact changes, apply it:

```powershell
git apply C:/PATH/TO/batchlens-review/batchlens-extract/INTEGRATION.patch
```

If your manifests or source have changed, do not force the patch or overwrite the checkout. Merge the feature paths and the small composition/settings/Docker/documentation changes deliberately. Add runtime `boto3` and `PyJWT[crypto]`, and dev `boto3-stubs[s3,textract,sqs,dynamodb]` through Poetry as shown in the component README; regenerate your own lock normally. Original locked versions in this snapshot were preserved.

New main paths are `src/app/document_conversion/`, `src/app/document_jobs/`, `src/app/api/documents.py`, `tests/document_conversion/`, `examples/document_conversion/` and `infra/document_conversion/`. `tests/__init__.py` makes shared fixture imports explicit. The optional offline verification helper is under `scripts/`. The existing LLM wrapper and its tests are unchanged. `.ai/` changes describe only the authorized preparation slice and its actual evidence.

Finally run your existing Ruff, format, strict Pyright and pytest quality gate; build and smoke-test the image before deploying. Do not treat the local test report as cloud acceptance or fidelity against your PDFs.
