# Document conversion reference slice

Converts complete Textract analysis JSON to typed evidence-bearing document data and semantic HTML. Adds one optional asynchronous document feature to the supplied BatchLens FastAPI template: authenticated direct S3 upload, durable jobs, SQS worker, status and versioned downloads.

This is document preparation, not recipe extraction, compliance classification, audit approval or a trained model. TABLES + LAYOUT is the implemented reference path. No representative PDFs, saved real Textract results or authorized alternative provider were supplied, so a multimodal-model comparison was **not run**. Before investing in further converter complexity, compare both approaches on the same approved pages for numbers/tables, omissions, evidence links, cost and reviewer effort. Final recipe extraction requires a separate common downstream task and reference output.

## Public Python operations

| Operation | Input → output | Execution |
|---|---|---|
| `convert_textract(response, source, limits=None)` | Complete saved provider JSON + `Source` → `Document` | Pure, deterministic; no network/credentials |
| `render_page(page)` | `Page` → complete HTML | Synchronous CPU |
| `render_pages(document, page_workers=1)` | `Document` → numerically ordered `{page_number: html}` | Sequential by default; bounded spawned process pool when >1 |
| `render_document(document)` | `Document` → single complete HTML | Synchronous CPU |
| `TextractAdapter.submit(source, request_token)` | `S3Source` → `JobHandle` | Blocking SDK request returning an asynchronous document job handle |
| `TextractAdapter.check(handle)` | Handle → `JobCheck` | One blocking SDK request; status and reported page count |
| `TextractAdapter.collect(handle, heartbeat=None)` | Completed handle → `Collected.raw` | All continuation batches, block/byte limits, explicit partial/failure handling |
| `TextractAdapter.wait_collect(handle, timeout_seconds=300, ...)` | Handle → collected response or `WaitTimeout(handle)` | Bounded blocking polling for CLI/worker only |
| `stage_pdf(client, path, bucket, prefix, region, encryption='AES256', ...)` | Local PDF → `S3Source` | Streaming upload to a unique key, SHA256, returned object version |

Pure imports:

```python
from app.document_conversion import Source, convert_textract, render_document

document = convert_textract(saved_json, Source(identity="approved-saved-response"))
html = render_document(document)
```

Cloud-specific imports are explicit from `app.document_conversion.aws`. Clients are injected or created through `document_jobs.composition.build_service` during FastAPI lifespan / worker main. Importing the pure package never constructs a client, reads credentials or performs network I/O. Boto3 uses the normal AWS credential chain; API SDK routes are normal `def` functions and execute in FastAPI's thread pool. The request never runs OCR polling/conversion itself.

## Representation and normalization

`Document` includes source identity/version/checksum when available, schema and converter versions, provider model version, partial status, warnings, numeric pages and semantic elements. Every emitted element/cell has references with original block IDs, available page/box/polygon/rotation/confidence. Source numeric strings and units are preserved as extracted; no measurement normalization or inferred pharmaceutical values.

The global block index and table ownership are built before layout projection. Ownership uses IDs, never equal text. Supported relationships are followed by type, including nested lists, words, selection elements and merged-cell members. Table rows/columns are numeric; merged headers retain spans; empty source cells retain position; missing grid positions become explicit inferred-empty cells with a warning and table provenance. Overlapping ambiguous spans and invalid coordinates fail explicitly. Table titles/footers remain associated, and captions sharing the same source words as a cell do not duplicate that content. Tables on different pages remain separate.

Textract layout blocks retain their declared array reading order (relative to other layout blocks); nested layout children retain relationship order. Unrelated provider block order does not affect table order/ownership. With no usable layout, the fallback sorts top/left/ID and warns that it is not reliable multi-column reading order. Unplaced tables or orphan content are appended with warnings, not quietly dropped. Page identity can propagate down supported relationships or be inferred from consistently assigned children; unresolved IDs remain explicit warnings and in the raw response, not a fabricated page zero. Cross-page content is not moved into the parent page.

Figures, signatures and unsupported regions retain type/location and an explicit interpretation limitation. OCR confidence is evidence, not a calibrated correctness probability. The renderer escapes source text/attributes, emits script-free HTML with no external resources and stable page/element/cell anchors. Geometry stays in JSON. HTML is readable, not a pixel-perfect PDF reproduction. It supplies page/element/cell boundaries, not a word-count token-budget guarantee. No Markdown renderer, cross-page table joining or token-aware table splitting is implemented.

Deterministic claims apply to identical complete saved input/configuration and this converter version, not fresh OCR runs. Operational job timestamps/handles remain outside the normalized document. `Collected.raw` and the `textract.json` artifact retain provider data once for later reprocessing; raw data is not embedded in each page.

## Job flow and security

