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
│   └── document_reviews.py          source/review/page approval/final approval/export routes
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
│   ├── contracts.py                 review envelope/head/API/catalogue/approval contracts
│   ├── mapping.py                   stable nodes, sparse text changes, hashes/findings
│   ├── rendering.py                 deterministic escaped reviewed HTML
│   ├── storage.py                   small Dynamo CAS head + UUID versioned S3 objects
│   ├── service.py                   ownership/save/decision/approval/export use cases
│   ├── composition.py               bounded production AWS adapters
│   ├── static/                      reproducible ignored Vite output
│   └── README.md                    review contract and consumer boundary
└── main.py                          feature lifespan, routers, CSP/isolation middleware

frontend/
├── src/                             Vue workspace, API/state, TipTap mapping/extensions
├── tests/                           editor/mapping/state/API/round-trip/build-output tests
├── package.json / package-lock.json pinned Node dependencies
└── vite.config.ts                   library output under document_review/static

tests/document_review/
├── test_backend_review.py           canonical lifecycle/mapping/API/approval
├── test_backend_storage.py          Dynamo/S3 SDK request shapes and pinned source
├── local_store.py                   test-only atomic file storage
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
| `src/app/api/document_reviews.py` | Review HTTP surface | Same `owner` dependency → `ReviewService` | Changing review routes or error codes |
| `src/app/document_review/contracts.py` | Review envelope/head/API models | Conversion `Document` → revisions/exports | Changing review schema, decisions, or approval |
| `src/app/document_review/mapping.py` | Stable node IDs, text-only apply, findings | Baseline `document.json` → catalogue/changes | Changing IDs, sparse changes, or finding hashes |
| `src/app/document_review/service.py` | Save/decision/approval/export use cases | Mapping + storage → immutable revisions | Changing revision/CAS/approval invalidation |
| `src/app/document_review/storage.py` | Dynamo head + versioned S3 objects | Service persist → reachable head | Changing CAS conditions or object keys |
| `src/app/document_review/rendering.py` | Deterministic reviewed HTML | `ReviewRevision.document` → export HTML | Changing approved HTML heading/table markup |
| `src/app/document_review/composition.py` | Production Dynamo/S3 wiring | Document settings → `ReviewService` | Changing production adapters; not used by harness |
| `frontend/src/mapping.ts` | Page projection, sparse text, skeleton | Canonical page → TipTap JSON | Changing heading/table projection or IDs |
| `frontend/src/extensions.ts` | Protected TipTap schema and load | Projection JSON → editor transactions | Changing structure lock, table attrs, page load |
| `frontend/src/state.ts` | Review client state and save payload | Editor drafts → `PUT /review` | Changing decisions, replacements, or dirty/save |
| `frontend/src/components/` | Workspace, PDF pane, editor, findings | State + API → browser UI | Changing navigation, findings, or status copy |
| `frontend/vite.config.ts` | Library build into Python static dir | `frontend/src` → `document_review/static` | Changing bundle names, `process.env.NODE_ENV`, worker |
| `tests/document_review/local_harness.py` | Localhost acceptance server | Real review routes + Vue bundle + file store | Changing harness bind, identity, or startup |
| `tests/document_review/local_store.py` | Synthetic identity + atomic local files | Supplied originals → `.local-review-data/` | Changing manifest, immutability, or overlap guards |
| `tests/document_review/` | Backend/harness tests | Review contracts and local adapters | Changing lifecycle, CAS request shapes, exports |
| `frontend/tests/` | jsdom/component/build tests | Frontend mapping/state/UI | Changing editor invariants or bundle output |
| `Dockerfile` | Node 22.12 review build then Python image | `frontend/` + `src/` → runtime static assets | Changing image layout or frontend copy path |
| `src/app/main.py` | Feature flag, routers, CSP middleware | Settings → conversion/review composition | Changing enablement, CSP, or router install |

Pharmaceutical extraction, graph views, and a rules/Audit layer have no implementation modules
yet. Do not invent those directories.

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
- A loser receives `409 REVIEW_CONFLICT`; its unique unreachable candidate expires under the
  existing lifecycle. Parent Artifact pointers resolve retained historical approved exports.
- Actor and times come from Cognito `sub` and the server clock.
- The local harness mirrors the same service contracts with atomic files under
  `.local-review-data/`; that is not proof of DynamoDB or S3 behaviour.

## HTTP surface

- Existing conversion shell: `/documents`
- Review assets: `/documents/review-assets/*`
- Production review:
  - `GET /api/v1/documents/jobs/{job_id}/source`
  - `GET|PUT /api/v1/documents/jobs/{job_id}/review`
  - `POST /api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve`
  - `POST /api/v1/documents/jobs/{job_id}/review/approve`
  - `GET /api/v1/documents/jobs/{job_id}/review/revisions/{revision_id}/exports/{format}`
- Test harness: `http://127.0.0.1:8765/documents/local-review`

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
acceptance, and remaining unverified AWS/production work. The accepted Textractor conversion
predates the HITL editor-boundary corrections. Local harness acceptance is complete for the
behaviours listed there; Cognito/DynamoDB/S3/deployment acceptance is not.
