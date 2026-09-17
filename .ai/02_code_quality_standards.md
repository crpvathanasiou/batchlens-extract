# 02 — Code Quality Standards

## Table of Contents

1. Purpose and Authority
2. Quality Philosophy
3. Core Engineering Principles
4. Technology Baseline
5. Project Structure
6. Python Standards
7. Pydantic v2 Standards
8. Async Standards
9. SOLID and Dependency Design
10. FastAPI Standards
11. Configuration Standards
12. Error Handling Standards
13. Guardrail Standards
14. Logging and Observability Standards
15. Security Standards
16. Testing Standards
17. Static Quality Gates
18. Ruff Standards
19. Pyright Standards
20. Docker Standards
21. CI Standards
22. Scripts and Developer Commands
23. Documentation Standards
24. Code Map Standards
25. Common Handoff Standards
26. AI-Assisted Engineering Standards
27. Git and Change Standards
28. Code Review Checklist
29. Exceptions and Architectural Decisions
30. Project-Wide Quality Gates
31. Core Code Quality Rules
32. Standards vs Current Compliance

---

## 1. Purpose and Authority

This document defines the long-lived engineering and code-quality standards for **BatchLens Extract** (`batchlens-extract`).

It applies to application code, tests, scripts, Docker configuration, project-defined CI/CD when introduced, infrastructure integration code, and AI-assisted changes.

It owns **stable engineering rules**. It does not own product scope, milestone sequencing, pipeline contracts, product data-handling policy, extraction-accuracy evaluation, or check inventories.

| Document | Owns |
|----------|------|
| [00_project_reference.md](00_project_reference.md) | Product purpose and boundaries |
| [01_implementation_roadmap.md](01_implementation_roadmap.md) | Milestones and DoD |
| [03_common_handoff.md](03_common_handoff.md) | Current execution state |
| [04_code_map.md](04_code_map.md) | Implemented modules |
| [05_pipeline_contracts.md](05_pipeline_contracts.md) | Pipeline semantics and contracts |
| [06_security_and_data_handling.md](06_security_and_data_handling.md) | Product data protection and security-claim evidence |
| [07_extraction_evaluation.md](07_extraction_evaluation.md) | Extraction-quality and reviewer-effort evaluation |
| [08_check_selection_strategy.md](08_check_selection_strategy.md) | Check selection strategy |

Do not require separate Task Definition / Detailed Specification / ADR documents by default. Milestone DoD lives in [01](01_implementation_roadmap.md).

Documentation-only changes require content, link, and scope checks — not application tests or Docker rebuilds.

When a milestone or design note conflicts with this document, resolve the conflict explicitly before implementation.

---

## 2. Quality Philosophy

BatchLens Extract follows:

```text
Quality by Design
```

Quality must be introduced through:

* clear contracts;
* controlled dependencies;
* explicit lifecycle rules where the system has lifecycle/state;
* validation;
* guardrails;
* tests;
* observability;
* review;
* measurable completion criteria.

Quality must not depend only on:

* developer memory;
* manual inspection;
* coding-assistant behaviour;
* production monitoring;
* comments describing intended behaviour.

The preferred engineering sequence is:

```text
Understand Requirement
→ Define Contract
→ Implement Small Capability
→ Validate Behaviour
→ Verify Failure Paths
→ Document Result
```

---

## 3. Core Engineering Principles

### 3.1 Correctness Before Abstraction

The implementation should first solve the approved requirement correctly.

Abstractions should be introduced only when they:

* protect an important boundary;
* support testing;
* isolate an external dependency;
* remove meaningful duplication;
* preserve a stable contract;
* are required by an approved future capability.

The project must avoid:

```text
Interface for every function
Factory for every class
Base class without demonstrated reuse
Generic framework before concrete use
Configuration option without a real requirement
```

### 3.2 Simplicity Before Generality

Prefer the simplest design that satisfies:

* current requirements;
* known near-term requirements;
* production safety;
* maintainability.

The project should not optimize for arbitrary future domains.

The preferred rule is:

```text
Current Requirement First
→ Reuse Where Proven
→ Generalize Only When Justified
```

Do not build abstractions for hypothetical future requirements.

### 3.3 Explicit Over Implicit

Important behaviour must be visible through:

* function signatures;
* models;
* enums;
* contracts;
* configuration;
* lifecycle transitions where state exists;
* named error types.

Avoid hidden:

* global state;
* fallback behaviour;
* automatic retries;
* environment assumptions;
* implicit coercion;
* side effects during import.

### 3.4 Immutable Historical State

When the system contains completed runs, versions, audit history, historical outputs, or other authoritative records that must remain reproducible, completed historical state must not be silently rewritten.

Prefer new version/run or supersede/version rather than silently mutating completed history when historical traceability matters.

Controlled deletion remains allowed under an explicit retention/deletion policy. Historical traceability requirements must coexist with product data-handling rules in [06_security_and_data_handling.md](06_security_and_data_handling.md). Do **not** imply unlimited retention of confidential content.

Not every application requires versioned historical state. Apply these principles only where reproducibility, auditability, or historical integrity is part of the approved design.

### 3.5 Fail Safely

The system should fail:

* explicitly;
* predictably;
* with sufficient diagnostic context;
* without exposing secrets;
* without creating invalid partial state;
* without silently continuing after a blocking failure.

---

## 4. Technology Baseline

### Current foundation (implemented)

```text
Python: 3.11.x  (>=3.11,<3.12 in pyproject.toml)
FastAPI + Uvicorn
Poetry
Pydantic v2 + Pydantic Settings
Docker + Docker Compose (Node 22.12 review-frontend builder stage)
Ruff + Pyright (strict) + pytest
Optional document conversion + document review (feature-flagged; not AWS-verified)
Optional async OpenAI LLM wrapper (present, not wired to product flows)
```

### Approved deployment direction (not implemented)

```text
FastAPI, Docker, ECR, ECS/Fargate on AWS
```

Detailed AWS service selection follows document-processing requirements. Do not treat AWS topology details as decided beyond this direction.

### Optional / deferred technology guidance

* The existing OpenAI wrapper is a **reusable optional asset**. Its presence does **not** commit BatchLens Extract’s extraction architecture to OpenAI.
* Prefer reuse of the existing wrapper only when an approved design selects OpenAI (or compatible chat-completions usage) for a concrete integration.
* Do not introduce speculative multi-provider factories, Neo4j, GraphRAG, queues, or persistence layers solely because they might be useful later.
* Graph visualization must be generatable deterministically from extracted data; Neo4j/GraphRAG are deferred and not required for the recipe graph.

Reuse before rewrite when an existing asset fits an **approved** need.

Dependencies must be:

* justified by an approved milestone or work item;
* added through Poetry;
* recorded in `pyproject.toml`;
* committed with the updated `poetry.lock`;
* reviewed for maintenance, licensing, and security risk.

Do not add a dependency when the standard library or an existing dependency provides a clear and maintainable solution.

---

## 5. Project Structure

Preserve the existing BatchLens Extract layout (`src/app`, `tests/`, `scripts/`, `.ai/`) unless there is a concrete reason to restructure it.

Do not migrate between layout styles such as `app/` and `src/` merely to satisfy this document.

The standard emphasizes responsibility boundaries over directory-name dogma.

Current package root:

```text
src/app/
├── api/
├── document_conversion/   # Textract/Textractor → canonical Document + unreviewed HTML
├── document_jobs/         # durable conversion jobs, Cognito, Dynamo/S3/SQS adapters
├── document_review/       # review domain, mapping, storage, reviewed exports
├── llm/                   # optional reusable asset; not product extraction
├── exceptions.py
├── logging_config.py
├── settings.py
└── main.py

frontend/                  # Vue 3 / TipTap 3 / PDF.js review workspace
tests/
tests/document_review/     # review tests + local harness (not production)
```

Additional directories (application, domain, infrastructure, etc.) should be created only when they contain real responsibilities.

Empty architectural folders should not be created merely to imitate a template.

### 5.1 Responsibility Boundaries

Where the architecture uses these layers, keep the conceptual responsibilities below.

#### API Layer

Responsible for:

* HTTP contracts;
* request parsing;
* response serialization;
* HTTP status codes;
* authentication context;
* dependency resolution;
* conversion of application errors into safe API responses.

The API layer must not contain:

* core domain or business rules;
* direct infrastructure-provider access;
* direct database, storage, or search SDK calls;
* large processing workflows.

#### Application Layer

Responsible for:

* use-case orchestration;
* transaction coordination;
* calling domain rules;
* calling infrastructure contracts;
* producing application outcomes.

The application layer should describe what the use case does without depending on FastAPI-specific concepts.

#### Domain Layer

Responsible for:

* domain concepts and invariants;
* domain value objects;
* state-transition validation where lifecycle/state exists;
* domain-specific errors;
* pure deterministic rules.

The domain layer must not depend directly on:

* FastAPI;
* provider SDKs;
* database drivers;
* Docker;
* environment variables.

#### Infrastructure Layer

Responsible for implementations of external concerns such as:

* database / persistence;
* object / file storage;
* search / vector infrastructure;
* queues / event systems;
* LLM / model providers;
* external APIs;
* system clocks or identifier providers when abstraction is justified.

These examples are not mandatory project components. They illustrate possible external concerns.

Infrastructure implementations should satisfy contracts defined closer to the application or domain layer.

### 5.2 Dependency Direction

The preferred dependency direction is:

```text
API
→ Application
→ Domain

Infrastructure
→ Application or Domain Contracts
```

Domain code must not import infrastructure modules.

Application services should depend on contracts, not concrete external clients, where isolation provides meaningful value.

---

## 6. Python Standards

### 6.1 Type Annotations

All public functions, methods, classes, and module-level contracts must be typed.

Type annotations should also be used for internal functions when they improve:

* readability;
* static verification;
* refactoring safety.

Avoid:

```python
def process(data):
    ...
```

Prefer:

```python
def process(request: ProcessingRequest) -> ProcessingResult:
    ...
```

### 6.2 `Any`

`Any` should not be used as a default escape from typing.

It is acceptable only when:

* interacting with an untyped external library;
* handling deliberately dynamic JSON at an external boundary;
* accompanied by validation or controlled conversion.

Prefer specific structures such as:

```python
dict[str, str]
Mapping[str, object]
Sequence[Item]
```

### 6.3 Function Design

Functions should:

* perform one cohesive responsibility;
* use clear names;
* avoid hidden side effects;
* return explicit results;
* raise documented typed errors for exceptional outcomes.

Long functions should be divided when they contain multiple independently understandable operations.

Function length alone is not the quality criterion.

### 6.4 Classes

Use a class when it provides meaningful:

* state;
* lifecycle;
* encapsulation;
* polymorphism;
* dependency coordination.

Do not create classes for simple stateless transformations when a typed function is clearer.

### 6.5 Dataclasses and Pydantic Models

Use:

* Pydantic models at validation and serialization boundaries;
* dataclasses or explicit domain classes for internal domain structures when runtime validation is unnecessary;
* enums for controlled lifecycle or status values where such values exist.

Avoid using dictionaries as long-lived domain entities.

### 6.6 Mutable Defaults

Mutable default arguments are prohibited.

Do not use:

```python
def process(items: list[str] = []):
    ...
```

Use:

```python
def process(items: list[str] | None = None):
    resolved_items = items or []
```

or a `default_factory` in models.

### 6.7 Time

Use timezone-aware timestamps.

Prefer UTC for persisted operational timestamps.

Do not use naive `datetime.now()` for persisted authoritative state.

### 6.8 Identifiers

Use stable application-level identifiers.

External identifiers such as:

* storage / object keys;
* execution / job IDs;
* provider-generated IDs;
* database sequence IDs;

must not silently replace application or domain identity unless explicitly approved.

---

## 7. Pydantic v2 Standards

Pydantic v2 is used for:

* API request and response validation;
* configuration;
* external-service payload validation;
* structured processing outputs;
* controlled serialization.

### 7.1 Boundary Validation

Untrusted or external data must be validated when entering the application.

Examples include:

* HTTP requests;
* environment variables;
* parsed metadata;
* external API responses;
* queue messages;
* model / LLM outputs where used;
* database payloads crossing a contract boundary.

### 7.2 Strictness

Use strict validation where silent coercion could create ambiguity or risk.

For example, a lifecycle status, enum, or other contract-critical numeric/string field must not be accepted through arbitrary coercion.

### 7.3 Model Configuration

Pydantic models should deliberately define:

* extra-field behaviour;
* aliases;
* serialization rules;
* immutability where useful;
* string normalization where required.

Avoid relying on undocumented default behaviour for critical contracts.

### 7.4 Validation Location

Use:

* field validation for one field;
* model validation for relationships between fields;
* domain services for rules that require external state or multiple entities.

Do not place database calls or infrastructure access inside Pydantic validators.

### 7.5 Transport and Domain Models

API models and persistence models must not automatically become the domain model.

Separate models when their responsibilities differ materially.

Avoid unnecessary duplication when one model accurately serves both purposes without coupling the domain to an external framework.

### 7.6 Settings

Configuration must use Pydantic Settings.

Settings should:

* load from environment variables;
* define explicit types;
* validate required production configuration;
* use safe defaults only for local development where appropriate;
* never contain committed secrets;
* be injectable for tests.

Settings should not be loaded repeatedly across the application.

---

## 8. Async Standards

### 8.1 General Rule

Use async for I/O-bound operations when it provides concurrency value.

Examples include:

* HTTP calls;
* database calls using async drivers;
* external storage, search, or provider calls using async-compatible clients;
* external model / LLM calls where used;
* queue operations.

These are examples, not required architecture.

Do not make code async solely because FastAPI supports async endpoints.

### 8.2 Pure Logic

Pure transformations should normally remain synchronous.

Examples include:

* metadata normalization;
* checksum calculation;
* lifecycle or state validation where applicable;
* boundary or range calculation;
* result aggregation;
* configuration comparison.

### 8.3 Blocking I/O

Blocking I/O must not execute directly inside the event loop.

When only a synchronous library is available, use a controlled strategy such as:

* thread-pool execution;
* background worker;
* synchronous endpoint where justified;
* replacement with an async-compatible adapter.

The strategy must be explicit in the approved milestone or design when it materially affects implementation.

Do not require a separate Detailed Specification document solely for this decision.

### 8.4 Async Signatures

Do not expose async interfaces when the implementation performs no asynchronous work and no approved contract requires it.

### 8.5 Concurrency Safety

Concurrent operations must consider:

* idempotency;
* duplicate submissions;
* race conditions;
* transaction boundaries;
* ordering;
* cancellation;
* timeouts;
* partial completion.

---

## 9. SOLID and Dependency Design

SOLID principles guide design but must not produce unnecessary abstraction.

### 9.1 Single Responsibility Principle

A module or class should have one cohesive reason to change.

This does not mean every function requires a separate file or class.

### 9.2 Open/Closed Principle

Stable contracts may support extension through adapters.

Do not create extension mechanisms before a second implementation or clear near-term requirement exists.

### 9.3 Liskov Substitution Principle

Implementations of a contract must preserve:

* expected inputs;
* outputs;
* errors;
* side effects;
* lifecycle or behavioural guarantees where applicable.

A test double must not behave so differently that it hides production failures.

### 9.4 Interface Segregation Principle