`UPLOADING → QUEUED → SUBMITTING → OCR → COLLECTING → RENDERING → SUCCEEDED | PARTIAL_SUCCESS`, with explicit FAILED paths. Partial output stays partial even when rendering succeeds. Converted warnings remain in document JSON and are visible in downloaded HTML, including for SUCCEEDED results. Full-document HTML lists every warning's code, page references and available block references. Page HTML includes warnings for that page and explicitly labeled document-level warnings without a page assignment; partial document status remains visible. The job UI shows partial results and a persisted warning count, with details in document.html. Existing job records without the count default to zero; historical artifacts/counts are not backfilled. No recorded warnings is not evidence of accuracy or human approval.

- `POST /api/v1/documents/uploads`: authenticated initiation, server-generated job/key and bounded S3 POST grant.
- `POST /api/v1/documents/jobs/{id}/start`: ownership + uploaded object verification, version pinning, persisted acceptance; returns 202 promptly.
- `GET /api/v1/documents/jobs` and `GET .../{id}`: owner-filtered recent jobs and status; no fictional OCR percentage.
- `POST .../{id}/retry`: explicit bounded recovery using the existing source, request token and available handle; old handles are refused.
- `GET .../{id}/artifacts/{name}`: owner check and a 60-second, version-bound attachment URL.
- `/documents`: file-picker/drag-and-drop, sign-in, multi-job status and downloads. No document HTML enters its DOM.

Versioned S3, DynamoDB conditional updates/renewable worker leases, durable capacity slots, SQS and a due-state/failure outbox sweep implement at-least-once recovery. Queue writes and database writes are **not atomic**: durable sweeps repair missed enqueue/failure notifications. Duplicate delivery is tolerated; exactly-once execution is not claimed. Unknown OCR submission outcome retains a slot rather than oversubscribing possibly active provider jobs. The worker does not sleep indefinitely while waiting for one PDF; it persists a next-due time and processes other jobs.

Authentication is Cognito JWT verification for approved test users, not a trusted caller owner-ID. Presigned upload replay cannot change a version already accepted by `/start`. Download grants remain bearer capabilities until their short expiry. Logout does not immediately invalidate previously issued JWTs. IAM roles and resource encryption are defined by IaC; deployment security is unverified until tested. No malware scanning, enterprise tenancy, SSO, revocation introspection, WAF or regulated-compliance claim is included.

## Limits and dependencies

Runtime additions: `boto3` and `PyJWT[crypto]`. Dev addition: selected `boto3-stubs` service types. Poetry regenerated the supplied lock; existing locked package versions were preserved. The optional `src/app/llm/` wrapper remains unwired and byte-for-byte unchanged.

Default job limits: 25 MiB PDF, 100,000 blocks, 64 MiB collected JSON, 200 pages; 2 durable OCR slots, 2 job threads/task, 1 page-render process/job. Complete provider blocks must fit worker memory before normalization. Raising limits requires measuring worst-case memory; it is not streaming normalization. The API never loads full PDFs. The development DynamoDB scans are appropriate for a small test environment, not a large multi-tenant backlog. No queue admission budget, per-user rate limiter or hard monthly spend cap is implemented; only approved users should have access.

See [AWS setup/run/teardown](../../../infra/document_conversion/AWS_SETUP.md) for exact settings, quotas, concurrency semantics, durable failure windows, networking/cost choices and PowerShell commands. See [runnable examples](../../../examples/document_conversion/README.md) for offline and local-PDF/existing-S3 submit/resume paths. See the root `VERIFICATION.md` for performed versus unperformed checks.

## Integration

The delivery is a complete **integrated snapshot of your attached template**, not a replacement framework. Extract it into a separate review directory; do not blindly overwrite a newer working tree. `INTEGRATION.patch` records changes relative to the supplied source archive; inspect/apply it only against a compatible baseline after preserving local edits. Existing manifests/lock files may contain newer changes, so integrate required dependencies through Poetry rather than overwriting them.

For a newer checkout, add/copy the feature paths and tests/examples/infra, merge the small changes in `src/app/main.py`, `src/app/settings.py`, Dockerfile, ignore/env files and documentation, and add the dependencies:

```powershell
poetry add 'boto3>=1.40,<2' 'PyJWT[crypto]>=2.10,<3'
poetry add --group dev 'boto3-stubs[s3,textract,sqs,dynamodb]>=1.40,<2'
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest
```

For the supplied snapshot itself, `poetry env use 3.11` and `poetry install` suffice. Feature-off system endpoint behavior stays the same. Feature enablement requires all deployed settings and occurs during lifespan, never module import. `.ai/` additions record this specific authorized conversion slice without choosing the later recipe/graph architecture.

## Official contract references

Checked for this implementation: [StartDocumentAnalysis](https://docs.aws.amazon.com/textract/latest/APIReference/API_StartDocumentAnalysis.html), [GetDocumentAnalysis](https://docs.aws.amazon.com/textract/latest/APIReference/API_GetDocumentAnalysis.html), [tables and merged cells](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-tables.html), [layout response order](https://docs.aws.amazon.com/textract/latest/dg/layoutresponse.html), [S3 source versions](https://docs.aws.amazon.com/textract/latest/APIReference/API_S3Object.html), [Cognito access-token claims](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html). AWS token idempotency/result lifetime is finite; preserve handles and recover promptly.
