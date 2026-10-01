# BatchLens — Stage 4: Detailed Local Execution Guide

This guide explains how to run and inspect the Stage 4 local page-classification MVP on Windows PowerShell. The shorter product overview is `docs/BatchLens-Stage4-Page-Classification-Overview-EN.md`. This document covers local inputs, directories, classifier behavior, workspace actions, PowerShell steps, verification, and troubleshooting.

Stage 4 here is local harness behavior only. It is not a production deployment, production authentication surface, or cross-process job platform.

## 1. Scope and current status

Stage 4 classifies every page of one Stage 1 approved/reviewed HTML v1 document, applies a conservative eligibility decision for later lexical extraction, and shows those results in the existing extraction-review workspace. **Extract All** then submits Stage 2 `full` over eligible pages only. Stage 3 remains the only human extraction-result review and approval scope.

| Concern | Owner |
|---|---|
| Source document approval | Stage 1, unchanged |
| Page classification and eligibility | Stage 4 |
| Deterministic lexical matching and publication | Stage 2 |
| Human Save / Download TXT / **Approve extraction result** | Stage 3 |

| Status | Meaning for Stage 4 |
|---|---|
| **implemented** | Page-classification package, local current-state store, diagnostic bundles, classified Extract All, Stage 4 adapter/API, and Vue workspace integration exist in the repository. |
| **test-verified** | Focused suites under `tests/page_classification/`, Stage 4-related `tests/extraction_review/`, and Stage 2 page-restriction coverage in `tests/lexical_extraction/` encode the contracts above. |
| **manually verified (recorded local)** | A recorded local harness acceptance used a real configured OpenAI classification and a subsequent classified Extract All path, including classification context with lexical findings and ordinary Stage 3 Save/Approve on a reviewable run. |
| **unverified as product guarantees** | Pharmaceutical correctness of labels, model output quality for arbitrary documents, production mounting/authentication, and AWS/live-cloud behavior. |

Configured OpenAI calls are live external requests. The live classifier sends complete reviewed-page HTML to the configured provider. That has cost and privacy implications. Deterministic tests use fakes and fixtures; they do not validate pharmaceutical correctness or guarantee model output quality.

## 2. Components and responsibilities

Browser polling is asynchronous. Inside one local application process, the classifier worker processes pages in document order and runs the three calls for each page serially. There is no parallel page fan-out, generic queue, or cross-process worker lock.

| Area | Principal path | Responsibility |
|---|---|---|
| Prepared page input | `src/app/page_classification/page_input.py` | Validate reviewed HTML v1 once; derive full-page fragments, readable text, and page-local identifier maps. |
| Response contracts | `src/app/page_classification/page_classification_schemas.py` | Three locked Pydantic response models and evidence rules. |
| Prompts / JSON schemas | `src/app/page_classification/prompts/`, `json_schemas/` | Fixed call prompts and regenerated JSON Schema assets. |
| Merge and eligibility | `src/app/page_classification/rules.py` | Source-evidence validation, merge, `OTHER_UNCLASSIFIED` fallback, and conservative eligibility. |
| Classifier runner | `src/app/page_classification/runner.py` | Three serial structured calls per page through the existing `app.llm` wrapper boundary. |
| Local service / store | `service.py`, `store.py`, `contracts.py` | Current classification lifecycle and one `current-classification.json` per reviewed-HTML identity. |
| Diagnostics | `src/app/page_classification/diagnostics.py` | Bounded local diagnostic bundles for troubleshooting. |
| Classified lexical jobs | `src/app/extraction_review/local_jobs.py` | Eligible-page allow-list, immutable classification snapshot, Stage 2 `full` submission. |
| Stage 2 restriction | `src/app/lexical_extraction/runner.py`, `contracts.py`, `publication.py` | Optional page allow-list and Stage 4 restriction provenance; unrestricted runs unchanged. |
| Local Stage 4 adapter | `src/app/extraction_review/stage4_local.py` | Approved-document selection, classify/Extract All coordination, snapshot views. |
| Local API | `src/app/api/extraction_reviews.py` | Harness-mounted Stage 3 and Stage 4 routes. |
| Vue workspace | `frontend/src/components/ExtractionReviewWorkspace.vue`, `extractionReview.ts` | Classify pages, Extract All, progress, classification panel, classifications TXT, Stage 3 controls. |
| Local harness | `tests/extraction_review/local_harness.py` | Localhost server; with `--config`, wires classified Extract All and classifier composition. |

