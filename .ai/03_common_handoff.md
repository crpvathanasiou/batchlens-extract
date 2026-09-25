# 03 — Common Handoff

## 1. Current state — 2026-09-25 Flat knowledge SQLite

**Implemented** as a standalone preparation utility. The earlier normalized design
(`terms`, `lexical_entries`, `entry_sources`, `source_records`) was not built and is
superseded. There is one flat table per source CSV. The lexical extraction engine is
**not implemented**.

- `scripts/prepare_lexical_knowledge_sqlite.py` streams the four current final CSVs into
  `knowledge.sqlite` (`PRAGMA user_version` 1, preparation `flat-sqlite-1`). Every source
  column is `TEXT NOT NULL`. `row_id` is the primary key. Empty cells stay empty strings.
  Fully blank records are counted and skipped; this snapshot skipped none. No foreign keys,
  extra columns, or second search index.
- Consumer contract: `docs/FLAT_SQLITE_CONTRACT.md`, copied into a snapshot at publication.
  The already published snapshot keeps the contract text it was built with.
- Pytest can import the script because `pyproject.toml` sets `pythonpath = ["scripts"]`.
- CSV reading uses the standard parser with `strict=True`. An unterminated quote is
  `MALFORMED_RECORD`. An oversized field remains `FIELD_TOO_LARGE`.
