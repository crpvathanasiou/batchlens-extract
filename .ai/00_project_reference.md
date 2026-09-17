# 00 — BatchLens Extract Project Reference

## Document ownership

This document owns product purpose, approved scope, boundaries, and navigation to design topics.

| Document | Owns |
|----------|------|
| [01_implementation_roadmap.md](01_implementation_roadmap.md) | Milestone sequence and acceptance criteria |
| [02_code_quality_standards.md](02_code_quality_standards.md) | Stable engineering standards |
| [03_common_handoff.md](03_common_handoff.md) | Current execution state and next action |
| [04_code_map.md](04_code_map.md) | Existing code, contracts, and tests |
| [05_pipeline_contracts.md](05_pipeline_contracts.md) | Pipeline responsibilities, data semantics, lifecycle invariants |
| [06_security_and_data_handling.md](06_security_and_data_handling.md) | Product data protection and evidence for security claims |
| [07_extraction_evaluation.md](07_extraction_evaluation.md) | Extraction-quality and reviewer-effort evaluation |
| [08_check_selection_strategy.md](08_check_selection_strategy.md) | Check selection/prioritization; Extract vs Audit ownership |

Status vocabulary:

```text
CURRENT / IMPLEMENTED
APPROVED TARGET / INVARIANT
PROPOSED EXAMPLE
OPEN DECISION
DEFERRED / OPTIONAL
```

Do not treat planned work as implemented.

---

## 1. Product identity

**Product:** BatchLens Extract
**Repository:** `batchlens-extract`

BatchLens Extract digitizes pharmaceutical manufacturing PDFs into structured, inspectable recipe data, reducing manual transcription and reconciliation work.

It has two core product legs:

| Leg | Status | Intent |
|-----|--------|--------|
| Evidence-preserving document preparation and review | CURRENT / IMPLEMENTED in this repository; not production-qualified | `source PDF → Textract raw result → Textractor/conversion → canonical document.json + HTML → human review/revisions/approvals → reviewed HTML/JSON exports`. Text-only review; structure, table identities, geometry, and source relationships stay protected. Document-review approval is not batch release, regulatory release, or a 21 CFR Part 11 electronic signature. |
| Pharmaceutical information extraction | APPROVED TARGET / not implemented | Extract pharmaceutical facts, recipe/process data, and other structured information from the reviewed document, preserving evidence and provenance links to the source and reviewed revision. |

Built incrementally by a solo AI engineer. User value, implementation effort, and operating cost guide design decisions.

A later rules capability may evaluate extracted facts against versioned FDA, EU, or customer rules. That layer is **not implemented**.

**BatchLens Audit** is a separate planned tool for regulatory and process-rule evaluation over compatible structured recipe/batch data, including input from other sources.

| Tool | Owns |
|------|------|
| **Extract** | Extraction, provenance, structural validation, document-consistency findings |
| **Audit** | Regulatory and process-rule evaluation |

Shared versioned contract and deployment separation: **OPEN** — see [05](05_pipeline_contracts.md) and product boundaries below.

---

## 2. Problem and value

Master Batch Records (MBRs) and executed batch records are PDF-heavy. Manual transcription is slow and hard to reconcile against source evidence.

Extract produces source-linked structured JSON that can be inspected, corrected, and visualized. It must not invent missing values or silently promote executed records into authoritative master recipes.

Discussed ~85% effort reduction and ~90% extraction accuracy are **hypotheses**, not measured results. Metrics and evaluation sets belong in [07](07_extraction_evaluation.md). Reported multi-month manual processes do not establish a validated customer baseline.

---

## 3. Current implementation

**Status:** CURRENT / IMPLEMENTED — foundation plus conversion and review slices in the working tree. Not production-qualified. Not AWS integration-verified.

- FastAPI application factory with injectable settings
- Validated configuration with defaults for `APP_ENV`, `APP_VERSION`, `LOG_LEVEL`, plus optional OpenAI settings
- Application logging under the `app` namespace
- `/health`, `/ready`, `/version`
- Python 3.11, Poetry, Ruff, Pyright strict, pytest
- Multistage Docker + Compose, including a Node 22.12 review-frontend build stage
- Optional async OpenAI wrapper with fake-based tests (unwired to product flows)
- Optional document conversion (disabled by default): Textract, Textractor 1.10.0, durable DynamoDB/S3/SQS jobs, Cognito-owned upload/jobs shell, canonical `document.json` + unreviewed HTML
- Optional document review (same feature flag): Vue/TipTap/PDF.js workspace, review API, immutable revisions, page/document approval, reviewed HTML/JSON exports
- Development/test-only local review harness under `tests/document_review/`

`/ready` is foundation readiness only — not document-processing or AWS dependency proof.

Pharmaceutical extraction, recipe graph UI, rules/Audit evaluation, and AWS deployment verification are **not** implemented. Intended production composition uses Cognito, DynamoDB, S3, and SQS; that wiring exists in code and is **not** live-cloud verified. See [04](04_code_map.md) and [03](03_common_handoff.md).

---

## 4. Approved product scope

**Status:** APPROVED TARGET

### 4.1 Inputs and extraction

Support MBRs and executed batch records, including scanned PDFs.

Extract where available: recipe/document identity and revision; BOM materials and quantities; LOE equipment; unit operations and process steps; material/equipment relationships to steps; parameters, values, ranges, units; explicit CPP/IPC information.

