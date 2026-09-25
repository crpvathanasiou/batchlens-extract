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
│   └── contracts.py                 L01 evidence, candidate, value, and outcome records
└── main.py                          feature lifespan, routers, CSP/isolation middleware

frontend/
├── src/                             Vue workspace, API/state, TipTap mapping/extensions, pendingSave
├── tests/                           editor/mapping/state/API/round-trip/build-output/pending-save tests
├── package.json / package-lock.json pinned Node dependencies
└── vite.config.ts                   library output under document_review/static

tests/lexical_extraction/
└── test_contracts.py                L01 public record and coherence tests

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
| `src/app/lexical_extraction/contracts.py` | L01 lexical evidence, candidate, unit/value, provenance, extraction-outcome, and publication-claim records | Reviewed HTML v1 identity and flat-SQLite field names → bounded records; no reader or publisher | Changing lexical record fields, span checks, outcome coherence, or publication claims |
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
`examples/lexical_extraction/result-example.json`. The lexical engine is not implemented.

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
