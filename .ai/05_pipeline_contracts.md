# 05 — Pipeline Contracts

**Status:** Document conversion and optional human review **are implemented** in code (not production-qualified). L01–L13 lexical building blocks (contracts through CLI and atomic final-manifest publication) **are implemented**, **test-verified**, and **user-accepted**. Stage 3 — Extraction Review Workspace **U1–U3 local slice is implemented**, **test-verified**, and **manually verified** (current-state review per `local_job_id`, approved-document selection, local Stage 2/L13 jobs, local UI/API/harness). Production mount/auth, page classification, duplicate-upload/fingerprint/reuse, SQLite review store, graph/association work, LLM, and automatic approval remain **out of this mini-project** or **unimplemented**. Rules/Audit evaluation and a persistent audit ledger are **not implemented**. Broader extraction productization remains **OPEN**.

Primary owner of pipeline responsibilities, data semantics, and lifecycle invariants. Product boundaries: [00_project_reference.md](00_project_reference.md). Engineering errors: [02_code_quality_standards.md](02_code_quality_standards.md). Check selection: [08_check_selection_strategy.md](08_check_selection_strategy.md). Security of artifacts: [06_security_and_data_handling.md](06_security_and_data_handling.md).

---

## 1. Design responsibilities (conceptual)

These are responsibilities to design, **not** a locked execution sequence or deployment topology.

| Responsibility | Intent |
|----------------|--------|
| Intake / source preservation | Accept manufacturing PDFs; retain original bytes and identity/revision metadata |
| Document / page preparation | Render or OCR pages as needed; produce workable page/text representations |
| Reference-section identification | Locate BOM/LOE (and similar) sections wherever they appear |
| Entity / relationship extraction | Extract materials, equipment, operations/steps, usages, parameters, limits |
| Reconciliation / validation | Compare extracted content to document-local references; emit consistency findings |
| Result assembly | Build versioned structured result with evidence, uncertainties, and findings |
| Optional review | Human inspection/correction without erasing provenance of prior machine output |

---

## 2. Conceptual data inventory

Design concepts — **not** existing classes or finalized JSON fields.

| Concept | Meaning |
|---------|---------|
| Source document and revision | Original PDF (or equivalent) and its document/revision identity where known |
| Processing run | One attempt to process a source into a result |
| Recipe representation | Structured recipe/batch content derived from the source |
| Materials | Substances/items identified in the document |
| Equipment | Equipment items identified in the document |
| Operations / steps | Unit operations and ordered or unordered process steps |
| Contextual material/equipment usage | Use of a material or equipment **in a particular step/context** |
| Parameter observations / limits | Values, ranges, units, and limits bound to a step/context |
| Evidence references | Pointers into the source sufficient to explain an assertion |
| Findings | Document-consistency or structural-validation outcomes (not Audit compliance) |
| Review revisions | Human corrections layered on a machine (or prior) result |

### Contextual binding (invariant)

A quantity belongs to a particular use/context. A temperature or speed belongs to a particular step/context. Do **not** collapse all occurrences into one material or equipment property.

---

## 3. Information meanings that must stay distinguishable

| Kind | Meaning |
|------|---------|
| Missing | Expected information was not found |
| Ambiguous | Multiple interpretations remain plausible |
| Conflicting | Sources disagree |
| Prescribed | Instruction, limit, or target stated by the document |
| Observed | Recorded execution value or deviation |
| Normalized | Transformed representation (e.g., unit conversion) with traceable link to source |
| Externally enriched | Added from catalog/RAG or other non-document sources (optional; must be labeled) |

When normalization occurs, preserve source values/units alongside the transformation trail.

Executed-record extraction produces an evidence-based recipe representation; it does **not** establish the authoritative master recipe ([00](00_project_reference.md)).

---

## 4. BOM / LOE and evidence rules

- Use BOM/LOE sections wherever present as document-local references for extraction and reconciliation.
- Preserve materials/equipment found elsewhere even when absent from those sections.
- Reconciliation can reveal omissions or mismatches; it **cannot** establish regulatory validity or completeness independently of the source.
- A missing reference section must not force custom Excel transcription as a product requirement.
- Evidence must support **relationships** as well as entities.
- Uncertain ordering must not be invented from proximity alone.

---

## 5. Processing, review, and findings (meanings)

Describe meanings without locking enum names or a complete transition table.

| Concern | Meaning |
|---------|---------|
| Processing completion | Pipeline finished producing a result artifact for the run |
| Partial output | Usable subset exists; some expected content missing or incomplete |
| Technical failure | Unrecoverable operational failure; distinct from data-quality findings |
| Review status | Whether a human has inspected/corrected (e.g., explicitly unreviewed in automatic mode) |
| Check / finding outcomes | Results of structural or consistency checks |

**Approved automatic mode:** return a usable result with uncertainty and an **explicit unreviewed** status. Missing evidence or uncertainty is not automatically a pass, a technical failure, or a mandatory human-review stop.

Human review may govern approval or consequential actions; it must not universally prevent automatic draft delivery.

Keep **operational errors** (engineering failures) distinct from **data-quality findings**. Error engineering rules: [02](02_code_quality_standards.md). Check selection: [08](08_check_selection_strategy.md).

---

## 6. Provenance, replay, and views

- Store references sufficient to explain outputs and corrections.
- Fixed configuration and temperature do **not** guarantee identical future LLM outputs.
- Distinguish **deterministic** projection/check replay from **rerunning** probabilistic extraction. Exact mechanisms: **OPEN**.
- Tabular and graph views use the **same versioned result**, with evidence links and synchronized corrections.
- Graph nodes/edges are generated deterministically from the versioned model — not a separate LLM reconstruction.
- Neo4j / GraphRAG: not required ([00](00_project_reference.md)).

### Future audit ledger (APPROVED TARGET / not implemented)

Initial persistence target, recorded as direction only — **no implementation in current work**:

- One canonical append-only JSON Lines audit ledger, for example `.audit/audit-events.jsonl`, under a persistent application-data directory.
- The ledger must remain outside source control and Docker images.
- Operational logs remain structured stdout logs, not another persistent audit file ([02](02_code_quality_standards.md) §14.5).
- Future audit events should store references, IDs, hashes, revision links, actors, times, actions, and outcomes — not duplicate full PDFs or complete JSON artifacts.
- A future AWS/Azure adapter should persist the same canonical event schema as append-only events or rows.
- A hash chain can be tamper-evident, but is not proof of tamper-proof storage or 21 CFR Part 11 compliance.

---

## 7. Extract vs Audit boundary

Extract owns extraction, provenance, structural validation, and document-consistency findings.

Audit (separate planned tool) owns regulatory/process-rule evaluation over compatible structured input, including from other sources.

Shared versioned contract schema and deployment separation: **OPEN**.

---

## 8. Open decisions

- Detailed stage inputs/outputs and orchestration order for **pharmaceutical extraction**
- Identifiers and serialization for recipe/result assembly beyond the L01 lexical records
- Exact lifecycle transition names for run control, retry, and resume (L01 outcome labels are settled below; the run state machine is not)
- Versioning mechanism for **extracted** results beyond `batchlens.lexical-record.v1` (document-review revisions are implemented in code; see [04](04_code_map.md))
- Retry / resume behavior after partial extraction failure
- Extract–Audit contract fields and versioning
- First demonstrable end-to-end **extraction** slice scope
- Audit-ledger event schema (direction in §6; implementation deferred)

These remain purposes of remaining **M-Design** work after intended-use / regulatory-boundary and audit/provenance design ([01](01_implementation_roadmap.md), [03](03_common_handoff.md)). Conversion and review contracts already exist in code and must not be silently redesigned here.

---

## 9. L01 lexical records (implemented contracts, not an extractor)

Code: `src/app/lexical_extraction/contracts.py`. Schema `batchlens.lexical-record.v1`.
A small synthetic fixture is `examples/lexical_extraction/result-example.json`.
Validation is by bounded records (input, page, block, occurrence, outcome, publication).
There is no production model that must hold every page and match at once.

**Input.** After successful validation, reviewed HTML v1 requires `html_sha256`, contract
version 1, and the producer root metadata: `job_id`, `review_revision_id`, `review_generation`,
and `conversion_status` (the HTML `data-job-id`, `data-review-revision-id`,
`data-review-generation`, and `data-conversion-status` values). An external document id may be
absent. A failure before that validation has no validated-input record and must not invent those
fields.

**Evidence.** A page has a positive physical page number, order, and coverage. A block keeps
its node id, structural kind, exact text (empty text is valid), page membership, order,
optional element/table/cell geometry, and original ordered OCR references (an empty list is
valid). A match span is a zero-based half-open Unicode code-point range with nonempty
`matched_text`. Standalone span checks do not prove the slice. `validate_match_against_block`
requires `block.text[start:end] == matched_text` and does not normalize text. Overlapping spans
are kept. Later ordering is by page order, block order, then span start/end and occurrence id.
This module does not sort or dedupe.

**Candidates.** A finalized dictionary occurrence has at least one source-backed candidate.
FDA/EMA and ChEBI stay separate. FDA/EMA search fields are `material_name`, `alias_name`, and
`UNII`; ChEBI search fields are `material_name` and `alias_name`. CAS numbers are not search
fields. `SMS_ID` and `CHEBI_ID` are identities, not search fields. Those column rules do not
filter Material aliases by language. Equipment matching excludes dedicated Greek fields, brand,
manufacturer, model, manufacturer/model ids, and Published range. Dedicated Greek fields are
also outside the Unit Operations matching boundary. Missing native ids do not
invalidate a source row. Generic cues have no operation id. `Index this row` is source text on
the unit-operation candidate and does not gate a process-step candidate. A parameter candidate
may carry catalogue equipment scope; that is not a detected equipment mention. Match methods are
exact, normalized exact, and fuzzy, with fixed rule ids. Exact evidence must equal the
occurrence text. Normalized-exact does not apply normalization here. Fuzzy evidence is one
alphabetic word of at least six characters and a recorded edit distance of 0 or 1; the
distance is not calculated. Phrases are not fuzzy. Fuzzy is rejected for chemicals, UNII, and
units. Ambiguity (`none`, `unresolved`, `context_required`) is not a technical failure.

**Units and values.** A unit mention has its own literal, span, rule, and either the fixed unit
vocabulary or an `equipment.Unit` row. The literal must equal the span text on the mention
itself. It has no parameter name, `parameter_id`, or equipment identity. Value forms are
scalar-with-unit, range, comparison, symmetric tolerance, categorical, and cued unitless.
`raw_expression` equals the expression span. A recorded source unit requires a unit span with
the same text, and that span lies inside the expression. A number–unit group lies inside the
expression, and its number and unit spans lie inside the group. Numbers are exact finite
decimal strings, or an explicit ambiguous token with no resolved value. Grouping is syntactic.
Each value occurrence records rule `lexical-v1-value`. One value occurrence may apply to both
quantity and parameter-value components without a second copy and without a parent entity.

**Outcomes.** Components are `unit_operations`, `process_steps`, `materials`, `equipment`,
`parameter_names`, `units`, `quantity_expressions`, and `parameter_value_expressions`. Requested
presets are a separate list from directly requested components and from resolved components.
Presets are not expanded here. Run provenance also stores a supplied internal-rules SHA-256
beside `lexical-internal-rules-v1`; L01 does not compute that digest. Every resolved component
has exactly one outcome and cannot be
`not_requested`. A component outside that selection may be absent or `not_requested`, and cannot
claim executed work. `not_requested` carries no counts.
`completed` includes a measured count, and zero is a real empty result. `partial` keeps usable
results with an explicit count. `failed` requires a safe structured error. An all-failed
requested run is `failed`, not `completed` or `partial`. Completed component results may sit
inside an overall `partial`. Unavailable measurements are omitted, not stored as zero.

**Publication.** Completed publication requires a final-manifest claim. Failed or interrupted
publication must not carry that claim. Partial extraction may be paired with completed
publication. The claim does not prove that files were written.

## 9a. Stage 3 — Extraction Review Workspace (U1–U3 local slice complete)

