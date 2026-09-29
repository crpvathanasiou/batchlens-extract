# 04 — Code Map

Repository code is authoritative when this map disagrees.

Documentation reading order and authority:

```text
03_common_handoff.md     current execution state and next action
00_project_reference.md  product purpose, two-leg model, boundaries
04_code_map.md           this file — where code and responsibilities live
01_implementation_roadmap.md  milestone sequence
02_code_quality_standards.md  how work must be performed
05–08                    pipeline, security, evaluation, check-selection design
```

Project/reference documents explain why and what. Roadmap/lifecycle documents explain order and
milestones. Quality/implementation documents explain how work must be performed. This map
explains where code lives. `03_common_handoff.md` is the current cross-session restart anchor.

## Runtime summary

- Python 3.11, FastAPI, Pydantic v2, Poetry
- Durable job metadata and review heads: DynamoDB (intended production composition; not
  integration-verified)
- Protected versioned source/results/review artifacts: S3 (intended; not integration-verified)
- Authentication and owner identity: Cognito access-token `sub` (intended; not
  integration-verified)
- Asynchronous OCR: SQS worker + AWS Textract
- Conversion: Amazon Textractor 1.10.0
- Review UI: Vue 3, TypeScript, TipTap 3, PDF.js; built by Vite into the Python image
- API prefix: `/api/v1/documents/jobs`
- Docker: Node 22.12 builder stage emits `src/app/document_review/static/` into the Python image

## Implemented modules