Prefer small, capability-focused Protocols.

Avoid large interfaces that force implementations to provide unrelated methods.

### 9.5 Dependency Inversion Principle

Application logic should depend on stable contracts rather than concrete external clients where this improves:

* testability;
* portability;
* boundary protection.

Example:

```python
class ObjectStore(Protocol):
    async def put(self, request: StoreObjectRequest) -> StoredObject:
        ...
```

Do not create a Protocol for a private helper function with one trivial implementation.

Do not create provider-neutral abstractions merely because one OpenAI wrapper exists. Prefer reuse of the existing OpenAI wrapper only when an approved design selects that integration path.

### 9.6 Dependency Injection

Prefer explicit constructor or function injection.

Avoid:

* service locators;
* mutable global dependencies;
* hidden singleton state;
* importing initialized clients throughout the codebase.

FastAPI dependency injection may be used at the API boundary.

Core application code should remain usable outside FastAPI.

---

## 10. FastAPI Standards

FastAPI is the approved application framework for BatchLens Extract.

### 10.1 Application Factory

The application should be created through:

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    ...
```

A module-level `app` may call the factory for Uvicorn compatibility.

### 10.2 Router Separation

Routers should be grouped by functional capability.

Do not place all endpoints in `main.py`.

### 10.3 Request and Response Models

Endpoints must use explicit request and response models.

Response schemas should not expose internal persistence structures directly.

### 10.4 Status Codes

Use HTTP status codes according to the operation outcome.

Do not return HTTP 200 for every failure.

Error mapping must remain consistent across endpoints.

### 10.5 Health and Readiness

Preserve the semantic requirement:

```text
Liveness ≠ Readiness
```

Preserve the existing health contract: `/health`, `/ready`, `/version`.

Do not rename working health endpoints merely to satisfy this document.

Liveness (`/health`) should not depend on external systems that may temporarily fail.

The current `/ready` endpoint reports **foundation readiness** (configured environment and version). It is not proof of document-processing or AWS dependency availability. When product dependencies are introduced, readiness must include only dependencies required for the application instance to serve its approved responsibility, and that change must be explicit.

### 10.6 Endpoint Responsibilities

Endpoints should:

* validate the transport contract;
* call an application use case;
* map the outcome;
* return a response.

Endpoints should not perform complete business workflows directly.

### 10.7 Lifespan Management

Use FastAPI lifespan management for resources requiring controlled startup and shutdown.

Examples include:

* connection pools;
* reusable HTTP clients;
* reusable provider clients;
* other long-lived resources requiring controlled lifecycle.

Do not initialize expensive or failure-prone resources during arbitrary module imports.

---

## 11. Configuration Standards

Configuration must be:

* environment-based;
* typed;
* validated;
* documented;
* safe to expose where appropriate;
* reproducible where reproducibility matters.

### 11.1 Environment Files

`.env.example` may contain:

* variable names;
* safe example values;
* comments.

It must not contain real secrets.

`.env` must not be committed.

### 11.2 Configuration Ownership

Each configuration value should have:

* one clear meaning;
* one owning component;
* an explicit default policy;
* validation when invalid values could create unsafe behaviour.

### 11.3 Configuration and Reproducibility

When outputs, runs, or results must be reproducible or auditable, preserve enough configuration, model, and version identity to explain how they were produced.

Runtime configuration changes must not silently rewrite the meaning of historical outputs where reproducibility matters.

Do not require persisted configuration snapshots for applications that have no such requirement.

### 11.4 Feature Flags

Do not add a feature flag unless:

* there is a concrete rollout or operational need;
* both behaviours are supported and tested;
* removal conditions are understood.

---

## 12. Error Handling Standards

### 12.1 Typed Errors

Use meaningful application or domain errors.

Representative categories include:

```text
InputValidationError
ConfigurationError
ConflictError
ExternalDependencyError
ExternalServiceUnavailableError
TimeoutError
AuthorizationError
ProcessingError
VerificationError
```

Exact error types remain project-specific.

### 12.2 Error Translation

External library errors should be translated at the infrastructure boundary into application-relevant errors.

Core application logic should not require knowledge of raw provider SDK, database-driver, or infrastructure-library exceptions.

### 12.3 Broad Exception Handling

Avoid:

```python
except Exception:
    return False