- Reuse requires `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and a
  nonempty `FLAT_SQLITE_CONTRACT.md`, plus report evidence that matches the manifest
  table counts. An incomplete snapshot is left in place; a new run writes a separate
  directory. Reuse does not compare the stored contract or producer hash with later code.

**Test-verified** in this correction pass: `scripts/quality.ps1` passed — Ruff check, Ruff
format check (69 files already formatted), Pyright 0 errors / 0 warnings / 0 informations,
pytest **270 passed**. Focused `tests/test_prepare_lexical_knowledge_sqlite.py` is included
(10 tests). A read-only smoke test of the published snapshot opened `mode=ro` with
`PRAGMA query_only=ON`, read two batches of five rows from each table, and matched each
chosen `row_id` lookup to that scan row. Database hash and companion hashes were unchanged
and no WAL sidecar appeared. Pyright also printed the pre-existing missing-file notices for
`merge_files.py`, `merge_files1.py`, `merge_files2.py`, `extract_chebi_materials.py`, and
`compare_material_names.py`; those notices did not fail the gate. The production build below
was not rerun. Human acceptance of the snapshot remains pending.

Published snapshot (sources unchanged; content digests match; `PRAGMA integrity_check` ok;
no WAL sidecar):

`C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed`

| Table | Rows | Columns | Source bytes |
|---|---:|---:|---:|
| `materials_fda_ema` | 1,111,030 | 12 | 186,152,422 |
| `materials_chebi` | 604,363 | 13 | 166,345,767 |
| `equipment` | 415 | 14 | 186,240 |
| `unit_operations` | 2,597 | 37 | 2,324,980 |

Database size 441,327,616 bytes. SHA-256
`cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2`.
Build elapsed 71.2 seconds inside the publisher. Batch size 5,000. Cache 65,536 KiB.
Journal `DELETE`, synchronous `FULL`. Peak working set 112,705,536 bytes by Windows
`GetProcessMemoryInfo` (`windows_psapi_peak_working_set`).

Those row, column, and byte counts match the 2026-09-25 profile reference. The profile
JSON still names historical `*_enhanced.csv` paths; this build used the current filenames
in the flat-SQLite prompt, and those files have the profile's byte sizes. `row_id` lookup
uses each table's `sqlite_autoindex_*`.

The three previously discussed unit-operation wordings are still stored as
`direct_candidate` / `Index this row` `TRUE`, with scope
`Manufacturing process text; Category is not an exclusion filter`
(`cell culture expansion` UO-029, four rows; `liquid bottle filling` UO-072, three rows;
`controlled rate freezing` UO-098, four rows). They were not edited.

**Not done:** lexical search, document matching, and human acceptance of this snapshot.
Import success is not pharmaceutical correctness.

**Next safe step:** review the snapshot contract, manifest, and validation report. Do not
implement the lexical engine from this preparation. Unrelated pending work remains the
reviewed-HTML provenance browser check and the Findings default manual verify below.

---

## 1e. Prior current state — 2026-09-25 Reviewed HTML provenance attributes

**Implemented** in `src/app/document_review/rendering.py` only. Newly rendered reviewed HTML
carries non-visible attribute contract version 1 so a later lexical reader can locate evidence.
The lexical engine itself is **not implemented**.

- Root `<html>`: `data-review-html-version="1"`, `data-job-id`, `data-review-revision-id`,
  `data-review-generation`, `data-conversion-status` from the supplied revision.
- Catalogue identities, resolved by physical page and structural path: `data-element-id` on
  each `article.element`, `data-node-id` on rendered element text, titles, cells, and footers,
  and `data-table-id` on each `<table>` (the owning element node).
- `data-source-id` is that node's own ordered, de-duplicated OCR block IDs. Empty reference
  lists omit the attribute. A missing or ambiguous catalogue node raises `ReviewError`
  `INVALID_REVIEW_STATE` (HTTP 409 if it surfaces through approval). `approve` renders before
  `put_export` and `_persist`, so a render failure does not publish a head.
- `data-generated="true"` marks the summary header, the partial-conversion banner, and each
  `Page N` heading. Source headings and footers are unmarked.
- Visible text is the current revision text. Previously approved export bytes are not rewritten.

**Test-verified** in this pass: `scripts/quality.ps1` passed — Ruff check, Ruff format check
(67 files already formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **260 passed**.
Focused `tests/document_review/test_rendering.py` plus `tests/document_review/test_backend_review.py`
were green before the full gate (24 tests). Pyright also printed pre-existing missing-file notices
for `merge_files.py`, `merge_files1.py`, `merge_files2.py`, `extract_chebi_materials.py`, and
`compare_material_names.py`; those notices did not fail the gate. Manual browser acceptance of the
new attributes is **unverified**.

**Not done:** lexical extraction, highlighting, search JavaScript, review JSON schema changes,
mapping/ID changes, and any rewrite of historical exports. HTML metadata is not proof of
authenticity or regulatory compliance. Source references identify original OCR blocks; displayed
text may include reviewed corrections.

**Client fix (2026-09-25, implemented):** `approvePage()` and `approveDocument()` clear
`state.error` only after a response passes `isReviewState`, is not stale or a generation
conflict, and `prepareProjection` / `applyPrepared` succeed. A prior `REVIEW_NOT_READY` banner
no longer remains after a later successful Approve & Export. Conflicts, malformed responses,
projection failures, and pending/blocked states still keep their errors. Backend and HTML
provenance attributes were not changed. Focused regression is in `frontend/tests/state.test.ts`.
Host `npm --prefix frontend run typecheck` failed: `vue-tsc` is a Unix shim, not a Windows
command. `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` in `frontend/` exited 0 on Node
20.18.0. `vitest` then failed because `@rolldown/binding` is missing (this `node_modules` is
not a Windows install). Docker Desktop was started, but the daemon was still down after three
minutes, so the Node 22.12 container path was not run. The new test and `npm test` / `npm run
build` are **unverified** in this session.

**Next safe step:** user browser verification of the isolated harness checklist in §2, including
that a failed Approve & Export banner disappears after a later successful approval. Do not
reset protected review directories. Unrelated pending work remains the Findings default manual
verify and the Unit Operations production CSV authorization below.

---

## 1c. Prior current state — 2026-09-24 Flat Unit Operations CSV builder (utility only)

This is the cross-session restart anchor. Repository code and tests are the source of truth for
implementation. Existing local-harness evidence is the source of truth for manually verified
review behaviour. Do not treat planned work as implemented.

### Unit Operations flat consolidation (2026-09-24)

**Implemented** (code + synthetic tests only; production CSV run **not** authorized):

- `scripts/build_unified_unit_operations.py` — stdlib builder that joins
  `uo_unified_table.csv`, `uo_lexical_terms.csv`, and `uo_operation_links.csv` into one flat
  denormalized `Unified_Unit_Operations.csv` (**37** scalar columns). Row grain is one combination
  of main-table step row × assigned lexical row × incident link row; generic blank-ID step cues
  append separately. Stable entity IDs (`row_id`, `category_id`, `process_step_id`,
  `lexical_term_id`, `source_evidence_id`, `link_id`) are deterministic SHA-256 prefixes;
  construction ordinals are internal only and are not output columns. `Operation ID` remains the
  unit-operation identifier (no duplicate column). Defaults point at the Desktop Unit-Operations
  directory; CLI is `--input-dir` / `--output`.
- `tests/test_build_unified_unit_operations.py` — focused temporary-fixture coverage
  (multiplication, missing terms/links, generic cues, link directions, Unicode/multiline,
  conflict/output preservation, shared entity IDs, collision failure, CLI). **Test-verified** on
  synthetic inputs only (19 passed after the stable-ID supplement).

**Not done in this pass:** production consolidation against the Desktop source CSVs;
`Unified_Unit_Operations.csv` creation from those inputs; dictionary updates; lexical search;
RAG. Do not run the production command until the user explicitly authorizes it.

**Next safe step for this utility:** user review of the builder, then an explicit separate
authorization to run the production command. Unrelated product next step remains Findings
default manual verify / prior handoff items below.

---

## 1b. Prior current state — 2026-09-18 Findings filter default: This page

The sections below retain the previous conversion/review handoff. They were not re-executed in
the Unit Operations builder pass.

### Product

**BatchLens Extract** has two core product legs.

1. **Evidence-preserving document preparation and review — CURRENT / IMPLEMENTED in this
   repository; not production-qualified.** Flow:

   ```text
   source PDF
     → Textract raw result (textract.json)
     → Textractor/conversion
     → canonical document.json + unreviewed HTML
     → human review / revisions / approvals
     → reviewed HTML/JSON exports
   ```

   The review workspace supports text-only corrections. Document structure, table identities,
   geometry, and protected source relationships must remain protected. Current document-review
   approval is not batch release, regulatory release, or a 21 CFR Part 11 electronic signature.

2. **Pharmaceutical information extraction — APPROVED TARGET / not implemented.** Extract
   pharmaceutical facts, recipe/process data, and other structured information from the reviewed
   document, preserving evidence and provenance links to the source document and reviewed
   revision.

A later rules capability may evaluate extracted facts against versioned FDA, EU, or customer
rules. That layer is **not implemented** and must not drive premature architecture. **BatchLens
Audit** remains a separate planned tool ([00](00_project_reference.md),
[08](08_check_selection_strategy.md)).

### Implementation status

**Implemented** (code present in the working tree; conversion and review are feature-flagged and
disabled by default in `create_app`):

- FastAPI foundation: `/health`, `/ready`, `/version`
- Conversion: AWS Textract SDK boundary, Amazon Textractor 1.10.0, durable DynamoDB/S3/SQS job
  FSM, Cognito-owned upload/jobs shell, canonical `document.json` + unreviewed HTML
- Review: Vue 3, TipTap 3, PDF.js workspace; backend under `src/app/document_review/`; review API
  routes; revision, decision, approval, validation, mapping, and export logic; intended
  production composition using Cognito `sub`, DynamoDB review heads/conditional writes, and
  versioned S3 review artifacts
- Local review harness under `tests/document_review/`
- A1 Save operation identity is the agreed working baseline. HTTP `PUT /review` still returns
  top-level `ReviewState`. Optional request `operation_id`; committed `save_operation` metadata
  on new `DRAFT_SAVED` envelopes (`schema_version` 1.1.0); server fingerprint v1; committed-chain
  replay; explicit `TextChange.origin` / `finding_id` for new changes; internal
  `update_with_receipt` and `reconcile_save_operation`. Legacy omitted/null operation IDs keep
  existing conflict behaviour and do not receive fabricated operation metadata. Isolated
  local HTTP Save/retry verification is recorded below.
- A2 browser Save identity/recovery (implemented; safety-corrected then F1–F3 follow-up
  2026-09-18; **manually accepted** in the preceding session against the isolated 8766
  checklist: ordinary Save/reload, real post-commit lost-response recovery, reload recovery,
  page-approval invalidation, tolerance suggestions, and same-directory harness restart).
  The original A2 contracts remain. Additional safety in force in the browser: exclusive
  action reservation before the first await; outcomes bound to captured workspace generation,
  context, and operation; current-key corrupt/actor-mismatch records are preserved and block
  mutation rather than being overwritten; runtime validation of pending records, ReviewContext,
  OperationLookup, and consumed ReviewState fields, including coherent lookup head/receipt
  relationships; known-commit versus pre-dispatch versus uncertain network outcomes;
  matching-record cleanup only; attempted-work presentation of text changes and finding
  decisions; revalidated context after terminal lookup/state GET before apply, disposition, or
  cleanup; in-session uncertainty preserved when metadata writes fail; recovered records
  are not treated as first-attempt-safe for a later 422. Recovery remains sessionStorage,
  same-tab, storage available. Automatic retirement remains only after exact guarded PUT
  confirmation, safe state application, and successful matching cleanup, or after explicit
  disposition with terminal proof. No operation TTL or multi-tab coordination. The local
  harness writes a derived `history.jsonl` after successful publication; A2 does not use
  it for Save reconciliation.
- B1 committed-history projector (2026-09-18 C2 frozen-head integrity; **user-accepted**
  after a separate isolated local-review regression: Save/reload, approval invalidation,
  suggestions, final export). Pure fail-closed in-memory projection of one frozen
  published `ReviewHead` parent chain (`src/app/document_review/history.py`,
  `project_committed_history`). Derived output only; it does not publish heads, mutate
  revisions, or verify source/raw/export bytes. Coverage states completeness through the
  supplied head revision/generation. Causal order is generation plus validated parent
  links; `revision_created_at` is envelope `created_at` (server revision creation before
  conditional head publication), not the publication instant. The frozen head's status,
  document approval, and export pointers must equal the top revision it points to; a
  mismatched supplied head is `INVALID_REVIEW_STATE`. Unpublished CAS candidates are
  excluded. Legacy missing `origin` remains `UNKNOWN`. Copied-forward finding
  decisions/approvals are not re-emitted. A derived `DERIVED_OUTCOME` invalidation is
  emitted only when a prior page/document approval is **absent** in the next snapshot; a
  repeated Approve page / Approve & Export grant is a later grant, not an invalidation.
  `DOCUMENT_APPROVED` without that revision's approval and stored HTML/JSON export
  pointers is `INVALID_REVIEW_STATE`. Present approvals whose content/document hashes do
  not match the current snapshot fail closed. Not a second record store and not a
  wire/API feature.
- B2a atomic `history.jsonl` materialisation (2026-09-18 C1 I/O normalisation;
  **accepted** as the test-verified derived-file primitive): `src/app/document_review/history_jsonl.py`
  writes one UTF-8 JSONL file from a successful B1 projection. The first line is
  `HISTORY_COVERAGE` (schema `batchlens.committed-history.jsonl.v1`) embedding B1 coverage
  through the named revision/generation; following lines are chronological
  `COMMITTED_TRANSITION` records. Same-directory exclusive temp, fsync, then replace.
  Any failure to prepare or write the final target path is
  `HistoryJsonlError(code="HISTORY_JSONL_WRITE_FAILED")`, never a raw `OSError`, and does
  not report coverage. A previous valid final file is left untouched. After a successful
  replace, leftover-temp cleanup is best-effort. Status is `CURRENT` / `STALE` /
  `INVALID_OR_MISSING`. Not an authority and not used for Save reconciliation.
- B2b local published-history rebuild (2026-09-18; **proposed-and-testable locally**;
  test-only harness/adapter): after `LocalReviewStore.publish` atomically publishes a
  `ReviewHead`, the adapter rebuilds `data-dir/history.jsonl` from that head via B2a.
  Startup inspects B2a status and rebuilds when `INVALID_OR_MISSING` or `STALE`; a
  `CURRENT` file is not rewritten merely because the harness restarted. No published
  head means no fake empty history file. A failed conditional publish does not
  materialise. Rebuild happens after the authoritative head write, so failure cannot
  roll back the committed revision; the caller receives
  `LOCAL_HISTORY_REBUILD_FAILED` (HTTP 503 on the local harness) rather than a normal
  Save/approval `ReviewState`. One structured operational log event records only safe
  correlation fields (event, job id, revision id, generation, history path, trigger
  `publish`/`startup`, error code/type). Supported model: one local harness process per
  `--data-dir`. The in-process `RLock` is not a directory lock and does not provide
  multi-process writer safety. Not wired into production cloud persistence, HTTP history
  routes, or the browser.
- HITL editor-boundary corrections (2026-09-16; still in the working tree): protected table
  `sourcePath` / `rows` / `columns`; page `setContent` failure reporting; single-application
  tolerance replacement handling; heading mapping for canonical `title` / `section_heading`;
  stable table-cell `data-source-cell` identity and node-decoration highlighting
- Later UI work present in code and frontend tests (not claimed as visual browser verification
  unless listed under manually verified): Vite `process.env.NODE_ENV` browser-bundle define;
  document status label; `Document findings` / `Page findings` counts; short accessible
  decision-button help text; immediate pending/recorded finding-decision feedback;
  Findings scope default **This page** (2026-09-18; `scope` ref initialises to `'page'`;
  an explicit **All warnings** choice is preserved across page navigation; empty pages
  keep `No findings in this view.` and do not fall back to document-wide findings)

**Test-verified** (latest executed gates: 2026-09-18 Findings filter default This page):

- Frontend (this Findings-default pass), `node:22.12-bookworm-slim` review-builder
  `batchlens-review-builder:findings-scope`: `npm --prefix frontend run typecheck` passed;
  focused `npm --prefix frontend test -- tests/findings-panel.test.ts` **15 passed**;
  complete `npm --prefix frontend test` with host `out/` mounted **100 passed**
  (12 files). First complete-suite run without `out/` failed `sample-roundtrip.test.ts`
  (`ENOENT` for the excluded comparison sample); that failure is not a product defect.
  `docker build --target review-builder` emitted `review.js`, `review.css`, and the
  PDF worker; assets copied into `src/app/document_review/static/`. Docker Python
  image, host npm, harness restart, OCR, and full-repo pytest were not run in this pass.
- Historical 2026-09-18 B2b local published-history rebuild: focused B1+B2a+local-history
  **51 passed**; `poetry run pytest tests/document_review/` **104 passed**; ruff/pyright
  clean. Those totals are not this Findings-default run.
- Historical 2026-09-18 B2a-C1 I/O normalisation: focused history tests **36 passed**;
  `poetry run pytest tests/document_review/` **95 passed**; ruff/pyright clean. That total
  is not this B2b run.
- Historical 2026-09-18 B2a JSONL materialisation: focused history tests **34 passed**;
  `poetry run pytest tests/document_review/` **93 passed**; ruff/pyright clean. That total
  is not this C1 run.
- Historical 2026-09-18 B1-C2 frozen-head integrity: focused history tests **19 passed**;
  `poetry run pytest tests/document_review/` **78 passed**; ruff/pyright clean. That total
  is not this B2a run.
- Historical 2026-09-18 B1-C1 correction: focused history tests **16 passed**;
  `poetry run pytest tests/document_review/` **75 passed**; ruff/pyright clean. That total
  is not this C2 run.
- Historical 2026-09-18 B1 projector implementation: focused history tests **10 passed**;
  `poetry run pytest tests/document_review/` **69 passed**; ruff/pyright clean. That total
  is not this C2 run.
- Historical 2026-09-18 A2 F1–F3 follow-up: `poetry run ruff check src tests` passed;
  `poetry run ruff format --check src tests` passed (59 files already formatted);
  `poetry run pyright` 0 errors/0 warnings/0 informations; `poetry run pytest` **206 passed**.
  Frontend in `node:22.12-bookworm-slim` with the existing lockfile: `npm run typecheck`
  passed; `npm test` **94 passed**; `npm run build` emitted `review.js`, `review.css`, and a
  local PDF.js worker into `src/app/document_review/static/`. Those totals are not this B1 run.
- Historical 2026-09-18 A2 pending-Save safety correction: Python **206 passed**;
  frontend **84 passed**. Those totals are not this follow-up's run.
- Historical 2026-09-17 A2 implementation pass: Python **206 passed**; frontend **57 passed**.
  Those totals are not this follow-up's run.
- Historical 2026-09-17 A1 acceptance-closure pass: Ruff passed, 58 files formatted, Pyright
  0/0, 199 Python tests passed; focused A1 `test_save_operations.py` plus
  `test_backend_review.py` 42 passed. That total is not this A2 run.
- Historical 2026-09-17 A1 implementation pass: Ruff passed, 58 files formatted, Pyright 0/0,
  189 Python tests passed; focused A1 32 passed. That total is not this run.
- Historical 2026-09-16 HITL correction pass: Ruff passed, 57 files formatted, Pyright 0/0, 152
  Python tests passed. 148 is historical from the HITL implementation session; 134 remains
  historical conversion evidence. Those totals are not this session's run.
- Frontend in `node:22.12-bookworm-slim` (historical 2026-09-16): typecheck passed, 23 tests
  passed (was 11 before that correction pass). That total is not this A2 run.
- Real `document.json` from `out/comparison/fexofenadine-textractor-20260916-173938/` loaded
  through the production TipTap extension list: all 18 pages passed projection → editor →
  structural validation with no sparse text changes. Sequential page loads including 18 → 1
  showed only that page's source IDs. The sample was not committed. That check is not browser
  acceptance.

**Manually verified locally** (user, local harness, localhost only; supplied originals
untouched):

- Side-by-side source PDF and editable converted document
- Synchronized page navigation, pagination, and PDF zoom
- Text editing
- Save draft with successful `PUT .../review`
- Persistence after browser reload, hard reload, and harness restart
- Findings filters
- Pending and recorded finding-decision feedback
- Page approval
- Approval invalidation after edit and save
- Final export rejection while unresolved or unapproved work remained
- Successful final reviewed HTML and JSON downloads after completion
- A deliberate test edit remaining in both reviewed exports

**User-accepted** (preceding session, 2026-09-18, isolated 8766 A2 checklist; not re-executed
in this B1 pass):

- Ordinary Save draft then F5 retained the text and left editing available
- Real post-commit lost-response recovery via Check save status
- Reload recovery with an outstanding pending record
- Page-approval invalidation after a subsequent saved edit
- Page-5 tolerance suggestions when applicable
- Same-directory harness restart retained existing semantics

**User-accepted** (2026-09-18, isolated local-review B1 regression; not re-executed in this
B2b pass): Save/reload, approval invalidation, suggestions, and final export. B1 is locked
except for a defect discovered directly in a later authorised task.

**User-reported** (2026-09-17, completed review on
`.local-review-data/fexofenadine-local-current`; not independently re-executed here; not
A1 human acceptance):

- Both page-5 tolerance suggestions were applied and saved
- Both corrections survived browser reload
- Page approval and Approve and export succeeded
- Both corrections appeared in the downloaded HTML and JSON
- After harness restart, the corrections, Approved state, and export downloads remained
  available

**Not deployed / not integration-verified:**

- Real Cognito authorization
- DynamoDB conditional writes against AWS
- S3 versioning
- AWS/IAM deployment or CloudFormation apply
- Production qualification
- 21 CFR Part 11 or other regulatory compliance
- Visual browser verification of the latest cosmetic UI (status label, findings counts,
  decision-button help text)

**Future / not implemented:**

- Pharmaceutical extraction (leg 2)
- Recipe graph visualization
- Rules / Audit evaluation
- Deliverable B2c/later production history publication, operator UI, retry policy,
  centralized operational logging, concurrent writers/process crashes, backup/restore,
  referenced artifact byte checks, retention/access control (B2b is local single-process
  harness wiring only)
- Persistent audit/observability ledger (direction recorded below; A1 reuses the committed
  revision chain and does not add a ledger)
- Multi-tab coordinated editing, recovery after tab close/storage clearing/private-mode
  restrictions, and independently writable clones of one store (A2 same-tab sessionStorage
  only)

### Local harness purpose and boundaries

`tests.document_review.local_harness` is development/test-only. It reuses the actual review
service, API routes, validation, mapping, frontend bundle, and export logic. It substitutes only
external identity and storage. It uses synthetic reviewer `local-test-reviewer` and synthetic
completed job `local-fexofenadine`, binds to `127.0.0.1`, persists generated review state under
`.local-review-data/` (gitignored), and leaves the supplied original PDF, `document.json`,
`textract.json`, and `document.html` untouched.

It does not verify real Cognito authorization, DynamoDB conditional writes, S3 versioning, or AWS
deployment. jsdom/component tests and API tests are not browser acceptance.

### Future audit/provenance direction (B1 accepted; B2a primitive; B2b local wiring)

A1 **implemented** committed-revision Save reconciliation. It is not a complete audit trail.
A2 implements same-tab browser recovery; it is not a complete audit trail. B1 **implemented**
and **user-accepted** a derived in-memory committed-history projection of the published
parent chain. B2a **implemented** and **accepted** as the atomic `history.jsonl` primitive
with embedded coverage and `CURRENT` / `STALE` / `INVALID_OR_MISSING` status. B2b
**implemented** local-harness rebuild after successful `LocalReviewStore.publish` and on
startup when the derived file is missing/invalid/stale. The file remains a replaceable
derived view. `head.json` plus reachable immutable revision envelopes remain
authoritative. A committed Save/approval is distinct from a post-publish history rebuild
failure: the revision stays committed; B2b surfaces `LOCAL_HISTORY_REBUILD_FAILED` and
does not mint another revision. One local harness process per `--data-dir` is supported;
multi-process writers, process-crash recovery of a partial rebuild, and backup/restore
are **not** guaranteed. B2c/later may decide production routing, operator UI, retry
policy, and centralized operational logging. Referenced artifact byte checks, retention,
access control, and privileged filesystem modification remain outside this guarantee.

Historical recorded direction (superseded as an authoritative store, retained as context): an
independent append-only JSON Lines ledger such as `.audit/audit-events.jsonl`.
The current engineering direction is to treat published revisions as authoritative evidence
and project a readable history file from that chain. B1 is the projector; B2a is the file
primitive; B2b is local-harness rebuild of that file after published heads.

- The ledger, if added later, must remain outside source control and Docker images.
- Operational logs remain structured stdout logs, not another persistent audit file.
- Future audit events should store references, IDs, hashes, revision links, actors, times,
  actions, and outcomes — not duplicate full PDFs or complete JSON artifacts.
- A hash chain can be tamper-evident, but is not proof of tamper-proof storage or Part 11
  compliance.
- Operation-aware search uses the retained committed chain with no separate operation TTL.
  Deleting retained revisions ends the supported lookup guarantee. A1 tests use one process
  and shared in-memory doubles; they do not prove multiprocess file safety or live DynamoDB/S3.

### Key non-goals for current work

- Batch release, regulatory release, or Part 11 electronic signature claims
- Recipe extraction, graph visualization, collaboration, or an extra identity/database service
- Implementing B2c production history routing, operator UI, extraction, rules, or cloud
  deployment in this B2b pass; do not start B2c from this local wiring alone
- Reopening accepted Textractor conversion behaviour
- Treating UI regression or automated tests as human acceptance of A1

The earlier HITL implementation (backend, local harness, IAM template, Docker) remains in the
working tree. No AWS calls, commit, push, deployment, CloudFormation, OCR, or infrastructure
change in this documentation pass.

## 2. Local review command

Build with Node 22.12+ and start from the repository root. Paths are relative to the repository
root. `--data-dir` defaults to `.local-review-data/fexofenadine`. Use a different data directory
when inputs change; a changed input is rejected instead of resetting existing review history.
Personal acceptance may use a distinct directory such as
`.local-review-data/fexofenadine-manual-01`. Do not use
`.local-review-data/fexofenadine-correction-verification/` for personal acceptance.

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-textractor-20260916-173938/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-textractor-20260916-173938/document.html" --data-dir ".local-review-data/fexofenadine" --port 8765
```

