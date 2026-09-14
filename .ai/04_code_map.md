# 04 — Semantic Code Map

## 1. Purpose and Authority

This document is the **semantic implementation map** of the repository.

Its purpose is to let Cursor, ChatGPT, developers, and reviewers move from an approved project concept to the correct implementation surface without treating the repository as an unstructured collection of files.

It answers:

```text
What important capabilities currently exist?
Which approved requirement / use case does each capability implement?
Where is each capability implemented?
Which contracts define its boundaries?
What depends on what?
Where does important state live?
Which external systems are involved?
Which tests prove important behaviour?
What is current, partial, deferred, example-only, legacy, or absent?
What else must be inspected before changing this area?
```

Primary navigation model:

```text
00 Project Requirement / Use Case
        ↓
01 Roadmap Milestone / Work Item
        ↓
04 Capability / Component
        ↓
Important Contract
        ↓
Implementation Location / Symbol
        ↓
Dependencies / State / External Effects
        ↓
Tests / Verification
```

This document is:

- an implementation navigation map;
- a responsibility and ownership map;
- a contract and dependency map;
- a bridge between project documentation and source code;
- a change-impact aid for AI-assisted engineering.

This document is **not**:

- the architectural source of truth;
- the implementation roadmap;
- the code-quality manual;
- the current operational handoff;
- a replacement for repository inspection;
- a complete file inventory;
- a future-architecture specification.

---

## 2. Long-Lived Documentation Relationship

| Document / Source | Owns |
|---|---|
| `00_project_reference.md` | Project-wide WHAT / WHY: requirements, scope, use cases, architecture, boundaries, cross-cutting requirements |
| `01_implementation_roadmap.md` | Delivery decomposition: milestones, sequencing, dependencies, priorities, milestone DoD, completion evidence |
| `02_code_quality_standards.md` | HOW implementation must be engineered |
| `03_common_handoff.md` | Current continuation state, active work, blockers, latest evidence, exact next action |
| `04_code_map.md` | WHERE important implementation lives and HOW responsibilities connect |
| Git / repository | Factual current implementation state |

Use this reasoning order:

```text
WHY / WHAT?
→ 00_project_reference.md

WHEN / IN WHAT ORDER?
→ 01_implementation_roadmap.md

HOW MUST IT BE ENGINEERED?
→ 02_code_quality_standards.md

WHERE ARE WE NOW?
→ 03_common_handoff.md

WHERE IS IT IMPLEMENTED?
→ 04_code_map.md + repository inspection
```

If this Code Map conflicts with the actual repository, the repository is factual evidence and the Code Map must be corrected.

If the repository conflicts with approved architecture, do **not** silently redefine architecture here. Surface the conflict against `00_project_reference.md`.

---

## 3. How Cursor Should Use This Code Map

Before materially changing an existing capability:

```text
1. Read `03_common_handoff.md`.
2. Identify the active requirement / use-case anchor in `00_project_reference.md`.
3. Identify the active milestone / work item in `01_implementation_roadmap.md`.
4. Locate the corresponding capability in this Code Map.
5. Inspect its important contracts, implementation locations, dependencies, tests,
   state ownership, and change-impact notes.
6. Re-read the relevant sections of `02_code_quality_standards.md`.
7. Inspect the actual source code and tests.
8. Make the smallest project-consistent change.
9. Update this Code Map only if information owned by this document materially changed.
```

Do not modify code solely from a filename match.

Do not infer responsibility solely from folder names.

Do not assume existing implementation automatically represents approved target architecture.

---

## 4. Mapping Scope and Compression Rules

Map **semantic responsibilities**, not every file.

### 4.1 Include Only When Material

Typical useful map targets include:

- application entry points;
- API / transport boundaries;
- application use cases / services;
- domain rules or important state transitions;
- important configuration ownership;
- cross-module contracts / Protocols / schemas;
- persistence / storage boundaries **when present**;
- external-provider adapters **when present**;
- LLM / model adapters **when present**;
- queue / event / worker boundaries **when present**;
- important processing components **when present**;
- observability / telemetry boundaries **when architecturally relevant**;
- important scripts / runtime entry points;
- tests that prove important behaviour.

These are examples, not mandatory architecture.

### 4.2 Usually Do Not Map

