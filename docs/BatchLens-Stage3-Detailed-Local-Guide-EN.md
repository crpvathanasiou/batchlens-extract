# BatchLens — Stage 3: Detailed Local Execution Guide

This guide explains the implemented local Stage 3 Extraction Review Workspace and how to run it on Windows PowerShell. The shorter introduction is `docs/BatchLens-Stage3-Extraction-Review-Overview-EN.md`. This document describes the local inputs, persisted data, user workflow, and local execution procedure.

The guide reflects the accepted U1–U3 local slice. It does not describe a production deployment, authentication, duplicate-upload handling, run reuse, or an audit-history product.

## 1. Scope and status

Stage 3 consumes completed local Stage 2/L13 lexical jobs. It projects their immutable artifacts into a reviewable page-and-finding workspace, persists one current review result per local execution run, and allows a human to save and finally approve that result.

| Status | Meaning |
|---|---|
| **implemented** | Current-state review contracts, JSON store, approved-document discovery, local serialized lexical jobs, local API, Vue workspace, TXT export, and local harness exist in the repository. |
| **test-verified** | Recorded focused and repository quality checks passed for the U1–U3 local slice. |
| **manually verified** | Local tests confirmed Save, approval, refresh persistence, TXT export, post-approval invalidation by Save, and isolation between two runs of the same approved HTML. |
| **not included** | Production API mount/authentication, page classification, duplicate-upload/fingerprint/reuse workflows, LLM, graph/association work, and review-history/audit features. |

Stage 3 has exactly one final approval action: **Approve extraction result**. It does not alter Stage 1 source-document approval and does not approve individual pages, categories, or findings.

## 2. Local components and responsibilities

| Component | Principal path | Responsibility |
|---|---|---|
| Current-state contracts | `src/app/extraction_review/contracts.py` | Finding provenance, current review state, edits, approval, and bounded validation. |
| Pure state transitions | `src/app/extraction_review/transitions.py` | Initialize, Save edits, Remove/Restore, and final approval. |
| JSON store | `src/app/extraction_review/store.py` | Atomic `current-review.json` per `local_job_id`. |
| Approved-document registry | `src/app/extraction_review/approved_documents.py` | Read-only discovery and Stage 2 reviewed-HTML validation. |
| Local jobs | `src/app/extraction_review/local_jobs.py` | Persisted local Stage 2/L13 job submission, progress, terminal result, and restart recovery. |
| Workspace service | `src/app/extraction_review/workspace.py` | Opens a completed run, projects published occurrences, applies page edits, saves, approves, and formats TXT. |
| Page renderer | `src/app/extraction_review/page_html.py` | Read-only page HTML with category-distinct evidence highlights. |
| Local API | `src/app/api/extraction_reviews.py` | Harness-only routes for runs, pages, Save, approval, and TXT. |
| Vue workspace | `frontend/src/components/ExtractionReviewWorkspace.vue` | Run selector, page navigation, findings, edits, category visibility, Save, TXT, and approval UI. |
| Local harness | `tests/extraction_review/local_harness.py` | Localhost server; optionally validates, runs, and opens a new local lexical job. |

Stage 2 remains responsible for deterministic matching, immutable component artifacts, final manifests, execution/publication outcomes, aliases, and matching rules. Stage 3 does not re-run matching while reviewing.

## 3. Local directory model

### 3.1 Approved document root

The local registry reads an approved reviewed HTML file from this layout:

```text
<approved-documents-root>/
  <job_id>/
    <review_revision_id>/
      document.html
      review.json                 optional; ignored by U2.1
```

The folder `job_id` and `review_revision_id` must agree with the provenance markers in `document.html`. The file is read-only to Stage 3.

### 3.2 Local data directory

The local harness writes only under its selected data directory:

```text
<data-dir>/
  extraction-jobs/
    <local-job-id>.json
  extraction-raw-runs/
    <stage2-run-id>/
      manifest.json
      artifacts/...
  extraction-reviews/
    <sha256(local_job_id)>/
      current-review.json
```

`extraction-raw-runs` contains immutable Stage 2/L13 output. `current-review.json` contains the one current saved review state for one local job. It is atomically replaced on effective Save or approval; it is not a history chain.

Two local jobs may reference the same approved HTML. They still use separate review directories because their `local_job_id` values differ.

## 4. Input rules and execution choices

The harness accepts one eligible reviewed HTML document and one existing Stage 2 execution YAML. It passes in-memory overrides to Stage 2 for the selected reviewed HTML, selected action, fuzzy flag, and output root. The YAML file itself is not rewritten.

