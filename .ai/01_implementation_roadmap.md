# 01 — Implementation Roadmap

## 1. Purpose

Owns milestone sequence, dependencies, and milestone acceptance criteria for BatchLens Extract.

| Document | Owns |
|----------|------|
| [00_project_reference.md](00_project_reference.md) | Product purpose and boundaries |
| [02_code_quality_standards.md](02_code_quality_standards.md) | Engineering standards |
| [03_common_handoff.md](03_common_handoff.md) | Current execution state |
| [04_code_map.md](04_code_map.md) | Implemented modules |
| [05](05_pipeline_contracts.md)–[08](08_check_selection_strategy.md) | Design-topic detail |

Do not invent a full implementation schedule, deadline, or milestone estimates.

---

## 2. Current repository baseline

- FastAPI factory, injectable settings, logging, `/health` `/ready` `/version`
- Python 3.11 / Poetry / Ruff / Pyright strict / pytest
- Multistage Docker + Compose, including Node 22.12 review-frontend build
- Optional unwired OpenAI wrapper with fake-based tests
- Optional document conversion and document-review slices in the working tree (feature-flagged; local harness accepted; not AWS integration-verified)

Scripts: `lint`, `format-check`, `format`, `typecheck`, `test`, `quality`, `dev`, `docker-up`, `docker-down` under `scripts/`.

Remaining gaps: pharmaceutical extraction, recipe graph UI, rules/Audit, persistent audit ledger, AWS deploy verification.

Operational detail: [03_common_handoff.md](03_common_handoff.md). Code locations: [04_code_map.md](04_code_map.md).

---

## 3. Milestone status

| Milestone | Outcome | Priority | Status |
|-----------|---------|----------|--------|
| M0 — Application foundation | Runnable FastAPI foundation + quality gates + Docker | MUST | DONE |
| B2.1 — FastAPI/Starlette security update | Starlette ≥ 0.47.2 via FastAPI + lock | MUST | DONE (working tree; see [03](03_common_handoff.md)) |
| D — Five-file documentation init | `.ai/` 00–04 reflect BatchLens Extract | MUST | DONE |
| D2 — Nine-document documentation set | Align 00–04; create 05–08 design docs | MUST | DONE (docs implemented/checked; awaiting user review / Git commit) |
| Conversion + HITL review slices | Textract/Textractor conversion, review workspace, local harness | MUST | DONE in working tree for local acceptance; not cloud-verified (see [03](03_common_handoff.md)) |
| M-Design — Pipeline & contracts design | Remaining extraction-pipeline semantics and contracts in 05 (+ 06–08 implications) | MUST | PLANNED |
| LLM wrapper hardening / redesign | Harden/redesign for extraction integration | — | DEFERRED |

```text
MUST / SHOULD / COULD
PLANNED | READY | IN_PROGRESS | BLOCKED | DONE | DEFERRED
```

`DONE` for documentation milestones means content exists and documentation checks passed — not user acceptance and not a Git commit unless separately recorded.

---

## 4. Milestone details

### M0 — Application foundation baseline

**Status:** DONE

User-supplied evidence: Poetry install; Ruff lint/format; Pyright zero errors; 36 tests; Docker build; container smoke (`/health` ok; `/ready` ready/local/0.1.0; `/version` 0.1.0).

Committed: `f5b3eba` — `chore: initialize BatchLens Extract baseline`

---

### B2.1 — FastAPI / Starlette dependency security update

**Status:** DONE (working tree)

Scope: `pyproject.toml`, `poetry.lock` only.

Result: FastAPI `^0.116.1` → resolved `0.116.2`; Starlette `0.46.2` → `0.48.0`.

Report evidence: quality + 36 tests passed; Docker build passed. No commit created as of D2. No post-update runtime smoke claimed without evidence.

---

### D — Five-file documentation initialization

**Status:** DONE

Replaced obsolete starter/template content in `.ai/` 00–04 with BatchLens Extract context. Docs-only; no app/dependency changes in that task.

---

### D2 — Nine-document documentation set

**Status:** DONE (documentation implemented and checked; awaiting user review)

**Objective:** Evolve the five-document set into nine coherent documents without restarting the project or recreating generic starter docs.

