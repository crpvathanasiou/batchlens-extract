# BatchLens — Stage 3: Extraction Review Workspace

## 1. Purpose and boundaries

Stage 3 lets a person inspect, correct, save, and approve the lexical extraction result for one completed execution run. It starts from a completed, published Stage 2/L13 local job and its reviewed HTML input. It ends when the user has either saved the current extraction result or approved that saved result.

Stage 3 is a review workspace. It does not run a second extractor, reinterpret Stage 2 matches, or prove a pharmaceutical fact. Stage 2 remains the independent deterministic Lexical Extraction Engine. Stage 1 approval of the source HTML also remains separate: Stage 3 approves an extraction result, never the source document.

The current implementation is a local U1–U3 slice. It is implemented, test-verified, and manually verified through the local harness. It is not a production-mounted or authenticated workflow.

## 2. What the user can do

1. Select a completed **Extraction run** for an eligible reviewed HTML document.
2. Inspect the reviewed HTML page on the left and the findings on the right.
3. Navigate by page, or use **All findings** to locate a finding on its assigned page.
4. Add, edit, remove, and restore findings in **By page** mode.
5. Save changes and return later to the same execution run.
6. Download the saved active findings as a plain-text report.
7. Use the one final action, **Approve extraction result**, when the saved result is satisfactory.

There are no page approvals, component approvals, individual finding approvals, automatic approvals, or approval dependencies.

## 3. The review result and approval

Each run has one current review state: its complete current finding list, immutable source/run provenance, a current revision identifier for stale-save detection, and either no approval or one approval of that current saved revision.

Save applies only committed edits. A successful effective Save creates a new current revision token and clears any existing extraction-result approval. Approval does not alter findings or extraction outcomes. Unsaved browser edits cannot be approved.

Stage 3 deliberately has no review revision history, approval ledger, version list, SQLite review database, automatic merge, or automatic transfer of edits from one run to another.

## 4. One review state per execution run

The same approved HTML may be processed more than once. Each completed lexical execution is a separate **Extraction run**, with its own `local_job_id` and its own current saved/approved review state:

```text
<data-dir>/extraction-reviews/<sha256(local_job_id)>/current-review.json
```

This prevents two runs of the same source HTML from overwriting or conflicting with each other. The run selector therefore shows runs, not duplicate documents. It distinguishes them by requested action, outcome, finished time when available, and a short local-job suffix.

This is not yet a duplicate-upload detector, an execution-fingerprint system, a cache/reuse workflow, or a historical result browser.

## 5. Findings and evidence

Imported lexical findings retain their original matched text and Stage 2 evidence: component, occurrence identity, page/block/span where supplied, and immutable source provenance. A user correction changes the current user-facing value without replacing that origin.

A user-added finding is assigned to the current page, but has `no_document_evidence`. It does not receive an invented node, span, or left-pane highlight merely because the same text happens to appear in the page. A removed finding remains a restoreable tombstone in the current state; removal is an edit, not a rejection workflow.

## 6. Viewing and highlights

The left pane renders the reviewed HTML read-only. The right pane offers:

- **By page** — the current page’s findings, including editing controls.
- **All findings** — active findings across the run, read-only; selecting one opens its page.

The legend controls category visibility for Unit Operations, Materials, Equipment, and Other lexical categories. A category toggle hides or restores that category’s right-pane rows and left-pane overlays. It is browser-session presentation state only: it does not create a draft, call the API, or change saved data. Selecting a finding focuses its evidence; it does not toggle visibility.

## 7. Outputs and current boundary

**Download TXT** produces a report from the saved current state only. It groups active findings by category and document order, excludes removed findings, and marks user additions without document evidence.

The local harness can validate an approved HTML, start a local Stage 2 job, wait for it, and open the exact submitted run in the Stage 3 UI. It stores local job metadata and immutable raw Stage 2/L13 output separately from the current review state.

Future work, deliberately outside this mini-project, includes production API mounting/authentication, page classification and page-policy exclusion, duplicate-upload detection, execution fingerprints/reuse, LLM extraction, graph/association work, and review/audit history.
