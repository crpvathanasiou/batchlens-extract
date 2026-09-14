# 01 — Implementation Roadmap Template

## 1. Purpose

This document defines the **implementation roadmap** for the current engineering assignment built from this starter repository.

It converts:

* the assignment / requirements;
* the canonical project reference;
* the current repository state;
* approved architecture and constraints;

into:

* implementation milestones;
* sequencing;
* dependencies;
* priorities;
* implementation boundaries;
* validation;
* milestone-level Definition of Done;
* evidence of completion.

The roadmap is intended to control implementation order and prevent:

* premature complexity;
* speculative infrastructure;
* unrelated refactoring;
* undocumented architectural changes;
* implementation before important requirements and boundaries are understood;
* loss of implementation context across sessions.

This document does **not** replace:

* `00_project_reference.md` — project-wide architectural source of truth;
* `02_code_quality_standards.md` — stable engineering / code-quality rules;
* `03_common_handoff.md` — current execution state and immediate operational handoff;
* `04_code_map.md` — important files/modules, responsibilities, contracts, and status.

The canonical project reference remains:

```text
.ai/00_project_reference.md
```

Do not invent architecture in this roadmap. Populate milestones only after the assignment and canonical reference are understood.

---

## 2. Document Ownership Boundaries

| Document | Owns |
|----------|------|
| `00_project_reference.md` | Architecture, project scope, requirements, major boundaries |
| `01_implementation_roadmap.md` | Sequencing, priorities, milestones, dependencies, milestone DoD, evidence |
| `02_code_quality_standards.md` | Stable engineering and code-quality rules |
| `03_common_handoff.md` | Current execution state and immediate operational handoff |
| `04_code_map.md` | Code/file/module navigation and ownership |

The roadmap should reference these responsibilities rather than copy large amounts of their content.

---

## 3. Implementation Control Model

Use a lightweight control loop appropriate for timeboxed engineering assignments:

```text
Assignment / Requirements
→ Canonical Project Reference
→ Repository Baseline Inspection
→ Implementation Roadmap
→ Milestone Definition
→ Cursor / Developer Implementation
→ Validation Against Milestone DoD
→ Evidence
→ Code Map / Handoff Update (when relevant)
```

Establish before meaningful coding:

1. clear scope;
2. understood dependencies and affected boundaries;
3. important contracts clear before dependent implementation;
4. verification defined before considering a milestone complete;
5. repository evidence takes precedence over assumptions;
6. implementation must not silently widen scope.

Planning before implementation remains required for substantial or architecture-affecting work.

Do **not** require a formal approval ceremony before every small implementation step.

Do **not** add unnecessary STOP / review bureaucracy.

Separate Task Definition / Detailed Specification / Cursor Prompt files may be used when complexity justifies them or when they already belong to the chosen workflow. They are **not** mandatory for every milestone.

The roadmap itself owns **milestone-level Definition of Done**.

---

## 4. Roadmap Inputs and Delivery Context

Capture the minimum information needed before constructing the implementation sequence.

Unknown values must remain `UNKNOWN` rather than invented.

### Assignment / Problem Input

<!--
Record:
- task or assignment source;
- core expected outcome.
-->

**Source:**

**Core expected outcome:**

### Delivery Timebox

**Deadline:**

**Available implementation window:**

### Required Deliverables

<!-- Check only what is externally required: code, tests, documentation, demo, deployment, architecture explanation, other. -->

| Deliverable | Required? | Notes |
|-------------|-----------|-------|
| Code | | |
| Tests | | |
| Documentation | | |
| Demo | | |
| Deployment | | |
| Architecture explanation | | |
| Other | | |

### Mandatory Technologies / Constraints

<!-- Only assignment-mandated technologies and constraints. -->

### Provided Resources

<!-- Datasets, APIs, credentials/environment, existing code, starter assets. -->

### Explicit Non-Goals / Exclusions

### Hard Non-Functional Requirements

<!-- Only where actually applicable. -->

### Evaluation / Demo Expectations

---

## 5. Current Repository Baseline

Reusable **CURRENT-STATE** snapshot. Populate from actual repository inspection.

Do not invent concrete repository state in the blank template.

### Existing Repository Structure

```text
src/app/          FastAPI application package
src/app/api/      System endpoints
src/app/llm/      Reusable async LLM wrapper + OpenAI provider construction
tests/            Unit / API tests (including tests/llm/)
.ai/              Long-lived project docs
scripts/          Quality / Docker helpers
Dockerfile, docker-compose.yaml
```

### Existing Working Capabilities