The available actions are:

| Harness action | Stage 2 preset |
|---|---|
| `unit_operations_with_steps` | Unit operations and process steps |
| `materials_with_quantities` | Materials, quantities, and units |
| `equipment_with_parameters` | Equipment, parameters, values, and units |
| `full` | All Stage 2 V1 components |

Fuzzy matching is optional and defaults to off. A completed run, including a published partial run, is never automatically approved.

The configured knowledge snapshot directory must contain the four Stage 2 snapshot companions:

```text
knowledge.sqlite
manifest.json
validation_report.json
FLAT_SQLITE_CONTRACT.md
```

## 5. Current review semantics

### 5.1 Save and approval

A current review state contains the complete finding list, immutable document/run binding, a current revision ID, and either no approval or one current approval.

- **Save** applies effective page edits, allocates a new current revision ID, and clears prior extraction-result approval.
- **Approve extraction result** approves the exact current saved revision. It changes no findings and no Stage 2 execution outcome.
- Unsaved changes remain only in the browser. The UI disables approval and TXT download while the state is dirty.
- A stale Save request is rejected rather than overwriting a newer saved revision.

There are no Stage 3 revision lists, approval ledgers, retry ledgers, SQLite storage, or automatic merge of edits.

### 5.2 Findings

In **By page** mode, the user can add, edit, remove, and restore findings for the current page.

- A lexical finding retains immutable original matched text and Stage 2 evidence after a user edit.
- A new manual finding is assigned to the current page and is marked `no_document_evidence`.
- A new manual finding does not get an invented node/span or a highlight.
- Remove creates a muted restoreable tombstone in current state. Restore activates the same finding and retains its origin/evidence.
- **All findings** is active-only and read-only. Selecting an item navigates to its page.

### 5.3 Highlights and TXT

The category legend controls only presentation. Unit Operation, Material, Equipment, and Other may be hidden or shown independently. The setting is not saved and refresh returns all categories to visible.

TXT export reads the saved state, not browser drafts. It groups active findings by category; within a category it follows page order and then saved finding order. Unassigned findings appear after page-assigned findings. Removed findings are excluded. A manual addition is marked `[no document evidence]`.

## 6. Local API surface

The following routes are mounted only by the local extraction-review harness:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/extraction-reviews/jobs` | List completed local extraction runs. |
| `GET` | `/api/v1/extraction-reviews/jobs/{local_job_id}` | Open one run and its saved/initialized review. |
| `GET` | `/api/v1/extraction-reviews/jobs/{local_job_id}/pages/{page_number}` | Read one rendered reviewed-HTML page. |
| `PUT` | `/api/v1/extraction-reviews/jobs/{local_job_id}` | Save page-scoped edits. |
| `POST` | `/api/v1/extraction-reviews/jobs/{local_job_id}/approve` | Approve the current saved extraction result. |
| `GET` | `/api/v1/extraction-reviews/jobs/{local_job_id}/results.txt` | Download the saved active findings as text. |

The local harness uses the test actor `local-test-reviewer`. It is not production authentication.

## 7. Local execution guide — Windows PowerShell

### 7.1 Prerequisites

Run commands from the repository root, for example:

```text
C:\Users\User\batchlens-extract
```

Activate the existing Poetry environment and confirm the frontend toolchain:

```powershell
& .\.venv\Scripts\Activate.ps1
poetry run python --version
node --version
```

The frontend build requires Node `22.12` or later. Use a compatible Node installation before building the harness assets.

### 7.2 Set the local paths

Use a reviewed HTML file that already has valid Stage 1 reviewed-HTML provenance. Read the `data-job-id` and `data-review-revision-id` from its `<html>` tag; do not invent them.

```powershell
$SourceHtml = 'C:\path\to\reviewed-document.html'
$JobId = 'job-id-from-the-html-root'
$ReviewRevisionId = 'review-revision-id-from-the-html-root'
$SnapshotDir = 'C:\path\to\flat-snapshot-directory'

