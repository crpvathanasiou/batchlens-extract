# BatchLens — Stage 1: Detailed Design and Local Execution Guide

This guide explains two separate local capabilities that are implemented in this repository. Path A converts a saved recognition response into canonical JSON and unreviewed HTML. Path B reviews an existing compatible artifact set: correct text, decide findings, approve pages, and export one approved revision. A review of the Path B sample does not show that the files just produced by Path A can be reviewed. It complements the short introduction in `docs/BatchLens-Stage1-Overview-EN.md`. Commands below are for later execution. They were not run while this document was written.

## 1. Scope and current status

Stage 1 prepares a pharmaceutical manufacturing PDF so a person can correct recognized text and approve that reviewed revision. The local path starts from files already on disk and ends when Approve & Export has written that revision’s reviewed HTML and reviewed JSON. Lexical matching, extraction review, and later recipe use are outside this stage. Section 9 only names the HTML file those later readers consume.

Two local capabilities stay separate:

| Entry | What you supply | What this path does |
|---|---|---|
| A. Standalone offline conversion | One complete saved recognition response | The offline converter writes canonical JSON and unreviewed HTML. The new canonical file records only `source.identity`. The current harness does not accept that file. |
| B. Local review of an existing compatible set | The PDF, a canonical `document.json` that already meets the harness source checks, the original recognition response, and the original `document.html` | Open review, save, approve, and export. This does not exercise the files written by Path A. |

Current integration limitation: the offline CLI and the review harness do not share one source-metadata contract. Path A does not fill `source.bucket`, `source.key`, `source.version`, or `source.checksum_sha256`. Path B starts only when those harness checks already pass. This guide does not define new metadata and does not describe a way to edit a canonical file so the harness will open it.

The harness does not recognize a PDF. A PDF alone is not a Stage 1 input. Recognition must already have been saved as JSON. The Path B sample inspected for this guide is `manual-input/source.pdf`, the saved response `out/comparison/fexofenadine-textractor-20260916-173938/textract.json`, and the canonical pair under `out/comparison/fexofenadine-local-current/`. That canonical document is status `SUCCEEDED`, 18 pages, with two `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` warnings on page 5 and nineteen `UNINTERPRETED_LAYOUT_FIGURE` warnings. Its `source.checksum_sha256` is exactly the SHA-256 of that PDF. Those facts come from reading the files, not from starting the harness, and not from running Path A.

Document-review approval records that this reviewer accepted the reviewed content of one revision. It is not manufacturing batch release, regulatory approval, or a 21 CFR Part 11 electronic signature. It does not approve downstream extraction.

Evidence labels for this stage:

| Label | What it covers here |
|---|---|
| Implemented | Offline conversion, the review service, the Vue editor, and the local file harness are in the repository. |
| Test-verified | Historical automated gates recorded in `.ai/03_common_handoff.md`, including save replay, history projection, `history.jsonl` materialisation, and local history rebuild. Those tests were not re-run for this document. |
| Manually verified | A person has confirmed, on the local harness, side-by-side PDF and text, editing, save and reload, findings, page approval, loss of approval after a later edit, blocked export while work remains, and downloads that contain a correction. Same-tab recovery after a lost save response was accepted on a separate local run. |
| Unverified for this task | Every command in section 7. Local history rebuild has no recorded manual acceptance. The Findings scope default **This page** is test-verified and has no recorded manual acceptance. Reviewed-HTML marker attributes are test-verified and have no recorded manual browser check. |

The local harness is the review application with a fixed test identity and files under a data directory you choose. Supplied PDF, recognition JSON, canonical JSON, and original HTML are read-only inputs.

## 2. Components and responsibilities

```text
Path A — standalone offline conversion
saved recognition JSON
  → offline converter (Textractor 1.10.0, single-threaded)
  → document.json + document.html + page-NNNN.html
  → stop. That new document.json is not a harness input.

Path B — local review of an existing compatible set
PDF + compatible document.json + recognition JSON + original document.html
  → local harness (identity and file store only)
  → review service + browser editor
  → immutable revision envelopes + head.json
  → derived history.jsonl
  → approved HTML and JSON for one revision
```

| Component | Role on this path | Principal path |
|---|---|---|
| Offline converter | Reads one complete recognition JSON and writes canonical JSON, full HTML, and per-page HTML. No network and no second copy of the raw response. | `src/app/document_conversion/__main__.py`, `adapter.py`, `provider.py`, `textractor_renderer.py`, `tolerance.py`, `contracts.py` |
| Canonical document | Pages, reading order, text, tables, geometry, block references, and warnings. Schema `1.0.0`. This is the unreviewed baseline. | `document.json` from conversion |
| Review service | Validates text-only saves, finding decisions, page approval, and final approval. Renders reviewed HTML. | `src/app/document_review/service.py`, `mapping.py`, `operations.py`, `rendering.py`, `contracts.py` |
| HTTP routes | Review read/update, context, save lookup, page approval, final approval, export URL, and PDF bytes. | `src/app/api/document_reviews.py` |
| Browser editor | TipTap projection of one page, PDF.js pane, findings, pending-save recovery. | `frontend/src/` and `frontend/src/components/ReviewWorkspace.vue`, `DocumentEditor.vue`, `FindingsPanel.vue`, `PdfPane.vue` |
| Local harness | Binds `127.0.0.1`, serves the built Vue bundle, and substitutes identity plus the file store. | `tests/document_review/local_harness.py` |
| Local file store | Atomic `head.json`, immutable revision files, input manifest, storage-id sidecar, download tokens, derived history rebuild. | `tests/document_review/local_store.py` |
| History projection | Fail-closed read of the published revision chain, then one replaceable `history.jsonl`. | `src/app/document_review/history.py`, `history_jsonl.py` |

The harness does not start a conversion worker. `LocalJobs` and `LocalHeads` are local stand-ins that expose the same review-service ports over the files in `--data-dir`. The fixed job id is `local-fexofenadine`. The fixed reviewer is `local-test-reviewer`. The browser sends `Authorization: Bearer local-review-token`. The on-screen label is `Local demo · test reviewer`.

Job and artifact objects in `src/app/document_jobs/contracts.py` are the shapes the service already expects. On this path the harness fills them from the four input files. `Job.phase` is the canonical document status, `SUCCEEDED` or `PARTIAL_SUCCESS`.

## 3. Inputs, outputs, and persisted data

### Artifact table