```text
src/app/
├── api/
│   ├── system.py                    health/version routes
│   ├── documents.py                 upload/jobs/original downloads/static shell/auth dependency
│   └── document_reviews.py          source/review/page approval/final approval/export/context/lookup routes
├── document_conversion/
│   ├── contracts.py                 frozen Document/evidence schema 1.0.0
│   ├── adapter.py                   Textractor → canonical Document
│   ├── tolerance.py                 unchanged conservative advisory detector
│   ├── textractor_renderer.py       original unreviewed HTML
│   ├── aws.py                       Textract and S3 source SDK boundary
│   └── provider.py                  raw response validation
├── document_jobs/
│   ├── contracts.py                 Job/Artifact/storage protocols
│   ├── auth.py                      Cognito JWT verification → sub
│   ├── storage.py                   DynamoJobStore, S3ObjectStore, SqsQueue
│   ├── service.py                   durable conversion FSM
│   ├── composition.py               bounded AWS SDK composition
│   ├── worker.py                    resumable queue worker
│   └── static/                      existing login/upload/jobs/original-download shell
├── document_review/
│   ├── contracts.py                 review envelope/head/API/catalogue/approval/save-operation/context contracts
│   ├── mapping.py                   stable nodes, sparse text changes, hashes/findings
│   ├── operations.py                Save fingerprint v1 and committed-chain reconciliation helpers
│   ├── history.py                   B1 derived fail-closed committed-chain projection
│   ├── history_jsonl.py             B2a atomic derived history.jsonl writer/reader
│   ├── rendering.py                 deterministic escaped reviewed HTML with catalogue provenance attributes
│   ├── storage.py                   small Dynamo CAS head + UUID versioned S3 objects
│   ├── service.py                   ownership/save/decision/approval/export; context; update_with_receipt
│   ├── composition.py               bounded production AWS adapters plus opaque storage namespace
│   ├── static/                      reproducible ignored Vite output
│   └── README.md                    review contract and consumer boundary
├── lexical_extraction/
│   ├── contracts.py                 L01 evidence, candidate, value, and outcome records
│   ├── configuration.py             L02 YAML load, preset resolution, effective digest
│   ├── html_reader.py               L03 reviewed HTML v1 reader → PageRecord/BlockEvidence
│   ├── knowledge_snapshot.py        L04 read-only flat SQLite snapshot paging and row_id lookup
│   ├── field_mapping.py             L05 fixed V1 SourceRow → eligible search-term mapping
│   ├── comparison.py                L06 fixed V1 comparison normalize / offset map / boundaries
│   ├── dictionary_matcher.py        L07/L11 bounded AC exact/normalized-exact + optional fuzzy raw discoveries
│   ├── fuzzy_matching.py            L11 deletion-signature index and distance-1 helpers
│   ├── dictionary_aggregation.py    L08 bounded dictionary occurrence aggregation → BlockRecord (incl. fuzzy)
│   ├── unit_value_rules.py          L10 fixed V1 quantity-unit vocabulary and categorical/cue rules
│   ├── unit_aggregation.py          L10 unit-mention aggregation (not L08)
│   ├── value_expressions.py         L10 controlled value-expression recognition
│   ├── parameter_unit_value.py      L10 independent parameter/unit/value block-stream API (+ fuzzy flag)
│   ├── monitoring.py                L12 compact in-memory operational monitoring helpers
│   ├── runner.py                    L12 callable run boundary + evidence-sink lifecycle
│   ├── publication.py               L13 filesystem EvidenceSink, atomic artifacts, final manifest
│   └── __main__.py                  L13 thin CLI: load L02 YAML → L12 run → finalize publication
├── extraction_review/
│   ├── contracts.py                 U1 current-state models: findings, provenance, revision id, approval
│   ├── transitions.py               pure initialize / save / approve over current state
│   └── store.py                     U1.2 atomic current-review.json under extraction-reviews/<sha256(job_id)>/
└── main.py                          feature lifespan, routers, CSP/isolation middleware

frontend/
├── src/                             Vue workspace, API/state, TipTap mapping/extensions, pendingSave
├── tests/                           editor/mapping/state/API/round-trip/build-output/pending-save tests
├── package.json / package-lock.json pinned Node dependencies
└── vite.config.ts                   library output under document_review/static

tests/lexical_extraction/
├── acceptance.py                    L09 read-only Materials feasibility measurement helper
├── test_acceptance.py               L09 helper synthetic fail-closed / digest checks
├── test_contracts.py                L01 public record and coherence tests
├── test_configuration.py            L02 configuration load/resolve/digest tests
├── test_html_reader.py              L03 reviewed HTML reader and evidence mapping tests
├── test_knowledge_snapshot.py       L04 flat snapshot preflight, paging, and row_id lookup tests
├── test_field_mapping.py            L05 fixed V1 field-mapping and eligibility tests
├── test_comparison.py               L06 comparison normalization, projection, and boundary tests
├── test_dictionary_matcher.py       L07 Aho–Corasick shard matching and raw-discovery tests
├── test_dictionary_aggregation.py   L08 dictionary aggregation and supporting-ref tests
├── test_fuzzy_matching.py           L11 optional fuzzy matching and L08/L10 bridge tests
├── test_parameter_unit_value.py     L10 independent parameter/unit/value tests
├── test_runner.py                   L12 callable runner, sink lifecycle, and failure-boundary tests
└── test_publication.py              L13 filesystem publication, CLI, and atomic-manifest tests

tests/extraction_review/
├── test_contracts.py                U1 current-state contract validation
├── test_transitions.py              U1 pure initialize/save/approve transitions
└── test_store.py                    U1.2 create/load/save/approve/reload and byte-stability

tests/document_review/
├── test_backend_review.py           canonical lifecycle/mapping/API/approval
├── test_rendering.py                reviewed HTML provenance attributes
├── test_save_operations.py          Save operation identity, fingerprint, replay, provenance
├── test_history_projection.py       B1 committed-history projector (in-memory, fail-closed)
├── test_history_jsonl.py            B2a atomic history.jsonl materialisation / status
├── test_local_history.py            B2b local-harness published-history rebuild / failure
├── test_backend_storage.py          Dynamo/S3 SDK request shapes and pinned source
├── test_review_context.py           storage namespace, sidecar identity, in-flight lookup
├── local_store.py                   test-only atomic files, sidecar, derived history.jsonl
├── local_harness.py                 localhost acceptance entry point
└── test_local_harness.py            restart/conflict/export/input-preservation tests
```

Inspect when:

| Path | Responsibility | Upstream → downstream | Inspect when |
|------|----------------|-----------------------|--------------|
| `src/app/document_conversion/contracts.py` | Frozen unreviewed `Document` 1.0.0 | Raw Textract JSON → jobs artifacts and review baseline | Changing conversion schema, evidence, or status |
| `src/app/document_conversion/adapter.py` | Textractor parse/map/validate | `provider.py` + Textract JSON → `Document` | Changing conversion mapping or relationship limits |
| `src/app/document_conversion/textractor_renderer.py` | Unreviewed HTML | Adapter `Document` / Textractor objects → `document.html` | Changing original HTML, banners, or warning lists |
| `src/app/document_conversion/tolerance.py` | Advisory `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` | Element/cell text → `Document.warnings` | Changing detector rules; must not rewrite OCR text |
| `src/app/document_conversion/aws.py` | Textract/S3 SDK boundary | Job worker → provider JSON + source identity | Changing OCR submit/collect or source pinning |
| `src/app/document_jobs/service.py` | Conversion job FSM | Upload/start/worker → immutable original artifacts | Changing job phases, retries, or artifact names |
| `src/app/document_jobs/auth.py` | Cognito JWT → `sub` | HTTP bearer → owner checks | Changing identity; local harness replaces this |
| `src/app/api/documents.py` | Upload/jobs/original downloads + `owner` | Cognito + job store → conversion shell | Changing job HTTP contracts or ownership hiding |
| `src/app/api/document_reviews.py` | Review HTTP surface | Same `owner` dependency → `ReviewService` | Changing review routes, context/lookup, or error codes |
| `src/app/document_review/contracts.py` | Review envelope/head/API models, optional Save operation metadata, change provenance, ReviewContext | Conversion `Document` → revisions/exports | Changing review schema, decisions, approval, Save operation fields, or context hash |
| `src/app/document_review/mapping.py` | Stable node IDs, text-only apply, findings | Baseline `document.json` → catalogue/changes | Changing IDs, sparse changes, or finding hashes |
| `src/app/document_review/operations.py` | Fingerprint v1 and committed parent-chain walk | Validated Save body → replay/mismatch/integrity errors | Changing Save identity, fingerprint material, or chain rules |
| `src/app/document_review/history.py` | Derived in-memory committed-history projection | Frozen `ReviewHead` + revision reader → coverage + chronological records | Changing projected fields, coverage, frozen-head/envelope summary equality, `revision_created_at` vs chain order, invalidation-only-when-absent, or fail-closed `DOCUMENT_APPROVED`/approval-hash rules |
| `src/app/document_review/history_jsonl.py` | Atomic derived `history.jsonl` writer/reader | B1 projection → one JSONL file with embedded coverage; `CURRENT`/`STALE`/`INVALID_OR_MISSING`; prepare/write I/O is `HISTORY_JSONL_WRITE_FAILED` | Changing JSONL schema, atomic replace, I/O error normalisation, validation, or status meanings |
| `src/app/document_review/service.py` | Save/decision/approval/export use cases; `update` remains `ReviewState`; receipts are `update_with_receipt` / `reconcile_save_operation`; additive `review_context` | Mapping + storage → immutable revisions | Changing revision/CAS/approval invalidation, Save replay, or context derivation |
| `src/app/document_review/storage.py` | Dynamo head + versioned S3 objects | Service persist → reachable head | Changing CAS conditions or object keys |
| `src/app/document_review/rendering.py` | Deterministic reviewed HTML. Attribute contract v1 on `<html>` (`data-review-html-version`, `data-job-id`, `data-review-revision-id`, `data-review-generation`, `data-conversion-status`); catalogue `data-element-id` / `data-node-id` / `data-table-id`; ordered deduped `data-source-id` on text-bearing nodes; `data-generated="true"` on the summary header, partial banner, and `Page N` headings | `ReviewRevision` catalogue plus current document text → export HTML | Changing approved HTML heading/table markup or provenance attributes |
| `src/app/extraction_review/contracts.py` | U1 current-state review models: complete finding list, per-finding provenance, one revision id, null-or-one approval | L01 provenance types + published run facts → versioned review contracts; no I/O | Changing current-state shape, finding provenance, approval semantics, or command shapes |
| `src/app/extraction_review/transitions.py` | Pure initialize / save / approve over one current state; Save clears approval and requires a new revision id | Commands + `ExtractionReviewState` → outcomes | Changing stale conflict, no-op, Add uniqueness, provenance stamping, or discard-on-save behavior |
| `src/app/extraction_review/store.py` | U1.2 local atomic JSON: one `current-review.json` per `sha256(job_id)` workspace | Data dir + job_id / commands → durable current `ExtractionReviewState` | Changing path layout, atomic write, create/load/save/approve persistence rules |
| `tests/extraction_review/test_contracts.py` | Contract validation for current-state models and provenance | Pydantic validation cases | Changing allowed finding/approval/command shapes |
| `tests/extraction_review/test_transitions.py` | Pure transition coverage for initialize/save/approve | In-memory state transitions | Changing Save/Approve semantics |
| `tests/extraction_review/test_store.py` | Local JSON create/load/save/approve/reload and non-changed byte stability | Temp directories only | Changing store persistence behavior |
| `src/app/lexical_extraction/contracts.py` | L01 lexical evidence, candidate, unit/value, provenance, extraction-outcome, and publication-claim records | Reviewed HTML v1 identity and flat-SQLite field names → bounded records; no reader or publisher | Changing lexical record fields, span checks, outcome coherence, or publication claims |
| `src/app/lexical_extraction/configuration.py` | L02 strict execution YAML load, fixed preset→component union, resource safeguards, effective SHA-256 | Config file path (+ optional typed selection override) → `EffectiveExecutionConfiguration`; no I/O beyond reading the YAML file | Changing YAML shape, preset map, path resolution, override semantics, resource bounds, or digest material |
| `src/app/lexical_extraction/html_reader.py` | L03 streaming reviewed HTML v1 reader; fail-closed provenance; final digest only on completed read | File path → chunked `iter_pages` → `PageRecord`/`BlockEvidence`; final `ReviewedHtmlV1Input` only when `completed` | Changing streaming/completion semantics, exact version `"1"`, duplicate-attribute rejection, or silent-omission failures |
| `src/app/lexical_extraction/knowledge_snapshot.py` | L04 read-only flat SQLite snapshot preflight, pinned connection, single-table `rowid` paging, and source `row_id` lookup | Snapshot directory + L02 batch/cache limits → `KnowledgeSnapshotIdentity` and raw source rows | Changing companion validation, read-only pinning, allowlisted paging, or `row_id` lookup |
| `src/app/lexical_extraction/field_mapping.py` | L05 fixed V1 per-table search-field mapping and eligibility over L04 `SourceRow` | Raw source rows + selected components → compact `EligibleSearchTerm` stream; no matching | Changing eligible fields, UNII/unit boundary hints, `Index this row` authorization, or unit-token eligibility |
| `src/app/lexical_extraction/comparison.py` | L06 fixed V1 per-term/per-block comparison normalization, comparison→original projection, and role-aware boundaries | One term or block text → temporary `ComparisonSurface` and optional `CharSpan`; no matcher | Changing NFC/casefold/whitespace rules, unit alignment, or `default` / `whole_code` / `atomic_unit` boundaries |
| `src/app/lexical_extraction/runner.py` | L12 callable run boundary: HTML/snapshot preflight, component execution, component-scoped sink streaming, outcomes/provenance/`run_error` | `EffectiveExecutionConfiguration` + `EvidenceSink` → `LexicalRunResult` | Changing sink lifecycle, page scoping, failure boundaries, component grouping, or outcome honesty |
| `src/app/lexical_extraction/monitoring.py` | L12 compact in-memory monitoring and nonprivileged peak-memory measurement | Runner accumulator → `RunMonitoringSummary` | Changing measured counters, unavailable semantics, or memory method labels |
| `src/app/lexical_extraction/publication.py` | L13 filesystem EvidenceSink, streamed page/block staging, atomic artifacts, final-manifest-last publication, snapshot output guard | Output directory + L12 result → run directory artifacts + optional `manifest.json` | Changing staging bounds, streaming read/write, locate_hit, atomic replace, or snapshot path guard |
| `src/app/lexical_extraction/__main__.py` | L13 thin CLI over L02 YAML + L12 runner + L13 finalize | `--config` path → exit code + compact summary | Changing exit codes, summary fields, or CLI surface |
| `src/app/document_review/composition.py` | Production Dynamo/S3 wiring plus opaque storage namespace | Document settings → `ReviewService` | Changing production adapters; not used by harness |
| `frontend/src/mapping.ts` | Page projection, sparse text, skeleton | Canonical page → TipTap JSON | Changing heading/table projection or IDs |
| `frontend/src/extensions.ts` | Protected TipTap schema and load | Projection JSON → editor transactions | Changing structure lock, table attrs, page load |
| `frontend/src/pendingSave.ts` | sessionStorage pending Save record | Frozen Save body → same-tab recovery | Changing recovery keys, schema validation, matching cleanup, or storage errors |
| `frontend/src/state.ts` | Review client state, exclusive Save reservation, pending lifecycle | Editor drafts → `PUT /review` | Changing reservation, terminal context revalidation, uncertainty vs 422 rejection, lookup proof, known-commit, or pending retirement |
| `frontend/src/components/` | Workspace, PDF pane, editor, findings | State + API → browser UI | Changing navigation, findings scope default/filter, status copy, or recovery controls |
| `frontend/vite.config.ts` | Library build into Python static dir | `frontend/src` → `document_review/static` | Changing bundle names, `process.env.NODE_ENV`, worker |
| `tests/document_review/local_harness.py` | Localhost acceptance server | Real review routes + Vue bundle + file store; startup prints history path/status | Changing harness bind, identity, startup, or local history rebuild failure surfacing |
| `tests/document_review/local_store.py` | Synthetic identity + atomic local files + `review-context.json` + derived `history.jsonl` | Supplied originals → `.local-review-data/` | Changing manifest, sidecar identity, immutability, overlap guards, or local history rebuild |
| `tests/document_review/` | Backend/harness tests, including `test_save_operations.py`, `test_history_projection.py`, `test_history_jsonl.py`, and `test_local_history.py` | Review contracts, Save replay, local adapters, B1 projection, B2a JSONL, B2b local rebuild | Changing lifecycle, CAS request shapes, exports, Save operations, committed-history projection, or local history.jsonl rebuild |
| `frontend/tests/` | jsdom/component/build tests | Frontend mapping/state/UI | Changing editor invariants or bundle output |
| `Dockerfile` | Node 22.12 review build then Python image | `frontend/` + `src/` → runtime static assets | Changing image layout or frontend copy path |
| `src/app/main.py` | Feature flag, routers, CSP middleware | Settings → conversion/review composition | Changing enablement, CSP, or router install |