Open `http://127.0.0.1:8765/documents/local-review`. Supplied originals stay untouched. Saved
drafts/approvals/exports survive restarting with the same data directory; unsaved browser edits do
not survive browser closure.

This checkout already contains generated `src/app/document_review/static/` assets (`review.js`,
`review.css`, PDF worker), so the Python harness can start without rebuilding the frontend.
The user's completed current local review is `.local-review-data/fexofenadine-local-current`
(inputs `out/comparison/fexofenadine-local-current/document.json` and `document.html`, raw
OCR `out/comparison/fexofenadine-textractor-20260916-173938/textract.json`). Do not reset it.
Historical personal progress `.local-review-data/fexofenadine-manual-01` remains on disk; do
not reset it either. A1 isolated evidence
`.local-review-data/a1-save-retry-verification-20260917-192410` remains on disk; do not
reset it. B1 regression `.local-review-data/b1-regression-20260918` remains on disk; do
not reset it. Use a separate empty data directory for synthetic checks.

**Reviewed HTML provenance harness** (2026-09-25; started in this session; manual checklist
**unverified**). Fresh data directory and unused port 8769. Do not use 8765–8768 or any existing
review data directory. GET `http://127.0.0.1:8769/documents/local-review` returned HTTP 200
`Cache-Control: no-store`. GET review for `local-fexofenadine` returned `NOT_REVIEWED`,
generation 0. That is not browser acceptance. Originals were not modified.

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/html-provenance-20260925" --port 8769
```

Open `http://127.0.0.1:8769/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Manual checklist (user browser; not done in this session):

