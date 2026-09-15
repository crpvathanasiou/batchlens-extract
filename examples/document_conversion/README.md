# Runnable examples

Run from the project root after `poetry install` (Python 3.11).

Offline; no AWS access or credentials:

```powershell
poetry run python -m app.document_conversion offline examples/document_conversion/synthetic-table.json --output out/table
poetry run python -m app.document_conversion offline examples/document_conversion/synthetic-layout.json --output out/layout --page-workers 2
```

Open `out/table/document.html` and inspect the 12 ordered rows, merged header and empty row-3/column-2 cell. `out/layout/document.html` contains two numerically ordered pages, a nested list, selection marker, inert script-looking text and an explicit figure limitation. These fixtures are synthetic, not OCR-quality evidence.

The following cloud commands upload/process a PDF and can incur charges. Run them only with an explicitly approved non-confidential sample and configured resources. The region and bucket must match. Use `AWS_PROFILE` from the operator guide.

```powershell
poetry run python -m app.document_conversion submit --region eu-west-1 --bucket YOUR_PRIVATE_VERSIONED_BUCKET --prefix documents/cli --pdf C:/samples/approved.pdf --handle out/approved-handle.json
poetry run python -m app.document_conversion resume --handle out/approved-handle.json --output out/approved --timeout-seconds 300
```

For an existing caller-owned S3 object:

```powershell
poetry run python -m app.document_conversion submit --region eu-west-1 --bucket YOUR_PRIVATE_BUCKET --key incoming/approved.pdf --version YOUR_VERSION_ID --request-token YOUR_UNIQUE_TOKEN --handle out/existing-handle.json
poetry run python -m app.document_conversion resume --handle out/existing-handle.json --output out/existing
```

`--version` is optional in the standalone adapter; without it an existing mutable key is **not** immutable document identity. Deployed API jobs require bucket versioning and pin the accepted version. The CLI's handle is written atomically before submission (as an intent), then updated with the provider ID. Resume reuses the same request token after an interrupted submit. Do not reuse a token for different source/configuration parameters. Handles older than six days are refused for automatic resume; AWS token/result retention is finite.

Optional local staging encryption: add `--kms-key-id YOUR_KMS_KEY_ARN`. The operator must configure the key's IAM/key policy permissions for their identity and Textract path. The deployed development stack uses explicit S3-managed AES256 encryption; no custom KMS protection is claimed.

CLI SDK calls block the calling process. Polling has a deadline between requests, each SDK request has bounded retries/timeouts, and collection has block/byte limits. A deadline leaves the saved handle for another `resume`; it does not cancel the AWS job. Output files only use the explicitly supplied directory; no source file or object is deleted. Existing named outputs in that directory are replaced, so use a dedicated directory per job. Protect the handle and output files as document metadata/content.

The direct CLI does not create application DynamoDB jobs and does not participate in the deployed worker's global capacity slots. Use the authenticated UI/API for the deployed acceptance tests and control any separate CLI load when setting account quotas.