- FastAPI application factory with `/health`, `/ready`, `/version`
- Validated Pydantic Settings (`APP_ENV`, `APP_VERSION`, `LOG_LEVEL`, optional OpenAI settings)
- Structured logging configuration
- Docker / Compose runtime assets
- Async OpenAI LLM wrapper (plain text + structured Pydantic output, guardrails, retries/timeouts)
- OpenAI provider helper (`create_async_openai_client`) separated from wrapper orchestration

### Reusable Starter Assets

Python, FastAPI, Docker, Pydantic Settings, pytest/Ruff/Pyright, and the OpenAI LLM client/wrapper.

`existing starter asset ≠ mandatory project capability` — the FastAPI app does **not** require OpenAI to start; LLM composition is opt-in when a key is configured.

### Existing Quality Tooling

Poetry, Ruff, Pyright, pytest, pytest-asyncio, helper scripts under `scripts/`.

### Existing Tests

- `tests/test_application.py`, `tests/test_settings.py`, `tests/test_system_endpoints.py`
- `tests/llm/test_openai_wrapper.py`, `tests/llm/test_openai_provider.py` (fake clients; no network)

### Current Deployment / Runtime Assets

Dockerfile, docker-compose.yaml, `.env.example`, PowerShell helper scripts.

### Known Gaps Relevant to the Assignment

No assignment-specific domain capabilities yet. LLM is a reusable asset, not a wired application feature.

### Baseline Validation Results

```text
poetry check                          PASS (Poetry deprecation warnings only)
poetry run ruff check .               PASS
poetry run ruff format --check .      PASS
poetry run pyright                    PASS
poetry run pytest                     PASS (36 tests)
```

**Reuse before rewrite.**

Do not replace a working starter capability unless:

* the assignment conflicts with it;
* it blocks the required design;
* it is technically unsuitable;
* or replacement provides concrete project value.

---

## 6. Technology Baseline and Project-Specific Additions

Distinguish three categories. Do not collapse them.

### A. Existing Starter Assets

Technologies / capabilities already present in the repository.

| Asset | Present? | Used by this assignment? | Notes |
|-------|----------|--------------------------|-------|
| Python 3.11 / Poetry | YES | YES | Package root `src/app` |
| FastAPI / Uvicorn | YES | YES | App factory + system routes |
| Pydantic Settings | YES | YES | Optional OpenAI settings included |
| Docker / Compose | YES | YES | Runtime assets |
| Ruff / Pyright / pytest | YES | YES | Quality gates |
| OpenAI LLM wrapper | YES | reusable asset | Async-only; injected client; not required to boot the API |
| openai SDK | YES | reusable asset | Used only by provider construction + wrapper OpenAI error/types |

### B. Assignment-Mandated Technologies

Technologies explicitly required by the task.

| Technology / Constraint | Source | Notes |
|-------------------------|--------|-------|
| UNKNOWN / NOT_SET | — | No external assignment populated yet |

### C. Project-Dependent Additions

Technologies introduced **only** when justified by actual requirements.

| Addition | Justification | Status |
|----------|---------------|--------|
| openai | Required by the async LLM wrapper / provider | DONE |
| pytest-asyncio | Required for async LLM unit tests | DONE |

**Principle:** the existence of a possible future use case is not sufficient justification for adding a dependency or infrastructure component.

---

## 7. Implementation Principles

### 7.1 Deliver Vertical Value

```text
Small Complete Capability
→ Verified Behaviour
→ Stable Contract
→ Next Capability
```

Prefer a working vertical slice early over broad unfinished surface area.

### 7.2 Contract First

Important external and cross-boundary contracts should be established before dependent implementation.

### 7.3 No Premature Platform Engineering

Do not build generic frameworks or abstractions unrelated to the task.

### 7.4 Explicit Dependency Direction

Keep dependency direction clear. Place infrastructure behind application / domain contracts where appropriate.

### 7.5 Safe Failure / Verification Discipline

Failures must be explicit and verifiable at the milestone level.

Detailed error-handling, logging, and coding standards belong in:

* `02_code_quality_standards.md`
* `00_project_reference.md`

Do not duplicate those detailed rules here.

### 7.6 Reuse Existing Assets Before Building New Ones

Before introducing new implementation:

1. inspect the existing repository;
2. identify reusable components / contracts / wrappers;
3. determine whether they satisfy the current requirement;
4. extend minimally where justified;
5. replace only with concrete technical reason.

Especially protect strong existing assets from unnecessary rewrites when present, for example:

* FastAPI foundation;
* Docker / runtime setup;
* shared error / config / logging patterns;
* existing OpenAI LLM wrapper;
* testing and quality tooling.

Do **not** force every milestone to use every asset.

---

## 8. Project-Wide Implementation Documents

### 8.1 `02_code_quality_standards.md`

Stable engineering / code-quality rules.

Reference them; do not recreate them inside the roadmap.

### 8.2 `03_common_handoff.md`

Current execution state, immediate next action, blockers, and evidence.

It must **not** become project history or duplicate this roadmap.

### 8.3 `04_code_map.md`

Important files / modules, responsibilities, contracts, and implementation status.

Update when implementation materially changes the codebase.

These documents should already exist as long-lived starter assets. Do not invent a “recreate before first milestone” ceremony unless the repository is actually missing them.

---

## 9. Roadmap Overview

Populate only after the real assignment is understood.

Do not use priorities to invent scope.

| Milestone | Outcome | Priority | Dependencies | Status | Evidence |
|-----------|---------|----------|--------------|--------|----------|
| M1 — Reusable async LLM wrapper | Working async OpenAI wrapper with provider construction separated; unit tests without network | MUST | Starter FastAPI foundation | DONE | `tests/llm/*`; quality gates PASS |

### Priority Interpretation

```text
MUST   = required for the assignment / final demonstrable solution
SHOULD = high-value improvement if the critical path is secure
COULD  = optional enhancement only after MUST work is complete
```

### Status Model

```text
PLANNED
READY
IN_PROGRESS
BLOCKED
DONE
DEFERRED
NOT_APPLICABLE   (optional, when relevant)
```

A milestone reaches `DONE` only when its embedded Definition of Done passes.

### Milestone M1 — Reusable async LLM wrapper

#### Objective

Provide a reusable async OpenAI LLM wrapper in the generic starter, with OpenAI client construction separated from wrapper orchestration.

#### Priority

`MUST`

#### Scope

- Async plain-text + structured Pydantic generation
- Timeouts / retries / guardrails / typed results / provider error translation
- Injected async client; `create_async_openai_client` owns `AsyncOpenAI`
- Minimal OpenAI settings; unit tests with fakes (no network)

#### Non-Goals

Multi-provider factories, sync LLM calls, wiring LLM into `create_app` by default.

#### Definition of Done

1. Wrapper async-only; no `AsyncOpenAI` construction inside wrapper.
2. Meaningful unit tests passing without network / real key.
3. `poetry check`, Ruff, Pyright, pytest pass.
4. App starts without `OPENAI_API_KEY`.
5. Code map / handoff updated; no commit / push.

#### Milestone Status

`DONE`

---

## 10. Critical Path and Sequencing

Identify:

* which milestone unlocks another;
* which milestones are sequential;
* which work can be parallelized;
* which capability is required for the first working vertical slice;
* which work can be deferred safely;
* which external dependency or unresolved decision can block progress.

For timeboxed assignments, optimize first for:

```text
Required Outcome
→ Working Vertical Slice
→ Verified Behaviour
→ Hardening / Extensions
```

Do **not** optimize for maximum architecture breadth.

**Critical path notes:** M1 (reusable LLM asset) complete. Further milestones depend on the concrete assignment.

**Parallelizable work:** N/A until assignment milestones are defined.

**Safe deferrals:** Real OpenAI smoke calls; wiring LLM into FastAPI routes.

**Known blockers / unresolved decisions:** NONE for the LLM capability boundary.

---

## 11. Timebox and Scope Discipline

For short assignments:

1. secure all `MUST` milestones first;
2. establish a working vertical slice early;
3. avoid optional infrastructure until justified;
4. prefer reuse of stable starter assets;
5. do not sacrifice correctness / testing of `MUST` behaviour for breadth;
6. move `SHOULD` / `COULD` work out of the critical path when time becomes constrained.

Do not invent time estimates inside the template.

The actual assignment defines the timebox.

---

## 12. Milestone Template

This is the core reusable unit of the roadmap.

Copy the block below for each real milestone. Do not invent milestones to fill the template.

---

### Milestone N — \<Name\>

#### Objective

<!-- What concrete outcome becomes true when the milestone is complete? -->

#### Why This Milestone / Why Now

<!-- What dependency or delivery need justifies its position? -->

#### Priority

`MUST` | `SHOULD` | `COULD`

#### Dependencies / Preconditions

<!-- Only real dependencies. -->

#### Scope

<!-- Concrete work included. -->

#### Non-Goals

<!-- Explicit exclusions. -->