1. Open the isolated workspace and confirm page navigation, text, and tables display normally.
2. Edit text, Save draft, reload, and confirm persistence.
3. Approve a page, edit/save again, and confirm its approval is invalidated.
4. Confirm Approve & Export still blocks incomplete review. Complete the required review and download newly approved HTML and JSON.
5. Open the HTML: visible content and tables remain correct. Inspect source for revision metadata, representative paragraph/cell IDs, source references where available, and generated-content markers.
6. Confirm both exports contain the saved correction, and restarting the same isolated harness preserves its saved state.

**B2b isolated harness** (2026-09-18; command for the user's manual run; **not executed
in this implementation session**). New `--data-dir` and unused port. Do not use 8765,
8766, or 8767.

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/b2b-history-20260918" --port 8768
```

Open `http://127.0.0.1:8768/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Startup should print the resolved `history:` path. Manual steps:

1. Make at least one Save draft and confirm `.local-review-data/b2b-history-20260918/history.jsonl` appears.
2. Complete the existing page-5 two-suggestion / page-approval / Approve and export flow.
3. Stop and restart the same harness directory and port.
4. Inspect the first JSONL coverage line and confirm its revision/generation match `head.json`.
5. Note whether a missing/invalid file was rebuilt to current, or an explicit
   `LOCAL_HISTORY_REBUILD_FAILED` startup failure occurred.