Code: `src/app/extraction_review/` (`contracts`, `transitions`, `store`,
`approved_documents`, `local_jobs`, `workspace`, `page_html`), local API
`src/app/api/extraction_reviews.py`, Vue `ExtractionReviewWorkspace`, harness
`tests/extraction_review/local_harness.py`. Review schema
`batchlens.extraction-review.v1`; local job schema `batchlens.extraction-local-job.v1`.

**Boundary.** Stage 2/L13 remains the independent Lexical Extraction Engine. Stage 1
document approval is unchanged. Stage 3 opens completed local Stage 2 jobs and
approves an **extraction result**, never Stage 1 HTML. One final human action:
**Approve extraction result** (`not_approved` / `approved` only). No page, component,
lexical, LLM, finding, or automatic approval. Execution/publication outcomes stay
independent of human approval; fuzzy defaults off.

### Accepted Stage 2 lexical display rules (engine facts; not redesigned here)

- Search includes canonical names and searchable aliases; canonical-name matches take
  precedence over alias matches.
- One deterministic candidate per exact component/block/span.
- One displayed occurrence per `(page, component, casefolded matched text)`.
- Different components remain independent.
- `hasRelatedSynonym` aliases are searchable.
- Short literals under three code points and `context_required` UO terms remain excluded.
- Per-page de-duplication buffering is bounded by `result_buffer_records`.
- Page classification and page-policy exclusion remain future work (not implemented).

### U1 — current review state

**Current state.** Immutable source/run/Stage 2 provenance (`WorkspaceBinding`); one
complete current finding list; one `current_revision_id` for stale Save detection;
`approval` null or one current `ExtractionResultApproval`. Latest state only—no Stage 3
revision history, version list, approval ledger, delta chain, parent link, retry ledger,
SQLite review store, or historical result retrieval. No automatic merge/transfer of edits
between runs.

**Findings.** Origins: `lexical` (immutable Stage 2 evidence + `original_matched_text`) vs
`user_added`. User-facing values use `page_assignment` and `evidence_status`. A user-added
finding is assigned to the current page by the By-page UI; it has `no_document_evidence` and
no invented document-evidence node, block, span, or highlight. Edit provenance:
`added_by_user`, `changed_by_user`, `removed_by_user`. Removal is a restoreable tombstone.

**Transitions.** Initialize from a completed published run with ≥1 completed component.
Save edits the complete list, stamps provenance, assigns a **new** revision token, and
clears approval. Approve targets only the current saved state and changes no findings.
Stale `expected_revision_id` → conflict; no-op Save retains approval.

**Per-run persistence (U1.2).** A current review belongs to one `LocalLexicalJob`
(`local_job_id`):

```text
<data-dir>/extraction-reviews/<sha256(local_job_id)>/current-review.json
```

Two runs of the same approved HTML have independent saved/approved states. Binding still
verifies the exact published run/manifest within that local job. Old source-`job_id` keyed
local files were not migrated. This is not a duplicate-upload, execution-fingerprint,
cache/reuse, or run-history system. Atomic temp + replace; one local process; create
refuses overwrite; Save/Approve write only on `changed` outcomes.

### U2.1 — approved-document selection

Caller-supplied root only:

```text
<approved-documents-root>/<job_id>/<review_revision_id>/document.html
# optional sibling review.json ignored by U2
```

Paginated discovery returns layout metadata without parsing HTML. Selection validates one
file through the Stage 2 reviewed-HTML reader. Folder identity must match HTML provenance.
Read-only: no registry/index/database.

### U2.2 — local Stage 2 / L13 jobs

```text
<data-dir>/extraction-jobs/<local-job-id>.json
<data-dir>/extraction-raw-runs/<stage2-run-id>/...
```

One job = one action (fixed preset mapping; `fuzzy_enabled` default false). L02 YAML
unchanged (in-memory overrides only). One active writer/worker per data directory; later
jobs stay `queued`. Restart marks abandoned `queued`/`running` jobs `interrupted`. Partial
extraction with completed publication is a completed job. No U2 job creates, modifies, or
approves `current-review.json`. A run is never automatically approved. Harness
`--run-extraction` validates HTML, submits/waits for Stage 2, then opens Stage 3 with
`initialLocalJobId`.

### U3 — local workspace / API / harness

- Left: read-only reviewed HTML with category-distinct highlights. Right: findings.
- By page editable; All findings read-only and navigates to the finding’s page.
- Add only in By page (current page assigned). Edit / Remove / Restore / Save /
  Download TXT / final approval as implemented.
- TXT: active saved findings by category and document order; removed excluded;
  no-evidence additions marked.
- Category legend (UO / Material / Equipment / Other): session-only hide/show on both
  sides; does not dirty Save; no API. Selection focuses/navigates evidence only.
- Selector labelled **Extraction run**; distinguishes runs via action, status, finished
  time when available, and local-job suffix.
- Local harness API (not production-mounted): list/open, page HTML, save, approve,
  results TXT under `/api/v1/extraction-reviews/...`.

**Manual acceptance (local):** add → Save → approve; refresh persistence; TXT download;
post-approval Save clears approval; two runs of the same HTML keep independent
reviews/approvals.

### Exclusions

**Out of this mini-project / not implemented:** production API mount/auth; page
classification; duplicate-upload / fingerprint / reuse; SQLite review store; job-history
projection; graph/association/LLM work; automatic approval; Stage 1 document-review
behavior changes; Stage 2 redesign.

## 10. L02 execution configuration (implemented loader, not an extractor)

Code: `src/app/lexical_extraction/configuration.py`. Synthetic example:
`examples/lexical_extraction/execution-config.example.yaml`.

**Root YAML shape (schema_version exactly 1).** Required mappings `input`, `knowledge`,
`output`, `extraction`, and `resources`. Unknown keys are rejected. Paths are nonempty
strings resolved against the configuration file's parent directory to absolute `Path`
values; existence and creation are later concerns.