| Artifact | Producer | Consumer | Purpose | Original or reviewed | When it is written |
|---|---|---|---|---|---|
| Source PDF | Already on disk | Harness PDF pane via `GET .../source` | Page image beside the text | Original | Never by this path |
| Saved recognition JSON (`textract.json` in the sample) | Already on disk | Offline converter; harness as `--textract` | Complete recognition response the converter and finding page lookup read | Original | Never by the offline converter’s output directory |
| `document.json` | Offline converter, or an older compatible file already on disk | Inspection after Path A. The harness `--document` input only when the file already satisfies the source checks below | Canonical unreviewed document | Original | Path A writes a new file. Path B reads a pre-existing compatible file |
| `document.html` | Offline converter, or already on disk | Harness as `--html` | Unreviewed reading view kept as an input artifact | Original | Conversion, before review |
| `page-NNNN.html` | Offline converter | Inspection only | One unreviewed HTML file per page | Original | Conversion. The harness does not read these files |
| `manifest.json` | Local store | Next harness start on that data directory | Absolute paths and SHA-256 of the four inputs, plus job id and owner | Review bookkeeping | First successful store init |
| `review-context.json` | Local store | Review context id | `schema_version` 1 and a UUID v4 `storage_id` | Review bookkeeping | First init of that data directory |
| `head.json` | Local store `publish` | Review service | Small pointer: revision id, generation, status, approval, export pointers. No document body | Authoritative reviewed pointer | Each committed save, page approval, or document approval |
| `objects/local-fexofenadine/revisions/<uuid>/review.json` | Local store | Head, history rebuild, export lookup | Immutable revision envelope. `document` inside it is the reviewed canonical document | Reviewed | Before the head is published |
| Browser TipTap draft | Editor | Save request only | In-memory page projection and unsaved text | Editing projection | Not persisted |
| Pending-save record | Browser `sessionStorage` | Same tab after an uncertain save | Frozen Save body, operation id, context id | Recovery aid | When a Save is submitted. Removed only after a confirmed commit and cleanup, or an explicit terminal disposition |
| `history.jsonl` | Local store after a published head | Operators reading the file; startup status line | Derived projection of the committed chain | Derived | After head publish, and on startup when missing, invalid, or stale |
| `downloads.json` | Local store | Download route | Opaque tokens for immutable artifacts | Review bookkeeping | First download of an artifact |
| `objects/.../exports/document.html` | `ReviewService.approve` | Download; Stage 2 reader | Reviewed HTML for that revision | Reviewed export | During final approval, before the final envelope is published |
| `objects/.../exports/document.json` | `ReviewService.approve` | Download | JSON snapshot of the approved candidate envelope | Reviewed export | Same approval, after the HTML file and before the final envelope |

The browser projection and the pending-save record are not the authoritative reviewed document. Authority is `head.json` plus the revision envelope it names. Unsaved editor text disappears when the tab closes. A pending-save record survives reload of the same tab only while `sessionStorage` still holds it.

### Directory layout

Conversion output (Path A), relative to the repository root:

```text
<conversion-output>/
  document.json
  document.html
  page-0001.html
  ...
```

That directory does not receive a new `textract.json`. Those Path A files are not the four inputs of the review harness.

Review data directory (created by the harness):

```text
<review-data-dir>/
  manifest.json
  review-context.json
  head.json
  downloads.json
  history.jsonl
  objects/local-fexofenadine/revisions/<revision-id>/review.json
  objects/local-fexofenadine/revisions/<revision-id>/exports/document.html
  objects/local-fexofenadine/revisions/<revision-id>/exports/document.json
```

`.local-review-data/` is gitignored. Use one new directory for a new review. The harness refuses a data directory that contains an input file or sits inside an input file’s directory (`DATA_DIR_OVERLAPS_INPUT`, `DATA_DIR_OVERLAPS_INPUT_DIRECTORY`). It refuses a non-empty directory that has no manifest (`LOCAL_DATA_DIR_NOT_EMPTY`). After the manifest exists, a later start must see the same absolute paths and the same SHA-256 bytes (`LOCAL_MANIFEST_MISMATCH` if not). Keep the four input files where they are. Do not delete `history.jsonl`, `head.json`, or revision files to force a different input set. Point a different unused `--data-dir` at different inputs.

Identity binding the harness actually checks:

- `document.json` `source.bucket` and `source.key` must both be present, or startup stops with `DOCUMENT_SOURCE_NOT_S3_COMPATIBLE`.
- When `source.checksum_sha256` is present, it must equal the SHA-256 of the `--source` PDF (`SOURCE_CHECKSUM_MISMATCH`).
- When the review service loads the baseline, `source.identity` must equal `s3://` + bucket + `/` + key. A mismatch is `INVALID_BASELINE` (HTTP 422). When `source.version` is present, it must match the version the store stored for that PDF.
- When the document has no `source.version`, the store sets version to `local-sha256:` plus the PDF SHA-256.
- `review-context.json` `storage_id` is created once. The server `context_id` is a separate SHA-256 over that storage id, job id, actor, baseline artifact, accepted source, and raw artifact. It is not the Save fingerprint.
- A copied data directory keeps the same `storage_id`. An independent review is a new empty data directory, not a second writer on a copy.

The Path B files inspected for this guide already satisfy the bucket, key, identity form, and exact PDF checksum checks. A `document.json` written by the offline CLI does not. Section 7 keeps the two commands apart. Reviewing the Path B sample does not demonstrate review of a Path A output.

Existing review directories to leave unchanged include `.local-review-data/fexofenadine-local-current`, `fexofenadine-manual-01`, `a1-save-retry-verification-20260917-192410`, `a2-save-recovery-20260917`, `b1-regression-20260918`, `b2b-history-20260918`, `html-provenance-20260925`, and `build-check`.

## 4. Execution flow in detail

Work is synchronous. The offline CLI converts and renders pages one after another in the calling process (`write_outputs` and `render_individual_pages`). `--page-workers` is accepted and ignored, including when it is greater than 1. The harness runs uvicorn with `workers=1`. Each browser action is one HTTP request and waits for that response. This path does not start a background worker. History rebuild runs inside `publish`, on the same request, after `head.json` is written. The in-process lock serializes that one process only.

### Path A — offline conversion

| Step | Input | Component | Operation | Output | Continue when |
|---|---|---|---|---|---|
| 1 | One UTF-8 JSON file | `python -m app.document_conversion offline` | `json.loads` the whole file | In-memory response | The file is one complete JSON document |
| 2 | That response | `provider.parse_analysis` and `validate_textract_response` | Require status `SUCCEEDED` or `PARTIAL_SUCCESS`, no `NextToken`, at least one block, within default block/page/relationship limits | Validated analysis, or `ConversionError` | No exception |
| 3 | Validated response plus `Source(identity=<--source-id>)` | Textractor 1.10.0 via `convert_and_render` | Map pages, tables, references, and warnings. Tolerance detection may add `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` without changing characters. Figures become warnings, not pictures | Canonical `Document` | Mapping succeeds |
| 4 | That result | `write_outputs` | Write `document.json`, then `document.html`, then `page-NNNN.html`, one page at a time | Files in `--output` | Process exit code 0. The output directory has no new raw `textract.json` |