**Prescribed** instructions/limits must remain distinguishable from **observed** execution values and deviations. Extraction from an executed record yields an evidence-based recipe representation; it does not establish the authoritative master recipe.

Missing or ambiguous information remains explicit. Do not invent values or relationships.

### 4.2 Document-local references

Identify BOM and LOE sections wherever present and use them for extraction and reconciliation. Preserve evidence found elsewhere, including unlisted materials or equipment. A missing reference section must not force users to transcribe into a custom Excel template.

Document consistency is not independent proof of regulatory compliance. Check ownership: [08](08_check_selection_strategy.md).

### 4.3 Outputs and review

Produce structured JSON with source references, uncertainties, missing information, and consistency findings.

Support automatic unreviewed delivery and optional human inspection/correction. Processing status, review status, and findings are separate. Missing evidence or uncertainty is not automatically a pass, a technical failure, or a mandatory human-review stop.

Detailed lifecycle semantics: [05](05_pipeline_contracts.md).

### 4.4 Views and graph

JSON, structured/tabular views, and an interactive recipe graph share the same versioned data model. Graph generation is deterministic from that model — not a separate LLM reconstruction. Evidence and review state stay synchronized across views.

Neo4j / GraphRAG: **DEFERRED** — not required for visualization.

### 4.5 Security and measurement

Security is required from the beginning. Product data handling and claim evidence: [06](06_security_and_data_handling.md). Evaluation strategy: [07](07_extraction_evaluation.md). Check prioritization: [08](08_check_selection_strategy.md).

Do not claim certification, guaranteed confidentiality, or AWS-only data residency before verified.

---

## 5. Non-goals, deferred, and optional work

### Outside agreed scope

- Batch release approval
- Comprehensive FDA/GMP certification claims

### Deferred

- LLM wrapper hardening/redesign until extraction integration is designed
- Neo4j and GraphRAG
- BatchLens Audit implementation and the future rules layer
- Persistent audit/provenance ledger (direction recorded in [03](03_common_handoff.md) and [05](05_pipeline_contracts.md); not implemented)
- Broader enterprise integrations

### Optional (pending measured quality improvement)

- Controlled materials/equipment/steps catalogs
- Retrieval/RAG over those catalogs

Catalog data must remain distinguishable from document evidence and respect customer access boundaries ([06](06_security_and_data_handling.md)).

---

## 6. Open decisions (by owner)

Do not duplicate full decision lists elsewhere; follow the owning document.

| Owner | Open topics |
|-------|-------------|
| [05](05_pipeline_contracts.md) | Stage I/O, identifiers, serialization, evidence location format, lifecycle transitions, versioning, retry/resume, Extract–Audit boundary, first demonstrable slice |
| [06](06_security_and_data_handling.md) | Retention durations, regions, tenancy, identity provider, encryption/keys, egress, provider processing/training/destinations |
| [07](07_extraction_evaluation.md) | Sample counts, matching/tolerance rules, numerical thresholds, evaluation-set versions |
| [08](08_check_selection_strategy.md) | Initial check inventory, severity/blocking policy, scoring (if any) |
| Product / deployment (this file + design) | OCR/parser and extraction model/provider; queue/persistence/auth details beyond the existing intended Cognito/DynamoDB/S3/SQS composition; live AWS topology verification |

---

## 7. Approved deployment direction

**Status:** APPROVED TARGET — not implemented

FastAPI, Docker, ECR, ECS/Fargate on AWS.

Detailed topology follows processing requirements. Documentation-only and local quality work need no cloud deployment; AWS remains the deployment target when deploying.

---

## 8. Technology baseline (current)

| Area | Current state |
|------|---------------|
| Language | Python 3.11.x (`>=3.11,<3.12`); Node.js 22.12+ for the review frontend build |
| API | FastAPI 0.116.2 / Starlette 0.48.0 (B2.1 working tree) |
| Packaging | Poetry; npm lockfile for `frontend/` |
| Validation | Pydantic v2 / Pydantic Settings |
| Quality | Ruff, Pyright strict, pytest; frontend vue-tsc + vitest |
| Containers | Multistage Dockerfile (Node review builder + Python), Compose |
| Conversion | Amazon Textractor 1.10.0; boto3 Textract/S3/DynamoDB/SQS (feature-flagged) |
| Review UI | Vue 3, TipTap 3, PDF.js (feature-flagged) |
| Optional LLM asset | Async OpenAI wrapper (unwired) |

---

## 9. Next design step

Operational current state: [03_common_handoff.md](03_common_handoff.md).

**Immediate next (from 03):** intended-use / regulatory-boundary and audit/provenance design before any audit-log implementation. Do not implement audit logging, extraction, rules, or deployment in that step.

**Later:** pharmaceutical-extraction **M-Design** develops remaining pipeline/contracts and the extraction slice primarily in [05](05_pipeline_contracts.md), with security, evaluation, and check-selection implications recorded in [06](06_security_and_data_handling.md)–[08](08_check_selection_strategy.md).

Conversion and document-review contracts already exist in code. Extraction schemas, provider choices, and detailed AWS topology may stay open until their requirements are understood.

Do not implement extraction, the rules layer, or the audit ledger in documentation-only work.