**Fixed preset map.** `unit_operations` → unit_operations; `unit_operations_with_steps` →
unit_operations + process_steps; `materials` → materials; `materials_with_quantities` →
materials + quantity_expressions + units; `equipment` → equipment;
`equipment_with_parameters` → equipment + parameter_names + parameter_value_expressions +
units; `full` → all eight components. Resolved output is always the canonical order
`unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`,
`quantity_expressions`, `parameter_value_expressions`. `with` means co-execution only.

**User switches.** Only `fuzzy_enabled` (strict bool, default `false` when omitted). No
policy file, algorithm selector, field selector, stage list, or LLM option.

**Resources (safeguards, not performance claims).** Defaults/max: `sqlite_read_batch_rows`
5000/100000; `sqlite_cache_kib` 65536/1048576; `max_terms_per_shard` 2000000/10000000;
`max_term_codepoints_per_shard` 50000000/500000000; `result_buffer_records` 50000/1000000.

**Overrides and provenance.** Typed `SelectionOverride` replaces YAML selection fields
entirely before resolution. Effective SHA-256 uses UTF-8 canonical JSON with sorted
request sets so selection order does not change operational provenance. Compatible with
`RunProvenance.configuration_sha256`. L04 consumes `knowledge.snapshot_directory`,
`sqlite_read_batch_rows`, and `sqlite_cache_kib`. Field mapping, matching, monitoring,
runner, and publication remain unimplemented.

## 11. L03 reviewed HTML v1 reader (implemented reader, not a matcher)

Code: `src/app/lexical_extraction/html_reader.py`.

**Input.** Reviewed HTML file path (optionally via L02 `reviewed_html_path`). Production
`iter_pages` streams finite byte chunks with incremental UTF-8 decoding and hashes the exact
bytes parsed. Root version must be exactly `"1"`. Duplicate provenance attributes are
rejected. Root fields are checked when `<html>` is seen. Final `ReviewedHtmlV1Input`
(including whole-file SHA-256) exists only after successful full iteration (`completed`).

**Pages and blocks.** Physical `section.page` elements emit in DOM order and are released;
the reader does not retain the whole HTML text or all pages. Generated ancestors and page
labels are skipped. Source-bearing `p`/`h2`/`h3`/`h4`/`footer`/`td`/`th` must sit under
`article.element` with `data-node-id` (including empty cells). Bare non-whitespace article
text, unsupported/void tags with `data-node-id`, out-of-page `data-node-id`, mismatched
`data-table-id` vs owning `data-element-id`, and unexpected nested markup inside a source
block fail closed. Text preserves source whitespace; `<br>` becomes newline. Page HTML
coverage `complete` is not PDF/OCR completeness.

**OCR references.** `data-source-id` is split on ASCII spaces. Block IDs that contain spaces
cannot be recovered from the joined attribute; L03 records this limitation and does not
alter the producer or invent a PDF/JSON lookup.

**Memory limits.** Retained: current page/block, short page queue, decode chunk, and
duplicate page/node identity sets (grow with distinct IDs). `read_all_pages` is a
small/test convenience only.

**Completion.** Early stop or late structural failure ⇒ not complete and no final digest.
Matching and publication remain unimplemented. Read-only snapshot access is L04.

## 12. L04 read-only flat snapshot access (implemented reader, not a field mapper)

Code: `src/app/lexical_extraction/knowledge_snapshot.py`.

**Preflight.** `open_knowledge_snapshot` takes an L02 snapshot directory plus
`sqlite_read_batch_rows` and `sqlite_cache_kib`.
`open_knowledge_snapshot_from_configuration` reads those from an effective
configuration. Success returns one handle and an L01 `KnowledgeSnapshotIdentity`:
`snapshot_id`, streamed `database_sha256`, exact `manifest_sha256`, schema/user
version 1, and preparation version `flat-sqlite-1`.

All four companions must exist and be readable: `knowledge.sqlite`, `manifest.json`,
`validation_report.json`, and a nonempty snapshot `FLAT_SQLITE_CONTRACT.md`. The
stored contract text and producer hash are not compared with later repository files.
Manifest and report are JSON objects. `completion_status` must be the string
`complete`. Schema and database `user_version` must be the exact JSON integer
`1`; Booleans, floats, and numeric strings are rejected even when Python would
compare them to `1`. Preparation version, database file name, size, and hash
must agree. Stringified counts and truthy non-booleans are not proof.
`snapshot_id` must equal the producer derivation from the validated
`snapshot_identity` (`flat-v1-` plus the first 20 lowercase hex characters of
SHA-256 over UTF-8 compact sorted JSON). Identity sources must be the four
expected names and hashes in producer order; a reordered list is rejected and
does not keep the original ID. The filesystem directory name need not equal
`snapshot_id`. The report must record `integrity_check` `ok`,
boolean true for content-digest, source-preservation, and WAL-absence, and table
names, columns, column counts, and imported row counts that match the fixed v1
headers and the manifest row counts.

The database is opened with an encoded `file:` URI and `mode=ro`, then
`PRAGMA query_only=ON`. Preflight requires journal mode `delete`, user version 1,
`PRAGMA integrity_check` of `ok`, exactly the four rowid tables, `TEXT NOT NULL`
columns in contract order, `row_id` as the only primary key, and database row
counts equal to the manifest. A WAL header or `-wal`, `-shm`, or `-journal`
sidecar is rejected. The database hash is streamed in finite chunks. CSV paths
named in the manifest are not required. The reader does not repair, import, or
prepare a snapshot.

**Reads.** Callers name one of `materials_fda_ema`, `materials_chebi`, `equipment`,
or `unit_operations`. `read_batch` and `iter_batches` use
`rowid > after_rowid ORDER BY rowid LIMIT batch_size`, starting at zero, and never
exceed the validated batch limit. An empty page ends the scan.
`lookup` uses that table's source `row_id` primary key and returns the row or
`None` when it is absent. `scan_cursor` is this file's SQLite `rowid`, not
`row_id`. Cells stay stored strings, including blanks, repeated non-key values,
and Unicode. There are no joins, added indexes, normalized tables, or field rules.