`PARTIAL_SUCCESS` is kept as partial. Missing text is not invented. HTML is a reading view, not a visual copy of the PDF. The same saved response and converter version produce the same canonical document; a new recognition run is a different input and is not available on this path.

The `--source-id` value is stored only as `source.identity`. Bucket, key, version, and checksum stay empty. That is a current integration limit: the harness rejects this file at startup (`DOCUMENT_SOURCE_NOT_S3_COMPATIBLE`) and, if those fields were present with a different identity string, the review service would still reject it (`INVALID_BASELINE`). Path A ends when the files are written. It does not continue into review. Do not edit `document.json` to add source fields.

Conversion failure: the exception is a `ConversionError` code such as `INVALID_TEXTRACT_RESPONSE`, `ANALYSIS_FAILED`, `ANALYSIS_IN_PROGRESS`, `PAGINATION_INCOMPLETE`, `EMPTY_ANALYSIS`, `BLOCK_LIMIT`, `PAGE_LIMIT`, `CYCLIC_RELATIONSHIP`, or `RELATIONSHIP_DEPTH_EXCEEDED`. A partial write can exist if failure happens after the first file. Leave the saved response untouched and retry into a new output directory.

### Path B — local review of a compatible artifact set

Path B does not read `$ConversionDir` or any other directory just produced by Path A. It uses a PDF, canonical JSON, recognition response, and original HTML that already satisfy section 3. Completing review on that set leaves the Path A outputs unreviewed.

| Step | Input | Component | Operation | Output / state | Continue when |
|---|---|---|---|---|---|
| 1 | PDF, canonical JSON, recognition JSON, original HTML, empty data directory, free port, built `review.js`, `review.css`, and PDF worker | `local_harness` | Check the four files are readable, assets exist, source fields and checksum match, write manifest and `review-context.json` if this directory is new | Process listening on `127.0.0.1`. Console prints `history-status: none (no published head)` | Exit code is not 2 and the URL is printed |
| 2 | Browser `GET /documents/local-review` | Harness page plus Vue bundle | Load workspace, fetch PDF and `GET /review` | Status `NOT_REVIEWED`, generation 0, findings from warnings. No revision file yet | Page text and PDF both open |
| 3 | Text edits and finding decisions still in the browser | Editor | Update the TipTap draft and decision map | Dirty / Unsaved. Nothing new on disk | You choose Save draft |
| 4 | `PUT /api/v1/documents/jobs/local-fexofenadine/review` with sparse `{node_id, text}`, decisions, `expected_revision`, and `operation_id` | Review service, then local store | Apply text, rebuild findings, drop approval on edited pages, clear document approval, write envelope schema `1.1.0` with action `DRAFT_SAVED`, publish head, rebuild `history.jsonl` | Status `IN_REVIEW`, generation increased. UI returns to Saved | HTTP body is a review state, or Check save status later shows the operation `COMMITTED` |
| 5 | `POST .../review/pages/{n}/approve` | Review service | Require every finding on that page to be resolved. Write action `PAGE_APPROVED`. No export files | That page’s `PageApproval` bound to the page content hash | The page dot shows approved and the error banner is clear |
| 6 | `POST .../review/approve` | Review service | Require a complete page set, every finding resolved, and every page approval hash current. Write HTML, then JSON export, then the final envelope, then the head, then history | Status `APPROVED`, action `DOCUMENT_APPROVED` | Download HTML and Download JSON appear |
| 7 | Export GET | Harness download route | Stream the artifact named by the published head | Browser file `reviewed-document.html` or `reviewed-document.json` | The correction is visible in both files |

Approve page and Approve & Export first call Save when the draft is dirty, and they force an initial Save when no revision exists yet. Page approval does not write export files. Final approval does. The inspected Path B sample uses its own canonical JSON and original HTML, together with the saved recognition response that those files were built from. That response is an input to Path B because the compatible canonical document already names it. It is not a handoff from a Path A directory created in the same session.

### Failure boundaries

| Boundary | What remains | What to do next |
|---|---|---|
| Conversion failure | Saved response and PDF unchanged. Output directory may be partial | Read the `ConversionError` code. Retry in a new output directory |
| Unreadable input or missing frontend assets | No review writes | Restore the missing path, or build assets only when `review.js`, `review.css`, or the PDF worker is absent |
| Source checksum or identity mismatch | Existing review directories unchanged. A new manifest is not written when the check fails first | Keep the PDF that matches the canonical checksum. Do not rewrite source fields. Use another empty data directory only when you intentionally change inputs |
| Manifest mismatch on restart | Previous head, revisions, and history stay as they are | Restart with the original four paths. A different input set needs a new data directory |
| Invalid edit (`INVALID_REVIEW`, HTTP 422) | Head unchanged | The browser marks the pending record `rejected` only when that record is not ambiguous and this client has no preceding uncertain attempt. Otherwise the record stays `uncertain`. A later 422 does not prove the earlier attempt failed to commit. Use **Discard attempted save** only after the phase is already `rejected`. While it is `uncertain`, use **Check save status** or **Retry same save** |
| Publication conflict (`REVIEW_CONFLICT`, HTTP 409) | Head stays on the revision that won. The same operation id and matching fingerprint create no new revision. HTTP `PUT /review` returns the current head as `ReviewState`, which may be newer than the original Save, and omits the service-level receipt. A different fingerprint for that operation id is `SAVE_OPERATION_MISMATCH` | The browser classifies the Save as committed, superseded, or still uncertain. Copy the attempted text shown in the recovery banner before any **Discard attempted save**. Leave an `uncertain` record in place. Do not treat unreferenced files from a lost publish as the current approval |
| Blocked approval (`REVIEW_NOT_READY`, HTTP 409) | Last committed revision unchanged | Decide every finding on the page before Approve page. For final approval, every page must be approved against current text, every finding decided, and declared pages, converted pages, and recognition pages must be the same set |
| History rebuild failure after a committed head (`LOCAL_HISTORY_REBUILD_FAILED`, HTTP 503) | `head.json` and the new envelope stay. A previous valid `history.jsonl` is left in place if the replace did not finish | The error does not prove the save or approval was lost. Reload or use Check save status before repeating the action. Section 6 is the recovery procedure |

`REVIEW_CONTEXT_CHANGED` (HTTP 409) is returned when `X-Review-Context` does not match the current context, and the handler does that before it mutates. The pending Save record is kept.

## 5. Review, saves, and approvals

The editor accepts text changes inside existing nodes. Table identity, row and column counts, `sourcePath`, cell structure, heading levels, and source references stay fixed. The protected-structure filter rejects transactions that change that skeleton. A page that cannot be loaded sets an editor content error and blocks approval buttons.