$ApprovedRoot = "$PWD\.local-extraction-approved"
$ApprovedDir = Join-Path $ApprovedRoot "$JobId\$ReviewRevisionId"
$DataDir = "$PWD\.local-extraction-review-data\first-run"
$ConfigPath = "$PWD\manual-input\extraction-review-local.yaml"
```

Confirm the source file and snapshot companions before copying or running anything:

```powershell
Test-Path -LiteralPath $SourceHtml -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir 'knowledge.sqlite') -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir 'manifest.json') -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir 'validation_report.json') -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir 'FLAT_SQLITE_CONTRACT.md') -PathType Leaf
```

Expected: all five values are `True`.

### 7.3 Prepare the approved-document folder and working YAML

Copy the reviewed HTML; never edit it in place. Copy the checked-in Stage 2 YAML example and change only the snapshot directory in the working copy.

```powershell
New-Item -ItemType Directory -Force $ApprovedDir, (Split-Path $ConfigPath) | Out-Null
Copy-Item -LiteralPath $SourceHtml -Destination (Join-Path $ApprovedDir 'document.html') -Force
Copy-Item -LiteralPath '.\examples\lexical_extraction\execution-config.example.yaml' -Destination $ConfigPath -Force

(Get-Content -LiteralPath $ConfigPath -Raw).Replace(
  'snapshot_directory: ./knowledge/flat-v1',
  "snapshot_directory: '$SnapshotDir'"
) | Set-Content -LiteralPath $ConfigPath -Encoding utf8
```

The harness supplies the selected HTML, selected action, and local raw-output directory in memory. Do not point the YAML output at the snapshot directory.

### 7.4 Build the browser bundle

Run this after any accepted frontend change, before starting the harness:

```powershell
npm --prefix frontend run build
```

Expected: Vite writes the local harness bundle under `src/app/document_review/static/`. These generated files are build output, not a separate source implementation decision.

### 7.5 Run extraction and open the workspace

Choose one action. The following example runs all components. Paste the command without the PowerShell continuation prompts (`>>`).

```powershell
poetry run python -m tests.extraction_review.local_harness `
  --data-dir $DataDir `
  --approved-documents-root $ApprovedRoot `
  --job-id $JobId `
  --review-revision-id $ReviewRevisionId `
  --config $ConfigPath `
  --action full `
  --run-extraction `
  --port 8767
```

Expected output includes a newly submitted `local-job-id`, the selected data directory, and:

```text
URL: http://127.0.0.1:8767/documents/local-extraction-review
```

Open that URL. In `--run-extraction` mode the browser opens the exact submitted run through `initialLocalJobId`. Leave the PowerShell process running while using the UI. Use `Ctrl+C` to stop the harness.

### 7.6 Reopen completed runs without running extraction again

To inspect data already created in the same `$DataDir`, start the harness without `--run-extraction`:

```powershell
poetry run python -m tests.extraction_review.local_harness `
  --data-dir $DataDir `
  --approved-documents-root $ApprovedRoot `
  --port 8767
```

Open the URL printed by the harness, then choose an entry from the **Extraction run** selector. This command does not start a new Stage 2 run.

### 7.7 Run the same HTML again

To intentionally create a second execution run of the same HTML, repeat section 7.5 with the same `$DataDir`. The new run has a new `local_job_id`. Its review is independent: it starts unapproved and does not inherit manual changes or approval from the first run. The selector lets the user return to the first run.

## 8. Troubleshooting

| Symptom | Meaning / safe action |
|---|---|
| No completed extraction runs | Confirm the job reached a published terminal result. Run with `--run-extraction` or inspect the selected data directory. |
| Reviewed document rejected | Check the copied `document.html`, its Stage 1 provenance attributes, and that the folder identity matches the HTML root identity. Do not edit the file to force acceptance. |
| Snapshot failure | Confirm all four snapshot companions exist and point at the snapshot directory, not at `knowledge.sqlite` itself. |
| UI shows an older bundle | Stop the harness, run `npm --prefix frontend run build`, restart the harness, then hard refresh the browser. |
| Save/Approve fails after another browser action | Reload the run and review the current saved state; stale writes are rejected rather than overwritten. |
| Manual addition has no highlight | Expected. It is page-assigned but has no document evidence node/span. |
| Two runs appear in the selector | Expected when the same HTML was run more than once. They are distinct extraction runs, not duplicate documents. |
| Old local review does not appear after the per-run store change | Expected for a source-`job_id` keyed local file created before this correction. It was not migrated or deleted. Use a newly created run for current local acceptance. |

## 9. Handoff and future boundary

Stage 3 hands forward a human-reviewed current extraction result that remains bound to a particular completed Stage 2 run and reviewed HTML provenance. Its final approval says only that the current saved extraction result for that run was approved by the local reviewer.

It does not say that every possible component was requested, that a finding is pharmaceutically correct, that a batch was executed, or that Stage 1 source-document approval was reissued. Future work must separately authorize production auth/storage, page classification/policy, duplicate detection and run reuse, LLM extraction, graph/association work, and audit/history capabilities.