`scripts/enhance_knowledge_csv_ids.py` adds content-based `row_id` / naming / equipment
grouping IDs to the three designated Materials and Equipment final CSVs (FDA/EMA, ChEBI,
Equipment). Synthetic tests: `tests/test_enhance_knowledge_csv_ids.py`. Production enhancement
requires explicit authorization; Unit Operations remains out of scope.

`scripts/profile_knowledge_files.py` is a thin streaming observer for the four designated
final knowledge CSVs (materials SMS, ChEBI, equipment, unit operations). It writes
`Knowledge_Data_Profile.json` only after all four profiles succeed. Synthetic tests:
`tests/test_profile_knowledge_files.py`.

`scripts/build_unified_unit_operations.py` is a standalone consolidation utility (stdlib CSV only)
that expands `uo_unified_table.csv`, `uo_lexical_terms.csv`, and `uo_operation_links.csv` into one
flat `Unified_Unit_Operations.csv` (37 scalar columns including stable entity IDs; cartesian
step × lexical × incident-link rows plus generic step cues). Construction source ordinals are
internal inputs to `row_id` only. It is not wired into the conversion/review runtime. Lexical
search and RAG consumers are separate. Focused synthetic tests live in
`tests/test_build_unified_unit_operations.py`. Production consolidation of the Desktop
Unit-Operations inputs requires explicit user authorization.