Findings are conversion warnings. On first load they are unresolved. The panel starts on **This page**; **All warnings** stays selected while you change pages. An empty page shows `No findings in this view.` Allowed decision actions are:

| Action | Meaning |
|---|---|
| `KEEP_ORIGINAL` | Keep the text and record the finding as reviewed |
| `ACKNOWLEDGED_LIMITATION` | Record a known limitation, including an uninterpreted figure |
| `RESOLVED_AFTER_EDIT` | Record that an edit resolved the finding. The server accepts it only when the evidence-region hash differs from the baseline region |
| Apply suggested ± | For one eligible `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` with a single plain `+`. The server applies the suggested text and marks the change `APPLIED_SUGGESTION` |

Decisions and text stay in the browser until Save draft. The server stores sparse text changes and finding decisions. It does not accept a new document structure from the browser.

Three layers of “saved”:

| Layer | Where it lives | Durability |
|---|---|---|
| Unsubmitted editor changes | TipTap draft in the tab | Lost on reload. The tab warns on close while dirty |
| Submitted but uncertain Save | `sessionStorage` key `batchlens.pending-save.v1:<origin>::<apiBase>:<context_id>`, phase `uncertain` or `committed` | Same tab, same browser profile, until storage is cleared or the record is retired. Not shared across tabs |
| Confirmed commit | Revision envelope plus `head.json` | Survives reload and a harness restart on the same data directory |

A Save sends a new UUID v4 `operation_id` and `expected_revision` (null only for the first revision). The fingerprint is SHA-256 of schema `batchlens.save-draft.fingerprint.v1`, job id, actor, expected revision, sorted text changes, and sorted decisions. The operation id is the lookup key and is not part of the fingerprint.

A retry with the same operation id and the same fingerprint creates no new revision. Inside the service, `_replay_committed` builds a `SaveReceipt` whose `revision_id` and `generation` are the revision that originally committed that operation, with `replayed` true. The `ReviewState` on that result is the current published head, and that head can be a later generation than the receipt. HTTP `PUT /review` returns only that `ReviewState`. It does not return the receipt and it does not return the older revision when the head has moved. `GET .../review/operations/{operation_id}` is the lookup that returns `{context, reconciliation}`. When reconciliation status is `COMMITTED`, `reconciliation.receipt` carries the original revision id and generation, while `head_revision_id` and `head_generation` name the current head.

The same operation id with a different fingerprint is `SAVE_OPERATION_MISMATCH`. A repeated Save that uses a new operation id is a new attempt and follows normal conflict rules. **Retry same save** resends the frozen body, so the operation id and fingerprint stay the same. The review state applied from that response is still the current head.

Optimistic concurrency: a new Save must send the current `expected_revision`. If the head has moved and this operation id is not already on the chain with the same fingerprint, the response is `REVIEW_CONFLICT` and the head is unchanged by this request.

Pending phases and what the buttons mean:

| Phase | Meaning | Safe next control |
|---|---|---|
| `uncertain` | The response was lost, malformed, or not yet classified | **Check save status**, or **Retry same save**. Leave the record in place |
| `committed` | Lookup or the response proved a commit, and local apply or cleanup did not finish | **Check save status** or **Retry same save**. A matching fingerprint does not create another revision. The `ReviewState` from retry is the current head, which may be newer than the receipt’s revision |
| `superseded` | Lookup shows a later head and this operation is not on the chain | Copy the attempted text in the banner, then **Discard attempted save**. That loads the current head. Save again only if that text is still wanted |
| `mismatch` | This operation id is committed with a different fingerprint | Copy anything you still need, then **Discard attempted save**. Do not expect retry of this body to commit |
| `rejected` | `INVALID_REVIEW` with HTTP 422, the pending record is not ambiguous, and this client has no preceding uncertain attempt | Copy anything you still need, then **Discard attempted save**, and save a corrected draft as a new operation. A 422 after an uncertain attempt does not move the record to `rejected` |

**Discard attempted save** is offered only for `superseded`, `mismatch`, and `rejected`. Do not clear `sessionStorage` or delete the data directory while a phase is `uncertain` or `committed`. Do not discard an uncertain Save because a later retry returned HTTP 422. The client keeps that record uncertain when `record.ambiguous` is set or `uncertainAttempt` is already true, and **Check save status** remains the reconciliation control.

Page approval stores `content_hash` of that page’s canonical JSON, actor, time, and revision id. The new `PAGE_APPROVED` envelope sets document approval to null, so a page approval after a previous final approval returns the head to `IN_REVIEW` until Approve & Export is run again. A later Save that changes text on a page clears that page’s approval. Pages whose text did not change keep their approval when the hash still matches. Any new `DRAFT_SAVED` revision also clears document approval. A finding decision stays resolved only while its stored region hash equals the current region hash.

Final approval checks declared page count, converted page numbers, recognition page numbers, and `DocumentMetadata.Pages` against one set from 1 through the declared count, then checks every finding and every page approval. The browser also blocks the approval buttons when PDF.js reports a different page count from `declared_pages`, when content is unsupported, or while a recovery banner is blocking edits. The banner text is `Source PDF has N pages but review data expects M.`

| Term | Values in this implementation | What it answers |
|---|---|---|
| Conversion status | `SUCCEEDED`, `PARTIAL_SUCCESS` | Did conversion finish, including partial recognition? |
| Review status | `NOT_REVIEWED`, `IN_REVIEW`, `APPROVED` | Is there a published review head, and does it carry document approval? |
| Revision action | `DRAFT_SAVED`, `PAGE_APPROVED`, `DOCUMENT_APPROVED` | What this immutable envelope recorded |
| Page approval | `content_hash`, actor, time, revision id | Who approved this page text |
| Document approval | `document_hash`, actor, time, revision id | Who approved the whole document payload |
| UI save chip | `SAVED`, `SAVING`, `UNKNOWN`, `BLOCKED` | Browser view of the draft. Dirty text displays as In review on the document chip even when the server is still `APPROVED` until Save commits |

The document chip follows the server status after a clean reload. Actor and timestamps on new revisions are `local-test-reviewer` and the server clock.

## 6. History and monitoring

Each committed envelope records revision id, parent id, generation, action, actor, `created_at`, the reviewed document, catalogue, page states, findings, sparse text changes, and, on final approval, document approval. New envelopes use schema `1.1.0`. `created_at` is the time before the head is published, not a separate publication timestamp.

`history.jsonl` is derived. `head.json` and the reachable `review.json` files remain authoritative. The projector does not verify PDF bytes, recognition bytes, baseline bytes, or export bytes. It walks the published parent chain only. A broken chain raises `INVALID_REVIEW_STATE` and does not write a partial file marked complete.