- trivial `__init__.py`;
- private helpers with no independent responsibility;
- every route method;
- every Pydantic model;
- every fixture;
- generated files;
- caches;
- virtual environments;
- every environment variable;
- every internal function call;
- every future capability mentioned in discussion.

### 4.3 Mapping Rule

Prefer:

```text
one semantic responsibility
→ one capability entry
→ one or more implementation locations
```

over:

```text
one file
→ one Code Map row
```

### 4.4 Hard Compression Rules

A populated Code Map must remain practical.

Use these rules:

- map only meaningful capabilities;
- use **Lite Capability Profile** by default;
- use **Expanded Capability Profile** only for cross-boundary, stateful, security-sensitive, externally integrated, or otherwise consequential capabilities;
- list only important symbols;
- list only cross-module or public contracts;
- list only tests that prove important behaviour;
- combine tightly coupled files under one capability;
- do not reproduce source trees;
- do not duplicate full API catalogs;
- do not duplicate the complete `.env.example`;
- do not preserve historical implementation states indefinitely;
- remove stale entries instead of accumulating history.

The goal is to document information that is **expensive or dangerous to infer**, not information that is trivial to rediscover from the repository.

---

## 5. Starter Assets vs Assignment Capabilities

An existing starter asset is not automatically an active project capability.

Possible reusable starter assets include:

- Python;
- FastAPI;
- Poetry;
- Pydantic v2 / Settings;
- Docker / Compose;
- Ruff;
- Pyright;
- pytest;
- an existing OpenAI LLM wrapper when present.

Use:

```text
Existing starter asset
≠ mandatory assignment capability
```

Examples:

```text
FastAPI may be present even if the assignment changes only internal application logic.

Docker may be present even if the current milestone does not touch container delivery.

An OpenAI wrapper may be retained as a reusable asset while the current assignment uses no LLM.
```

Do not invent provider factories, databases, queues, workers, RAG, persistence, or other infrastructure merely because the Code Map can represent them.

---

## 6. Status and Verification Vocabulary

### 6.1 Implementation Status

```text
CURRENT
→ Exists and participates in the active implementation.

PARTIAL
→ Exists, but the approved capability is intentionally incomplete.

NOT_IMPLEMENTED
→ Approved / required capability has no current implementation.

DEFERRED
→ Explicitly postponed and outside the active delivery boundary.

EXAMPLE_ONLY
→ Starter / demonstration code exists but is not authoritative project implementation.

TRANSITIONAL
→ Temporary current structure exists during an approved migration or milestone transition.

LEGACY
→ Still present, but not part of the preferred active path.

UNKNOWN
→ Repository state has not yet been verified.
```

Do not use `CURRENT` for future target architecture.

Do not use `NOT_IMPLEMENTED` for arbitrary future ideas that are not approved requirements.

### 6.2 Verification Status

```text
VERIFIED
PARTIALLY_VERIFIED
NOT_VERIFIED
FAILED
NOT_APPLICABLE
```

Implementation status and verification status are separate.

---

# PART A — REPOSITORY ORIENTATION

## 7. Repository Summary

Keep this concise and factual.

**Application / repository name:** fastapi-prod-starter-v2-slim

**Primary runtime / language:** Python 3.11

**Primary framework(s):** FastAPI, Pydantic Settings, OpenAI SDK (optional LLM asset)

**Application package / root:** `src/app`

**Primary entry point(s):** `app.main:app` / `create_app`

**Test root:** `tests/`

**Container / runtime model:** Dockerfile + docker-compose.yaml

**Current major external dependencies:** fastapi, uvicorn, pydantic-settings, openai

**Current state / persistence systems, if any:** NONE

**Current provider integrations, if any:** OpenAI (reusable LLM asset; not required at app boot)

### Repository Shape

```text
src/app/
├── api/                 system routes
├── llm/                 async LLM wrapper + OpenAI provider
├── exceptions.py
├── settings.py
├── logging_config.py
└── main.py

tests/
├── llm/                 wrapper + provider unit tests (no network)
├── test_application.py
├── test_settings.py
└── test_system_endpoints.py
```

---

## 8. High-Level Semantic Implementation Map

This is the main project-level implementation index.