**Lifecycle.** One connection stays open for the handle. After preflight, database
changes are detected by size and modification time, and the three small companions
are re-hashed before each read. A detectable change is `SNAPSHOT_CHANGED`: the
connection closes and no rows are returned under the previous identity.
`SnapshotReadError` maps to `SafeStructuredError`. Scans before a successful open
and after close fail. Validation failure does not claim success.

Normalization, matching, value parsing, orchestration, runner/CLI, monitoring, and
publication remain unimplemented. Fixed search-field mapping is L05. Optional
restricted fuzzy matching on the dictionary path is L11.

## 13. L05 fixed V1 source-field mapping (implemented mapper, not a matcher)

Code: `src/app/lexical_extraction/field_mapping.py`.

**Input.** An L04 `SourceRow` plus the independently selected L01/L02 components.
Optional `snapshot_id` is attached for later candidate provenance. The mapper does
not open or rebuild the snapshot by itself; `iter_eligible_terms` may page an
already validated L04 handle and requests only tables needed by those components.

**Output.** Zero or more compact `EligibleSearchTerm` records per row: original
literal spelling, component, term role, source table/field/`row_id`, optional
`lexical_term_id` / snapshot id, selected native IDs/display/qualification/
traceability, and fixed internal `boundary_hint` / `fuzzy_allowed` hints. Blank or
whitespace-only search cells yield no term. Empty optional IDs stay `None`. Exact
case-insensitive unavailable markers (`N/A`, `NA`, `unknown`, `None`) are excluded
from UNII code search and from optional native ID attributes; they are not applied
to Materials names or aliases, and naming rows are retained. Distinct rows and
repeated spellings stay separate. No global vocabulary, persistent index,
normalized comparison key, document span, match evidence, or L01 candidate is
created.

**Fixed V1 fields.**

| Source table | Eligible search cells → component | Notes |
|---|---|---|
| `materials_fda_ema` | `material_name`, `alias_name`, `UNII` → `materials` | Display `material_name`; optional UNII and SMS_ID identities; `alias_type`; `source`. UNII is whole-code and not fuzzy. Unavailable UNII markers are not code-search terms. No CAS or SMS_ID search. |
| `materials_chebi` | `material_name`, `alias_name` → `materials` | Display `material_name`; optional CHEBI_ID; preserve `alias_type` (exact vs related). No CAS or CHEBI_ID search; no cross-catalogue merge. |
| `equipment` | `Equipment type (EN)` → `equipment`; `Operating parameter (EN)` → `parameter_names`; eligible atomic `Unit` → `units` | Equipment identity `equipment_type_id`; parameter identity `parameter_id` plus catalogue equipment scope only. No Greek, brand, model, manufacturer/model ids, or Published range terms. |
| `unit_operations` | `Search term (EN)` → `unit_operations` when `Index this row` is exact `TRUE`; `Process step (EN)` → `process_steps` independently | Preserve known `Match policy` / `record_type` roles. Support/inspection/step-cue become `generic_cue` without inventing `Operation ID`. Unrecognized nonempty policy/record-type values raise `FieldMappingError` with a ≤200-character diagnostic (truncated `row_id` context only; source keys unchanged). |

**Unit eligibility.** Equipment `Unit` is vocabulary only. The fixed conservative rule
rejects placeholders/uncertainty prose, alternatives (` or `, spaced `/`),
semicolons, dash prose, footnote `*` / bare `¹`, embedded whitespace, pure
numerics, and numeric ranges. Compact tokens, slash compounds without spaces, and
mathematical reciprocal forms such as `min⁻¹` remain eligible. Original spelling is
preserved. Quantity/parameter-value components have no catalogue search fields here.

**Fuzzy hint.** `fuzzy_allowed` is an internal V1 shape/scope hint only: eligible
natural-language roles with one alphabetic word of length ≥6 may be true;
chemicals/UNII/units, phrases, short words, and context/support/inspection/generic
cues stay false. L05 does not calculate edit distance.

**Limits.** Matching, normalization, fuzzy distance, value parsing, occurrence
aggregation, runner/CLI, monitoring, and publication remain unimplemented at L05.
Dictionary search omits short literals (under three Unicode code points) and
explicitly `context_required` unit-operation terms; `hasRelatedSynonym` aliases
remain searchable. Normalization helpers are L06. Page classification /
page-policy exclusion remain future work.

## 14. L06 fixed V1 comparison normalization, offsets, and boundaries

Code: `src/app/lexical_extraction/comparison.py`.

**Input.** One L05 `EligibleSearchTerm` and/or one L03 `BlockEvidence` (or raw
literal text with the same `term_role` / `boundary_hint`). Helpers are pure and
do not scan the snapshot, HTML file, or a document-wide index.

**Output.** An immutable `ComparisonSurface`: temporary `comparison_text` plus
ordered `ComparisonUnit` provenance linking each comparison span to a half-open
original code-point range. `project_comparison_range` / `project_against_block`
return an L01 `CharSpan` whose `matched_text` equals the original slice.
Empty/whitespace-only term keys and misaligned or boundary-rejected ranges raise
`ComparisonError` (bounded code/message → `SafeStructuredError`).

**Fixed V1 comparison rules.** Each normalization unit is a Unicode starter plus
any immediately following combining marks; that unit is NFC'd then
`casefold`'d. This is **not** a whole-string NFC pass: adjacent Hangul Jamo such
as `가` remain uncomposed under V1 even though `unicodedata.normalize('NFC', …)`
would compose them. Natural-language roles (`equipment_type`, `parameter_name`,
`unit_operation`, `generic_cue`, `process_step`) also collapse each whitespace
run (including CR/LF) to one separator. Materials names/aliases, UNII
(`whole_code`), and units (`atomic_unit`) do not collapse whitespace and preserve
chemical punctuation, signs, digits, stereochemistry, unit slashes, and
superscripts. No stemming, NFKC, accent stripping, OCR hyphen repair, lookalike
transliteration, or cross-block joining. Projection must cover complete
normalization units (including case-fold expansions such as `ß` → `ss`);
normalized indices are never used as original offsets.

**Fixed V1 boundaries** (checked on original exteriors):

