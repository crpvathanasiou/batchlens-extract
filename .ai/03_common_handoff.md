# 03 — Common Handoff

## 1. Current state — 2026-09-17 documentation and local-acceptance alignment

This is the cross-session restart anchor. Repository code and tests are the source of truth for
implementation. Existing local-harness evidence is the source of truth for manually verified
review behaviour. Do not treat planned work as implemented.

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
- HITL editor-boundary corrections (2026-09-16; still in the working tree): protected table
  `sourcePath` / `rows` / `columns`; page `setContent` failure reporting; single-application
  tolerance replacement handling; heading mapping for canonical `title` / `section_heading`;
  stable table-cell `data-source-cell` identity and node-decoration highlighting
- Later UI work present in code and frontend tests (not claimed as visual browser verification
  unless listed under manually verified): Vite `process.env.NODE_ENV` browser-bundle define;
  document status label; `Document findings` / `Page findings` counts; short accessible
  decision-button help text; immediate pending/recorded finding-decision feedback

**Test-verified** (latest recorded gates: 2026-09-16 HITL correction pass; not re-run in this
documentation pass):

- Python: Ruff passed, 57 files formatted, Pyright 0 errors/0 warnings, 152 tests passed. 148 is
  historical from the HITL implementation session; 134 remains historical conversion evidence.
- Frontend in `node:22.12-bookworm-slim`: typecheck passed, 23 tests passed (was 11 before that
  correction pass); production build emitted `review.js`, `review.css`, and a local PDF.js worker
  into `src/app/document_review/static/`.
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
- Persistent audit/observability ledger (direction recorded below; no implementation in this
  pass)

### Local harness purpose and boundaries

`tests.document_review.local_harness` is development/test-only. It reuses the actual review
service, API routes, validation, mapping, frontend bundle, and export logic. It substitutes only
external identity and storage. It uses synthetic reviewer `local-test-reviewer` and synthetic
completed job `local-fexofenadine`, binds to `127.0.0.1`, persists generated review state under
`.local-review-data/` (gitignored), and leaves the supplied original PDF, `document.json`,
`textract.json`, and `document.html` untouched.

It does not verify real Cognito authorization, DynamoDB conditional writes, S3 versioning, or AWS
deployment. jsdom/component tests and API tests are not browser acceptance.

### Future audit/provenance direction (unimplemented)

Recorded as an approved future direction only. No audit or observability implementation is part
of this pass.

- Initial persistence target: one canonical append-only JSON Lines audit ledger, for example
  `.audit/audit-events.jsonl`, under a persistent application-data directory.
- The ledger must remain outside source control and Docker images.
- Operational logs remain structured stdout logs, not another persistent audit file.
- Future audit events should store references, IDs, hashes, revision links, actors, times,
  actions, and outcomes — not duplicate full PDFs or complete JSON artifacts.
- A future AWS/Azure adapter should persist the same canonical event schema as append-only events
  or rows.
- A hash chain can be tamper-evident, but is not proof of tamper-proof storage or Part 11
  compliance.

### Key non-goals for current work

- Batch release, regulatory release, or Part 11 electronic signature claims
- Recipe extraction, graph visualization, collaboration, or an extra identity/database service
- Implementing audit logging, observability, rules, or cloud deployment in the next step
- Reopening accepted Textractor conversion behaviour

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

## 3. Acceptance evidence and remaining unverified work

1. Local visual/functional acceptance against the source PDF: **COMPLETE** (user). Evidence is
   listed under §1 Manually verified locally. Do not extend that list to unlisted behaviour.
2. On physical page 5, one `Toler +0.1%` cell may still need a manual `Toler ±0.1%` correction
   after checking the PDF. The conversion sample has zero tolerance findings; that correction
   stays a document-content task, not a harness defect. Record it only when actually performed.
3. Original orchestrator technical review of the working tree and gate evidence remains available
   as a later step; it is not local-harness acceptance.
4. Later production acceptance uses `/documents`, a Cognito-owned completed job, and a deployed
   version of the prepared IAM update. The local harness is not a cloud integration test.

**Next safe step:** intended-use / regulatory-boundary and audit/provenance design before any
audit-log implementation. Do not implement audit logging, extraction, rules, or deployment in
that step.

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