`scripts/prepare_lexical_knowledge_sqlite.py` builds one flat SQLite snapshot from the four
current final CSVs (`materials_fda_ema`, `materials_chebi`, `equipment`, `unit_operations`).
Schema version 1 stores original columns as `TEXT` with source `row_id` as the primary key.
It does not normalize terms, entries, or links. The consumer contract is
`docs/FLAT_SQLITE_CONTRACT.md`. Synthetic tests:
`tests/test_prepare_lexical_knowledge_sqlite.py`. Pytest imports the script through
`pythonpath = ["scripts"]` in `pyproject.toml`. Pyright `extraPaths` includes `src` and `scripts`.

`src/app/lexical_extraction/contracts.py` is the L01 record boundary: reviewed-HTML v1 input
identity, page/block/span evidence, catalogue candidates, independent unit and value records,
run provenance, extraction outcomes, and publication claims. Importing the package does no I/O.
It does not read HTML, query the snapshot, normalize, match, parse values, or publish artifacts.
Focused tests: `tests/lexical_extraction/test_contracts.py`. Synthetic fixture:
`examples/lexical_extraction/result-example.json`.

`src/app/lexical_extraction/configuration.py` is the L02 execution-configuration boundary:
strict SafeLoader YAML with duplicate-key/merge/anchor/unsafe-tag rejection, fixed preset
resolution to the canonical component union, finite resource defaults/bounds, typed per-run
selection overrides, and effective-configuration SHA-256. Paths resolve against the config
file directory and are not created or required to exist. Focused tests:
`tests/lexical_extraction/test_configuration.py`. Synthetic example:
`examples/lexical_extraction/execution-config.example.yaml`.