| Capability / Component | Project Reference | Roadmap | Status | Primary Implementation | Important Contract(s) | Primary Tests |
|---|---|---|---|---|---|---|
| Application factory / system API | starter foundation | foundation | CURRENT | `src/app/main.py`, `src/app/api/system.py` | FastAPI app + `/health` `/ready` `/version` | `tests/test_application.py`, `tests/test_system_endpoints.py` |
| Configuration | starter foundation | foundation | CURRENT | `src/app/settings.py` | `Settings` / env aliases incl. optional `OPENAI_*` | `tests/test_settings.py` |
| LLM Invocation | reusable starter asset | `01 → M1` | CURRENT | `src/app/llm/openai_wrapper.py` | `AsyncOpenAIWrapper`, `LLMCallResult`, guardrails | `tests/llm/test_openai_wrapper.py` |
| OpenAI provider construction | reusable starter asset | `01 → M1` | CURRENT | `src/app/llm/openai_provider.py` | `create_async_openai_client` | `tests/llm/test_openai_provider.py` |

Use one row per meaningful capability / component.

Capability names below are illustrative only.

Map only capabilities that are actually present, approved, or materially relevant to the current project.

Examples such as Search Retrieval or LLM Invocation do not imply those capabilities belong in every project.

```text
System API
Dataset Intake
Order Placement
Prompt Resolution
Execution Context
Search Retrieval
LLM Invocation
Telemetry Boundary
Configuration
Health / Readiness
```

Avoid vague rows such as:

```text
utils
misc
helpers
models
```

unless they genuinely own a semantic responsibility.

---

## 9. Requirement → Implementation Traceability — Conditional

Populate this section **only when one approved requirement / use case spans multiple capabilities** and the relationship is not already obvious from §8.

Otherwise:

```text
Requirement traceability table: NOT_APPLICABLE — §8 is sufficient.
```

| Requirement / Use Case | `00` Anchor | `01` Delivery Anchor | Implementing Capabilities | Status | Verification |
|---|---|---|---|---|---|
| | | | | | |

Do not duplicate full requirement text.

---

# PART B — CAPABILITY MAP

## 10. Capability Profiles

Use the **Lite Profile by default**.

Use the Expanded Profile only when the capability is complex enough that additional context materially reduces implementation risk.

---

### 10.1 Application Factory / System API — Lite Profile

**Status:** `CURRENT`

**Verification:** `VERIFIED`

#### Purpose

Create the FastAPI app and expose liveness/readiness/version endpoints without constructing external clients.

#### Project / Roadmap Anchors

```text
01_implementation_roadmap.md → foundation / baseline
```

#### Owns

- `create_app`
- system router registration
- logging configuration at app creation

#### Implementation Locations

| Path | Important Symbol(s) | Responsibility |
|---|---|---|
| `src/app/main.py` | `create_app`, `app` | Application factory |
| `src/app/api/system.py` | router | `/health`, `/ready`, `/version` |

#### Important Contracts

| Contract | Defined At | Main Consumer(s) |
|---|---|---|
| Injected `Settings` on `app.state.settings` | `src/app/main.py` | system endpoints / tests |

#### Tests

| Path | What It Proves |
|---|---|
| `tests/test_application.py` | factory behaviour / settings injection |
| `tests/test_system_endpoints.py` | system route payloads |

#### Inspect Before Editing

- `src/app/settings.py`
- LLM package (must remain optional at boot)

---

### 10.2 Configuration — Lite Profile

**Status:** `CURRENT`

**Verification:** `VERIFIED`

#### Purpose

Load and validate environment configuration, including optional OpenAI settings.

#### Owns

- `Settings`, `get_settings`
- `OPENAI_API_KEY` (optional), `OPENAI_MODEL`, timeout, max retries

#### Implementation Locations

| Path | Important Symbol(s) | Responsibility |
|---|---|---|
| `src/app/settings.py` | `Settings`, `get_settings` | Validated env config |

#### Important Contracts

| Contract | Defined At | Main Consumer(s) |
|---|---|---|
| Optional OpenAI settings fields | `src/app/settings.py` | LLM composition callers |

#### Tests

| Path | What It Proves |
|---|---|
| `tests/test_settings.py` | defaults, validation, OpenAI env loading |

