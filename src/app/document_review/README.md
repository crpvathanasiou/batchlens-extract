# Document review

This package implements optional human review after a document conversion reaches
`SUCCEEDED` or `PARTIAL_SUCCESS`. Conversion status and artifacts remain unchanged and available
as original, unreviewed outputs. Review approval is document-review approval only; it is not batch
release, regulatory release, or a 21 CFR Part 11 electronic signature.

## Canonical revision

`ReviewRevision` envelopes use schema `1.1.0`. Existing `1.0.0` artifacts remain readable and
unchanged. The `.document` field is the existing validated
`document_conversion.contracts.Document`; consumers of reviewed JSON must
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
losing CAS candidate remains unreachable and expires under the existing lifecycle. Callers
receive `409 REVIEW_CONFLICT` unless A1 Save reconciliation finds a matching committed
operation and replays it. New envelopes use schema `1.1.0`; unchanged legacy `1.0.0`
revisions remain readable.

Actor and timestamps come from the verified Cognito `sub` and server clock. Page approvals bind to
server-computed page hashes. Editing a page invalidates only that page and document approval;
finding decisions bind to the reviewed region hash. Historical approved revisions and exports
remain reachable through trusted parent artifact pointers for the existing retention period.

## API

All routes first apply the existing ownership-hiding job check:

- `GET /api/v1/documents/jobs/{job_id}/source`
- `GET /api/v1/documents/jobs/{job_id}/review/context`
- `GET /api/v1/documents/jobs/{job_id}/review/operations/{operation_id}`
- `GET|PUT /api/v1/documents/jobs/{job_id}/review`
- `POST /api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve`
- `POST /api/v1/documents/jobs/{job_id}/review/approve`
- `GET /api/v1/documents/jobs/{job_id}/review/revisions/{revision_id}/exports/{format}`

An untouched GET returns transient `NOT_REVIEWED` state and performs no write. Final approval
requires all verified physical pages to be approved and every finding to have a current explicit
decision. Approved HTML is deterministic escaped server markup. Approved JSON is a review
envelope; it is not valid as a bare `Document`.

Reviewed HTML attribute contract version 1 is non-visible markup for a later lexical reader.
The root `<html>` element carries `data-review-html-version="1"`, `data-job-id`,
`data-review-revision-id`, `data-review-generation`, and `data-conversion-status` from the
rendered revision. Catalogue node IDs, resolved by physical page and structural path, appear as
`data-element-id` on each element article, `data-node-id` on that element's rendered text and on
each title, cell, and footer, and `data-table-id` on each `<table>`. `data-source-id` is the
ordered, de-duplicated block IDs of that node's own references, and is omitted when the node has
none. `data-generated="true"` marks the summary header, the partial-conversion banner, and each
`Page N` heading. Previously approved export bytes stay unchanged. These attributes are not proof
of authenticity or regulatory compliance; source references identify original OCR blocks, while
the visible text may include reviewed corrections.

`PUT /review` remains a top-level `ReviewState`. Optional `operation_id` and optional
`X-Review-Context` are accepted for compatibility; omitted/null operation IDs keep A1
behaviour. When the header is present it must match the server's freshly derived authorized
context or the request fails with `409 REVIEW_CONTEXT_CHANGED` before mutation. Context and
lookup responses use no-store semantics. Lookup requires the header, reuses
`reconcile_save_operation`, and never publishes revisions. `GET /review/context` does not
read review history.

Browser Save recovery (A2) stores one sparse pending record in sessionStorage, scoped by
backend origin/API root and server `context_id`. Recovery is same-tab/session only. The
browser reserves a Save before its first await, binds later outcomes to that operation and
revalidated context, and treats a current-key unreadable or identity-mismatched record as
corrupt recovery data rather than as an ignorable foreign record. The pending record is
not deleted on error, conflict, reload, logout, or unmount; retirement requires a
confirmed exact PUT after valid state application and successful matching-record cleanup,
or an explicit user acknowledgement after a proven superseded, mismatch, or first-attempt
validation rejection. A successful commit whose local cleanup then fails remains a
committed Save with a local recovery problem, not an unsent draft. The recovery panel
shows attempted text changes and finding decisions until permitted disposition. Terminal
recovery paths revalidate authorized context after lookup or state GET before applying
state, granting discard, or removing the matching record. Uncertainty is kept in the live
workspace even when recovery metadata cannot be persisted; a later 422 cannot prove that
an earlier unknown request failed. Lookup evidence must be internally coherent before it
can prove UNRESOLVED, superseded, or COMMITTED.

## Local acceptance harness

`tests.document_review.local_harness` composes this package and these real API routes with only a
fixed test identity (`local-test-reviewer`), synthetic job `local-fexofenadine`, and file-backed
storage. It binds to `127.0.0.1`. Generated state defaults to `.local-review-data/fexofenadine/`,
survives process restart, and is excluded from production composition and images. Each writable
data directory also holds `review-context.json` (schema version plus a generated UUID v4 storage
ID) created once after input/manifest validation and reused across restarts. Distinct newly
initialized directories receive different IDs even with identical inputs. A full restored copy
retains identity; independently writable clones must be initialized separately before use.
Invalid existing sidecars are not replaced. Read-only/`initialize_manifest=False` paths do not
write the sidecar. Supplied original PDF, `document.json`, `textract.json`, and `document.html`
are not modified. It does not prove Cognito verification, DynamoDB conditional writes, or S3
versioning. Those boundaries require separate stub or live evidence.