OpenAI settings remain in `src/app/settings.py` (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`). Stage 4 reuses the existing LLM wrapper; it does not redesign that boundary.

## 3. Local directory model and persistence

### 3.1 Approved-document root

```text
<approved-documents-root>/
  <job_id>/
    <review_revision_id>/
      document.html
      review.json                 optional; ignored by selection
```

Folder `job_id` and `review_revision_id` must match the reviewed-HTML root provenance. Stage 4 does not rewrite that file.

### 3.2 Data directory layout

```text
<data-dir>/
  page-classifications/
    <sha256(reviewed-html-binding)>/
      current-classification.json
  page-classification-diagnostics/
    <classification-run-id>/
      manifest.json
      assets/prompts/...
      assets/schemas/...
      pages/page-NNN/call-*-request.json
      pages/page-NNN/call-*-response.json
      pages/page-NNN/result.json
  extraction-jobs/
    <local-job-id>.json
    <local-job-id>/
      classification.json         immutable snapshot for a classified job
  extraction-raw-runs/
    <stage2-run-id>/
      manifest.json
      artifacts/...
  extraction-reviews/
    <sha256(local_job_id)>/
      current-review.json         Stage 3 only; one per lexical local job
```

| Path | Meaning |
|---|---|
| `current-classification.json` | One current classification state for the reviewed-HTML identity (source provenance + HTML-byte SHA-256). |
| Diagnostic bundle | Local troubleshooting copy of prompts/schemas, requests, responses/errors, and merged page results. Retention keeps the newest valid bundles (currently five). |
| `extraction-jobs/<id>.json` | Local lexical job record. |
| `extraction-jobs/<id>/classification.json` | Exact classification snapshot used by that classified job. Later current reclassification does not rewrite it. |
| `extraction-reviews/.../current-review.json` | Separate Stage 3 current review per `local_job_id`. |

### 3.3 Current-state and restart semantics

- No classifier history, revision browser, approval ledger, retry ledger, or SQLite classification store.
- A completed classification persists and reloads with the same data directory.
- An in-progress classification abandoned across harness restart is marked `interrupted`, keeps finished page results, and is not automatically resumed.
- Within one local application process, one active classifier worker is allowed per data directory. This is not cross-process locking or a queue platform.
- A fresh data directory is the normal way to run a new classification experiment without overwriting the current local classification for that reviewed HTML.

## 4. Input, classifier contract, and source validation

Each page is classified with three locked structured calls. The user message for each call is the complete page HTML fragment.

| Call | Group |
|---|---|
| 1 | Materials and equipment |
| 2 | Process, operations, and controls |
| 3 | Document and supporting records |

Returned labels must come from that call’s locked set. Exactly one evidence item is required per returned label. Quote and reason are each 1–240 characters. Labels and evidence are order-independent for validity and retain received order. Evidence is associated by its own `label`, not by list position.

`OTHER_UNCLASSIFIED` is application-generated only. The model cannot return it. The application assigns it when all three calls are valid `ok` responses with an empty merged label union; the page then requires review and remains eligible.

Readable source excludes scripts, styles, and comments. Source validation uses one HTML-entity decode and whitespace collapsing. Supported exact identifiers are `id`, `data-node-id`, `data-element-id`, and `data-table-id` on the current page only. When the same value appears on exactly two elements that are an `article.element` wrapper and its direct content child, the article wrapper is used; other multi-matches are ambiguous.

Verified evidence means the quote was found in the resolved page/element text. Unverified evidence preserves the label and evidence, marks the page as requiring review, and does **not** by itself make the page ineligible for lexical extraction. Source verification proves location only, not that the label is semantically correct.

There is no classifier label editing, classifier approval, page-level approval, retry UI, or manual-resolution workflow.

## 5. Classification outcome, page routing, and review meaning

Keep these four outcomes distinct:

1. Classifier call / current classification state (`running`, `completed`, `failed`, `interrupted`, plus per-page merge kinds).
2. Per-page eligibility / exclusion for Stage 2.
3. Stage 2 lexical processing and publication state.
4. Stage 3 final **Approve extraction result**.

A page is excluded only when every final label belongs to this fixed exclusion set **and** the result is fully valid, non-empty, exclusively exclusion labels, with no incomplete, failed, invalid, conflicting, `needs_review`, or unverified-source-evidence state:

```text
NON_RELATED
COVER_PAGE
TABLE_OF_CONTENTS
DOCUMENTATION_INSTRUCTIONS
REFERENCE_DOCUMENTATION
SIGNATURE_LOG
SIGNATURE_APPROVAL
ACKNOWLEDGEMENT
BATCH_REVIEW_DISPOSITION
DOCUMENT_CHANGE_HISTORY
```

| Case | Eligibility |
|---|---|
| Exclusion-only, fully verified, completed | Excluded |
| Any extraction-relevant or mixed label set | Eligible |
| Empty, `OTHER_UNCLASSIFIED` fallback, `needs_review`, incomplete, failed call, interrupted/unprocessed page, source-unverified evidence | Eligible |

**Extract All** uses Stage 2 `full` on eligible pages only. Reviewed HTML bytes and page identities are unchanged. Stage 2 provenance records the Stage 4 restriction; skipped pages get no synthetic Stage 2 records. If no page restriction is supplied, ordinary Stage 2 behavior is unchanged.

Zero eligible pages is an informational completed outcome: the workspace shows the implemented no-eligible-pages message and does not submit an empty Stage 2 run.

Classifier labels remain informational beside lexical findings. They do not change Stage 3 Save, Download TXT, or approval semantics.

## 6. Local API and workspace behavior

These routes are harness-mounted only (`tests/extraction_review/local_harness.py`). There is no production auth.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/extraction-reviews/approved-documents` | List eligible approved documents. |
| `GET` | `.../approved-documents/{job_id}/{review_revision_id}/pages` | Page numbers for the selected document. |
| `GET` | `.../pages/{page_number}` | Approved page HTML for the left pane before a lexical run is open. |
| `GET` | `.../classification` | Current classification for the selected document. |
| `POST` | `.../classify` | Start classification. |
| `POST` | `.../extract-all` | Submit classified Extract All, or return `no_eligible_pages`. |
| `GET` | `/api/v1/extraction-reviews/local-jobs/{local_job_id}` | Lexical job status, selected pages, `reviewable`. |
| `GET` | `/api/v1/extraction-reviews/jobs/{local_job_id}/classification` | Immutable classification snapshot for a classified job. |
| Stage 3 routes | open/save/approve/page/results.txt | Unchanged extraction-result review surface. |

Workspace behavior:

1. Select an approved document.
2. **Classify pages** starts once when no current classification exists for that selection.
3. Progress and terminal classification are polled while running.
4. Left pane shows approved HTML; right pane shows labels, evidence, source-validation state, and eligible/excluded.
5. **Extract All** is available after a terminal classification (`completed`, `failed`, or `interrupted`).
6. Lexical progress is shown separately. A reviewable completed run opens automatically and shows the immutable classification snapshot with lexical findings.
7. A terminal but non-reviewable lexical result shows an informational message and does not expose Save, Stage 3 Download TXT, or Approve.
8. **Download classifications TXT** exports page classifications and is distinct from Stage 3 findings TXT.

## 7. Local execution guide — Windows PowerShell

### 7.1 Prerequisites and safe preflight

Run from the repository root. Activate Poetry and confirm Node for the browser bundle:

```powershell
& .\.venv\Scripts\Activate.ps1
poetry run python --version
node --version
```

The harness requires built assets `src/app/document_review/static/review.js` and `review.css`. If they are missing:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
```

Confirm OpenAI configuration without printing the key:

```powershell
poetry run python -c "from app.settings import get_settings; s=get_settings(); print('OPENAI_API_KEY configured' if s.openai_api_key else 'OPENAI_API_KEY missing'); print('model=', s.openai_model)"
```

Expected: `OPENAI_API_KEY configured`, plus the configured model name. Settings load from environment variables and optional `.env` (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`). Do not print or paste the key into logs, tickets, or this guide.