#### Inspect Before Editing

- `.env.example`
- LLM provider construction (`create_async_openai_client`)

---

### 10.3 LLM Invocation — Expanded Profile

**Status:** `CURRENT`

**Verification:** `VERIFIED`

#### Purpose

Reusable async orchestration for plain-text and structured OpenAI chat completions with guardrails, retries, timeouts, and typed results.

#### Project / Roadmap Anchors

```text
01_implementation_roadmap.md → M1
```

#### Owns

- async `generate_text` / `generate_structured`
- input/output guardrail execution
- retry / timeout orchestration
- `LLMCallResult` metadata (latency, attempts, notes)
- provider error translation to application exceptions

#### Explicitly Does Not Own

- `AsyncOpenAI` construction
- reading `OPENAI_API_KEY`
- assignment-specific domain prompts
- FastAPI route composition

#### Implementation Locations

| Path | Important Symbol(s) | Responsibility |
|---|---|---|
| `src/app/llm/openai_wrapper.py` | `AsyncOpenAIWrapper`, `LLMCallResult`, protocols | Orchestration |
| `src/app/llm/guardrails.py` | `BaseGuardrail`, `MaxPromptLengthGuardrail` | Deterministic guards |
| `src/app/exceptions.py` | `GuardrailBlockedError`, `ModelOutputParsingError`, `UpstreamServiceError` | Error vocabulary |

#### Important Contracts

| Contract | Defined At | Main Consumer(s) |
|---|---|---|
| `AsyncOpenAIClientProtocol` | `src/app/llm/openai_wrapper.py` | wrapper + tests fakes |
| `LLMCallResult[T]` | `src/app/llm/openai_wrapper.py` | callers |
| Guardrail interface | `src/app/llm/guardrails.py` | wrapper |

#### Dependency Direction

```text
Caller / test
→ AsyncOpenAIWrapper
→ AsyncOpenAIClientProtocol (injected)
→ OpenAI provider client OR fake
```

#### External Systems / Providers

| External Dependency | Purpose | Adapter / Boundary | Failure Translation |
|---|---|---|---|
| OpenAI Chat Completions | LLM inference | injected async client | `UpstreamServiceError` / `ModelOutputParsingError` |

#### Tests

| Path | What It Proves |
|---|---|
| `tests/llm/test_openai_wrapper.py` | text/structured success, guardrails, parsing failure, upstream failure, retry |

#### Inspect Before Editing

- `src/app/llm/openai_provider.py`
- `src/app/settings.py`
- `tests/llm/test_openai_wrapper.py`

---

### 10.4 OpenAI Provider Construction — Lite Profile

**Status:** `CURRENT`

**Verification:** `VERIFIED`

#### Purpose

Construct `AsyncOpenAI` from configuration for injection into the wrapper.

#### Owns

- `create_async_openai_client`
- SDK `max_retries=0` so wrapper owns retries

#### Implementation Locations

| Path | Important Symbol(s) | Responsibility |
|---|---|---|
| `src/app/llm/openai_provider.py` | `create_async_openai_client` | AsyncOpenAI construction |

#### Important Contracts

| Contract | Defined At | Main Consumer(s) |
|---|---|---|
| `create_async_openai_client(*, api_key, timeout_seconds)` | `openai_provider.py` | real composition paths |

#### Tests

| Path | What It Proves |
|---|---|
| `tests/llm/test_openai_provider.py` | returns `AsyncOpenAI` with retries disabled (no network) |

#### Inspect Before Editing

- wrapper injection contract
- settings OpenAI fields

---

# PART C — CROSS-CAPABILITY MAPS

The sections in Part C are **conditional**.

Populate them only when the information crosses multiple capabilities and would otherwise be expensive or risky to infer.

Do not create parallel registries merely because a template section exists.

---

## 11. Important Contract Registry — Conditional

Populate only for contracts with meaningful cross-module impact.

Otherwise:

```text
Cross-capability contract registry: NOT_APPLICABLE.
```

| Contract | Kind | Location | Owner | Main Consumers | Change Risk | Tests |
|---|---|---|---|---|---|---|
| | API / schema / Protocol / event / model | | | | | |

Good candidates:

- public API contracts used by multiple areas;
- repository/storage Protocols;
- LLM/provider interfaces;
- shared application result models;
- event/message envelopes;
- state-transition contracts.

Do not list private local models.

---

## 12. Important Runtime / Processing Flows — Conditional

Populate only for **multi-step flows whose implementation path is not obvious**.

Otherwise:

```text
Runtime flow map: NOT_APPLICABLE.
```

### Flow `<Name>`

**Project anchor:**

```text
00_project_reference.md → §...
```

**Semantic flow:**

```text
<entry>
→ <validation>
→ <orchestration>
→ <processing / domain rule>
→ <external effect or state change if applicable>
→ <result>
```

**Implementation path:**

```text
<module / symbol>
→ <module / symbol>
→ <module / symbol>
```

**Important failure boundaries:**

- ...

**Primary tests:**

- ...

Do not create flow entries for trivial helpers or simple getters.

---

## 13. Dependency Direction Map — Conditional

Populate this section only when dependency direction is materially useful for understanding or protecting the implementation.

For a flat or simple repository, a short actual-direction sketch is sufficient.

Do not invent architectural layers merely to populate this section.

If there is no material dependency structure worth documenting:

```text
Dependency direction map: NOT_APPLICABLE — repository inspection is sufficient.
```

Any dependency diagram must describe the **actual current repository direction**.

Do not force a layered architecture that the repository does not have.

### Current Direction

```text
<actual current component/module>
→ <actual dependency>
→ <actual downstream boundary>
```

### Optional Layered Pattern — Example Only

If the approved project uses layered boundaries, a pattern may be:

```text
API / Transport
→ Application
→ Domain / Contracts

Infrastructure Adapters
→ Application / Domain Contracts
```

This is an example, not mandatory architecture.

API / Application / Domain layers are not required.

### Important Dependencies

| From | Depends On | Through | Reason | Allowed? |
|---|---|---|---|---|
| | | import / Protocol / DI / API / event | | YES / EXCEPTION |

### Forbidden / High-Risk Directions

- ...
- ...

---

## 14. State / Persistence / Ownership Map — Conditional

Populate only when meaningful state exists.

Otherwise:

```text
State ownership map: NOT_APPLICABLE.
```

| State / Entity / Artifact | Authoritative Owner | Storage / Location | Writers | Readers | Lifecycle / Consistency Notes |
|---|---|---|---|---|---|
| | | | | | |

Distinguish:

```text
authoritative state
≠ cache
≠ derived state
≠ transport state
≠ logs / telemetry
```

---

## 15. External Integration / Provider Map — Conditional

Populate only when external integrations materially affect architecture or change impact.

Otherwise:

```text
External integration map: APPLICABLE — OpenAI only.
```

| Integration / Provider | Status | Purpose | Adapter / Boundary | Configuration Owner | Failure Handling | Tests |
|---|---|---|---|---|---|---|
| OpenAI | CURRENT (opt-in) | Chat completions / structured parse | `create_async_openai_client` + injected client into `AsyncOpenAIWrapper` | `Settings.openai_*` / `OPENAI_*` env | `UpstreamServiceError`, `ModelOutputParsingError`, `GuardrailBlockedError` | `tests/llm/*` |

Do not list unused dependencies.

Do not invent provider-neutral abstractions solely because one provider exists.

---

## 16. Configuration Ownership Map — Conditional

Use only for **behaviourally important configuration groups** whose ownership is not obvious.

Otherwise:

```text
Configuration ownership map: APPLICABLE for OpenAI group.
```

| Setting / Group | Owner | Defined At | Used By | Required? | Operational / Security Note |
|---|---|---|---|---|---|
| App env / version / log level | `Settings` | `src/app/settings.py` | app factory / logging / system API | YES (defaults exist) | Standard runtime config |
| OpenAI API key / model / timeout / retries | `Settings` | `src/app/settings.py` | LLM composition callers | KEY optional | Secret via env; never hard-code |

Group related settings.

Do not copy the complete `.env.example`.

---

# PART D — TESTS, TOOLING, AND CHANGE IMPACT

## 17. Test Infrastructure Map

Capability-level behaviour tests belong inside the capability profiles.

Use this section only for shared test infrastructure.

| Path / Fixture Area | Responsibility | Important Notes |
|---|---|---|
| | | |