- `default`: rejects embedded hits beside letters/marks/decimal digits/connector
  punctuation **or hyphen-minus**, so shorter material names are not accepted
  inside hyphen-connected forms (`glucose-6-phosphate`, `water-soluble`). A full
  punctuation-bearing chemical term still matches as itself. Space-separated
  phrase overlaps at a word edge remain valid.
- `whole_code`: same continuation set as `default` for exterior checks (including
  `-`), so a UNII is not found inside a longer alphanumeric/hyphen/underscore
  identifier.
- `atomic_unit`: continuation includes letters/marks/connectors, `/`, middle dot
  `·`, hyphen-minus, superscript signs, and numeric characters in categories
  `Nd` and `No`. Shorter hits inside `min⁻¹`, `mL·min⁻¹`, `kg²`, and `rpm/min`
  are rejected; complete compounds remain eligible. Left number-adjacent
  permission uses ordinary decimal digits (`Nd`) only (`37°C`, `120rpm`), not
  superscript/`No` numbers.

**Limits.** Value parsing, occurrence/candidate aggregation, runner/CLI,
monitoring, and publication remain unimplemented. Bounded exact /
normalized-exact matching is L07; optional restricted fuzzy matching is L11.

## 15. L07 bounded Aho–Corasick raw discoveries (implemented matcher core, not aggregation)

Code: `src/app/lexical_extraction/dictionary_matcher.py` (+ `fuzzy_matching.py` for L11).
Dependency: `pyahocorasick`.

**Input.** An iterable of L05 `EligibleSearchTerm` records, a replayable
`BlockReplaySource` of L03 `BlockEvidence` (synthetic `StaticBlockSource` or
`ReviewedHtmlBlockReplay`), L02 `ResourceLimits`, and optional keyword-only
`fuzzy_enabled` (default `False`). L02's YAML schema is not modified here; a later
runner may pass the effective selection through this seam.

**Output.** Streamed intermediate `RawDiscovery` records: method
`exact` / `normalized_exact` / optional `fuzzy`, fixed L01 rule ids, component/role,
source table/field/`row_id`, optional `lexical_term_id` / snapshot id, original
dictionary spelling, block `node_id`, L01 `CharSpan` with
`block.text[start:end] == matched_text`, and optional `edit_distance` (fuzzy only).
Not an L01 `DictionaryOccurrence`, candidate, or publication claim.

**Shard / replay lifecycle.** Terms are consumed once into finite shards counted
by source references (`max_terms_per_shard`) and retained string code points
(`max_term_codepoints_per_shard`, including deletion-signature storage when fuzzy
is ON). Each shard indexes distinct L06 comparison keys with Aho–Corasick (all
colliding source references retained), partitions by whitespace-collapse profile,
optionally builds a fuzzy deletion-signature index over eligible keys, rescans
every block, emits through a buffer of at most `result_buffer_records`, then
releases automata, fuzzy index, and shard-local maps. When `fuzzy_enabled` is
false, fuzzy state is not built. Shards may rescan blocks. For reviewed HTML,
each pass reopens the file; the first complete pass pins `html_sha256`; a changed
or incomplete identity fails closed. Discovery multisets for identical pinned
inputs are independent of shard limits; emission order may follow shard order.

**Fuzzy rule (when ON).** Ordinary Levenshtein distance 1 on L06 comparison
strings for eligible single alphabetic natural-language words of at least six
Unicode code points (equipment type, parameter name, unit operation, independently
eligible process step), gated by L05 `fuzzy_allowed` and fixed role/policy
exclusions. Distance 0 is never fuzzy. Adjacent transposition alone costs two and
is rejected. Materials/chemicals/UNII/units/generic cues/abbreviations/phrases/
equipment codes remain available to exact/normalized-exact only. A document word
one character shorter than an eligible term is still considered for deletion
matches. Projection uses L06 default boundaries; partial units and invalid
boundaries are non-hits or fail closed without silent misprojection.

**Failures.** Oversized single references (including fuzzy signature cost), shard
construction failures, fuzzy-index failures, block-read failures, and identity
mismatches raise bounded `DictionaryMatchError` (→ `SafeStructuredError`).
Projection skips only `BOUNDARY_REJECTED` and `PARTIAL_NORMALIZATION_UNIT` as
normal non-hits; other L06 `ComparisonError` codes become `PROJECTION_FAILED`.
Exceptions while creating or consuming the Aho–Corasick iterator are
`MATCH_FAILED` (not `BLOCK_READ_FAILED`). Early generator close releases shard
state. Hits are never silently truncated; references are never last-write-wins
deduplicated.

**Limits.** Aggregation of same-span discoveries, canonical result order,
value parsing, runner/CLI, monitoring, and publication remain unimplemented.
Bounded dictionary aggregation is L08.

## 16. L08 bounded dictionary aggregation (implemented aggregator core, not a runner)

Code: `src/app/lexical_extraction/dictionary_aggregation.py`. Optional L01 field:
`supporting_row_ids` on the shared candidate base (default empty).

**Input.** An iterable of L07 `RawDiscovery` records (dictionary components only),
a replayable `BlockReplaySource`, an open L04 `SnapshotLookup` /
`KnowledgeSnapshot`, and L02 `ResourceLimits`. Required
`expected_source_identity` must equal the pinned L07 document identity after
replay (`SOURCE_IDENTITY_REQUIRED` when omitted).

**Output.** `AggregatedBlockStream` yielding L01 `BlockRecord` values in document
order (empty-match blocks preserved). After complete successful consumption
**and** successful spool cleanup, `coverage` reports block/occurrence/candidate/
discovery counts and the final source identity. Emitted records before that point
are provisional. Not a whole-run tree, final outcome, or published artifact.