`src/app/lexical_extraction/html_reader.py` is the L03 reviewed HTML v1 reader: chunked byte
streaming with incremental UTF-8 decode, SHA-256 of exact bytes parsed, exact root version
`"1"`, duplicate-attribute rejection, fail-closed missing `data-node-id` / out-of-page source
nodes / nested source markup, and page emission without retaining the whole file or all pages.
Final `ReviewedHtmlV1Input` exists only when `completed` is True. `data-source-id` is
space-split; IDs containing spaces are not round-trippable. Focused tests:
`tests/lexical_extraction/test_html_reader.py`. Matching is not implemented.

`src/app/lexical_extraction/knowledge_snapshot.py` is the L04 read-only flat snapshot
boundary. It validates the four snapshot companions once, opens `knowledge.sqlite`
with `mode=ro` and `PRAGMA query_only=ON`, and returns an L01
`KnowledgeSnapshotIdentity`. Callers page one allowlisted table by SQLite `rowid`
or look up one source `row_id`. Cells stay stored text. The reader does not map
search fields, normalize, match, or publish. Focused tests:
`tests/lexical_extraction/test_knowledge_snapshot.py`.

`src/app/lexical_extraction/field_mapping.py` is the L05 fixed V1 source-field mapper.
It interprets allowlisted L04 `SourceRow` cells into compact `EligibleSearchTerm`
records for selected components, including UNII whole-code / unit atomic-token hints
and UO `Index this row` authorization. It does not normalize, match, parse values, or
emit L01 candidates. Focused tests: `tests/lexical_extraction/test_field_mapping.py`.

`src/app/lexical_extraction/comparison.py` is the L06 fixed V1 comparison helper.
It builds temporary per-term/per-block `ComparisonSurface` text with original-offset
provenance, projects comparison ranges to L01 `CharSpan` values, and applies
`default` / `whole_code` / `atomic_unit` boundaries. It does not match documents,
run Aho–Corasick, or aggregate occurrences. Focused tests:
`tests/lexical_extraction/test_comparison.py`.

`src/app/lexical_extraction/dictionary_matcher.py` is the L07/L11 bounded matching
core. It shards L05 eligible terms under L02 resource limits, indexes comparison
keys with `pyahocorasick`, optionally builds a deletion-signature fuzzy index when
`fuzzy_enabled=True`, replays L03 blocks via `StaticBlockSource` or
`ReviewedHtmlBlockReplay` (pinned HTML SHA-256), and streams `RawDiscovery`
records with original spans and all colliding source references. Occurrence
aggregation and publication are out of scope. Focused tests:
`tests/lexical_extraction/test_dictionary_matcher.py` and
`tests/lexical_extraction/test_fuzzy_matching.py`.

`src/app/lexical_extraction/fuzzy_matching.py` holds the fixed V1 ordinary
Levenshtein distance-1 helpers and deletion-signature candidate index used only
when fuzzy is explicitly enabled.