**A2 isolated harness** (2026-09-18 F1–F3 follow-up restart; same directory as the
2026-09-17 startup and morning correction restart; user's 8765 process left running;
this restart itself was not the later A2 acceptance):

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/a2-save-recovery-20260917" --port 8766
```

Open `http://127.0.0.1:8766/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Reused `review-context.json` storage ID
`08c3e9b4-3b70-42ee-81a2-8bde3ae9fb64` (not regenerated). No review head was written.
Live GET checks on this restarted process: `/documents/local-review` HTTP 200
`Cache-Control: no-store`; `GET /api/v1/documents/jobs/local-fexofenadine/review/context`
HTTP 200 `context_id=6bdec862ee21fd500e00b4cb2a8e1fab6299d4a622e49913fbd0da30fbee414e`,
`actor=local-test-reviewer`; GET review `NOT_REVIEWED` generation 0 `revision_id` null
with two page-5 `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` findings
(`finding_c084cac7554719ec066283115a746dcb`, `finding_dda8b3733bfb23d27ea12c08fc280cbd`).
This F1–F3 restart reconfirmed those same read-only GET values; no review head exists yet.
The 2026-09-17 lookup-without-header 422 and never-committed UUID `UNRESOLVED` checks
were not repeated as writes; they remain historical for that first startup.