The file is UTF-8 JSON Lines. Line 1 is `HISTORY_COVERAGE` with schema `batchlens.committed-history.jsonl.v1` and coverage through the head revision and generation. Later lines are `COMMITTED_TRANSITION` records in generation order: text changes, finding decisions, page-approval grants, document-approval grants, export pointers, and derived invalidations. A page or document approval is marked invalidated only when the next snapshot no longer has that approval. A repeated approval is another grant.

| Status | Meaning |
|---|---|
| `CURRENT` | The file parses and its coverage matches the head revision id and generation |
| `STALE` | The file parses and names a different head |
| `INVALID_OR_MISSING` | The file is absent or fails validation |

Startup rebuilds when status is `STALE` or `INVALID_OR_MISSING`. A `CURRENT` file is left as it is across restarts. No published head means no history file is created. A failed conditional publish does not write history. The console line `history-status:` prints `none (no published head)` or one of the three statuses. There is no history screen in the review UI. The review UI does not read this file to decide a Save.

Operational logs on this path are the harness process output and uvicorn’s request log. A history rebuild failure also logs one error on logger `tests.document_review.local_store` with event `local_history_rebuild_failed`, job id, revision id, generation, history path, trigger `publish` or `startup`, and the error code. That log is not a second ledger. This is not a regulatory audit system.

When rebuild fails after the head is written, the HTTP response is `{"code":"LOCAL_HISTORY_REBUILD_FAILED"}` with status 503. Startup failure prints `Local review harness did not start:` and `LOCAL_HISTORY_REBUILD_FAILED`, and the process exits 2. In both cases the new head remains.

Safe recovery:

1. Leave `head.json`, `objects/`, and any existing `history.jsonl` in place.
2. If the harness is still running, reload the workspace. For a Save, use **Check save status** in the same tab before editing again.
3. If the process exited, free the disk or permission problem that blocked the replace, then start the same command on the same data directory. Startup retries the rebuild because the file is stale or missing.
4. After a successful rebuild the startup line should report `CURRENT`.
5. Do not delete the history file, and do not start a second harness on that data directory.

One harness process per writable data directory is the supported model. The lock is not a directory lock.

## 7. Local execution guide — Windows PowerShell

Repository root: `C:\Users\User\batchlens-extract`. Run every step from that directory. Path A and Path B use different outputs. Review uses only the Path B variables. The worked review directory is the new path in `$ReviewDataDir`. Do not point it at an existing review directory.

PowerShell variables exist only in the window where they were assigned. A second window must assign `$ListenPort`, `$ReviewDataDir`, and any path it uses before the commands that follow. After each conversion or build command, read `$LASTEXITCODE` before treating files as a successful result.

Inspection on 2026-09-29 found Python 3.11.4 under Poetry, Poetry 2.2.1, a `.venv`, `frontend/node_modules`, `review.js`, `review.css`, and one PDF worker whose name matched `pdf.worker*.mjs` under `src\app\document_review\static\assets`. That worker filename is a build output and can change. Host `node --version` was v20.18.0. `frontend/package.json` requires Node.js `>=22.12`. Ordinary harness start uses the assets already present and does not need Node. A frontend rebuild on this host needs a Node 22.12 or newer executable; this task did not rebuild.

### 7.1 Confirm toolchain and whether a build is required

Prerequisites: repository checkout. Poetry is on `PATH`.

```powershell
Set-Location C:\Users\User\batchlens-extract
poetry run python -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Python version check failed" }
node --version
Get-ChildItem -File src\app\document_review\static\review.js, src\app\document_review\static\review.css
Get-ChildItem -Recurse -File src\app\document_review\static -Filter "pdf.worker*"
```

Expected: Python `3.11.x`, `review.js`, `review.css`, and at least one `pdf.worker*` file. The worker’s hashed name is whatever that listing prints. Node may print v20.18.0; that still allows the harness to start when these files are present.

First-time Python setup, only if `poetry run` reports a missing environment. Uses the lockfile. Does not upgrade packages.

```powershell
Set-Location C:\Users\User\batchlens-extract
poetry env use 3.11
if ($LASTEXITCODE -ne 0) { throw "poetry env use failed" }
poetry install
if ($LASTEXITCODE -ne 0) { throw "poetry install failed" }
```

Expected: both commands leave `$LASTEXITCODE` at 0. Ordinary later sessions skip this.

Frontend build, only if the asset listing is missing a file, or you changed `frontend/src` and intend to rebuild. Requires Node.js `>=22.12`.

```powershell
Set-Location C:\Users\User\batchlens-extract
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Get-ChildItem -File src\app\document_review\static\review.js, src\app\document_review\static\review.css
Get-ChildItem -Recurse -File src\app\document_review\static -Filter "pdf.worker*"
```

Expected: `$LASTEXITCODE` is 0 after the build, then `review.js`, `review.css`, and a `pdf.worker*` file are listed. The worker filename is a new build output, not a fixed name. The harness error `REVIEW_BUILD_MISSING` names `npm --prefix frontend ci` and `npm --prefix frontend run build` if you start without those files.

### 7.2 Bind one input set

Prerequisites: section 7.1 assets exist.

```powershell
Set-Location C:\Users\User\batchlens-extract
$SourcePdf = "manual-input\source.pdf"
$SavedResponse = "out\comparison\fexofenadine-textractor-20260916-173938\textract.json"
$CanonicalJson = "out\comparison\fexofenadine-local-current\document.json"
$OriginalHtml = "out\comparison\fexofenadine-local-current\document.html"
$ConversionDir = "out\stage1-local-guide-conversion"
$ReviewDataDir = ".local-review-data\stage1-local-guide-example"
$ListenPort = 8771
foreach ($path in @($SourcePdf, $SavedResponse, $CanonicalJson, $OriginalHtml)) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Missing $path" }
  Get-Item -LiteralPath $path | Select-Object FullName, Length
}
poetry run python -c "import hashlib, json, sys; from pathlib import Path; pdf, doc = Path(sys.argv[1]), Path(sys.argv[2]); recorded = json.loads(doc.read_text(encoding='utf-8'))['source'].get('checksum_sha256'); digest = hashlib.sha256(pdf.read_bytes()).hexdigest(); print(digest); print(recorded); print(digest == recorded)" $SourcePdf $CanonicalJson
if ($LASTEXITCODE -ne 0) { throw "checksum comparison failed" }
```

Expected: four existing files, then two identical SHA-256 strings and `True`. The harness requires exact equality when `source.checksum_sha256` is present. A prior read of these two files found that equality; this command is how you confirm it again before review. `$ConversionDir` and `$ReviewDataDir` are not required to exist yet. If either path already exists, pick a new name and assign the variable again. Do not delete an existing review directory.