```

Broad exception handling is acceptable only at a controlled boundary where it:

* logs the original exception safely;
* converts it into an explicit failure outcome;
* does not hide programming errors;
* preserves diagnostic context.

### 12.4 Error Context

Errors should preserve safe context such as:

* entity identifier;
* operation / job / run identifier where applicable;
* stage;
* external operation;
* retryability;
* failure category.

They must not expose:

* credentials;
* tokens;
* connection strings;
* raw sensitive content;
* unnecessary infrastructure details.

### 12.5 Partial Failure

Partial failure behaviour must be explicitly defined.

The system must not assume that all multi-record operations are atomic.

For batch operations, record:

* attempted count;
* successful count;
* failed count;
* failed-item references where safe;
* recovery strategy.

---

## 13. Guardrail Standards

Guardrails exist at multiple layers.

### 13.1 Input Guardrails

When relevant, examples include:

* payload / file size;
* format;
* empty content;
* malformed metadata;
* unsupported values;
* query / input limits;
* prohibited patterns.

### 13.2 Contract Guardrails

Examples include:

* required identifiers;
* valid enum values;
* compatible configuration;
* schema constraints;
* provenance when required.

### 13.3 State-Transition Guardrails

Invalid or unsafe state transitions must be rejected before side effects occur.

Where the system has lifecycle or stateful workflows, prevent transitions that would leave the system inconsistent, unverifiable, or unauthorized.

### 13.4 External-Action Guardrails

Before consequential external writes to concerns such as:

* persistence;
* storage;
* search / index;
* queue / event system;
* external API;
* provider;

validate:

* required inputs;
* identity;
* authorization;
* idempotency;
* compatibility;
* intended target.

### 13.5 Output Guardrails

Structured outputs from parsers, model / LLM providers, or other external systems must be validated before they affect authoritative application state, where applicable.

### 13.6 Human Review and Automatic Delivery

Approved product mode includes **automatic unreviewed delivery**: when a usable result exists, return it with uncertainty/findings and an **explicit unreviewed** status. Human review must not universally prevent automatic draft delivery.

Human review may be required for:

* governance judgment or consequential approval actions;
* cases where the product policy explicitly gates an action on review;
* unsafe automatic reconciliation that would mutate authoritative state without evidence.

Missing evidence or uncertainty is not automatically a pass, a technical failure, or a mandatory human-review stop ([05_pipeline_contracts.md](05_pipeline_contracts.md)).

Invalid input, authorization failure, and unrecoverable technical failure still receive explicit handling.

Guardrails should prevent unsafe action, not merely produce warnings after the action occurs.

---

## 14. Logging and Observability Standards

### 14.1 Structured Logging

Application logs should be structured and machine-readable in production.

Each relevant log should include available context such as:

* timestamp;
* level;
* service;
* environment;
* request / correlation ID;
* operation ID;
* entity ID;
* job / run ID where applicable;
* stage / component;
* event name;
* safe error category.

### 14.2 Logger Names

Use the actual application / package namespace.

Example pattern:

```text
<application_package>
<application_package>.api
<application_package>.application
<application_package>.infrastructure
```

Do not retain stale template or old-project logger names.

### 14.3 Log Levels

Use levels consistently:

* `DEBUG` for diagnostic development detail;
* `INFO` for important normal operational events;
* `WARNING` for recoverable or non-blocking concerns;
* `ERROR` for failed operations;
* `CRITICAL` for severe application-level failure.

### 14.4 Sensitive Data

Logs must not contain:

* secrets;
* access tokens;
* passwords;
* complete connection strings;
* private keys;
* unrestricted protected content;
* raw personal data unless explicitly required and approved.

### 14.5 Logs vs Authoritative State

Logs are diagnostic records, not authoritative application state.

Where lifecycle, domain, or audit events exist, distinguish them explicitly from ordinary logs:

```text
Log
→ Technical diagnostic record