**Spool / grouping lifecycle.** Discoveries are written to a run-local temporary
SQLite spool (`PRAGMA temp_store=FILE`), then regrouped by block and original
span. Per-block capacity uses a disk-backed `block_hit_counts` primary-key
counter updated with each discovery insert (same deferred transaction /
rollback), plus fetch `LIMIT result_buffer_records + 1` as a defensive read
guard. Capacity checks do not repeatedly `COUNT(*)` the discoveries table.
Hits loaded for an
emitted block are marked consumed; leftover unconsumed hits after replay raise
`UNMATCHED_SPOOL_HITS`. Same-span source references keep `exact` over
`normalized_exact` over `fuzzy`. Fuzzy rows store verified integer `edit_distance=1`;
L08 also requires the observed comparison text to be one alphabetic word within
one-edit length of the source key (observed span edges are **not** stripped, so
leading/trailing whitespace inside ``matched_text`` fails), and during block replay
requires the fuzzy span to satisfy literal slice equality and the source term's
fixed L06 boundary against `block.text`. Ineligible, non-word, distance-mismatched,
or boundary-invalid fuzzy claims raise bounded errors (`FUZZY_NOT_ELIGIBLE` /
`FUZZY_OBSERVED_NOT_WORD` / `FUZZY_DISTANCE_MISMATCH` / `FUZZY_BOUNDARY_REJECTED` /
`INVALID_FUZZY_DISCOVERY`) instead of turning injected raw hits into evidence.
Equivalent mapped candidate interpretations collapse to one
candidate with lexicographic representative `row_id` and sorted
`supporting_row_ids`. Optional interpretation-key fields sort with a deterministic
comparable form (`None` before strings) without changing grouping equality.
Candidates are rehydrated by single-table L04 `lookup` plus L05 `map_source_row`.
Unit raw discoveries are rejected. Spool connection close precedes directory
delete (Windows-safe); cleanup failure is `SPOOL_CLEANUP_FAILED` and does not set
coverage. Final spool `commit()` failure is `SPOOL_WRITE_FAILED` (not a raw
sqlite error). Early ingest failure closes a closable upstream discovery iterator.

**Failures.** Missing/mismatched lookup or snapshot identity, unexpected unit
input, missing required source identity, replay identity change, unmatched spool
hits, invalid/ineligible fuzzy claims, spool I/O/cleanup errors, and
per-block/group overflow of `result_buffer_records` raise bounded
`DictionaryAggregationError`. Failures do not claim completed coverage.

**Limits.** Same-span discoveries collapse to one candidate per component/block/span
with canonical-name precedence over aliases where applicable. After aggregation,
page buffering retains one displayed dictionary occurrence per
`(page, component, casefolded matched text)`, bounded by `result_buffer_records`.
Components stay independent. Runner/CLI/monitoring/publication are L12/L13.
Stage 3 projects published occurrences into the current review UI. Independent
unit/`UnitOccurrence` aggregation and value-expression recognition are L10.
Full-Materials time/peak-memory feasibility requires a local reviewed HTML v1
export and is recorded separately when run.

## 17. L10 independent parameter names, units, and value expressions

Code: `unit_value_rules.py`, `unit_aggregation.py`, `value_expressions.py`,
`parameter_unit_value.py`.

**Public API.** `iter_parameter_unit_value_block_records` streams per-block
`BlockRecord` values for independently selected `parameter_names`, `units`,
`quantity_expressions`, and/or `parameter_value_expressions`.
`recognize_block_values` is the per-block value-only helper. The stream composes
ordered L08 dictionary blocks, L10 unit blocks, and per-block value recognition
incrementally (no whole-document discovery/result containers). Early `close()`
releases owned spool/stream resources; coverage is available only after complete
successful consumption and child-stream cleanup. Value-only selection without
parameter/unit streams may drive a fresh `ReviewedHtmlBlockReplay` when an
expected full-file SHA-256 is supplied: blocks stream without an all-document
buffer, the unpinned first pass is permitted for that case only, and the
finalized replay identity is checked after full consumption before coverage is
published. Wrong digest, read failure, or early close leaves coverage
unpublished (`STREAM_INCOMPLETE` / explicit identity failure). Already-pinned
sources keep immediate identity checks.

**Parameter names.** Stay on the accepted L05→L07→L08 path. Equipment detection
is never required or performed when only parameter-name terms are supplied.
Optional `fuzzy_enabled` (default `False`) is forwarded only to that dictionary
seam; units and value expressions remain non-fuzzy.

**Units.** L07 raw discoveries for `Component.UNITS` are aggregated by L10 unit
aggregation, not L08. L08 continues to reject unit discoveries with
`UNEXPECTED_UNIT_DISCOVERY`. Equipment `Unit` rows require a pinned snapshot and
L05 mapping; they use `EquipmentUnitRecord` with additive optional
`supporting_row_ids` when denormalized rows repeat one spelling, and
deterministic representative `Source / section`. Fixed quantity units use
`FixedUnitVocabulary` and the versioned vocabulary in `unit_value_rules.py`
(`lexical-unit-vocabulary-v1` / `lexical-unit-value-rules-v1`). Dual
fixed+equipment hits keep controlled spelling/identity and equipment row refs.
`result_buffer_records` is per-block.

**Values.** Controlled scalar-with-unit, range, comparison, symmetric-tolerance,
categorical (`OFF`, `under vacuum`), and cued-unitless (`Speed:`) forms. Exact
original spans and nested number/unit/group agreement are required. Unit
recognition inside values is casefold-consistent with L06/L07 while preserving
the exact source substring. Selecting a value component may recognize a unit
inside an expression without emitting a standalone `UnitOccurrence` unless
`units` is also selected. Both value components together emit one occurrence
with both `applies_to` values. Ambiguous `1,000` stays unresolved
(`AmbiguousNumber`); free-standing page/date/identifier/step-label quantities,
identifier-prefixed range/tolerance tails, and embedded cues are rejected. No
unit conversion, parent binding, or catalogue Published-range substitution.

**Limits.** Not a CLI, publisher, review UI, or LLM workflow. L12 composes this
capability into the callable runner; final-manifest publication remains L13.

## 18. L12 callable extraction runner and operational monitoring

Code: `runner.py`, `monitoring.py`.

**Public API.** `run_lexical_extraction(config: EffectiveExecutionConfiguration,
sink: EvidenceSink) -> LexicalRunResult`. Optional
`run_lexical_extraction_from_config_path` loads L02 YAML then delegates.
`fixed_rules_sha256()` digests the fixed V1 rules actually used (not a synthetic
fixture digest).