The live classifier sends complete reviewed-page HTML to the configured provider. Treat the approved document as protected content.

Prepare:

- an approved-documents root with valid Stage 1 reviewed HTML layout;
- a Stage 2 execution YAML whose knowledge snapshot directory contains `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and `FLAT_SQLITE_CONTRACT.md`.

### 7.2 Variables for an isolated run

Use a new data directory and an unused localhost port. Example values; replace paths that do not match your machine:

```powershell
$ApprovedRoot = "$PWD\.local-extraction-approved"
$ConfigPath = "$PWD\out\lexical-l13\execution-full.yaml"
$Stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$DataDir = "$PWD\.local-s4-guide-$Stamp"
$Port = 8773
$Url = "http://127.0.0.1:$Port/documents/local-extraction-review"
```

### 7.3 Safe path checks

```powershell
New-Item -ItemType Directory -Force $DataDir | Out-Null
Test-Path -LiteralPath $ApprovedRoot -PathType Container
Test-Path -LiteralPath $ConfigPath -PathType Leaf
Get-ChildItem -LiteralPath $ApprovedRoot -Recurse -Filter document.html |
  Select-Object -ExpandProperty FullName
```

Expected: approved root and config exist; at least one `document.html` is listed under `<job_id>/<review_revision_id>/`.

Confirm snapshot companions from the YAML’s `knowledge.snapshot_directory` (resolved relative to the YAML file directory). All four companions must exist.

Confirm the port is free before starting:

```powershell
Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
```

Expected: no listening connection, or choose another port.

### 7.4 Start the Stage 4 harness (no legacy auto-extraction)

For Classify pages plus in-workspace Extract All, start with `--config` and **without** `--run-extraction`:

```powershell
poetry run python -m tests.extraction_review.local_harness `
  --data-dir $DataDir `
  --approved-documents-root $ApprovedRoot `
  --config $ConfigPath `
  --port $Port