### 7.3 Path A — standalone offline conversion

Prerequisites: `$SavedResponse` from section 7.2 exists in this window. `$ConversionDir` does not exist yet. This step does not start the harness and does not make `$CanonicalJson`.

```powershell
Set-Location C:\Users\User\batchlens-extract
if (Test-Path -LiteralPath $ConversionDir) { throw "Pick a new conversion directory" }
poetry run python -m app.document_conversion offline $SavedResponse --output $ConversionDir --source-id "saved-textract-response"
if ($LASTEXITCODE -ne 0) { throw "offline conversion failed" }
Get-ChildItem -Name $ConversionDir
```

Expected: `$LASTEXITCODE` is 0 before the listing. The listing then shows `document.json`, `document.html`, and `page-0001.html` through `page-0018.html` for this 18-page response. No `textract.json` in `$ConversionDir`. `--page-workers` may be omitted. If you pass it, rendering stays single-threaded. If conversion fails, leave `$SavedResponse` unchanged and assign a new `$ConversionDir` for a retry. Do not list or inspect a directory from a non-zero exit as a successful conversion.

Read-only identity check, only after exit code 0:

```powershell
Set-Location C:\Users\User\batchlens-extract
poetry run python -c "import json, sys; from pathlib import Path; s=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['source']; print('bucket', s.get('bucket')); print('key', s.get('key')); print('identity', s.get('identity'))" (Join-Path $ConversionDir "document.json")
if ($LASTEXITCODE -ne 0) { throw "identity check failed" }
```

Expected: `bucket None`, `key None`, `identity saved-textract-response`. Stop. Do not pass `Join-Path $ConversionDir "document.json"` to the harness, and do not add bucket or key fields. A later Path B review uses `$CanonicalJson` and does not demonstrate that this file can be reviewed.

### 7.4 Path B — existing compatible artifacts

Prerequisites: `$SourcePdf`, `$SavedResponse`, `$CanonicalJson`, and `$OriginalHtml` from section 7.2, including the exact checksum result `True`. Do not run Path A first, and do not replace `$CanonicalJson` or `$OriginalHtml` with files under `$ConversionDir`.

The harness arguments are those four paths. `$CanonicalJson` must be the bare conversion `Document`, not an approved `review.json` or an export JSON. Per-page HTML is not an argument. Section 7.5 starts review from this set only.

### 7.5 Start the harness on the Path B set

Prerequisites: assets from section 7.1, the Path B variables from section 7.2 in this window, `$ReviewDataDir` absent, `$ListenPort` unused. Path A outputs are not arguments.

```powershell
Set-Location C:\Users\User\batchlens-extract
if (Test-Path -LiteralPath $ReviewDataDir) { throw "Pick a new review data directory" }
Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue
```

Expected: the data-directory check throws nothing, and the port check prints nothing. If a listener is listed, choose another port, assign `$ListenPort`, and check again.

```powershell
Set-Location C:\Users\User\batchlens-extract
poetry run python -m tests.document_review.local_harness --source $SourcePdf --document $CanonicalJson --textract $SavedResponse --html $OriginalHtml --data-dir $ReviewDataDir --port $ListenPort
```

Expected console, then the process stays running:

```text
Local document review harness
  source: <resolved PDF>
  document: <resolved canonical JSON>
  textract: <resolved recognition JSON>
  html: <resolved original HTML>
  data-dir: <resolved ReviewDataDir>
  history: <ReviewDataDir>\history.jsonl
  history-status: none (no published head)
  URL: http://127.0.0.1:<ListenPort>/documents/local-review
  reviewer: local-test-reviewer
  originals: untouched (all generated state stays in data-dir)
```

The printed URL uses the port you passed. Open that URL. This process stays running, so it has no success `$LASTEXITCODE` to check.

In a second PowerShell window, assign the same port again. Variables from the harness window are not visible here:

```powershell
Set-Location C:\Users\User\batchlens-extract
$ListenPort = 8771
$ReviewBase = "http://127.0.0.1:$ListenPort"
Invoke-WebRequest -Uri "$ReviewBase/documents/local-review" -UseBasicParsing | Select-Object StatusCode, @{Name="Cache";Expression={$_.Headers["Cache-Control"]}}
Invoke-WebRequest -Uri "$ReviewBase/api/v1/documents/jobs/local-fexofenadine/review" -Headers @{ Authorization = "Bearer local-review-token" } -UseBasicParsing | Select-Object -ExpandProperty Content
```

If section 7.5 used a different port, set `$ListenPort` to that value before these requests. Expected: HTTP 200 and `Cache-Control` containing `no-store`. The review JSON includes `"status":"NOT_REVIEWED"` and `"generation":0`. That check is not browser acceptance. It also says nothing about files under `$ConversionDir`.

### 7.6 Review, save, approve, and collect files

Prerequisites: the harness from section 7.5 is running and the workspace is open.

1. Confirm the PDF and converted text for the same page, and that page counts are both 18.
2. On page 5, use **Apply suggested ±** for each tolerance finding, or edit the text yourself. For each figure finding, choose **Acknowledge limitation** or **Keep original**. Save draft. The chip returns to Saved and the document chip reads In review.
3. Reload the browser. The correction is still there.
4. Approve each page only after every finding on that page has a decision. Approve page does not enable the download buttons.
5. After every page is approved, choose Approve & Export. If work remains, the banner shows `REVIEW_NOT_READY` and no new export pair is published.
6. When status is Approved, choose Download HTML and Download JSON.

On disk after a successful export, use a window other than the harness process and set `$ReviewDataDir` again:

```powershell
Set-Location C:\Users\User\batchlens-extract
$ReviewDataDir = ".local-review-data\stage1-local-guide-example"
Get-ChildItem -Recurse -File (Join-Path $ReviewDataDir "objects\local-fexofenadine\revisions") | Select-Object FullName, Length
Get-Item (Join-Path $ReviewDataDir "head.json") | Select-Object FullName, Length
```

Expected: at least one `review.json`, and under that revision’s `exports` folder both `document.html` and `document.json`, plus `head.json`. Search the HTML for the correction string you typed. The export JSON is the approved candidate and contains `"exports": null`. The sibling `review.json` envelope contains export pointers. They are different files. These paths are under `$ReviewDataDir`, not under `$ConversionDir`.

### 7.7 Stop, restart, and keep reviews separate

Prerequisites: you know which PowerShell window is the harness.

Stop with Ctrl+C in that window. In that same window, confirm the port is free:

```powershell
Set-Location C:\Users\User\batchlens-extract
Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue
```

Expected: no listener. Inputs and `$ReviewDataDir` stay on disk. Unsaved editor text does not.