`src/app/lexical_extraction/dictionary_aggregation.py` is the L08 dictionary aggregator.
It rejects unit discoveries (`UNEXPECTED_UNIT_DISCOVERY`) and revalidates fuzzy
claims before emitting L01 `FuzzyEvidence`. Focused tests:
`tests/lexical_extraction/test_dictionary_aggregation.py`.

`src/app/lexical_extraction/unit_value_rules.py`, `unit_aggregation.py`,
`value_expressions.py`, and `parameter_unit_value.py` are the L10 independent
parameter-name / unit / value capability. Parameter names reuse L05→L07→L08 and
may pass `fuzzy_enabled` through that seam. Units use L07 plus L10 unit aggregation
(not L08) and remain non-fuzzy. Values use the shared V1 parser.
Fixed quantity-unit vocabulary and narrow categorical/cue rules live in
`unit_value_rules.py`. Focused tests:
`tests/lexical_extraction/test_parameter_unit_value.py`.

`src/app/lexical_extraction/runner.py` and `monitoring.py` are the L12 callable
run boundary. The runner validates reviewed HTML fully (counts only; no retained
all-page list), prefights the flat snapshot once, executes exactly L02's resolved
component union (dictionary components independently; co-selected L10 components
in one composition), streams provisional component-scoped page/block evidence
through a caller-owned `EvidenceSink` (`write_page(component, page)`), and returns
`LexicalRunResult` with identities, `RunProvenance` when complete, outcomes,
compact monitoring, and optional `run_error` for sink-finalization failure while
preserving committed component outcomes. Eligible term/row counts use
`EligibleTermCounter` (previous-key integer; no row-id set). Final artifact
publication and CLI are L13. Focused tests:
`tests/lexical_extraction/test_runner.py`.

`src/app/lexical_extraction/publication.py` and `__main__.py` are the L13
filesystem publisher and thin CLI. The sink stages page/block evidence under a
new `{output.directory}/{run_id}/` tree with finite in-memory counters and
per-page disk meta, commits one versioned JSON artifact per completed component
via checked write-all + hash-from-file + atomic replace, seals on `complete_run`,
and writes the final `manifest.json` only from `finalize_publication` after the
runner returns. Concurrent provisional components are allowed for L10 shared
composition. Streaming readers and exact `locate_hit` support integrity checks
and page/node/span navigation. Output roots inside the snapshot are refused
before directory creation. Focused tests:
`tests/lexical_extraction/test_publication.py`.

Graph views and a rules/Audit layer have no implementation modules yet. Do not invent those
directories.

## Conversion and review boundaries

```text
accepted versioned PDF
  → Textract/Textractor conversion
  → immutable original textract.json + document.json + document.html
  → optional review (separate status)
  → immutable ReviewRevision envelope + reviewed HTML/JSON
```

`Job.phase` remains OCR/conversion state (`SUCCEEDED` or `PARTIAL_SUCCESS`); it never becomes
approved. Existing artifact downloads remain original and unreviewed.

`ReviewRevision.document` is the sole canonical reviewed `Document`. TipTap JSON is an editing
projection only. The editor schema retains table `sourcePath`/`rows`/`columns`, cell source IDs,
and fixed heading levels so structural validation matches the projection. Stable node IDs derive
from the pinned baseline artifact, physical page, and structural path. Browser saves contain
sparse `{node_id, text}` values and explicit finding decisions; source metadata and structure are
server-owned. A queued suggested replacement is omitted from `changes` when it is identical to the
decision replacement.

Text edits on a page invalidate that page approval and document approval. Finding decisions bind
to the current evidence-region hash and become unresolved again if the region changes.

## Persistence and conflict handling

- Job rows: `job#{job_id}`; OCR capacity rows: `slot#{n}`.
- Review head: `review#{job_id}` in the same DynamoDB table. It contains no document body.
- Revisions: `documents/results/{job_id}/review/revisions/{uuid}/review.json`.
- Approved exports are under that same revision-specific namespace.
- S3 object writes happen before conditional head publish. First publish uses
  `attribute_not_exists(pk)`; later publishes require expected revision and generation.