#### Existing Assets to Reuse

<!-- Existing modules, wrappers, infrastructure, contracts, or patterns to reuse rather than rebuild. -->

#### Contracts / Boundaries

<!-- Important API / schema / interface / data boundaries that must be preserved or defined. -->

#### Expected Implementation Areas

<!-- Expected modules/files/components if known. Do not invent filenames before repository inspection. -->

#### Risks / Open Decisions

<!-- Only issues that can materially affect the milestone. -->

#### Validation

<!-- Commands, tests, scenarios, inspections, or other evidence required. -->

#### Definition of Done

Definition of Done lives **inside** the milestone.

Use measurable, milestone-specific gates.

Do **not** create generic boilerplate DoD unrelated to the milestone.

Do **not** force Docker / API / deployment checks when the milestone does not involve them.

Possible categories **when applicable**:

* required behaviour works;
* relevant tests pass;
* lint / type checks pass;
* required failure paths tested;
* contracts respected;
* no unrelated changes;
* security requirements satisfied;
* deployment / build succeeds if in scope;
* code map updated when relevant;
* handoff updated when relevant.

**Milestone-specific DoD gates:**

1.
2.
3.

#### Completion Evidence

Record concrete evidence:

* commands run;
* tests passed;
* relevant outputs;
* changed files;
* demo evidence.

| Evidence Item | Result / Location |
|---------------|-------------------|
| | |

#### Milestone Status

`PLANNED` | `READY` | `IN_PROGRESS` | `BLOCKED` | `DONE` | `DEFERRED`

---

## 13. Tasks and Subtasks

A milestone may contain tasks / subtasks when they create independently verifiable implementation units.

Do not create a subtask for every file or function.

**Sizing principle:**

```text
Large enough to produce meaningful value.
Small enough to review completely.
```

Separate Task Definition / Detailed Specification / Cursor Prompt packages may be used when complexity justifies them.

They are **not** required for every milestone.

The roadmap owns milestone-level Definition of Done.

---

## 14. Cursor / Developer Implementation Discipline

For meaningful implementation work:

1. read the relevant canonical references;
2. inspect the actual repository;
3. establish current state;
4. identify reusable existing assets;
5. identify affected files;
6. identify important contracts / boundaries;
7. propose implementation steps;
8. define validation;
9. avoid unrelated modifications.

Do **not** require a formal STOP for approval after every minor planning step.

Use explicit STOP only when:

* required information is genuinely unavailable;
* the requested change would violate an approved architecture / contract;
* implementation would require touching forbidden / out-of-scope files;
* a material conflict with the canonical reference is discovered.

Otherwise continue within the approved milestone.

---

## 15. Change Control

Implementation must not silently diverge from approved architecture.

When implementation discovers a conflict:

**If the conflict changes:**

* project scope;
* major architecture;
* important contract;
* technology constraint;
* ownership boundary;
* delivery requirement;

→ update the appropriate canonical source before proceeding with the affected work.

**If it is a local implementation detail** that does not change project-wide architecture:

→ resolve it at milestone / task level.

Do **not** require an ADR by default.

Do **not** create change-control bureaucracy for ordinary implementation details.

---

## 16. Current Execution Status

Roadmap-level status view only.

Do **not** duplicate the detailed Common Handoff (`03_common_handoff.md`).

| Milestone | Status | Last Verified Evidence | Blocker / Next Dependency |
|-----------|--------|------------------------|---------------------------|
| M1 — Reusable async LLM wrapper | DONE | poetry/ruff/pyright/pytest PASS | Awaiting review; no commit/push |

---

## 17. Final Delivery / Assignment Completion Boundary

Derive criteria from the actual assignment. Do not invent capabilities to make this section look comprehensive.

### Required End-to-End Outcome

### Mandatory Deliverables

### Required Validation

### Required Demo / Evidence

### Required Quality Gates

### Explicitly Deferred Items

### Final Completion Rule

The assignment is complete only when:

* all `MUST` milestones satisfy their Definition of Done;
* all externally required deliverables satisfy their acceptance criteria;
* required evidence is recorded.

---

## 18. Immediate Next Action

Keep this intentionally small.

It is only the roadmap-level pointer to the current execution position.

It must **not** duplicate `03_common_handoff.md`.

**Current milestone:** M1 — Reusable async LLM wrapper

**Current status:** DONE — awaiting human review

**Immediate next action:** Review the LLM capability; do not commit/push until authorized.

**Blocking dependency:** NONE

**Expected evidence:** Reviewer confirmation / next assignment milestone definition.