Resume the same review with the same four paths and the same `$ReviewDataDir`. In a new PowerShell window, assign `$SourcePdf`, `$SavedResponse`, `$CanonicalJson`, `$OriginalHtml`, `$ReviewDataDir`, and `$ListenPort` again before the port check. Check that the port is free, then run the section 7.5 harness command again. Expected: startup prints a history status rather than `none`, and the workspace reloads the committed status, corrections, and download buttons when the head is `APPROVED`. A `CURRENT` history file is not rewritten just because the process restarted.

An independent review uses a new empty directory name and the same inputs. Do not copy `$ReviewDataDir`. Do not run two harness processes against one data directory. Changing any input path or byte content requires another new directory; the original directory will refuse the mismatch and keep its history.

## 8. Manual verification and troubleshooting

The checks in this section are procedures to perform later. They were not performed while writing this guide.

### Checklist for the Path B directory in `$ReviewDataDir`

| Action | Expected result |
|---|---|
| Open the workspace | PDF and converted text for the same page. Navigation and zoom work. Status Not reviewed before the first save |
| Edit text, Save draft, reload | Saved text remains. Document status In review |
| Apply or edit both page-5 tolerance findings and decide the figure findings that the panel shows | Findings for this sample are two tolerance warnings on page 5 and nineteen figure warnings. A missing warning code that is not in `document.json` is not a UI failure |
| Approve one page | That page’s dot shows approved. Download buttons stay hidden |
| Edit that page again and Save | That page’s approval clears. Document approval clears if it had been set. Other untouched approved pages stay approved |
| Approve & Export while a page is unapproved or a finding is undecided | Banner `REVIEW_NOT_READY`. No new export pair |
| Finish every page and Approve & Export | Status Approved. Both downloads contain the correction |
| Stop and start the same data directory | Approved state and downloads remain |

### Two-tab conflict (isolated directory)

This procedure was not run while writing this document. Use a new data directory, not `$ReviewDataDir` from the checklist and not an existing user directory.

1. Start the harness on that directory and open the same localhost URL in two tabs. Wait until both tabs show the same revision (generation 0 before any save, or the same revision id after a shared reload).
2. In the first tab, edit a distinctive sentence and choose Save draft. Wait until that tab’s save chip reads Saved.
3. In the second tab, edit different text and choose Save draft. That tab’s `expected_revision` is the revision it loaded, so the server responds with HTTP 409 `REVIEW_CONFLICT` when this new operation is not already on the chain. The head remains the first tab’s commit.
4. The second tab keeps a pending Save and shows the recovery banner, including the attempted text. While that record exists, **Reload server state** does not run (`reloadAfterConflict` returns immediately). `handleConflict` then classifies the operation as one of three outcomes:
   - **Committed.** Lookup status is `COMMITTED`. The client retries the same body. No new revision is created. The `ReviewState` applied from `PUT /review` is the current head, which may be newer than the receipt’s revision. If the workspace cannot finish applying or clearing the record, the phase stays `committed`.
   - **Superseded.** Lookup status is `UNRESOLVED`, the head revision differs from this Save’s `expected_revision`, and the head generation is greater than this Save’s base generation. The banner text is `Review conflict. This Save did not commit. Discard the attempted Save to load the current review, then save again if needed.` The save chip reads Review conflict.
   - **Uncertain.** Lookup fails, the context does not match, or the response does not prove superseded. The banner text is `Save status unknown. Check save status or retry the same save.`
5. Next action depends on that outcome. Copy the attempted text from the banner before any disposition that replaces the editor. For `uncertain` or `committed`, use **Check save status** or **Retry same save**, and leave the record in place. For `superseded`, after the copy, **Discard attempted save** loads the current head and removes the matching pending record. Do not discard an uncertain record, and do not treat a later HTTP 422 as proof that this Save failed to commit.

### Pending-save recovery (another isolated directory)

Use another new data directory. Edit text, choose Save draft, and reload the same tab or stop the harness before the Saved chip returns. Expected when the record was stored: a banner with **Check save status** and **Retry same save**, and the attempted text listed. Restart the harness on that same directory if you stopped it. Use **Check save status**. If lookup reports `COMMITTED`, retry sends the same operation and does not create another revision; the review state in the `PUT` body is the current head. If the attempt stays uncertain, leave the record in place. A later `INVALID_REVIEW` response with HTTP 422 does not change an uncertain record to `rejected`. **Discard attempted save** appears only when the phase is already `superseded`, `mismatch`, or `rejected`. Do not delete the data directory or clear site data while the banner is up. This procedure was not run for this document.

### Troubleshooting

| Symptom | Likely cause | Read-only check | Safe next action |
|---|---|---|---|
| `REVIEW_BUILD_MISSING` | `review.js`, `review.css`, or the PDF worker is absent | List `src\app\document_review\static` | Build with Node `>=22.12` using the commands in section 7.1. A stale bundle still starts; rebuild only after frontend source changes |
| Process will not stay up and the port check lists a listener | Another process has `$ListenPort` | `Get-NetTCPConnection -LocalPort $ListenPort -State Listen` | Choose a different port and check it. Leave an existing harness running if it is yours |
| `UNREADABLE_LOCAL_INPUTS` | A flag path is missing or unreadable | `Test-Path` on the four variables | Correct the path. Do not substitute an export JSON for `--document` |
| `DOCUMENT_SOURCE_NOT_S3_COMPATIBLE` | Canonical `source.bucket` or `source.key` is empty. This is the expected startup result if `--document` is the Path A file | Print `source` keys with the section 7.3 command | Start Path B with `$CanonicalJson`. Do not patch the Path A file, and do not treat a Path B session as proof that the Path A file was reviewed |
| `SOURCE_CHECKSUM_MISMATCH` | The PDF SHA-256 is not exactly `source.checksum_sha256` | Re-run the section 7.2 comparison. The last printed line must be `True` | Point `--source` at `$SourcePdf` for this sample |
| `LOCAL_MANIFEST_MISMATCH` or `LOCAL_DATA_DIR_NOT_EMPTY` | Data directory was reused with different inputs, or was not empty | Read `manifest.json` paths. Do not delete it | Resume with the original paths, or create a new directory name |
| `INVALID_BASELINE` | Identity is not `s3://<bucket>/<key>`, or the recognition JSON is not a JSON object | Read `source.identity` and confirm `--textract` is the saved response | Keep the Path B pair together with `$SavedResponse` |
| Banner `Source PDF has N pages but review data expects M` | PDF page count differs from `declared_pages` | The banner itself. This sample expects 18 and 18 | Approval buttons stay disabled until the PDF and canonical document describe the same count. Do not approve from another file set in this directory |
| `REVIEW_NOT_READY` on Approve page | A finding on that page has no current decision | Findings panel, scope **This page** | Record a decision, Save if the text changed, then approve |
| `REVIEW_NOT_READY` on Approve & Export | Unapproved page, unresolved finding, or page-set mismatch | Page dots and findings | Finish decisions and page approvals. Section 4 lists the server completeness check |
| Page shows approved, then Save after an edit clears it | The page content hash changed | Page dot after reload | Approve that page again. Final export must be repeated after document approval clears |
| HTTP 409 `REVIEW_CONFLICT` on Save | `expected_revision` is behind the head and this operation is not replayed | Recovery banner and its phase, not a reload button while the pending record exists | Follow the two-tab outcomes in section 8. Copy attempted text first. Matching operation id and fingerprint create no new revision; the `PUT` body is the current head and has no receipt |
| HTTP 422 `INVALID_REVIEW` after an uncertain Save | The body is invalid, or an earlier attempt was never classified | Pending phase in the recovery banner | Stay on **Check save status** or **Retry same save**. Discard only when the phase is already `rejected` |
| Save chip `Save status unknown` | Response lost after submit, lookup could not classify a conflict, or a 422 arrived after an uncertain attempt | Pending banner and, if useful, `head.json` `revision_id` | **Check save status** or **Retry same save**. Do not discard an `uncertain` record |
| HTTP 503 `LOCAL_HISTORY_REBUILD_FAILED` | Head was published and the derived file replace failed | Startup line, or the 503 body. `head.json` still exists | Follow section 6. Reload before repeating the click |
| Startup history status `STALE` or `INVALID_OR_MISSING`, then the process continues | Rebuild ran because the derived file did not match the head | Next startup should print `CURRENT` when rebuild succeeded | If it exits 2 instead, use section 6. The review screen can still load from the head when the process is up |
| `EXPORT_NOT_FOUND` | This revision is not a published document approval with export pointers | `head.json` `status` | Complete Approve & Export on the current revision. Earlier draft revisions have no export pair |