- A CAS loser remains unreachable and expires under the existing lifecycle. Callers receive
  `409 REVIEW_CONFLICT` unless A1 Save reconciliation finds a matching committed operation
  and replays it without advancing the head. Parent Artifact pointers resolve retained
  historical approved exports. New committed envelopes use schema `1.1.0`; unchanged
  legacy `1.0.0` revisions remain readable.
- Actor and times come from Cognito `sub` and the server clock.
- Optional Save `operation_id` is reconciled against the published parent chain before a new
  write. Matching fingerprint replays without advancing the head. `SAVE_OPERATION_MISMATCH` is
  409. Receipts remain service-level; HTTP lookup returns `{context, reconciliation}` and
  does not wrap PUT `ReviewState`.
- Server `context_id` is a separate SHA-256 of storage namespace, job, actor, baseline,
  accepted source, and raw Artifact. It does not alter the A1 request fingerprint.
- The local harness mirrors the same service contracts with atomic files under
  `.local-review-data/`, including auxiliary `review-context.json` (schema 1 + UUID v4
  storage ID). A restored copy retains that identity; independently writable clones must be
  initialized separately. That is not proof of DynamoDB or S3 behaviour.

## HTTP surface

- Existing conversion shell: `/documents`
- Review assets: `/documents/review-assets/*`
- Production review:
  - `GET /api/v1/documents/jobs/{job_id}/source`
  - `GET /api/v1/documents/jobs/{job_id}/review/context` (authenticated `ReviewContext`; no-store)
  - `GET /api/v1/documents/jobs/{job_id}/review/operations/{operation_id}` (requires
    `X-Review-Context`; `{context, reconciliation}`; no-store; no revision writes)
  - `GET|PUT /api/v1/documents/jobs/{job_id}/review`
    (`PUT` still returns top-level `ReviewState`; optional `operation_id` on the body;
    optional `X-Review-Context`; mismatch is `409 REVIEW_CONTEXT_CHANGED` before mutation.
    Legacy omitted/null operation IDs and absent context header remain valid.)
  - `POST /api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve`
  - `POST /api/v1/documents/jobs/{job_id}/review/approve`
  - `GET /api/v1/documents/jobs/{job_id}/review/revisions/{revision_id}/exports/{format}`
- Test harness: `http://127.0.0.1:8765/documents/local-review` (user completed review);
  isolated A2: `http://127.0.0.1:8766/documents/local-review`

Every production data operation reuses bearer verification and ownership-hiding job lookup before
artifact or review access.

## Local harness boundary

The harness is imported only from `tests/`, binds to `127.0.0.1`, uses the synthetic
`local-test-reviewer` and synthetic job `local-fexofenadine`, and persists generated state under
`.local-review-data/` (default `.local-review-data/fexofenadine/`). It mounts the actual built Vue
workspace and real review API/service. Only identity and external storage are replaced. It is
excluded from production Docker context/composition and makes no AWS clients or calls. Supplied
originals are read-only.

The harness proves local mapping, persistence, conflicts, approvals, and exports. It does not prove
Cognito authentication, DynamoDB conditional behavior, or S3 versioning; SDK Stubber tests cover
request contracts, and live cloud acceptance remains separate.

## Current evidence and pending acceptance

See `.ai/03_common_handoff.md` for command results, the completed local visual/functional
acceptance, A1 Save-operation evidence, A2 implementation and preceding-session manual
acceptance, B1 user-accepted committed-history projection, B2a accepted atomic
`history.jsonl` primitive, B2b local-harness published-history rebuild, 2026-09-18 pending-Save
safety-correction and F1–F3 follow-up evidence, and remaining unverified AWS/production work. The accepted
Textractor conversion predates the HITL editor-boundary corrections. Local harness
acceptance is complete for the behaviours listed there; A1 remains the agreed working
baseline without a recorded human sign-off. A2 browser Save recovery was accepted in the
preceding session. B1 was accepted after an isolated local-review regression. B2b local
`history.jsonl` rebuild is test-verified and not yet manually accepted. The Findings
scope default **This page** is test-verified and not yet manually accepted. B2c production
history routing and Cognito/DynamoDB/S3/deployment acceptance are not complete.