**Evidence sink lifecycle.** Caller-owned: `begin_run` → per-component
`begin_component` → provisional component-scoped `write_page(component, page)` /
`write_block` → `complete_component` or `abort_component` → `complete_run` or
`abort_run`. Page skeletons are streamed from a fresh L03 reader per component
(no retained all-page list); empty pages and identity checks are preserved.
Writes before `complete_component` are provisional. A failed sink write is an
execution/output failure (`SINK_WRITE_FAILED`). `abort_component` must not be
called for an already completed component. `abort_run` after committed components
is a run-level finalization signal and must leave those completed outcomes
intact. `complete_run` failure preserves validated identities and committed
outcomes and sets additive `LexicalRunResult.run_error`
(`SINK_COMPLETE_RUN_FAILED`). L13 owns atomic publication; a successful L12
stream is not itself a published result and does not construct a completed
`PublicationRecord`.

**Preflight.** One full L03 HTML validation (exact-byte SHA-256 + producer
metadata; page/block counts only) and one L04 snapshot preflight before search.
Failures before HTML validation use `PreValidationFailure` without fabricating
job/revision/generation/hash. Snapshot preflight failure marks all requested
components failed with validated HTML identity retained when available. Snapshot
and streams close on success, failure, and early stop.

**Execution grouping.** Exactly L02's resolved component union; `fuzzy_enabled`
is the sole matching switch passed to dictionary and parameter-name search.
Materials, UNII, and units remain non-fuzzy via accepted L05/L07/L10 rules.
`unit_operations`, `process_steps`, `materials`, and `equipment` each run an
independent L05→L07→L08 pass. Selected `parameter_names`, `units`,
`quantity_expressions`, and `parameter_value_expressions` share one L10
composition so values are not duplicated. Preset resolution is not reimplemented.
Eligible term/row monitoring uses `EligibleTermCounter` (previous-key integer;
no retained row-id set).

**Outcomes.** Zero-hit requested components complete with count 0 only after full
stream/replay success. Failed shards or incomplete child streams are not
completed. Independent completed components remain usable when another fails
(overall `partial`). Shared prerequisite failure fails all affected requested
components.

**Provenance and monitoring.** `RunProvenance` is emitted when HTML and snapshot
identities are known, including effective configuration SHA-256, requested/
resolved selection, fuzzy flag, engine/dependency versions, timings, measured
values, and `rules_sha256`. Monitoring summarizes observed pages/blocks,
completed/failed/zero-result components, matches by component/method, eligible
terms/rows/candidates when accurately measured, stage elapsed times, configured
resource limits, and peak process memory with method label when measurable;
unavailable counters are omitted or marked unavailable, never guessed as zero.

**Limits.** No CLI, dashboard, telemetry server, audit ledger, final manifest,
or new monitoring-only dependency. Shard-phase splits that cannot be observed
without changing accepted L07/L08 modules are omitted. Final-manifest publication
and the operator CLI are L13.

## 19. L13 CLI and atomic lexical-result publication

Code: `publication.py`, `__main__.py`.

**Operator entry.** `poetry run python -m app.lexical_extraction --config
<path-to-execution.yaml>` loads strict L02 YAML and calls the same L12
`run_lexical_extraction` used by tests, then `finalize_publication`. Exit codes:
`0` extraction completed + publication completed; `1` extraction partial +
publication completed; `2` extraction/pre-validation failure; `3` publication or
CLI/config failure. Compact stdout summary: run id, extraction/publication
status, per-component match counts or error codes, peak memory when measured,
manifest path when present. No source block text or catalogue rows in logs.

**Run directory.** Creates `{output.directory}/{run_id}/` and never replaces an
earlier run or mutates input/snapshot. Staging lives under `.staging/`. Completed
components commit `artifacts/component-<name>.json` (schema
`batchlens.lexical-component-artifact.v1`) via temporary file + atomic replace.
Each artifact retains ordered pages (including empty), original block text,
`node_id`, OCR refs, exact spans, overlaps, ambiguous candidates, and
`supporting_row_ids`. Zero-hit completed components still publish full
page/block coverage.

**Sink lifecycle.** L12 `complete_run` seals the sink but does not write the
final manifest. Orchestration finalizes after `LexicalRunResult` returns.
Requires sealed state, matching run id, no `run_error`, no provisional
component, validated identities, and artifact/outcome agreement. Concurrent
provisional components are allowed while L10 emits page skeletons before the
shared block stream. `abort_component` discards that component's provisional
output only.

**Final manifest.** Written last as `manifest.json` (schema
`batchlens.lexical-run-manifest.v1`) via temporary file + atomic replace. Carries
validated HTML identity, snapshot identity, provenance (effective config/rules
digests, engine/dependency versions, selection, fuzzy flag), extraction
outcomes, compact monitoring, artifact relative paths/byte sizes/SHA-256, and an
L01-compatible completed `PublicationRecord`. Partial extraction may claim
publication `completed` while listing only completed-component artifacts. Failed
or interrupted publication must not leave a final manifest claiming completed
publication. The manifest is never hashed as though its own bytes were known.

**Readers.** `load_final_manifest`, `verify_artifact_hashes`,
`open_component_artifact_stream`, `iter_component_pages` /
`iter_component_pages_from_stream`, and `locate_hit` support integrity checks and
page/node/span navigation. Page/block iteration uses a compacting incremental
UTF-8 JSON buffer (one value at a time; never a whole-file `json.loads`; retained
lookahead does not grow with previously consumed records). Invalid UTF-8,
truncated envelopes, trailing data after the root object, and `page_count`
mismatches fail closed. `locate_hit` requires an exact occurrence span match.
Early close of `iter_blocks()` still drains remaining block JSON so the next
page stays aligned. Staging uses disk meta for page/block order; out-of-order
blocks fail closed. Artifact bytes are write-all checked and hashed from the
completed file. `output.directory` must not equal or lie inside the snapshot
directory (resolved containment), enforced before `begin_run` creates paths.

**Limits.** Not a review/approval UI, API, resume/retry service, cross-process
run registry, or background cleanup worker. No new dependency without need.