Examples:

- shared fixtures;
- integration environment setup;
- test client / app factory;
- common fakes/adapters;
- containerized integration-test setup.

`02_code_quality_standards.md` owns testing policy.

---

## 18. Runtime / Tooling Entry Points

Record only operationally meaningful commands and artifacts.

| Purpose | Location / Command | Status | Notes |
|---|---|---|---|
| Local development | | | |
| Lint | | | |
| Format check | | | |
| Type check | | | |
| Tests | | | |
| Combined quality gate | | | |
| Docker build / run | | | |
| Deployment, if applicable | | | |

Current command **results** belong in `03_common_handoff.md`, not here.

---

## 19. Important Repository Artifacts — Conditional

Record only artifacts with non-obvious implementation or operational responsibility.

| Path | Responsibility | Main Effect / Consumer | Notes |
|---|---|---|---|
| | | | |

Possible examples:

```text
pyproject.toml
pyrightconfig.json
Dockerfile
docker-compose.yaml
```

Do not populate this section merely because the files exist.

If their role is obvious and stable:

```text
Important repository artifacts: NOT_APPLICABLE — repository inspection is sufficient.
```

---

## 20. Change-Impact Navigation

This is a primary anti-drift section.

Population rule:

- the table must contain only change-impact paths that are true and useful for the actual repository;
- example / template rows that do not apply MUST be deleted;
- do not retain provider, LLM, persistence, state, Docker, telemetry, or other generic rows unless that concern actually exists and creates meaningful change impact;
- add project-specific rows for real high-risk boundaries where useful.

The rows below are seed examples for template guidance only. Delete every row that does not apply when populating a project map.

| If Changing... | Also Inspect... | Why |
|---|---|---|
| Public API schema | handler, application contract, consumers, contract tests | Prevent contract drift |
| LLM wrapper orchestration | provider construction, guardrails, exceptions, `tests/llm/test_openai_wrapper.py` | Preserve async behaviour and error semantics |
| OpenAI provider construction | settings OpenAI fields, wrapper injection contract, provider tests | Keep API-key ownership outside wrapper |
| Important configuration | settings owner, composition, runtime/deployment config, tests | Prevent environment divergence |
| Docker/runtime command | health semantics, settings, Compose | Preserve runtime consistency |

---

## 21. Known Implementation Gaps / Limitations — Conditional

Record only gaps necessary to understand current implementation structure.

| Gap / Limitation | Affected Capability | Status | Approved Handling / Source |
|---|---|---|---|
| | | PARTIAL / NOT_IMPLEMENTED / DEFERRED / LEGACY | `00 / 01 → ...` |

This is not the general backlog.

Immediate blockers belong in `03_common_handoff.md`.

If no map-relevant gaps exist:

```text
Known implementation-map gaps: NONE.
```

---

## 22. Example / Transitional / Legacy Code

This prevents Cursor from treating non-authoritative code as target architecture.

| Path / Area | Classification | Why It Exists | Reuse Policy | Decision / Removal Source |
|---|---|---|---|---|
| | EXAMPLE_ONLY / TRANSITIONAL / LEGACY | | YES / NO / CASE-BY-CASE | |

If none:

```text
No known example-only, transitional, or legacy code relevant to current implementation.
```

---

# PART E — HANDOFF INTEGRATION AND MAINTENANCE

## 23. Integration With `03_common_handoff.md`

The handoff should point to this map precisely.

Preferred pattern:

```text
Current capability
→ 04_code_map.md → §10.x <Capability>

Important cross-module contract, if relevant
→ 04_code_map.md → §11 <Contract>

Important flow, if relevant
→ 04_code_map.md → §12 <Flow>

Important state, if relevant
→ 04_code_map.md → §14 <State / Entity>
```

`03_common_handoff.md` owns:

- current milestone / task / subtask;
- current factual state;
- blockers;
- latest evidence;
- exact next approved action.

`04_code_map.md` owns:

- stable implementation navigation;
- semantic responsibilities;
- important contracts;
- dependency structure;
- state/source-of-truth ownership;
- important test locations;
- implementation status.

Do not copy handoff history into the Code Map.

---

## 24. Code Map Maintenance Rules

Update this document when implementation materially changes information it owns.

### Update When