## 9. Handoff to Stage 2

Stage 2’s reader consumes the approved HTML file only: `objects/local-fexofenadine/revisions/<revision-id>/exports/document.html` for the revision `head.json` names after Approve & Export. It does not read the downloadable JSON, the original `document.html`, or `history.jsonl`.

The renderer writes contract version `1` on the root element, from the approved candidate revision:

```html
<html data-review-html-version="1"
      data-job-id="local-fexofenadine"
      data-review-revision-id="<revision uuid>"
      data-review-generation="<generation>"
      data-conversion-status="SUCCEEDED">
```

`data-conversion-status` is the canonical document status, `SUCCEEDED` or `PARTIAL_SUCCESS`. Catalogue nodes add `data-element-id`, `data-node-id`, and `data-table-id` where the renderer emits those elements. Text nodes that have block references include `data-source-id` as a space-separated list of those block ids, in order, without duplicates. Empty reference lists omit the attribute. Block ids that themselves contain spaces cannot be split back apart by the Stage 2 reader. `data-generated="true"` marks the summary header, a partial-conversion banner, and each `Page N` heading. Visible body text is the reviewed text. The header line is `Approved by local-test-reviewer at <server timestamp>` when document approval is present.

Those attributes name the revision that was rendered. They do not, by themselves, prove that a person approved it. Approval is the `document_approval` object on the published envelope, together with review status `APPROVED`.

Three different digests are in use:

| Digest | What is hashed |
|---|---|
| Document hash on `document_approval.document_hash` | Canonical JSON of the whole reviewed `Document` |
| Page `content_hash` | Canonical JSON of that page |
| HTML SHA-256 | SHA-256 of the export HTML bytes. The Stage 2 reader records it only after `iter_pages` finishes and `completed` is true. It is not copied out of the JSON |

`ReviewService.approve` writes the downloadable JSON from the candidate envelope while `exports` is still null, and it writes the HTML from that same candidate. It then stores a final `review.json` that adds `exports` pointers to those two files, and publishes the head with those pointers. The file you download as JSON and the persisted `review.json` are not the same bytes. The downloadable JSON does not contain the export pointers, so it does not by itself prove the HTML byte identity. Use the HTML file the head’s HTML artifact names, and let a later reader hash those bytes after a full read.

Local Stage 1 is complete for a data directory when all of the following are true:

- The harness was started from the four original inputs and left those files unchanged.
- Review status is `APPROVED` after reload.
- The head’s revision has both export files on disk, and both downloads show the correction you saved.
- A later text Save moves status back to `IN_REVIEW`, clears approval on the edited page, and requires page approval plus Approve & Export again before a new export pair exists.

Stop there. Do not start lexical extraction from this guide.

## Source and verification note

Inspected 2026-09-29 at commit `f4a9f97412e44c39434e9c39ba5be613d3d076fd` (2026-09-28, “lexical search L13”). A same-day documentation correction re-read `ReviewService._replay_committed`, the HTTP `PUT /review` return type, and the Save 422 and `handleConflict` paths in `frontend/src/state.ts` and `ReviewWorkspace.vue`. Working tree at the original inspection had untracked `docs/BatchLens-Stage1-Overview-EN.md`, `docs/BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`, and `prompts/overview/`. No application files were modified. Tests were not executed. Commands in section 7 were not executed. Host Node v20.18.0 is below the frontend engine floor; existing static assets were present and were not rebuilt. The PDF worker filename is a build hash, not a permanent name.

Paths consulted: `.ai/03_common_handoff.md`, `.ai/00_project_reference.md`, `.ai/04_code_map.md`, `.ai/01_implementation_roadmap.md`, `.ai/02_code_quality_standards.md`, `docs/BatchLens-Stage1-Overview-EN.md`, `src/app/document_conversion/` (`__main__.py`, `adapter.py`, `contracts.py`, `provider.py`, `textractor_renderer.py`, `tolerance.py`), `src/app/document_review/` (`contracts.py`, `mapping.py`, `service.py`, `operations.py`, `rendering.py`, `history.py`, `history_jsonl.py`), `src/app/api/document_reviews.py`, `src/app/document_jobs/contracts.py`, `tests/document_review/local_harness.py`, `tests/document_review/local_store.py`, `frontend/src/` (`api.ts`, `contracts.ts`, `state.ts`, `pendingSave.ts`, `mapping.ts`, `extensions.ts`, and the four review components), `frontend/package.json`, `frontend/vite.config.ts`, `pyproject.toml`, `src/app/lexical_extraction/html_reader.py`, and `src/app/lexical_extraction/contracts.py` (`ReviewedHtmlV1Input` only). Sample identity and warning pages were read from `out/comparison/fexofenadine-local-current/document.json` and `out/comparison/fexofenadine-textractor-20260916-173938/textract.json` without running conversion or the harness.