```

Expected console output includes the data directory, approved-documents root, config path, and:

```text
URL: http://127.0.0.1:<port>/documents/local-extraction-review
```

Leave that PowerShell process running. `--run-extraction` is a separate legacy Stage 3 helper that submits an ordinary lexical job before the UI starts; do not use it for this Stage 4 classify-then-Extract All sequence.

### 7.5 Browser sequence

Open `$Url`.

1. Select the approved document.
2. Click **Classify pages** once.
3. Watch truthful progress (current page and completed/total counts).
4. When classification is terminal, inspect pages: labels, evidence, source-validation state, eligible/excluded.
5. Click **Extract All** only after classification is terminal.
6. Observe lexical job status separately from classification.
7. When the run is reviewable, confirm immutable classification context and lexical findings together.
8. Optional: make one harmless Stage 3 edit, Save, Download TXT (findings), and use the single final **Approve extraction result** action.
9. Optional: use **Download classifications TXT** for the page-classification table; it is not the Stage 3 findings export.

### 7.6 Stop, restart, and persistence

Stop the harness with `Ctrl+C`.

Restart with the same `$DataDir`, `$ApprovedRoot`, `$ConfigPath`, and `$Port` using the same command as section 7.4.

Expected:

- completed classification reloads for the same reviewed HTML;
- a previously running classification appears as `interrupted` and is not auto-resumed;
- classified lexical jobs and Stage 3 reviews remain under the same data directory;
- a fresh classification experiment normally uses a new `$DataDir` because the workspace starts Classify only when no current classification exists for the selection.

### 7.7 Locate artifacts without exposing credentials

```powershell
Get-ChildItem -LiteralPath (Join-Path $DataDir 'page-classifications') -Recurse -Filter current-classification.json
Get-ChildItem -LiteralPath (Join-Path $DataDir 'page-classification-diagnostics')
Get-ChildItem -LiteralPath (Join-Path $DataDir 'extraction-jobs') -Filter *.json
Get-ChildItem -LiteralPath (Join-Path $DataDir 'extraction-jobs') -Recurse -Filter classification.json
Get-ChildItem -LiteralPath (Join-Path $DataDir 'extraction-reviews') -Recurse -Filter current-review.json
```

Do not open or share diagnostic bundles casually: they may contain full page HTML and model outputs. Do not print `OPENAI_API_KEY`. Do not hand-edit JSON state files to force outcomes.

## 8. Manual verification and troubleshooting

### 8.1 What evidence already covers

| Area | Evidence class |
|---|---|
| Contracts, merge, eligibility, store, diagnostics, adapter, restricted Stage 2 | **test-verified** in focused suites |
| Live classify → Extract All → reviewable Stage 3 path on local harness | **manually verified** in the recorded Stage 4 local acceptance |
| Five-bundle diagnostic retention | **test-verified** implementation boundary; recheck manually only if needed |
| Label quality / pharmaceutical correctness | **unverified** as a product guarantee |

### 8.2 Operator checklist for a new isolated run

Use a fresh `$DataDir`. Confirm:

- classification starts and shows truthful progress;
- labels, evidence, status, and eligibility are visible by page;
- `needs_review` remains informational, not an approval action;
- an exclusion-only fully verified page can be excluded from lexical selection;
- a mixed or extraction-relevant page remains eligible;
- Extract All produces separate lexical status and, when pages remain, a classified job;
- a reviewable run shows immutable classification context plus findings;
- Stage 3 Save / Remove / Restore / Download TXT / Approve retain ordinary Stage 3 behavior;
- a diagnostic bundle under `page-classification-diagnostics/<run-id>/` contains manifest, copied prompts/schemas, per-page request/response, and merged result;
- for future structured-output parse failures after the diagnostic correction, failed-call response records may retain raw rejected content and structured validation/decode information (older historical failures must not be assumed to contain that raw content).

### 8.3 Symptom map

| Symptom | Likely meaning / safe action |
|---|---|
| Classify unavailable / classifier not configured | `OPENAI_API_KEY` missing or Stage 4 composition failed. Confirm key presence without printing it; restart harness from repo root so `.env` resolves. |
| Invalid approved document | Folder identity does not match HTML provenance, or HTML is not reviewed v1. Fix placement/source export; do not hand-repair markers. |
| Classification busy | Another classifier worker is already active for this data directory in this process. Wait for completion or restart after the worker finishes. |
| Interrupted after restart | Expected for abandoned in-progress work. Not auto-resumed. Use Extract All on terminal state, or start a fresh data directory for a new classify. |
| No eligible pages | Informational success under the exclusion policy. No empty Stage 2 job is created. |
| Lexical completed but not reviewable | Extraction/publication finished without a usable completed component for Stage 3. Save/TXT/Approve stay hidden; inspect local job status and raw-run outcomes. |
| Missing/invalid classification snapshot | Classified job snapshot missing, malformed, or digest mismatch. Do not invent a snapshot; inspect `extraction-jobs/<id>/classification.json` and the job record. |
| UI looks stale after frontend changes | Rebuild with `npm --prefix frontend run build`, restart harness, hard-refresh browser. |
| Port already in use | Choose another `$Port`. |

## 9. Handoff and explicit non-goals

Stage 4 hands forward:

- current page classifications bound to reviewed-HTML identity;
- conservative eligible/excluded page selection;
- restricted lexical-run provenance when Extract All uses that selection;
- an immutable per-run classification snapshot beside each classified lexical job;
- the unchanged Stage 3 review boundary and single final approval action.

Not in this local MVP:

- production mounting or authentication;
- classifier label editing, classifier approval, or classification history;
- LLM entity extraction;
- graph, association, or recipe-assembly work;
- generic queue infrastructure;
- cross-process locking;
- automatic approvals;
- broader audit/history systems.

---

Source and verification note. Written from the accepted Stage 4 overview, current Stage 4 implementation and focused tests, local harness/API/workspace composition, and the Stage 2 page-restriction boundary. Principal areas: `src/app/page_classification/`, `src/app/extraction_review/stage4_local.py`, `local_jobs.py`, `src/app/api/extraction_reviews.py`, `tests/extraction_review/local_harness.py`, `frontend/src/components/ExtractionReviewWorkspace.vue`, `frontend/src/extractionReview.ts`, `src/app/lexical_extraction/runner.py` and `contracts.py`, `src/app/settings.py`, and focused tests under `tests/page_classification/`, `tests/extraction_review/`, and `tests/lexical_extraction/`. Commands and live classification were not executed for this documentation task.