- an important capability is added, removed, split, or merged;
- a module changes semantic responsibility;
- an important implementation location moves;
- a public or cross-module contract changes;
- dependency direction changes;
- an external integration is introduced or removed;
- source-of-truth / state ownership changes;
- an important runtime flow changes;
- important test ownership changes;
- example/transitional/legacy code classification changes.

### Do Not Update Mechanically When

- a private helper is renamed;
- formatting changes;
- comments change;
- a trivial fixture changes;
- a local internal implementation detail changes without affecting mapped responsibility;
- line numbers change.

### Maintenance Principle

Prefer:

```text
semantic responsibility
+ exact implementation location
+ important contract
+ change impact
+ proving tests
```

over:

```text
large file inventory
```

---

## 25. Anti-Drift Rules

### 25.1 Repository Reality vs Approved Architecture

The repository tells you **what exists**.

`00_project_reference.md` tells you **what the approved project means**.

This Code Map connects them.

Do not let current code silently redefine approved architecture.

### 25.2 Current vs Target vs Deferred

Do not describe future target components as `CURRENT`.

Use:

```text
PARTIAL
NOT_IMPLEMENTED
DEFERRED
EXAMPLE_ONLY
TRANSITIONAL
LEGACY
```

only when those classifications are factually justified.

### 25.3 Reuse Before Replacement

Before creating a component, inspect this map and the repository for an existing production-grade asset or responsibility that already solves the need.

### 25.4 Important Contract Changes Are High Impact

When a cross-module/public contract changes:

```text
identify owner
→ identify consumers
→ identify state / external effects
→ identify proving tests
→ inspect change-impact notes
→ update Code Map if responsibility changed
```

### 25.5 Small Diffs Can Have Large Semantic Reach

Judge change impact by:

- ownership;
- contract boundaries;
- state semantics;
- external effects;
- security;
- observability;
- downstream consumers;

not by line count alone.

---

## 26. End-of-Work Code Map Checklist

Before considering a meaningful implementation boundary complete, check:

### Capability Mapping

- [ ] changed capability is mapped when materially relevant;
- [ ] exact `00` project anchors are correct;
- [ ] exact `01` roadmap anchor is correct;
- [ ] implementation status is factual;
- [ ] verification status is not overstated.

### Implementation Navigation

- [ ] important implementation locations are current;
- [ ] important contracts are current;
- [ ] ownership boundaries are correct;
- [ ] dependency direction is current;
- [ ] external integrations are current when applicable;
- [ ] state/source-of-truth ownership is current when applicable.

### Tests and Impact

- [ ] proving tests are mapped;
- [ ] known material test gaps are explicit;
- [ ] change-impact notes remain accurate.

### Drift Control

- [ ] future architecture is not presented as implemented;
- [ ] example/transitional/legacy code is clearly classified;
- [ ] starter assets are not misrepresented as mandatory capabilities;
- [ ] the map does not duplicate source code;
- [ ] the map does not duplicate roadmap or handoff history;
- [ ] stale responsibilities were removed.

---

## 27. Compact Semantic Snapshot

Keep this short and current.

```text
APPLICATION ENTRY
→ src/app/main.py::create_app

PRIMARY ACTIVE CAPABILITIES
→ System API; Settings; LLM Invocation (reusable); OpenAI provider construction

IMPORTANT CROSS-MODULE CONTRACTS
→ AsyncOpenAIClientProtocol; LLMCallResult; Settings.openai_*

AUTHORITATIVE STATE / STORAGE, IF ANY
→ NONE

EXTERNAL PROVIDERS / SERVICES, IF ANY
→ OpenAI (opt-in via env key)

CRITICAL DEPENDENCY DIRECTION
→ callers → AsyncOpenAIWrapper → injected client; provider owns AsyncOpenAI

PRIMARY TEST SURFACES
→ tests/llm/*; tests/test_settings.py; tests/test_application.py

EXAMPLE / TRANSITIONAL / LEGACY AREAS
→ NONE for the LLM capability

IMPORTANT CURRENT IMPLEMENTATION GAPS
→ LLM not wired into FastAPI routes by default (intentional)
```

This is a rapid orientation aid.

The capability profiles and actual repository remain the primary implementation-navigation sources.