Lifecycle / audit event
→ Authoritative audit-relevant state change
```

Logs must not be the sole source of truth for authoritative state.

Do not require lifecycle-event infrastructure in projects that do not need it.

### 14.6 Measurements

Record relevant measurements such as:

* execution duration;
* stage duration;
* record counts;
* retry count;
* external-call latency;
* token or model cost where applicable.

Metrics must not replace authoritative entity records where such records exist.

---

## 15. Security Standards

### 15.1 Least Privilege

Application components should receive only the permissions required for their approved responsibility.

### 15.2 Secrets

Secrets must be provided through approved secret-management or runtime mechanisms.

Secrets must not be:

* committed;
* placed in source code;
* placed in Docker images;
* printed in logs;
* returned by APIs.

### 15.3 Input Trust

All external input is untrusted until validated.

This includes:

* uploaded files and source documents;
* metadata;
* HTTP headers;
* query parameters;
* environment configuration;
* external-service responses;
* model-generated output where used;
* OCR / extracted text derived from documents.

Source documents are untrusted data. Extracted text must **not** become instructions that override application policy or authorization.

Product-specific data handling, retention, provider flows, and UI security claims belong in [06_security_and_data_handling.md](06_security_and_data_handling.md). This section retains general secure-coding principles only.

### 15.4 Authorization

Permission checks must be enforced in application or service logic.

Hiding a UI button is not an authorization control.

### 15.5 Protected Data and Artifacts

Protected data and artifacts require:

* authorized access;
* controlled access;
* traceability where required;
* no unrestricted infrastructure access.

### 15.6 Dependency Security

Dependency changes should be reviewed for:

* necessity;
* maintenance status;
* known vulnerabilities;
* transitive impact;
* license suitability.

---

## 16. Testing Standards

Testing must focus on behaviour and risks, not only line coverage.

**Scope split:** code/unit/integration/contract tests belong here. Extraction accuracy, reviewer-effort measurement, and evaluation datasets belong in [07_extraction_evaluation.md](07_extraction_evaluation.md). Fake-model unit tests do not establish extraction accuracy.

### 16.1 Test Categories

#### Unit Tests

Used for:

* pure domain rules;
* validation;
* transformations;
* error classification;
* lifecycle or state transitions where applicable;
* deterministic helpers.

#### Integration Tests

Used for:

* persistence;
* storage adapters;
* external-provider / service adapters;
* external-service boundaries;
* migrations;
* transaction behaviour.

#### Contract Tests

Used for:

* API request and response schemas;
* adapter contracts;
* configuration contracts;
* published interface behaviour.

#### End-to-End Tests

Used selectively for critical vertical flows required by the actual product milestone or application.

An illustrative generic pattern:

```text
Entry request
→ Processing / orchestration
→ Persistence or external effect
→ Observable result
```

Do not imply that every project requires ingestion, indexing, or retrieval.

### 16.2 Test Independence

Tests must:

* be repeatable;
* avoid dependency on execution order;
* isolate state;
* avoid real production services;
* use deterministic fixtures where possible.

### 16.3 Failure-Path Tests

Each consequential capability must test relevant failures.

Examples include:

* invalid input;
* duplicate / idempotency issues where relevant;
* dependency failure;
* timeout;
* partial completion;
* authorization failure;
* invalid state transition where state exists;
* unavailable external dependency.

### 16.4 Mocking

Mock external boundaries, not internal implementation details.

Avoid tests that assert every private function call.

Prefer asserting:

* returned outcomes;
* state changes;
* emitted lifecycle or audit events where they exist;
* external contract interactions.

### 16.5 Test Doubles

Test doubles must preserve the semantics of the real contract.

An in-memory adapter must not silently accept invalid operations that production would reject.

### 16.6 Coverage

Coverage may be measured, but no single percentage proves correctness.

Critical rules and failure paths require explicit tests regardless of overall coverage.

---

## 17. Static Quality Gates

The standard local quality commands are:

```powershell
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest
```

Where formatting is intentionally performed:

```powershell
poetry run ruff format .
```

The project may provide PowerShell scripts that execute the same commands.

When a project introduces CI, that pipeline must execute the approved quality gates.

A milestone or work item cannot be marked complete when required quality checks fail.

---

## 18. Ruff Standards

Ruff is the standard linting and formatting tool.

The configuration should detect at least:

* syntax and style errors;
* unused imports;
* import ordering;
* common bug patterns;
* outdated Python constructs.

Rules should be tightened deliberately.

Do not ignore a rule globally only to bypass one local issue.

When an ignore is necessary:

* keep it narrow;
* document the reason where non-obvious;
* remove it when the underlying limitation no longer exists.

---

## 19. Pyright Standards

Pyright is the standard static type checker.

The preferred / target mode is:

```text
strict
```

New code must satisfy the repository's approved Pyright configuration.

If tightening an existing repository from `basic` to `strict` would create broad unrelated work, treat that migration as an explicit milestone or change, not opportunistic cleanup.

Do not weaken strict typing merely to make implementation easier.

New code must not introduce avoidable type errors.

Suppressions such as:

```python
# type: ignore
```

must:

* be narrow;
* identify the specific diagnostic where possible;
* have a valid documented reason.

Do not use casts or ignores merely to silence incorrect design.

---

## 20. Docker Standards

Docker is part of the approved BatchLens Extract packaging and local runtime path.

### 20.1 Image Design

Docker images should:

* use an approved Python 3.11 base;
* use multi-stage builds where valuable;
* avoid unnecessary build tools in runtime;
* run as a non-root user where practical;
* copy only required files;
* expose no secrets;
* support deterministic dependency installation.

### 20.2 Build Context

`.dockerignore` must exclude:

* virtual environments;
* Git metadata;
* caches;
* local environment files;
* test artifacts;
* unnecessary documentation or temporary files where appropriate.

### 20.3 Runtime Command

The runtime command must be explicit and suitable for the deployment model.

Development-only features such as `--reload` must not be used in production.

### 20.4 Health Checks

Docker or deployment health checks should use the appropriate application endpoint.

Liveness and readiness must not be confused.

### 20.5 Docker Compose

Docker Compose should contain only services required by the current approved local development capability.

Do not add services to Compose speculatively.

Do not retain unused services as speculative placeholders.

---

## 21. CI Standards

CI/CD is **project-dependent** and is not part of the current BatchLens Extract baseline.

When a project introduces CI, it should verify at least:

```text
Dependency installation
→ Ruff
→ Formatting check
→ Pyright
→ pytest
→ Docker build when Docker / container delivery is part of the active delivery path
```

Project CI, when present, should:

* run on relevant pull requests;
* run on protected integration branches where configured;
* fail on quality-gate failure;
* use dependency caching safely;
* prefer short-lived federated / OIDC cloud authentication over long-lived cloud credentials when cloud auth is required.

AWS is the **approved deployment direction** for BatchLens Extract (FastAPI, Docker, ECR, ECS/Fargate). Documentation-only and local quality work need **no** cloud deployment. Do not require AWS verification for milestones that do not touch deployment. Do not treat alternative clouds as required; do not contradict the approved AWS target when deployment work begins.

Do not require unrelated deployment verification for milestones that do not touch deployment.

Deployment must remain separate from general quality validation where practical.

---

## 22. Scripts and Developer Commands

Scripts must:

* fail fast;
* execute real commands;
* avoid commented placeholders presented as operational scripts;
* use consistent naming;
* return non-zero status on failure;
* be documented in the README.

Expected commands include:

```text
Development server
Lint
Format check
Type check
Tests
All quality checks
Docker build or Compose startup where part of active delivery
```

Scripts must not hide failing commands or continue after a quality failure.

---

## 23. Documentation Standards

Documentation should remain proportional to the responsibility.

### 23.1 Code Comments

Comments should explain:

* why a decision exists;
* why behaviour is non-obvious;
* important risk or invariant;
* external-system constraint.

Comments should not repeat obvious code.

### 23.2 Docstrings

Use docstrings for:

* public contracts;
* non-obvious services;
* important domain behaviour;
* modules with significant responsibility.

Do not require verbose docstrings for trivial private helpers.

### 23.3 Reference Separation

```text
00 Project Reference → product purpose, scope, boundaries
01 Roadmap → milestones and DoD
02 Code Quality → stable engineering standards
03 Handoff → current execution state
04 Code Map → implemented modules
05 Pipeline Contracts → pipeline semantics and open contract decisions
06 Security and Data Handling → product data protection and claim evidence
07 Extraction Evaluation → accuracy and reviewer-effort measurement
08 Check Selection → check prioritization; Extract vs Audit ownership
```

Prefer links and short summaries over copying whole sections. Read only task-relevant documents during Cursor work.

Do not make ADR mandatory.

### 23.4 Documentation Updates

Update documentation when implementation materially changes information owned by that document.

Do not update documentation mechanically when nothing relevant changed.

Documentation-only milestones require content/link/scope checks, not application tests or Docker rebuilds.

A milestone or work item is not complete when it changes project structure or behaviour but leaves relevant authoritative documentation stale.

---

## 24. Code Map Standards

`04_code_map.md` must be updated when implementation materially changes:

* modules;
* responsibilities;
* public contracts;
* dependency direction;
* important components.

Do not require a mechanical Code Map edit when none of these changed.

The Code Map should record:

* path;
* responsibility;
* public contracts;
* important dependencies;
* related milestone / work item;
* implementation status.

It must not duplicate source code.

---

## 25. Common Handoff Standards

`03_common_handoff.md` must be updated when meaningful execution-state information changes.

It should remain concise and current, using concepts such as:

* current milestone / work item;
* current status;
* completed relevant work;
* blockers;
* files materially changed;
* verification / evidence;
* known issues;
* immediate next action;
* Git status when relevant.

It must not contain:

* the full conversation;
* duplicated reference documents;
* a history diary;
* speculative future implementation detail;
* unresolved assumptions presented as decisions.

Do not duplicate the roadmap.

Do not require a handoff rewrite after a trivial change if no meaningful execution-state information changed.

---

## 26. AI-Assisted Engineering Standards

Cursor and other coding assistants are implementation tools, not architectural authorities.

### 26.1 Required Workflow

```text
Approved Scope / task-relevant references
→ Repository Inspection
→ Milestone / Work-Item Plan (when needed)
→ Implementation Within Approved Scope
→ Validation Against Milestone Definition of Done
→ Evidence
→ Code Map / Handoff Update When Relevant
```

Planning depth must be proportional to complexity.

**Read only task-relevant documents.** Do not require rereading all nine `.ai/` files for every small edit. Use [03](03_common_handoff.md) plus the owning docs for the change.

For substantial, cross-boundary, or architecture-affecting work, plan before implementation. For small already-approved changes, do not create artificial approval ceremonies.

### 26.2 Cursor Planning

For meaningful work, Cursor must:

* inspect the actual repository;
* summarize current relevant code;
* identify affected files;
* identify reusable assets;
* identify contracts and boundaries;
* propose ordered implementation steps;
* define tests / validation;
* identify risks;
* identify conflicts with canonical references.

STOP only when:

* required information is genuinely unavailable;
* implementation conflicts materially with the canonical architecture;
* required work would touch forbidden or out-of-scope files;
* an unresolved decision blocks safe implementation.

Otherwise proceed within the approved milestone or work item.

### 26.3 Scope Control

Cursor must not:

* implement unrelated improvements;
* refactor unrelated modules;
* introduce speculative frameworks;
* add unapproved dependencies;
* change architecture silently;
* modify references to justify implementation choices;
* mark work complete without evidence.

### 26.4 Reviewability

AI-generated changes must remain small enough to review.

Large uncontrolled patches should be divided before approval.

### 26.5 Verification

Claims such as:

```text
Tests pass
Typing passes
Docker builds
```

must be supported by actual command output.

Generated code is not accepted solely because it appears reasonable.

---

## 27. Git and Change Standards

### 27.1 Focused Changes

Each milestone or work item should produce focused changes aligned with its approved scope.

Avoid mixing:

* feature implementation;
* unrelated refactoring;
* dependency upgrades;
* documentation cleanup;
* formatting of unrelated files.

### 27.2 Commits

Commits should:

* represent coherent work;
* use clear messages;
* avoid secrets;
* include required documentation changes when those documents are materially affected.

### 27.3 Generated and Local Files

Do not commit:

* `.venv`;
* caches;
* local `.env`;
* temporary artifacts;
* local test output;
* IDE-specific state unless intentionally standardized.

### 27.4 Dependency Lock

When dependencies change:

```text
pyproject.toml
+
poetry.lock
```

must remain consistent.

---

## 28. Code Review Checklist

Each implementation review should verify:

### Scope

* Does the change implement only the approved milestone / work item?
* Are unrelated changes absent or justified?

### Architecture

* Are dependencies flowing in the approved direction?
* Are external systems isolated appropriately?
* Has unnecessary abstraction been avoided?

### Correctness

* Are lifecycle invariants preserved when lifecycle / state exists?
* Are edge cases and failure paths handled?
* Is historical state preserved when historical / reproducibility requirements exist?

### Validation and Guardrails

* Is untrusted input validated?
* Are unsafe state transitions prevented where state exists?
* Are external outputs validated where applicable?

### Typing and Contracts

* Are public contracts typed?
* Are Pydantic models used at appropriate boundaries?
* Are broad dictionaries and `Any` avoided?

### Async

* Is async used for real I/O concurrency?
* Is blocking I/O kept out of the event loop?

### Errors

* Are errors explicit and classified?
* Are safe details preserved?
* Are secrets and sensitive data protected?

### Tests

* Are normal, edge, and failure cases tested?
* Do tests verify behaviour rather than implementation trivia?

### Observability

* Are important operations traceable?
* Are logs structured and safe?
* Are identifiers and stage / component context included where needed?

### Documentation

* Is the Code Map updated when materially affected?
* Is the Common Handoff updated when relevant?
* Are canonical references and the roadmap still accurate where affected?

---

## 29. Exceptions and Architectural Decisions

A standard may be intentionally violated only when:

* the current requirement justifies it;
* the risk is understood;
* the exception is documented;
* the relevant review approves it.

Material exceptions must be documented in the appropriate authoritative location, such as:

* the canonical project reference;
* the relevant roadmap milestone / work item;
* a Code Quality Standards exception note where appropriate;
* an ADR only when the project intentionally uses ADRs.

Temporary exceptions must include a clear removal condition.

---

## 30. Project-Wide Quality Gates

A milestone or work item may be considered technically complete only when applicable checks pass:

```text
Poetry dependency installation succeeds when dependencies are involved
Ruff lint passes
Ruff formatting check passes
Pyright passes
pytest passes
Docker build passes when Docker is part of active delivery / affected scope
Required integration tests pass
Required contract tests pass
No secrets are committed
No unrelated code changes remain
Code Map is updated when relevant
Common Handoff is updated when relevant
Milestone Definition of Done is verified
```

Not every milestone requires every infrastructure integration test.

The relevant milestone / work-item Definition of Done must state which applicable gates are required.

---

## 31. Core Code Quality Rules

1. Implement only approved scope.
2. Prefer correctness and clarity over abstraction.
3. Use Python 3.11-compatible typed code.
4. Use Pydantic v2 at validation and serialization boundaries.
5. Preserve explicit dependency direction.
6. Use Protocols only for meaningful boundaries.
7. Use async for I/O-bound concurrency, not by default.
8. Keep pure application / domain logic independent from frameworks and infrastructure where appropriate.
9. Validate external input and external output.
10. Preserve lifecycle invariants and historical traceability when such requirements exist.
11. Translate external errors into safe application errors.
12. Do not hide failures or rely on logs as authoritative state.
13. Use structured, safe, contextual logging.
14. Test normal behaviour, edge cases, and failure paths.
15. Enforce Ruff, Pyright, and pytest as quality gates locally and in any project-defined CI; enforce Docker build when container delivery is part of the active path.
16. Do not introduce speculative dependencies or services.
17. Keep AI-generated changes focused and reviewable.
18. Update the Code Map and Common Handoff when the implementation materially affects the information they own.
19. Record justified exceptions explicitly.
20. A milestone / work item is complete only when its applicable measurable Definition of Done passes.
21. Reuse existing production-grade assets before replacing or rebuilding them when they fit an approved need. The OpenAI LLM wrapper may be reused only when the approved extraction/integration design selects it; its presence alone does not mandate OpenAI.

The resulting engineering model is:

```text
Clear Contracts
→ Controlled Dependencies
→ Validated Behaviour
→ Safe Failure Handling
→ Testable Implementation
→ Observable Operation
→ Reviewable Change
→ Production Discipline
```

---

## 32. Standards vs Current Compliance

Stable standards describe desired engineering behaviour. They are **not** proof that every current module already implements every future control.

In particular:

* Documented desired errors, retries, tracing, or lifecycle behaviour do **not** prove the optional OpenAI wrapper implements them fully.
* Those standards must **not** trigger wrapper hardening during documentation tasks (D2). Wrapper hardening remains deferred until extraction integration is designed ([01](01_implementation_roadmap.md)).
* Product security requirements in [06](06_security_and_data_handling.md) are not current implementation claims unless the evidence register says so.
* Pipeline lifecycle meanings in [05](05_pipeline_contracts.md) remain approved semantics for **extraction** design. Conversion job phases and document-review revision/approval state machines **are** implemented in code; they are not production-qualified and are not pharmaceutical-extraction lifecycle.
* A future append-only audit ledger is recorded as direction only. Structured stdout logs are not that ledger.