**Scope:** Only `.ai/00`–`.ai/08`. Preserve prior B2.1 and D working-tree changes.

**Definition of Done:**

1. All nine files exist with substantive project-specific content
2. Ownership and relative links are consistent
3. Automatic unreviewed delivery, graph-without-Neo4j, and Extract/Audit boundaries are consistent
4. Open decisions remain explicit; no fake results or finalized unapproved schemas/providers
5. Documentation checks pass (`git diff --check -- .ai/`; new files inspected); no app tests/Docker required
6. Pre-existing non-`.ai/` modifications preserved

Evidence: see [03_common_handoff.md](03_common_handoff.md).

---

### Conversion + HITL review slices

**Status:** DONE in working tree for local acceptance; not cloud-verified
**Priority:** MUST
**Dependencies:** M0 foundation; conversion contracts in code

**Objective:** Evidence-preserving PDF conversion and optional human document review.

Implemented in the working tree: Textract/Textractor conversion, durable jobs, Vue/TipTap/PDF.js review workspace, review API, local harness. Local visual/functional acceptance is recorded in [03](03_common_handoff.md). This is not AWS integration verification, production qualification, or Part 11 evidence.

Pharmaceutical extraction and the rules/Audit layer remain out of this slice.

---

### M-Design — Document-processing pipeline and data contracts

**Status:** PLANNED
**Priority:** MUST
**Dependencies:** D2 reviewed; foundation available

**Objective:** Design (not implement) the pipeline and data contracts.

**Primary output location:** [05_pipeline_contracts.md](05_pipeline_contracts.md)

Also update implications in:

- [06_security_and_data_handling.md](06_security_and_data_handling.md)
- [07_extraction_evaluation.md](07_extraction_evaluation.md)
- [08_check_selection_strategy.md](08_check_selection_strategy.md)

**Must define / review:**

- Stage responsibilities and inputs/outputs
- Document, recipe, entity, relationship, and evidence structures (schemas are a purpose of this milestone; they remain open until designed and reviewed)
- Prescribed versus observed values
- Processing, partial-failure, and review semantics
- Synchronization of JSON, structured UI, and graph view
- First demonstrable end-to-end slice and evaluation criteria

**May remain open until requirements are clearer:** extraction model/provider, detailed AWS topology verification, remaining persistence/auth specifics beyond the existing intended composition.

**Non-goals:** Implementing pharmaceutical extraction in this design milestone; hardening the LLM wrapper; introducing Neo4j/GraphRAG; inventing acceptance thresholds without evaluation design; implementing the audit ledger.

**Definition of Done (design):**

1. Design consistent with [00](00_project_reference.md) and recorded in 05 (with 06–08 links)
2. Open decisions remain labeled where undecided
3. First vertical slice and evaluation criteria named
4. No speculative infrastructure mandated without processing justification

---

### Deferred: LLM wrapper hardening / redesign

**Status:** DEFERRED

Do not harden or redesign `src/app/llm/` until extraction integration is designed. Documented desired errors/retries/tracing elsewhere do not prove the wrapper implements every future standard and must not trigger hardening during D2.

---

## 5. Critical path

```text
M0 (DONE)
→ B2.1 (DONE in working tree)
→ D five-file docs (DONE)
→ D2 nine-document set (DONE — awaiting review)
→ Conversion + HITL review slices (DONE in working tree; local acceptance complete; not cloud-verified)
→ Intended-use / regulatory-boundary and audit/provenance design (next; no audit-log implementation)
→ M-Design remaining extraction pipeline/contracts
→ Extraction implementation slice (after design; not yet defined)
```

Safe deferrals: Neo4j, GraphRAG, catalogs/RAG, Audit product / rules layer, audit-ledger implementation, wrapper hardening, enterprise integrations.

---

## 6. Immediate next action (roadmap pointer)

Operational detail: [03_common_handoff.md](03_common_handoff.md).

**Current:** Conversion and HITL review slices are implemented in the working tree. Local harness visual/functional acceptance is complete for the behaviours listed in 03. AWS/production integration remains unverified.

**Next:** intended-use / regulatory-boundary and audit/provenance design before any audit-log implementation. Extraction M-Design remains later.