Browser Save/reload/lost-response/approval/export and same-directory restart were
**accepted** in the preceding session against the isolated 8766 checklist. SessionStorage
recovery is same-tab only; tab close, storage clearing, and private-mode restrictions can
lose the pending record. After a successful Check/Retry confirmation and matching cleanup,
F5 must not leave the user blocked. A post-commit lost-response drill is not proof of
pre-commit in-flight absence.

Historical 2026-09-17 A1-closure harness startups (processes later stopped; not this
verification run): `--data-dir ".local-review-data/fexofenadine-manual-01" --port 8765`
(`IN_REVIEW`, generation 70, revision `7d1400d4-bc6c-44a0-be8a-cd7eeb5f2bbd`); isolated
`--data-dir ".local-review-data/a1-operation-api-check" --port 8766`. That isolated
directory was later removed as disposable runtime data.

**A1 local HTTP Save/retry verification** (2026-09-17 execution; isolated harness only;
user's 8765 review untouched; not human acceptance of A1):

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/a1-save-retry-verification-20260917-192410" --port 8766
```

Evidence directory: `.local-review-data/a1-save-retry-verification-20260917-192410`.
Job `local-fexofenadine`, bearer `local-review-token`. Node
`node_36d6122f84e425aa74a50a8654f1d0b7` (page 1 `TABLE_CELL`, baseline `Item Type`)
chosen from that GET catalogue. Operations
`fa42fa71-da8a-4422-bf1e-3558921c4a19` (A) and `e475fa26-a162-4e99-a421-ca443438f0cf` (B).
PUT `/api/v1/documents/jobs/local-fexofenadine/review` returned top-level `ReviewState`
(no `receipt`). Save A → revision `4446700b-be5e-4d82-b6be-e01d829ac0fb` generation 1;
Save B → `d7a1ea21-c8e8-4874-bde8-8543404bbf1f` generation 2, text `A1-SAVE-B Item Type`.
Exact retry of A and a controlled stop/restart of this isolated process with the same
data directory both returned HTTP 200 with head B, generation 2, text B, and unchanged
revision-file hashes. Same operation A with different text returned HTTP 409
`SAVE_OPERATION_MISMATCH` with head/files unchanged. Committed envelope A records
operation A; envelope B records operation B and `parent_revision_id` A. Isolated process
stopped after the run. This is not browser recovery, power-loss durability, multiprocess
safety, or live-cloud verification.

`update(...)` still returns `ReviewState`. Receipts remain service-level; A2 adds HTTP
lookup of `reconcile_save_operation` without wrapping PUT. The A2 browser submits
`operation_id` and `X-Review-Context` for new Saves. UI tests are not browser acceptance.

## 3. Acceptance evidence and remaining unverified work

1. Local visual/functional acceptance against the source PDF: **COMPLETE** (user). Evidence is
   listed under §1 Manually verified locally. Do not extend that list to unlisted behaviour.
2. Historical 173938 conversion sample stored zero `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY`
   warnings. The current local conversion (`out/comparison/fexofenadine-local-current`)
   produced two page-5 tolerance findings. **User-reported:** both suggestions were applied
   and saved on `.local-review-data/fexofenadine-local-current`. That report is not A1
   human acceptance.
3. Original orchestrator technical review of the working tree and gate evidence remains available
   as a later step; it is not local-harness acceptance.
4. Later production acceptance uses `/documents`, a Cognito-owned completed job, and a deployed
   version of the prepared IAM update. The local harness is not a cloud integration test.
5. A1 Save operation identity remains the agreed baseline. It is **test-verified** and has
   an isolated local HTTP Save/retry execution recorded in §2. It is **not human-accepted**.
   `svc.update(...)` still returns `ReviewState`.
6. A2 browser Save identity/recovery is **implemented**, **test-verified** (historical
   2026-09-18 F1–F3: Python 206, frontend 94, ruff/pyright, isolated 8766 GET checks), and
   **manually accepted** in the preceding session against the isolated 8766 checklist below.
   SessionStorage recovery remains same-tab only. A later 422 after an unknown outcome is not
   proof that an earlier request failed or was cancelled.
7. B1 committed-history projection is **implemented**, **test-verified**, and
   **user-accepted** after the isolated local-review regression. Causal order is generation
   plus parent links; `revision_created_at` is envelope creation time, not the CAS
   publication instant.
8. B2a `history.jsonl` materialisation is **implemented**, **test-verified**, and
   **accepted** as the derived-file primitive (historical C1: 36 focused B1+JSONL tests;
   95 document-review tests; ruff/pyright). Embedded coverage states exactly through
   which revision/generation the file is complete. Stale/invalid/missing is explicit.
   Path preparation and write failures are `HISTORY_JSONL_WRITE_FAILED`.
9. B2b local published-history rebuild is **implemented** and **test-verified**
   (historical this-session B2b: 51 focused tests; 104 document-review tests;
   ruff/pyright). It is local single-process harness wiring only. After a successful
   local publish, `data-dir/history.jsonl` is rebuilt from that head. Startup rebuilds
   missing/invalid/stale files and does not rewrite `CURRENT`. Post-publish rebuild
   failure leaves the committed head in place, preserves prior history bytes, logs a
   safe structured event, and returns `LOCAL_HISTORY_REBUILD_FAILED` rather than a
   normal Save/approval response. Referenced PDF/raw/export bytes are still not
   verified by the history file. Production cloud persistence, browser/UI, directory
   locking, and multi-process safety are **not implemented**.
10. Findings scope default **This page** is **implemented** and **test-verified** in this
    frontend pass (`FindingsPanel` `scope` ref `'page'`; focused 15; complete frontend
    100 with `out/` mounted; review-builder assets copied). It is **not manually
    accepted**. Counts remain findings counts, independent of the list filter. An
    explicit **All warnings** selection survives page navigation.

**Next safe step:** manually verify the Findings default on an existing local harness
after a hard reload of the rebuilt assets, without Save/approval. Do not stop the
running 8767/8768 processes. Do not start B2c or extraction.

### A2 manual checklist (accepted in the preceding session; isolated 8766 only)

1. Ordinary edit → **Save draft** → F5 retains the text and leaves editing available.
2. Lost response: make an unsaved edit, arm the one-shot fetch wrapper below, click
   **Save draft** once. The wrapper must await a real successful PUT before hiding it and
   must restore `fetch` automatically. Expected: unknown status, retained record, blocked
   new mutation. This post-commit drill does not prove pre-commit in-flight absence.
3. In that drill, click **Check save status**. A valid `COMMITTED` lookup plus exact
   replay/application/cleanup should retire the record and unlock editing. F5 after this
   successful recovery must not leave the user blocked.
4. To test reload with an outstanding record, use a separate edited Save/lost-response
   drill and press F5 **before** Check/Retry. The record must be read and reconciled. A
   committed operation may recover automatically through lookup and exact replay; a
   genuinely `UNRESOLVED` operation remains blocked without a new ID. Do not require it
   to remain blocked after successful confirmation.
5. **Approve page** / invalidation, both page-5 tolerance suggestions when still
   applicable, **Approve & Export**, and restart with the same isolated directory retain
   existing semantics. Do not reset progress merely to repeat a test.

Lost-response snippet (8766 only; one-shot; restores `fetch`):

```javascript
(() => {
  if (location.port !== '8766' || !location.pathname.startsWith('/documents/local-review')) {
    throw new Error('Run this only at http://127.0.0.1:8766/documents/local-review');
  }
  const original = window.fetch.bind(window);
  let used = false;
  window.fetch = async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url, location.origin).pathname;
    const target = request.method === 'PUT' && path === '/api/v1/documents/jobs/local-fexofenadine/review';
    if (!target || used) return original(input, init);
    used = true;
    window.fetch = original;
    const response = await original(input, init);
    if (!response.ok) return response;
    await response.clone().arrayBuffer();
    throw new TypeError('A2 lost-response drill: server Save completed, browser hid the response.');
  };
  console.log('Armed: next review Save PUT completes on the server, then fails in the app.');
})();
```

---

## Historical HITL editor-boundary corrections — 2026-09-16

Four focused review-editor corrections were applied on top of the existing uncommitted HITL
slice. The accepted Textractor conversion was not reopened or changed. Local visual acceptance
was still pending at that date and is now recorded as complete in §1.

- Table `sourcePath` / `rows` / `columns` now survive the production TipTap schema, so
  projection, editor JSON, and structural validation agree. Page `setContent` is verified; a
  rejected load is reported and does not silently keep the previous page.
- Suggested ± replacements are queued for the guarded backend operation only. Identical preview
  text is omitted from sparse `changes`. Stale suggestions are refused; editing a preview
  invalidates the queued decision and keeps the newer text as a manual change.
- Canonical lowercase `title` and `section_heading` render as heading levels 2 and 3 in the
  editor and reviewed HTML. Table-title `TITLE` and ordinary text stay non-heading regions.
- Table cells/headers emit `data-source-cell` from the node attribute. Finding focus uses a
  node decoration so the existing highlight survives the table view.

At that date, `manual-input/source.pdf` had not yet been used for built-bundle browser
acceptance. jsdom/component tests and API tests were not browser acceptance.

## Historical conversion handoff — earlier 2026-09-16 correction pass

**Textractor integration complete with three focused corrections applied.**

Amazon Textractor 1.10.0 remains the active parser and HTML renderer.
All three corrections from the focused task are implemented, verified, and passing.

No commit, push, deployment, or live AWS call was performed.

## 2. What was integrated (original baseline)

Selected implementation: `C:\Users\User\Downloads\textractor_to_html.py`

The integration placed the PoC as `src/app/document_conversion/textractor_renderer.py`
and added a thin adapter in `src/app/document_conversion/adapter.py`.
See §3 for accepted PoC limitations that remain unchanged.

## 3. Three focused corrections (this session)

### 3.1 Partial-result visibility in full HTML

**Problem:** `render_full_document_html()` called `document_html(textractor_doc, raw_tables)`
without passing status or warnings.  PARTIAL_SUCCESS and AWS_PAGE_ERROR could appear in
`document.json` and `page-NNNN.html` but be absent from the downloadable `document.html`.

**Fix:**
- `document_html()` in `textractor_renderer.py` now accepts `status: str` and
  `warnings: Sequence[tuple[str, Sequence[int]]]` (defaults preserve existing callers).
- A `<div class="partial-banner">` is rendered between `<nav>` and `<details>` only for
  PARTIAL_SUCCESS; SUCCEEDED conversions get no banner.
- All warning codes and page references appear in the collapsed **Conversion notes**
  `<details>` section as an escaped `<ul>`.  Dynamic content (codes, page numbers) is
  HTML-escaped via `escaped()`.
- `render_full_document_html()` in `adapter.py` extracts `(w.code, list(w.pages))` pairs
  from the structured document and passes them to the renderer.
- Individual `page-NNNN.html` artifacts already received status/codes; unchanged.
- The POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY code receives a plain-language note in HTML:
  "Possible tolerance-symbol ambiguity. Check this value against the source PDF;
  the extracted text has not been changed."

### 3.2 Flexible table sizes (remove max_table_positions)

**Problem:** `ConversionLimits` contained `max_table_positions` (default 10 000).
`normalize.py` was deleted but the field remained; no code enforced it.
`max_relationship_depth` was also non-functional since normalize.py was removed.

**Changes:**
- `max_table_positions` removed from `ConversionLimits` (`contracts.py`).
  Passing it now raises a Pydantic `ValidationError` (extra="forbid").
- `max_relationship_depth` is now enforced via `_check_relationship_graph()` in
  `adapter.py`, called from `validate_textract_response()` before `textractor_parse()`.
- Algorithm: Kahn's topological sort (BFS).  Detects cycles (`CYCLIC_RELATIONSHIP`)
  and longest-path depth > max (`RELATIONSHIP_DEPTH_EXCEEDED`) in O(V+E).
- Overall block-count and page-count limits are preserved unchanged.
- Table size (row × column) is not limited; only relationship chain depth is checked.

### 3.3 Conservative tolerance-review detector

**Location:** `src/app/document_conversion/tolerance.py`

**Rules (all must hold):**
1. Explicit tolerance cue: `\btolerance\b` or `\ballowable\s+deviation\b` in same text.
2. Bare `+<number>` present (decimal separator: `.` or `,`; whitespace allowed).
3. Explicit `±` absent (already expressed).
4. Explicit asymmetric `+X / -Y` absent (already expressed).

**Not flagged:** plain addition, unit presence alone, "mass"/"weight"/"target".

**Output:** `Warning(code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY", pages=(page,), block_ids=(...))`

**Deduplication:** by frozenset of block_ids (source-region identity, not text identity).
Two items with identical text but different block_ids are treated as distinct source
locations and each produces its own warning.  Only an exact match of the block_id set
suppresses a duplicate.

**Guarantees:**
- `textract.json`, `document.json` text, `document.html` content: unchanged.
- No correction, annotation, or replacement inserted.
- SUCCEEDED status not changed to PARTIAL_SUCCESS for advisory findings alone.

## 4. Accepted PoC limitations (unchanged)

- Merged-cell reading order and within-cell line boundaries may be imperfect.
- Some table captions/headings appear twice (layout stream + direct table title).
- OCR symbols and undetected visual tables are not recovered.
- Checkbox-state detection: NOT_SELECTED displays as ☑ in HTML; document.json is correct.
- Caption markup may be duplicated in some documents.
- Adjacent tables with equal Textractor `reading_order` scores: insertion-order sort
  (PYTHONHASHSEED-dependent between runs; deterministic within a single run).

## 5. Offline regeneration command

```powershell
poetry run python -m app.document_conversion offline "out\comparison\fexofenadine-20260916-151835\textract.json" --source-id fexofenadine --output "out\comparison\fexofenadine-textractor-reviewed"
```

## 6. Real-sample verification — fexofenadine-textractor-reviewed

Input: `out\comparison\fexofenadine-20260916-151835\textract.json`
Output: `out\comparison\fexofenadine-textractor-reviewed\`

| Check | Result |
|---|---|
| 18 source pages | ✓ (18 `page-NNNN.html` artifacts; `id="source-page-18"` present) |
| 31 raw TABLE IDs represented exactly once | ✓ (31 `table-wrap` elements in `document.html`) |
| Page navigation controls present | ✓ |
| OCR text unchanged by detector | ✓ |
| PARTIAL_SUCCESS banner absent (status=SUCCEEDED) | ✓ |
| Warning list in Conversion notes | ✓ (19 UNINTERPRETED_LAYOUT_FIGURE warnings listed) |
| `document.json` validates against `contracts.Document` | ✓ |
| Existing output directories preserved | ✓ |

**Tolerance advisory findings in this sample:** None found.

The detector found zero expressions meeting its current same-element/cell rules.
Zero findings do not establish that tolerance transcription is correct in this sample.
Physical page 5 of the reviewed response contains separate LINE blocks for "If tolerance"
and "+0.1%"; the intended ± was NOT correctly recognized in that case.  The current
detector requires the cue word and ambiguous `+` to appear in the same extracted text
element or cell — detecting cues across different blocks or cells is outside this task's
scope and was not implemented.  Do not treat a clean advisory report as confirmation that
all tolerances are correctly transcribed; inspect the source PDF directly.

**Warnings breakdown:**
- 19 × UNINTERPRETED_LAYOUT_FIGURE (figure blocks skipped in HTML; block_id recorded)
- 0 × AWS warnings (clean SUCCEEDED response)
- 0 × POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY

## 7. Quality results (post-correction)

| Command | Result |
|---|---|
| `poetry run ruff check .` | Passed |
| `poetry run ruff format --check .` | Passed (43 files) |
| `poetry run pyright` | 0 errors, 0 warnings |
| `poetry run pytest` | **134 passed** |

Test count: 110 (baseline) → 132 (previous pass) → 134 (+2 new: large-table fixture, distinct-location deduplication).

## 8. Changed files (this session)

| File | Change |
|---|---|
| `src/app/document_conversion/contracts.py` | Removed `max_table_positions`; added docstring to `ConversionLimits` |
| `src/app/document_conversion/adapter.py` | Added `_check_relationship_graph()` (Kahn's BFS); call it in `validate_textract_response()`; import `Block`; import `detect_tolerance_ambiguities`; invoke detector in `convert_and_render()`; update `render_full_document_html()` to pass status/warnings |
| `src/app/document_conversion/textractor_renderer.py` | Updated `document_html()` signature (status, warnings); added `_warning_item_html()`; added partial banner and warning list HTML |
| `src/app/document_conversion/tolerance.py` | **NEW** — conservative tolerance-symbol ambiguity detector; deduplication by frozenset of block_ids (not text) |
| `tests/document_conversion/test_converter.py` | 22 focused tests (previous); +2 this pass: `_large_table_fixture` (101×100) + replaced `test_large_table_converts_without_truncation`; replaced `test_duplicate_text_on_same_page_produces_one_warning` with `test_same_source_region_deduplicated`; added `test_distinct_cells_same_text_retain_both_locations` and `test_same_text_different_pages_independently_reported` |

## 9. Preserved directories

| Directory | Status |
|---|---|
| `out\comparison\fexofenadine` | Unchanged |
| `out\comparison\fexofenadine-20260916-151835` | Unchanged (source input) |
| `out\comparison\fexofenadine-python-fixed` | Unchanged |
| `out\comparison\fexofenadine-textractor-standalone` | Unchanged |
| `out\comparison\fexofenadine-textractor-integrated` | Unchanged |
| `out\comparison\fexofenadine-textractor-reviewed` | NEW: reviewed output |

## 10. Historical next steps (superseded by current handoff above)

1. User/operator review of `out\comparison\fexofenadine-textractor-reviewed\document.html`.
2. Docker/API worker verification when requested.
3. Live AWS conversion was subsequently completed and accepted by the user.
4. No commit, push, or deployment without explicit instruction.
