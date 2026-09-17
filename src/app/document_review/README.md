# Document review

This package implements optional human review after a document conversion reaches
`SUCCEEDED` or `PARTIAL_SUCCESS`. Conversion status and artifacts remain unchanged and available
as original, unreviewed outputs. Review approval is document-review approval only; it is not batch
release, regulatory release, or a 21 CFR Part 11 electronic signature.

## Canonical revision

`ReviewRevision` schema `1.0.0` is the authoritative reviewed record. Its `.document` field is the
existing validated `document_conversion.contracts.Document`; consumers of reviewed JSON must
explicitly select a committed approved revision and read `.document`. TipTap JSON is only a browser
projection and is never persisted as an independent truth.

The server derives immutable node IDs from the exact baseline `document.json` key/version,
physical page, and structural path. Clients submit sparse `{node_id, text}` changes. The server
resolves those IDs through its catalogue and preserves structure, selections, references,
confidence, warnings, table geometry, children, titles, and footers.

Canonical lowercase `title` and `section_heading` kinds are projected as fixed heading levels 2
and 3. Table-title `TITLE` nodes and ordinary text remain non-heading regions. Suggested
tolerance replacements are applied by the guarded backend operation; the browser must not also
send the same node in `changes`.

Every committed action writes a UUID-addressed immutable S3 revision beneath:

`documents/results/{job_id}/review/revisions/{revision_id}/`

The existing DynamoDB table stores only `review#{job_id}`, a small authoritative head containing
the current revision artifact, generation, owner, baseline/source identity, expiry, and current
approval/export pointers. Publishing uses a conditional expected-revision/generation update. A
losing candidate remains unreachable and expires under the existing lifecycle; callers receive
`409 REVIEW_CONFLICT`.

Actor and timestamps come from the verified Cognito `sub` and server clock. Page approvals bind to
server-computed page hashes. Editing a page invalidates only that page and document approval;
finding decisions bind to the reviewed region hash. Historical approved revisions and exports
remain reachable through trusted parent artifact pointers for the existing retention period.

## API

All routes first apply the existing ownership-hiding job check:

- `GET /api/v1/documents/jobs/{job_id}/source`
- `GET|PUT /api/v1/documents/jobs/{job_id}/review`
- `POST /api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve`
- `POST /api/v1/documents/jobs/{job_id}/review/approve`
- `GET /api/v1/documents/jobs/{job_id}/review/revisions/{revision_id}/exports/{format}`

An untouched GET returns transient `NOT_REVIEWED` state and performs no write. Final approval
requires all verified physical pages to be approved and every finding to have a current explicit
decision. Approved HTML is deterministic escaped server markup. Approved JSON is a review
envelope; it is not valid as a bare `Document`.

## Local acceptance harness

`tests.document_review.local_harness` composes this package and these real API routes with only a
fixed test identity (`local-test-reviewer`), synthetic job `local-fexofenadine`, and file-backed
storage. It binds to `127.0.0.1`. Generated state defaults to `.local-review-data/fexofenadine/`,
survives process restart, and is excluded from production composition and images. Supplied
original PDF, `document.json`, `textract.json`, and `document.html` are not modified. It does not
prove Cognito verification, DynamoDB conditional writes, or S3 versioning. Those boundaries
require separate stub or live evidence.
