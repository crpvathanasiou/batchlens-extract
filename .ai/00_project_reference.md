# Full Project Reference Template

## Template Usage

This document defines a comprehensive project reference for a software, data, or AI engineering project.

Populate it by replacing HTML guidance comments with project-specific facts, approved decisions, explicit constraints, or clearly identified assumptions. Guidance comments may remain during drafting; they must not be treated as project answers.

Sections that genuinely do not apply may be marked `NOT APPLICABLE` with a short reason. Optional capability sections must not force architecture or technology into a project.

Only facts, approved decisions, explicit constraints, or clearly identified assumptions should populate the final project reference. Unknown information must remain explicitly unknown rather than guessed.

When recording architectural or capability state, distinguish:

```text
CURRENT / IMPLEMENTED
APPROVED TARGET
DEFERRED / OPTIONAL
UNKNOWN / OPEN
```

Do not describe future or proposed architecture as already implemented.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Project Goals](#3-project-goals)
4. [Non-Goals](#4-non-goals)
5. [Target Users and Roles](#5-target-users-and-roles)
6. [MVP / Initial Delivery Scope](#6-mvp--initial-delivery-scope)
7. [Functional Areas](#7-functional-areas)
8. [Core Use Cases](#8-core-use-cases)
9. [System Context](#9-system-context)
10. [Logical Components](#10-logical-components)
11. [Core Domain Entities / Data Objects](#11-core-domain-entities--data-objects)
12. [Core Entity / Data Lifecycle](#12-core-entity--data-lifecycle)
13. [Request / Processing / Query Lifecycle](#13-request--processing--query-lifecycle)
14. [Evaluation / Quality Model](#14-evaluation--quality-model)
15. [Data and Artifact Ownership](#15-data-and-artifact-ownership)
16. [Configuration Boundary](#16-configuration-boundary)
17. [Security, Privacy and Compliance Requirements](#17-security-privacy-and-compliance-requirements)
18. [Observability and Auditability](#18-observability-and-auditability)
19. [Failure, Retry and Idempotency Principles](#19-failure-retry-and-idempotency-principles)
20. [Deployment Direction](#20-deployment-direction)
21. [Open Technical Decisions](#21-open-technical-decisions)
22. [Project-Level Success Criteria](#22-project-level-success-criteria)

- [Appendix A — Population Checklist](#appendix-a--population-checklist)
- [Appendix B — Status Vocabulary](#appendix-b--status-vocabulary)

# 1. Executive Summary

<!--
Describe:
- the business or technical problem in one short paragraph;
- the intended users;
- the primary value delivered by the first meaningful release;
- the high-level system boundary;
- the expected first meaningful outcome.

Do not invent technology choices here. Record only approved direction or leave UNKNOWN.
-->

## 1.1 Primary Functional Areas

<!--
Define the project's primary functional areas and their ordered relationship.

Example pattern (adapt or replace; do not force this split):
Input / Ingest
→ State / Monitoring / Visibility
→ Query / Processing / Evaluation / Serving

Record:
- area names;
- one-sentence purpose of each;
- whether areas are workflow boundaries, deployment boundaries, or both.
-->

## 1.2 End-to-End Outcome

<!--
State the shortest end-to-end outcome the project must prove.

Use a lifecycle-style description appropriate to the domain, for example:
input accepted → validated → persisted → processed → observable → queryable/usable → evaluated (if applicable).

Do not assume documents, embeddings, indexing, or RAG exist.
-->

## 1.3 Initial Product Boundary

<!--
Define what the first release is and is not.

Include:
- capabilities that must be demonstrable;
- capabilities explicitly deferred;
- whether generative AI / LLM answers are in or out of the first release;
- the primary value of the first release (reliability, measurability, automation, analytics, etc.).
-->

## 1.4 Technical Direction (Approved or Provisional)

<!--
Record only approved or explicitly provisional technical direction.

For each item, mark status:
CURRENT / APPROVED TARGET / PROVISIONAL / UNKNOWN / DEFERRED

Typical categories (include only those that apply):
- language(s) and runtime;
- application framework / API style;
- packaging and dependency management;
- containerization;
- primary storage / database;
- search / analytics / serving stores;
- compute / hosting model;
- infrastructure-as-code approach;
- CI/CD baseline.

Do not invent a stack. Optional examples of managed services (e.g. object storage, container registry, managed search, secrets manager) may be listed only after approval.
-->

## 1.5 Configuration Philosophy

<!--
Define where the project must be configurable vs where behaviour must remain in code.

Record:
- parameters expected to change during experimentation or environment setup;
- what must not become a plugin framework prematurely;
- whether configuration snapshots are required for reproducibility.
-->

## 1.6 Delivery Constraints and Mandatory Requirements

<!--
Capture hard constraints that shape architecture and scope. Especially important for short engineering assignments.

Define:
- delivery deadline or timebox;
- mandatory technology stack (only if externally required);
- explicitly required services, frameworks, or libraries;
- forbidden or unavailable technologies;
- provided datasets, files, APIs, or credentials boundaries;
- environment or deployment restrictions;
- required deliverables (code, docs, demo, tests, IaC, etc.);
- evaluation or demo expectations;
- hard non-functional constraints (latency, cost ceiling, offline operation, data residency, etc.).

Do not populate with assumptions. Mark UNKNOWN where not known.
Leave blank subsections that do not apply, or mark NOT APPLICABLE with reason.
-->

### Delivery Timebox

<!-- Deadline, milestone dates, or assignment duration. -->

### Mandatory Stack / Services

<!-- Required languages, frameworks, cloud providers, or services if any. -->

### Forbidden / Unavailable Technologies

<!-- Explicit exclusions. -->

### Provided Inputs

<!-- Datasets, files, APIs, accounts, seed content. -->

### Environment / Deployment Restrictions

<!-- Local-only, specific cloud account, no internet at runtime, etc. -->

### Required Deliverables

<!-- What must be handed over. -->

### Evaluation / Demo Expectations

<!-- How success will be judged in a demo or review. -->

### Hard Non-Functional Constraints

<!-- Latency, cost, security, residency, availability, offline, etc. -->

---

# 2. Problem Statement

<!--
Describe the real problem the project exists to solve.

Focus on:
- who experiences the problem;
- what fails today;
- why naive solutions are insufficient;
- what “wrong but plausible” outcomes look like;
- what must be true for the problem to be considered addressed.

Avoid solution-first framing.
-->

## 2.1 Core User / Business Pain

<!--
What is difficult, costly, risky, or unreliable for the intended users today?
-->

## 2.2 Correctness and Validity Risks

<!--
Where can the system return something that looks right but is wrong?

Consider versioning, stale data, incomplete processing, mis-ranked results, wrong entity identity, silent truncation, or unvalidated outputs.
-->

## 2.3 Traceability Gaps

<!--
What provenance chain is missing today?

Define what every important result or artifact must be traceable to (source input, configuration, processing run, actor, timestamp, etc.).
-->

## 2.4 Uncontrolled Processing or Workflow Risk

<!--
Which stages can fail silently, partially succeed, or produce unreproducible outputs today?
-->

## 2.5 Visibility and Operability Gaps

<!--
What can operators or users not currently determine about system state, data readiness, failures, or configuration?
-->

## 2.6 Quality / Evaluation Gaps

<!--
OPTIONAL for projects with measurable quality.

Is quality judged subjectively today? What objective comparison is missing?
If no evaluation model applies, mark NOT APPLICABLE.
-->

## 2.7 Configuration and Experiment Comparison Gaps

<!--
Are changes hard to compare because configuration is not versioned, snapshotted, or linked to runs?
Mark NOT APPLICABLE if experimentation is not in scope.
-->

## 2.8 Source-of-Truth Confusion Risks

<!--
Which stores or indexes risk being treated as canonical when they should be derived or rebuildable?
-->

## 2.9 Premature Solution Dependence

<!--
What advanced capability (e.g. final generative answers, multi-agent orchestration, full DMS features) would hide unfinished foundations if adopted too early?
-->

## 2.10 Core Problem to Be Solved

<!--
Condense into one clear problem statement the project must solve.

Distinguish technical success from domain correctness where relevant.
-->

---

# 3. Project Goals

<!--
The goal subsections below form a coverage checklist, not a mandatory capability list.

Populate only goals justified by the actual project requirements.

Mark irrelevant goals NOT APPLICABLE or leave them unused as appropriate.

Do not introduce architecture, infrastructure, workflows, or capabilities merely to satisfy this template.

List project goals that are outcomes, not implementation details.

For each goal, define:
- outcome;
- who benefits;
- how it will be verified;
- whether it is MVP-required or foundation-for-later.

Prefer goals that map to functional areas and cross-cutting qualities
(traceability, reproducibility, observability, security, reliability).
-->

## 3.1 End-to-End Lifecycle Goal

<!-- Establish a controlled end-to-end lifecycle for the primary entity or workflow. -->

## 3.2 Canonical Input / Source Preservation Goal

<!-- Preserve authoritative inputs independently of derived or serving representations, if applicable. -->

## 3.3 Controlled Ingestion / Intake Goal

<!-- Support controlled intake with validation, identity, and explicit failure. -->

## 3.4 Traceability Goal

<!-- Maintain identity and provenance across entities, runs, and outputs. -->

## 3.5 Monitoring / Visibility Goal

<!-- Provide application-level visibility into state, history, and readiness. -->

## 3.6 Governance / State Control Goal

<!-- Support explicit lifecycle or governance states where the domain requires them. -->

## 3.7 Usable / Inspectable Outputs Goal

<!-- Produce outputs that can be inspected with enough context for human judgment. -->

## 3.8 Experimentation / Configurability Goal

<!-- OPTIONAL: support controlled experiments where parameters genuinely need to vary. -->

## 3.9 Query / Request Testing Goal

<!-- OPTIONAL: support interactive testing of the primary user-facing operation. -->

## 3.10 Processing / Retrieval Mode Goal

<!--
OPTIONAL: define required processing or retrieval modes for this project.

Examples that apply only when relevant:
- synchronous API processing;
- asynchronous jobs;
- analytical query;
- lexical / vector / hybrid retrieval.

Do not mandate retrieval architecture.
-->

## 3.11 Objective Quality Measurement Goal

<!-- OPTIONAL: measure quality objectively where evaluation is in scope. -->

## 3.12 Reproducibility Goal

<!-- Ensure important runs can be reproduced or compared using recorded configuration and inputs. -->

## 3.13 Safe Reprocessing / Replay Goal

<!-- OPTIONAL: support safe reprocessing, rebuild, or replay without corrupting canonical data. -->

## 3.14 Failure and Retry Clarity Goal

<!-- Establish explicit failure categories and retry behaviour where needed. -->

## 3.15 Operational Observability Goal

<!-- Provide structured logs, correlation, health/readiness, and actionable failure visibility. -->

## 3.16 Security-by-Default Goal

<!-- Apply least privilege, secrets hygiene, input validation, and safe defaults from the start. -->

## 3.17 Focused Scope Goal

<!-- Keep the first release focused on proving the core lifecycle rather than becoming a generic platform. -->

## 3.18 Foundation for Future Capabilities Goal

<!--
OPTIONAL: state which later capabilities the architecture should not block,
without pulling them into MVP scope.
-->

## 3.19 Project Goal Summary

<!--
Summarize the goal set as a short ordered chain from intake to value delivery.
Mark each summary item MVP-required vs later foundation.
-->

---

# 4. Non-Goals

<!--
Record what the project is explicitly not building.

Non-goals are as important as goals for scope control.

For each non-goal:
- state the exclusion;
- give a short reason (why not now);
- note whether it is permanently out or deferred.

Do not invent a long list of irrelevant exclusions. Include only exclusions that protect this project's scope.
-->

## 4.1 Scope-Control Principle

<!--
Define the rule that gates new work, for example:
A capability enters the initial delivery only when it is necessary to prove or protect the end-to-end lifecycle / primary outcome.
-->

## 4.2 Explicit Non-Goals

<!--
Use one subsection per non-goal, or a structured list:

Non-Goal:
Reason:
Status: DEFERRED | OUT OF SCOPE | REJECTED

Common categories to consider (include only if relevant):
- generic multi-domain platform;
- plugin framework / premature abstraction;
- autonomous decision-making beyond system authority;
- full conversational assistant;
- multi-agent orchestration;
- full document/content management system;
- general-purpose search engine;
- formats or modalities not required for first release;
- automatic crawling / sync from external sources;
- automatic trust or authority determination;
- mandatory advanced ML features on day one;
- model fine-tuning;
- multi-cloud / cloud-agnostic infrastructure (unless required);
- arbitrary datastore interchangeability;
- production-scale multi-tenancy;
- complete enterprise IAM;
- replacing provider-native infrastructure monitoring;
- premature microservice decomposition;
- premature introduction of optional infrastructure components;
- optimization for unproven scale;
- claiming certification or legal/compliance approval the system cannot provide.
-->

---

# 5. Target Users and Roles

<!--
Identify primary and secondary actors.

For each role, define:
- purpose;
- primary responsibilities;
- questions this role must be able to answer;
- expected technical / domain knowledge;
- limitations / non-authority;
- whether the role is in MVP or future.

Preserve the distinction:
Technical operator authority ≠ domain approval authority
Application monitoring ≠ infrastructure monitoring
-->

## 5.1 Role Template

<!--
Repeat this structure for each role.

### Role Name

Status: CURRENT MVP | FUTURE | INFORMATIONAL ONLY

#### Primary Responsibilities
-

#### Questions This Role Must Be Able to Answer
-

#### Expected Knowledge
-

#### Role Limitations
-
-->

## 5.2 Initial MVP Role Simplification

<!--
If full RBAC is deferred, define the practical MVP access levels
(e.g. Technical Operator, Query/Read User) and which richer roles they temporarily combine.
-->

## 5.3 High-Level Capability Matrix

<!--
Create a matrix of roles vs capabilities such as:
intake, monitor, mutate governance/state, query/use, evaluate, administer, audit/read-only.

Mark: Allowed / Denied / Deferred.
-->

## 5.4 Role and Permission Design Principles

### Least Privilege

<!-- Users and components receive only the permissions required for their role. -->

### Separation of Technical and Domain Authority

<!--
Technical ability to ingest, process, or index does not automatically grant authority
to classify content as active, official, approved, or authoritative.
-->

### Read and Write Separation

<!-- Prefer distinct read vs write / mutate capabilities where useful. -->

### Traceable Administrative Actions

<!-- Privileged actions that change state, governance, or configuration should be auditable. -->

### Progressive Security Implementation

<!--
MVP may start with simplified access controls if explicitly accepted,
but must not block later hardening or rely on UI-only enforcement.
-->

## 5.5 Primary User Priority for the First Release

<!-- Who is the primary first-release user and why? -->

---

# 6. MVP / Initial Delivery Scope

<!--
Define the Minimum Viable Product or first delivery as a vertical slice that proves the core lifecycle,
not a checklist of disconnected components.

MVP Objective pattern:
prove that a primary input/entity can move through the complete required lifecycle to a measurable or demonstrable outcome.
-->

## 6.1 MVP Objective

<!-- One paragraph + short lifecycle chain. Prioritize correctness, traceability, reproducibility, observability, and controlled scope as applicable. -->

## 6.2 Primary MVP User

<!-- Who completes the end-to-end workflow, and what is that workflow? -->

## 6.3 Supported Inputs / Formats / Modalities

<!--
List first-release supported inputs and explicit exclusions.
Unsupported inputs must be rejected explicitly rather than partially processed.
Mark NOT APPLICABLE if no format matrix applies.
-->

## 6.4 Intake / Ingest Scope

<!--
OPTIONAL.

Use this section only when the project has an explicit intake, ingestion, upload, import, source-acquisition, or equivalent input-processing capability.

Do not create an ingestion subsystem merely because this section exists.

If no such capability exists, mark this section NOT APPLICABLE.

Define required intake stages for this project.

OPTIONAL example stage categories (include only if applicable; not a mandatory pipeline):
receive → validate → persist → transform → derive → publish / serve → verify

Expanded illustrative variants of the same idea (still optional; include only applicable stages):
receive → validate → store canonical input → identify entity/version → handle duplicates
→ transform/parse/normalize → enrich metadata → derive representations
→ index/serve/publish → verify readiness

For each included stage, define:
- required behaviour;
- failure behaviour;
- minimum recorded identifiers/metadata.
-->

### 6.4.1 Receive / Upload / Intake

### 6.4.2 Validation

### 6.4.3 Canonical Storage / Persistence of Inputs

### 6.4.4 Identity and Versioning

### 6.4.5 Duplicate Handling

### 6.4.6 Transformation / Parsing / Normalization

<!-- OPTIONAL depending on domain. -->

### 6.4.7 Metadata Handling

### 6.4.8 Derived Representation Generation

<!--
OPTIONAL. Examples: chunks, features, aggregates, compiled artifacts, embeddings.
If semantic/vector representations are part of the project, define model/provider, dimensionality,
similarity strategy, pinning, and compatibility requirements.
If not part of the project, mark NOT APPLICABLE.
-->

### 6.4.9 Indexing / Publishing / Serving Preparation

<!-- OPTIONAL. -->

### 6.4.10 Processing Verification

<!-- Content must not be marked available before required verification succeeds, where applicable. -->

## 6.5 Monitoring / Visibility Scope

<!--
Define what operators must be able to see about:
entities, versions, runs, failures, configuration, governance/state, serving targets.

Clarify that application/knowledge-lifecycle monitoring does not replace infrastructure monitoring.
-->

## 6.6 Query / Request / Serving Scope

<!--
Define the primary user-facing operation for the first release.

May be:
- API request processing;
- SQL/analytical query;
- retrieval query;
- ML inference;
- asynchronous job submission/status;
- hybrid operation.

Define:
- inputs and validation;
- filters/parameters;
- result contract;
- provenance/inspection requirements;
- distinct outcomes for no-result vs failure vs weak/partial result where relevant.
-->

## 6.7 Evaluation / Quality Scope

<!--
OPTIONAL chapter usage for first release.
If evaluation is in scope, define dataset, metrics, run records, and baseline comparison.
If not, mark NOT APPLICABLE.
Retrieval metrics such as Precision@K, Recall@K, nDCG@K are examples for search/retrieval projects only.
-->

## 6.8 Configuration Scope

<!-- List first-release configurable parameters by category. Secrets are not ordinary configuration. -->

## 6.9 Deployment Scope

<!--
Define first-release deployment expectations without assuming a cloud provider.
Include container/runtime, environments, IaC expectations if required by constraints.
-->

## 6.10 User Interface Scope

<!--
Define minimum UI/API surfaces.
UI technology choice is not necessarily an architectural commitment.
-->

## 6.11 Operational Scope

<!-- Logging, health/readiness, config validation, non-root containers, basic alerting expectations, etc. -->

## 6.12 Testing Scope

<!-- Critical workflows that must have automated tests in the first release. -->

## 6.13 Explicitly Deferred From the MVP

<!-- Group deferred items: content/modalities, AI features, platform abstractions, enterprise concerns. -->

## 6.14 MVP End-to-End Scenario

<!-- Numbered scenario an authorized user can execute to prove the vertical slice. -->

## 6.15 MVP Completion Boundary

<!-- Boolean gates that must all be true for MVP completion. -->

## 6.16 MVP Scope Principle

<!--
A capability enters the MVP only when necessary to prove or protect the end-to-end lifecycle / primary outcome.
-->

---

# 7. Functional Areas

<!--
Define workflow and responsibility boundaries.

Functional areas do not necessarily imply microservices.
Initial implementation may be a modular monolith with clear module boundaries.
-->

## 7.1 Area Definitions

<!--
For each functional area, define:
- purpose;
- responsibilities;
- explicit non-responsibilities;
- primary inputs;
- primary outputs;
- failure ownership;
- whether detailed requirements live in a separate reference doc (optional).
-->

## 7.2 Shared Responsibilities

<!--
Cross-cutting capabilities implemented consistently without merging area ownership, for example:
configuration validation, identifiers/contracts, structured logging, security, error handling,
auditability, configuration traceability, testing.
-->

## 7.3 Functional Boundary Principle

<!--
Each area should have clear inputs, outputs, responsibilities, and failure states.
A component belongs to the area that owns its primary business responsibility.
Cross-area dependencies should use explicit contracts rather than internal implementation access.
-->

---

# 8. Core Use Cases

<!--
Define main user-visible capabilities as outcomes, not implementation steps.

Do not invent hypothetical use cases. Record only use cases that actually belong to this project.

Use Case fields:
- Use Case ID
- Name
- Primary Actor
- Trigger
- Preconditions
- Primary Flow
- Expected Result
- Important Failure / Alternative Paths
- Relevant Contracts
-->

## 8.1 Use Case Template

### UC-XX — Name

**Use Case ID:**

**Name:**

**Primary Actor:**

**Trigger:**

**Preconditions:**

**Primary Flow:**

<!-- Numbered steps. -->

**Expected Result:**

**Important Failure / Alternative Paths:**

**Relevant Contracts:**

## 8.2 Use-Case Inventory

<!-- List UC IDs and names that are in scope for the initial release. Leave empty until known. -->

## 8.3 Core Use-Case Boundary

<!-- Summarize the outcome chain the use cases must reinforce, and what remains outside initial scope. -->

---

# 9. System Context

<!--
Define what sits inside vs outside the application boundary.

Do not assume a specific cloud provider, search engine, database, or model vendor.
-->

## 9.1 High-Level Context

<!--
Diagram or textual context map:
Users / Actors
→ Application
→ External dependencies (storage, compute, models, identity, queues, etc.)
-->

## 9.2 Primary Actors

<!-- Human and system actors that interact with the application. -->

## 9.3 Application Boundary

<!-- Capabilities owned by the application. -->

## 9.4 External Dependencies

<!--
For each dependency, define:
- purpose;
- what it owns;
- what it must not own;
- whether it is CURRENT / TARGET / DEFERRED / UNKNOWN.

Example dependency categories (include only if needed):
artifact/object storage; relational/operational state store; search/serving index;
cache; queue; embedding/model service; identity provider; UI hosting; observability backend.
-->

## 9.5 Infrastructure Monitoring Boundary

<!--
Clarify that application lifecycle monitoring does not replace provider/platform infrastructure monitoring.
-->

## 9.6 Initial Deployment Context

<!-- High-level runtime topology without inventing services. -->

## 9.7 Trust Boundaries

<!--
Where validation, authentication, authorization, and logging are required when crossing boundaries.
-->

## 9.8 Context Boundary Principle

<!--
The application owns its domain lifecycle and contracts.
It does not become the authority for external legal/domain judgment unless explicitly in scope.
Retrieved or computed outputs are evidence/results for interpretation according to project rules.
-->

---

# 10. Logical Components

<!--
Describe logical components, not necessarily deployment units.

Do not invent future components. Define only components that this project needs.

For each component, use:
- Purpose
- Responsibilities
- Explicit non-responsibilities
- Inputs
- Outputs
- Dependencies
- Ownership / boundary
- Failure behaviour (brief)
-->

## 10.1 Component Description Template

### Component Name

**Purpose:**

**Responsibilities:**

**Explicit Non-Responsibilities:**

**Inputs:**

**Outputs:**

**Dependencies:**

**Ownership / Boundary:**

**Failure Behaviour:**

**Status:** CURRENT / TARGET / DEFERRED / UNKNOWN

## 10.2 Component Inventory

<!--
List components actually required. Typical categories to consider (not mandatory):
UI, API, intake/validation, registry/identity, artifact storage adapter,
processing orchestrator, transformers, metadata, derivation/indexing/publishing,
query/request processing, result assembly, evaluation, configuration,
operational state, observability, shared contracts.
-->

## 10.3 Shared Contracts

<!--
Name the explicit contracts that cross component boundaries
(identifiers, DTOs/schemas, error model, configuration snapshot references, etc.).
-->

## 10.4 Initial Deployment Mapping

<!--
Map approved logical components to the runtime or deployment units defined by the project architecture.

Logical components do not imply separate deployment units or microservices.
-->

## 10.5 Logical Component Principle

<!--
One clear responsibility per component; testable contracts;
minimal infrastructure knowledge outside the owning boundary;
UI must not bypass application contracts to reach storage directly.
-->

---

# 11. Core Domain Entities / Data Objects

<!--
Define the project's core entities / data objects.

Do not retain unrelated domain entities as mandatory.
Do not invent entities.

For each entity, define:
- Purpose
- Identity
- Important fields
- Ownership
- Lifecycle
- Relationships
- Persistence / source of truth
- Versioning if applicable
- Invariants
-->

## 11.1 Entity Relationship Overview

<!-- Describe the entity graph at a conceptual level. -->

## 11.2 Entity Description Template

### Entity Name

**Purpose:**

**Identity:**

<!-- Stable application identity. Avoid filenames, row IDs, or index-internal IDs as sole identity. -->

**Important Fields:**

**Ownership:**

**Lifecycle:**

**Relationships:**

**Persistence / Source of Truth:**

**Versioning:**

**Invariants:**

**Status:** CURRENT MVP ENTITY / FUTURE / UNKNOWN

## 11.3 Entity Inventory

<!-- List entities that actually exist for this project. Leave empty until known. -->

## 11.4 Entity Identity Principles

<!--
Define identity rules, for example:
- stable IDs independent of storage paths;
- distinguish source identity vs processing execution vs serving representation vs evaluation execution;
- do not overload one ID for multiple concepts.
-->

## 11.5 Entity Versioning Principles

<!--
Separate version concepts that must not be merged, for example:
source/content version, processing/config version, serving/index version,
dataset version, application version.
-->

## 11.6 Canonical and Derived Entity Boundary

<!-- Classify entities as canonical/authoritative vs derived/rebuildable vs serving copies. -->

## 11.7 Initial MVP Entity Set

<!-- Minimum persistent set required to prove the lifecycle. -->

## 11.8 Domain Entity Principle

<!--
Entities are conceptual first; physical schemas follow after query and consistency requirements are known.
Preserve distinctions that protect traceability and regeneration.
-->

---

# 12. Core Entity / Data Lifecycle

<!--
Define the lifecycle of whichever primary entity/entities matter for this project.

Examples of primary entities (choose what applies; do not assume):
document, dataset, transaction, job, order, model execution, request, artifact.

Do not assume documents, embeddings, chunking, or indexing exist.

Preserve useful lifecycle concepts:
creation, validation, state transitions, processing, retries, failure, cancellation,
supersession/versioning, deletion, monitoring, auditability, lifecycle invariants.
-->

## 12.1 Lifecycle Overview

<!--
If useful, separate interacting lifecycles, for example:
Source / Input lifecycle
Processing lifecycle
Serving / Publishing lifecycle
Governance / Business-state lifecycle

Record how they interact and which states are independent.
-->

## 12.2 Creation

<!-- When and how the primary entity is created; required identity and metadata. -->

## 12.3 Validation

<!-- Entry criteria, rejection behaviour, what must not proceed. -->

## 12.4 Input / Source Persistence

<!--
OPTIONAL.

Define whether persistence of the original input/source is required by this project.

If inputs/sources are persisted, define:
- authoritative location;
- ownership;
- retention;
- identity/version relationship where applicable;
- relationship to derived or serving representations;
- independence of canonical inputs from derived stores where that distinction applies.

If the project intentionally does not persist the original input/source, mark this section NOT APPLICABLE.

Do not introduce persistence merely because this section exists.
-->

## 12.5 State Model

<!--
Define states and legal transitions.
Distinguish technical readiness states from business/governance states if both exist.
-->

## 12.6 Processing / Transformation

<!-- Stages, entry/exit criteria, what constitutes stage success. -->

## 12.7 Verification and Availability

<!-- When an entity becomes available for normal use/query/serving. -->

## 12.8 Versioning and Supersession

<!-- When a new version is required vs when reprocessing the same version is correct. -->

## 12.9 Reprocessing / Rebuild / Replay

<!--
Safe patterns for reprocessing or rebuilding derived representations
without modifying canonical inputs or inventing false source versions.
-->

## 12.10 Retry Behaviour in the Lifecycle

<!-- What may be retried, at what scope, and how duplicates are prevented. -->

## 12.11 Failure and Partial Failure

<!--
Failed and partially successful states must remain visible.
Partial success must not be presented as complete success.
-->

## 12.12 Cancellation

<!-- OPTIONAL. Define cancellation semantics if applicable. -->

## 12.13 Disablement / Soft Withdrawal

<!-- OPTIONAL. Prevent normal use without deleting canonical data, if applicable. -->

## 12.14 Deletion

<!--
Define deletion layers if multiple stores exist, for example:
withdraw from serving → delete derived → retain or delete canonical → retain or delete metadata.
Deleting in one layer must not silently delete all layers.
-->

## 12.15 Lifecycle Monitoring

<!-- Distinctions operators must be able to make (received ≠ processed ≠ verified ≠ active, etc.). -->

## 12.16 Lifecycle Auditability

<!-- Which transitions require audit events. -->

## 12.17 Lifecycle Invariants

<!--
Number and adopt the invariants that apply to this project. Reusable themes to consider:

1. Received/created ≠ validated ≠ persisted ≠ processed ≠ verified ≠ available for normal use.
2. Canonical inputs are not modified by reprocessing, rebuild, or replay.
3. A new processing/execution run against the same source version must not invent a false source version.
4. Derived/serving data is rebuildable from canonical inputs + configuration snapshot + implementation version where that is the design.
5. Availability for normal use requires successful verification whenever verification is part of the design.
6. Business/governance state is enforced in backend logic, not only in UI filters.
7. Inactive, superseded, disabled, or deleted states (if used) must be distinguishable and respected by normal serving paths.
8. Partial success must not be presented as complete success.
9. Deleting a derived/serving store does not delete canonical inputs unless explicitly intended and authorized.
10. Retrying a failed run must not create uncontrolled duplicate active representations.
11. Cancellation (if supported) leaves the entity in an explicit terminal or resumable state.
12. Every important state transition that affects availability, governance, or deletion is observable and, where required, auditable.

Record project-specific invariants below once known. Leave unused themes out rather than forcing them.
-->

## 12.18 Initial MVP Lifecycle

<!--
If the project requires explicit lifecycle states, define the minimum lifecycle/state model required for the initial release.

Where applicable define:
- states in scope;
- allowed transitions;
- user-visible states;
- states that block normal use/serving;
- failure states;
- retryable vs terminal states.

If an explicit state model is not required by the project, mark this section NOT APPLICABLE.

Do not introduce a state machine solely to satisfy this template.
-->

## 12.19 Lifecycle Design Principle

<!--
Never conflate:
source exists / processing succeeded / serving succeeded / content active / content domain-correct.

Technical success ≠ domain correctness unless the project explicitly defines them as the same.

Where lifecycle state or readiness is consequential, prefer explicit states and verification criteria over implicit best-effort progression.
-->

---

# 13. Request / Processing / Query Lifecycle

<!--
Define the lifecycle of the project's primary operation.

This chapter must support projects where the primary operation is any of:
- API request processing;
- SQL/analytical query;
- retrieval query;
- ML inference;
- asynchronous job;
- hybrid AI operation.

Do not assume embeddings, lexical search, vector search, managed search services, or RAG.

Retrieval-specific concepts below are OPTIONAL and apply only to retrieval-based projects.
-->

## 13.1 Lifecycle Overview

<!-- Stages from submission to completed outcome. -->

## 13.2 Submission

## 13.3 Validation

## 13.4 Authentication / Authorization Checks

## 13.5 Configuration / Parameter Resolution

<!-- Record whether a configuration snapshot is required for reproducibility. -->

## 13.6 Target Selection

<!--
Which dataset, index, model, environment, or partition is targeted and how it is selected.
-->

## 13.7 Representation Preparation

<!--
OPTIONAL.
Examples: query parsing, embedding generation, feature assembly, prompt assembly.
Mark NOT APPLICABLE if unused.
-->

## 13.8 Execution

<!--
Primary execution path.
OPTIONAL retrieval examples (retrieval projects only):
lexical retrieval, vector retrieval, hybrid retrieval, ranking fusion.
-->

## 13.9 Result Assembly

<!-- Ranking, truncation, deduplication, enrichment, provenance attachment as applicable. -->

## 13.10 Outcome Classification

<!--
Distinguish outcomes that must not be confused, for example:
invalid request, execution failure, empty/no-result, weak/partial result, successful result.
-->

## 13.11 Inspection / Provenance

<!-- What a user must be able to inspect about why a result was produced. -->

## 13.12 Run Recording

<!-- What is recorded for an execution/run and for how long. -->

## 13.13 Evaluation Variant

<!-- OPTIONAL. How evaluation executions differ from interactive executions. -->

## 13.14 Future Generative / Answer Extension Boundary

<!--
OPTIONAL for LLM/RAG projects.
Define what would be required before answer generation is added,
and what must remain true (evidence inspection, provenance, non-presentation of answers as certified truth, etc.).
-->

## 13.15 Request / Query Lifecycle Invariants

<!--
Example themes:
- failed execution ≠ valid empty result;
- scores/probabilities are not calibrated certainty unless validated as such;
- technical success ≠ relevance ≠ completeness ≠ domain correctness.
-->

## 13.16 MVP Minimum Request Lifecycle

## 13.17 Request Lifecycle Design Principle

<!-- Keep the operation inspectable, classifiable, and reproducible before optimizing convenience features. -->

---

# 14. Evaluation / Quality Model

<!--
OPTIONAL depending on the project.

If the project has no evaluation/quality model, mark this chapter NOT APPLICABLE with reason.

If applicable, define:
- what quality means;
- evaluation dataset or test corpus where applicable;
- metrics;
- baseline;
- regression thresholds;
- reproducibility;
- comparison methodology;
- human evaluation where applicable.

Metrics such as Precision@K, Recall@K, and nDCG@K may appear only as examples for retrieval/search projects, not mandatory requirements.
-->

## 14.1 Evaluation Objective

<!-- What is being measured and why. -->

## 14.2 Evaluation Boundary

<!-- What evaluation does and does not prove (especially vs domain/legal/business correctness). -->

## 14.3 Evaluation Dataset / Test Corpus

<!-- Schema, versioning, ownership, no-answer cases, difficulty labels if used. -->

## 14.4 Judgment / Label Model

<!-- Granularity, scale, reviewer guidance, disagreement handling. -->

## 14.5 Metrics

<!--
Define metrics actually used.
OPTIONAL retrieval examples: Precision@K, Recall@K, nDCG@K, MRR@K, Hit Rate@K.
Other domains may use accuracy, F1, latency SLOs, cost, calibration, business KPIs, etc.
-->

## 14.6 Baseline Definition

## 14.7 Evaluation Run Configuration

<!-- Immutable snapshot of configuration used for a run. -->

## 14.8 Execution Pipeline

## 14.9 Aggregation and Reporting

## 14.10 Regression Rules

<!-- Including critical-item protections so aggregate gains cannot hide severe local regressions. -->

## 14.11 Reproducibility Requirements

## 14.12 Human Evaluation

<!-- OPTIONAL. -->

## 14.13 Leakage and Contamination Safeguards

## 14.14 Evaluation Storage Ownership

<!-- Authoritative store for datasets, judgments, runs, and reports. Serving stores are usually not canonical for evaluation history. -->

## 14.15 Evaluation Invariants

## 14.16 Evaluation Design Principle

<!-- Metrics guide decisions; they do not automatically prove domain correctness. -->

---

# 15. Data and Artifact Ownership

<!--
Ownership thinking is mandatory even when specific stores are unknown.

For each important data category, define:
- authoritative source;
- canonical vs derived vs cached vs searchable/serving;
- which component may write;
- which components may read;
- persistence ownership;
- regeneration policy;
- consistency expectations across stores;
- retention/deletion ownership;
- backup/recovery ownership;
- security/access ownership.

Do not assume object storage, search engines, relational databases, or caches.
They may be used only as examples after selection.
-->

## 15.1 Ownership Principles

<!--
Adopt and adapt these reusable principles:

1. Every important data object has exactly one authoritative owner.
2. Derived data remains traceable to its canonical inputs and producing configuration.
3. Serving/search/cache copies are not automatically canonical and should be treated as rebuildable unless proven otherwise.
4. Logs are not the durable operational state store.
5. Metrics and traces support operations; they do not replace authoritative run/entity state.
6. UI state is not authoritative application state.
7. Filenames, object paths, and index-internal IDs must not independently define application identity.
8. Deleting one layer does not imply deletion of all layers.
9. Secondary copies must have an explicit consistency relationship to the authoritative record.
10. Security/access ownership must be defined for each sensitive category, not assumed from storage defaults.
-->

## 15.2 Ownership Record Template

### Data Category

**Authoritative Owner:**

**Canonical / Derived / Cached / Serving:**

**Writers:**

**Readers:**

**Persistence Location:**

**Regeneration Policy:**

**Consistency Expectations:**

**Retention / Deletion Owner:**

**Backup / Recovery Owner:**

**Security / Access Owner:**

**Status:** CURRENT / TARGET / UNKNOWN

## 15.3 Ownership Inventory

<!--
Populate only known categories. Consider these categories and keep only those that apply:

- canonical inputs / source artifacts
- identity and registry records
- metadata (authoritative vs serving copy)
- governance / business state
- processing / job / run state and stage history
- derived artifacts (transformed files, features, chunks, compiled outputs, etc.)
- embeddings / model artifacts (if any) — usually derived, not business-canonical
- serving representations / indexes / materialized views
- configuration files vs configuration snapshots
- evaluation datasets, judgments, runs, and reports (if any)
- audit events
- application logs
- metrics / traces
- UI ephemeral state
- infrastructure telemetry (owned by platform/ops tooling, not the app domain model)

For each retained category, complete the Ownership Record Template.
-->

## 15.4 Cross-Store Consistency

<!--
When multiple stores exist, define:

- write/commit sequence for multi-store operations;
- what happens if a later write fails after an earlier write succeeds;
- orphan detection expectations;
- reconciliation jobs or manual repair procedures;
- whether serving copies may briefly lag authoritative state;
- read-your-writes requirements, if any.

Do not invent a multi-store design if the project uses a single store.
-->

## 15.5 Regeneration Formula

<!--
Where derived data is rebuildable, record:

derived = f(canonical inputs, configuration snapshot, implementation version)

Also define:
- what must be retained to make regeneration possible;
- what is intentionally non-regenerable;
- whether regeneration is automatic, operator-triggered, or out of scope.
-->

## 15.6 Access Path Rules

<!--
Default rule:
clients and UI should access data through application contracts, not by bypassing to storage APIs,
unless an explicit approved exception exists (and is documented with security implications).
-->

## 15.7 Initial MVP Ownership Matrix

<!--
Compact table:

| Data Category | Authoritative Owner | Store / Location | Canonical or Derived | Notes |
|---------------|---------------------|------------------|----------------------|-------|
|               |                     |                  |                      |       |
-->

## 15.8 Ownership Invariants

<!--
Example themes to adopt if applicable:

1. Every durable business entity references its canonical inputs where inputs exist.
2. Serving-layer governance/filter fields reflect authoritative governance state.
3. Configuration used to produce derived data is recoverable via snapshot or equivalent.
4. UI state must not become authoritative application state.
5. Deleting a serving/index representation must not delete canonical inputs by side effect.
6. Audit events are append-oriented and not silently rewritten to change history.
-->

## 15.9 Data Ownership Design Principle

<!--
Maintain a clear distinction among:
canonical information, operational state, derived representations, and serving-time data.

Ownership ambiguity is an architecture defect, not a documentation detail.
-->

---

# 16. Configuration Boundary

<!--
Define what is configurable vs what must remain in code.

Configurable ≠ arbitrary.
Flexible ≠ uncontrolled.
CURRENT config ≠ historical run config.
-->

## 16.1 Configuration Objectives

## 16.2 Configuration Categories

<!-- List categories that apply (intake, processing, models, serving, retrieval, evaluation, environments, etc.). -->

## 16.3 Per-Category Settings

<!-- Indicative settings, validation rules, and whether changes require reprocessing/rebuild. -->

## 16.4 Secrets Exclusion

<!-- Secrets are not ordinary configuration values and must use a secret mechanism. -->

## 16.5 Precedence Order

<!-- defaults → files → environment → explicit overrides (adapt as needed). -->

## 16.6 Configuration Snapshots

<!-- When snapshots are mandatory for runs and what they must contain. -->

## 16.7 Configuration Identity and Versioning

<!-- Distinguish file version, snapshot ID, application version, mapping/schema version, etc. -->

## 16.8 Experiment Design Rules

<!-- OPTIONAL. Prefer changing one major factor at a time when comparing runs. -->

## 16.9 Runtime Change Consequences

<!-- Which changes may apply immediately vs require rebuild/reprocess/redeploy. -->

## 16.10 What Must Not Be Configurable in MVP

## 16.11 Local vs Deployed Configuration

## 16.12 Configuration Observability and Drift

## 16.13 Configuration Invariants

## 16.14 Configuration Design Principle

<!-- Configure parameters expected to change; implement structural behaviour in code until proven otherwise. -->

---

# 17. Security, Privacy and Compliance Requirements

<!--
Define security, privacy, and (if applicable) compliance requirements.

Preserve useful security areas:
authentication; authorization; least privilege; secrets; network boundaries;
encryption; input validation; dependency security; container security;
sensitive logging; data retention; incident handling.

Compliance-specific content is OPTIONAL guidance.
AI-specific threats such as prompt injection are OPTIONAL for LLM/RAG projects.
-->

## 17.1 Security Objectives

<!-- Confidentiality, integrity, availability, traceability, least privilege, controlled lifecycle. -->

## 17.2 Security Boundaries

<!-- Application / data / infrastructure / access / audit / domain-specific safeguards. -->

## 17.3 Authentication

<!-- MVP vs production path. Mark UNKNOWN if undecided. -->

## 17.4 Authorization

<!-- Capability groups, role mapping, MVP simplification if any. -->

## 17.5 Least Privilege

## 17.6 Separation of Technical and Domain Authority

## 17.7 Secrets Management

## 17.8 Network Boundaries

## 17.9 Encryption in Transit and at Rest

## 17.10 Input Validation and Upload Safety

## 17.11 API / Interface Hardening

<!-- Validation, CORS, rate limits, safe error messages, etc. as applicable. -->

## 17.12 Data Access Enforcement

<!-- Backend enforcement; not UI-only. Governance filters enforced server-side where relevant. -->

## 17.13 Integrity Mechanisms

## 17.14 Sensitive Logging Restrictions

## 17.15 Audit Requirements

## 17.16 Retention and Deletion

## 17.17 Backup Security

## 17.18 Dependency Security

## 17.19 Container / Runtime Security

## 17.20 CI/CD and Infrastructure-as-Code Security

## 17.21 Environment Separation

<!-- Including rules about production data in non-production environments. -->

## 17.22 Data Classification and Privacy

<!-- OPTIONAL personal-data / sensitive-data handling. -->

## 17.23 Compliance Requirements

<!--
OPTIONAL.
Record only externally imposed compliance regimes that actually apply.
Do not claim certification the system does not provide.
-->

## 17.24 AI / LLM-Specific Threats

<!--
OPTIONAL for LLM/RAG projects.
Examples: prompt injection, unsafe tool invocation, sensitive data in prompts/logs,
model-provider data handling, over-trust in generated answers.
Mark NOT APPLICABLE if unused.
-->

## 17.25 Incident Handling

## 17.26 Security Testing and Threat Modeling

## 17.27 MVP Security Baseline

<!--
Checklist themes for the first release (adapt to project constraints):

- authentication approach decided or explicitly deferred with compensating controls
- authorization enforced server-side for mutating and sensitive read paths
- secrets not committed; injected via approved mechanism
- TLS or equivalent for network exposure as required by environment
- upload/input validation rejects unsafe or unsupported inputs
- containers run as non-root where applicable
- dependency baseline reviewed or pinned
- environments separated at least for secrets and data
- sensitive fields redacted from logs
- incident contact / response path identified at least informally

Record what is CURRENT vs DEFERRED.
-->

## 17.28 Security Invariants

<!--
Example themes:
1. authenticated ≠ authorized
2. stored/indexed ≠ approved for retrieval/use
3. encrypted ≠ domain-valid or policy-approved
4. UI hiding is not access control
5. secure defaults must not block later hardening
6. production secrets never appear in local config by default
7. destructive retention/deletion actions are authorized and auditable
-->

## 17.29 Security Design Principle

<!-- Secure defaults, backend enforcement, least privilege, and explicit human responsibility boundaries. -->

---

# 18. Observability and Auditability

<!--
Define observability and auditability without requiring a specific vendor.

Guide definition of, where applicable:
request/correlation identifiers; important domain/entity identifiers; operation/stage;
structured logs; latency; external dependency latency; retry count; success/failure outcome;
health/readiness; metrics; alerting; audit events; sensitive-data logging restrictions.
-->

## 18.1 Observability Objectives

<!-- What questions must logs/metrics/traces answer during operation and incident response? -->

## 18.2 Auditability Objectives

<!-- What questions must audit records answer for governance, security, and accountability? -->

## 18.3 Scope Split

<!-- Application lifecycle observability ≠ infrastructure telemetry. -->

## 18.4 Observability Layers

<!--
Consider:
application logs; operational state; metrics; traces/correlation; audit events.
These layers are complementary and must not be collapsed into one.
-->

## 18.5 Correlation and Identifiers

<!--
Define identifiers that must appear in structured logs / traces where applicable:

- request / correlation ID
- user or service principal ID (if safe to log)
- important domain/entity IDs
- version IDs
- run / job / execution IDs
- stage / operation name
- target resource IDs (dataset, index, model, queue message, etc.)
- configuration snapshot ID
- retry attempt count

Correlation should allow an operator to follow one meaningful operation across all applicable application and external-dependency boundaries.
-->

## 18.6 Structured Logging Requirements

<!--
Prefer structured logs with stable field names.
For important operations, record at least:
operation/stage, start/end or duration, outcome, error class (if failed), and correlation IDs.
Avoid free-text-only logs for state-changing operations.
-->

## 18.7 Sensitive Data in Logs

<!--
Explicitly forbid or redact:
secrets, credentials, raw personal data beyond policy, full payload bodies where sensitive,
and any content the project classifies as non-loggable.
Define truncation/redaction rules before implementation convenience invents them.
-->

## 18.8 Per-Workflow Observability

<!--
For each major workflow (API, intake, processing stages, serving/query, evaluation, config changes),
define the minimum observable events and outcomes.
Valid empty/no-result outcomes must be distinguishable from failures.
-->

## 18.9 Latency and Dependency Telemetry

<!--
Record end-to-end latency and, where useful, external dependency latency separately
(storage, database, model provider, search, queue, identity).
-->

## 18.10 Application Metrics

<!--
Define metrics that matter for this project, for example:
intake success/failure counts, processing durations, queue depth,
query/request success/failure/empty-result counts, evaluation run counts,
dependency error rates, resource utilization if application-owned.
Do not require a specific metrics backend.
-->

## 18.11 Health and Readiness

<!--
Distinguish:
- liveness/health: process is alive;
- readiness: process can accept work given current dependency state.

Define behaviour under dependency degradation (fail ready checks vs serve degraded mode).
-->

## 18.12 Error and Warning Taxonomy

<!-- Stable error classes for operators and clients; avoid opaque catch-all failures for expected categories. -->

## 18.13 Alerting and Dashboards

<!-- OPTIONAL maturity; define minimum alerts if required by delivery constraints. -->

## 18.14 Audit Event Model

<!--
Actors, actions, targets, before/after where needed, timestamps,
correlation to runs, and whether the audit trail is append-only.
Typical auditable actions: governance changes, permission changes, retention/deletion,
configuration promotion, manual retries that change state, evaluation baseline changes.
-->

## 18.15 Observability vs Audit Distinction

<!--
Logs ≠ operational state ≠ audit records.

- Logs: diagnostic narrative and telemetry
- Operational state: durable current/historical business/technical state
- Audit records: accountable history of sensitive or governed actions
-->

## 18.16 Retention by Layer

## 18.17 Reconciliation and Reporting

## 18.18 MVP Observability / Auditability Minimum

## 18.19 Observability and Auditability Invariants

<!--
Example themes:
1. Every state-changing operation is correlatable by ID.
2. Failures record enough information to diagnose without unsafe payload dumps.
3. UI must not reconstruct authoritative state only from logs.
4. Empty/no-result is not logged/alerted as a hard failure unless it truly is one.
5. Audit events for governed actions are durable and attributable.
-->

## 18.20 Observability and Auditability Design Principle

<!-- Make important operations reconstructible through identifiers, structured events, and durable state — not tribal knowledge. -->

---

# 19. Failure, Retry and Idempotency Principles

<!--
Preserve this as a reusable design area.

Do not assume every operation needs retries or idempotency.
Make explicit decisions about:
failure categories; retryable vs non-retryable; retry limits; timeout handling;
partial failure; unknown outcomes; idempotency where required; concurrency;
cross-store failures; rollback/compensation; reconciliation; terminal states.

Project-specific values remain blank until known.
-->

## 19.1 Failure Objectives

## 19.2 Failure Categories

<!--
Define categories relevant to this project. For each category record:
- examples;
- retry allowed?;
- stop run/request?;
- cleanup / compensation needed?;
- user-visible message class.

Common category themes (include only if relevant):
- validation / contract failures (usually non-retryable without changing input)
- authentication / authorization failures
- dependency unavailable / timeout
- dependency logical error (bad mapping, incompatible schema/dimensions, etc.)
- partial multi-write failure
- resource exhaustion
- corrupt or unreadable input
- invariant violation
- unknown outcome after timeout or crash
-->

## 19.3 Severity Model

<!-- e.g. user-fixable, operator-retryable, blocking, data-corrupting-risk, security-sensitive. -->

## 19.4 Retryability Classification

```text
Retryable
Non-Retryable
Conditionally Retryable
Unknown Outcome
```

<!--
Conditionally retryable examples: after verifying no side effects, after fixing config, after dependency recovery.
Unknown outcome: crash/timeout after a side-effecting call — verify before repeating.
-->

## 19.5 Failure Recording

<!--
Fields typically worth recording:
failure category, stage/operation, timestamp, correlation IDs, entity/run IDs,
retry attempt, safe error summary, whether partial side effects may exist.
User-facing messages must be safe and actionable without leaking secrets.
-->

## 19.6 Partial Failure Handling

<!--
Define what “partially succeeded” means for multi-step or multi-item operations.
Incomplete results must not be marked fully available.
Previous successful active representations should remain protected when a candidate fails.
-->

## 19.7 Timeout and Unknown Outcome Handling

<!--
Never treat timeout as confirmed failure without verification when side effects are possible.
Define the verification step before retry for side-effecting operations.
-->

## 19.8 Retry Principles

<!--
Bounded retries, explicit max attempts, backoff (and jitter if needed),
explicit scope (single request, stage, batch, whole run),
and clear escalation to manual intervention.
Retrying ≠ recovering safely.
-->

## 19.9 Automatic vs Manual Retry

## 19.10 Idempotency

<!--
Where required, define:
- idempotency keys / fingerprints;
- per-operation rules;
- what “same business intent” means;
- protection against duplicate side effects;
- behaviour of repeated upload/submit/process/index/publish calls.

Repeated request ≠ same business intent unless made idempotent by design.
-->

## 19.11 Concurrency Controls

<!--
Consider optimistic locking, compare-and-set version fields, leases,
duplicate worker prevention, poison-message handling, and dead-letter behaviour if queues exist.
Only define mechanisms the project actually needs.
-->

## 19.12 Cross-Store Failure, Compensation, and Reconciliation

<!--
If multiple stores are written:
- define write order;
- define compensation or reconciliation for mid-sequence failure;
- define orphan detection;
- define whether serving promotion is gated on verification.
-->

## 19.13 Rollback and Safe Replacement

<!-- Failed candidates must not replace active verified representations. -->

## 19.14 Terminal States

<!-- Explicit terminal success/failure/cancelled states; what may leave them. -->

## 19.15 Failure Monitoring and Audit

## 19.16 Failure Testing Requirements

<!-- Representative failure scenarios that automated or staged tests must cover. -->

## 19.17 MVP Failure Model

## 19.18 Failure Invariants

<!--
Example themes:
1. retrying ≠ recovering safely
2. repeated request ≠ same business intent unless idempotent by design
3. failed candidate must not become active
4. unknown outcomes require verification before repeat
5. validation failures do not enter processing as partial successes
6. terminal failure states remain visible and diagnosable
-->

## 19.19 Failure, Retry and Idempotency Design Principle

<!-- Prefer explicit, bounded, observable failure handling over silent best-effort behaviour. -->

---

# 20. Deployment Direction

<!--
Document deployment direction without assuming AWS, Azure, GCP, or any provider.

Guide the project to define:
deployment target; container/runtime model; compute; networking; storage; database;
external services; secrets; observability infrastructure; environment separation;
infrastructure as code; deployment strategy; rollback; backup/recovery; cost;
resource naming; CI/CD where required.

Managed-service examples such as container registries, object storage, managed search,
secrets managers, KMS, or CloudFormation-style IaC may appear only as optional examples
after selection — never as mandatory architecture.
-->

## 20.1 Deployment Objectives

<!--
Typical objectives (keep only those that apply):

- reproducible infrastructure and application deployment
- containerized or otherwise repeatable runtime
- durable externalization of state that must survive process replacement
- secure service-to-service and user access
- application and infrastructure observability hooks
- controlled configuration and secret management
- safe deployment and rollback
- clear path from local development to deployed environments

The first deployment does not need speculative enterprise scale, multi-region, or multi-tenancy unless required by constraints.
-->

## 20.2 Deployment Non-Goals

<!-- e.g. speculative multi-region, multi-tenancy, premature scale — only if relevant. -->

## 20.3 Deployment Target

<!-- Local, VM, containers, PaaS, specific cloud account, on-prem, etc. Status: CURRENT / TARGET / UNKNOWN. -->

## 20.4 Container / Runtime Model

<!-- Image build, runtime user, health probes, resource limits, 12-factor style config if applicable. -->

## 20.5 Compute Topology

<!--
Prefer the simplest compute topology that satisfies the approved project requirements.

Do not introduce additional runtime components or infrastructure unless they are justified by the project's actual requirements and architecture.
-->

## 20.6 Networking

<!-- Public vs private exposure, ingress, egress restrictions, service-to-service auth. -->

## 20.7 Storage

<!-- Object/block/file stores for canonical and derived artifacts if needed. -->

## 20.8 Database / Operational State Store

<!-- Introduce only when justified by concrete requirements (relationships, run state, governance, audit, evaluation history, etc.). -->

## 20.9 External / Managed Services

<!--
List approved services only.
Optional examples that may appear after selection (not mandatory):
object storage, container registry, managed containers/compute, managed search,
secrets manager, KMS, managed database, queue, identity provider, IaC engine.
-->

## 20.10 Secrets and Configuration Injection

## 20.11 Observability Infrastructure

<!-- Where logs/metrics/traces/alerts go; app vs infra split. -->

## 20.12 Environment Separation

<!-- local / dev / staging / prod or project-specific set; no production secrets in local by default. -->

## 20.13 Infrastructure as Code

<!-- Tooling, module boundaries, review requirements, drift handling. -->

## 20.14 CI/CD

<!-- Build, test, security checks, deploy gates, deployment identity. -->

## 20.15 Deployment Strategy

<!-- rolling, blue/green, recreate, etc. — only what is chosen. -->

## 20.16 Rollback Strategy

<!--
Separate where they differ:
- application rollback
- configuration rollback
- data / index / serving-representation rollback
Serving promotion is often a lifecycle action, not only an infra deploy.
-->

## 20.17 Backup and Recovery

<!-- Reconstructability expectations vs active-active DR; RPO/RTO if required; what must be retained to rebuild derived data. -->

## 20.18 Cost and Capacity Notes

<!-- Primary cost drivers and any hard ceilings from Delivery Constraints. -->

## 20.19 Resource Naming and Tagging

## 20.20 MVP Deployment Minimum

<!-- Smallest deployable topology that proves the product lifecycle. -->

## 20.21 Deployment Invariants

<!--
Example themes:
1. app compute is replaceable; durable state is externalized
2. no production deployments from uncontrolled local state
3. infrastructure components are added only when justified
4. secrets are never baked into images
5. environment isolation is enforced for data and credentials
-->

## 20.22 Deployment Design Principle

<!-- Prefer simple, reproducible, least-privilege deployment that supports the product lifecycle without speculative platform complexity. -->

---

# 21. Open Technical Decisions

<!--
Record only decisions that actually exist for this project.
Do not pre-populate dozens of hypothetical decisions.

Unresolved technical decisions are useful project information.
Prefer a reversible baseline over a complex permanent commitment when uncertainty remains.
Not decided ≠ not important.
Provisional ≠ permanent.
Do not hide undecided items behind undocumented defaults.
-->

## 21.1 Decision-Making Structure

Each important decision should record:

```text
Decision
Status
Context
Options
Current / Selected Direction
Rationale
Consequences
Validation Method
Revisit Trigger
```

## 21.2 Allowed Statuses

```text
OPEN
UNDER_INVESTIGATION
PROVISIONAL
ACCEPTED
DEFERRED
REJECTED
```

### OPEN

Not yet investigated sufficiently.

### UNDER_INVESTIGATION

Options are being evaluated through research, prototyping, or measurement.

### PROVISIONAL

Temporary direction selected to unblock implementation; may change before final acceptance.

### ACCEPTED

Sufficient evidence; becomes project baseline.

### DEFERRED

Not required for the current deliverable.

### REJECTED

Option explicitly excluded with documented reasoning.

## 21.3 Decision Record Template

### D-XX — Decision Title

**Decision:**

**Status:** OPEN | UNDER_INVESTIGATION | PROVISIONAL | ACCEPTED | DEFERRED | REJECTED

**Context:**

**Options:**

**Current / Selected Direction:**

**Rationale:**

**Consequences:**

**Validation Method:**

**Revisit Trigger:**

**Required-by Deliverable:**

**Owner:**

## 21.4 Decision Register

<!--
Maintain a compact register of real decisions only:

| ID | Decision | Status | Required-by | Owner | Outcome Ref |
|----|----------|--------|-------------|-------|-------------|
|    |          |        |             |       |             |
-->

## 21.5 Decision Dependencies

<!-- Record sequences where one decision blocks others. Leave empty until known. -->

## 21.6 Decisions Required Before Intermediate Deliverables

## 21.7 Decisions That May Remain Deferred

## 21.8 Technical Decision Invariants

<!--
- Do not treat provisional choices as accepted architecture in documentation.
- Prefer measurable validation over preference.
- Record rejections so excluded options are not rediscovered endlessly.
-->

## 21.9 Open Technical Decisions Principle

<!-- Prevent implicit assumptions from becoming accidental architecture. -->

---

# 22. Project-Level Success Criteria

<!--
The success subsections below form a coverage checklist, not mandatory success requirements.

Use only criteria corresponding to capabilities, qualities, and outcomes actually required by the project.

Mark irrelevant criteria NOT APPLICABLE or leave them unused as appropriate.

Do not implement a capability solely because a corresponding success-criteria subsection exists.

Project-Level Success Criteria define outcomes that must be demonstrably true for the first release to be considered successful.

Project-Level Success Criteria
≠
Milestone Definition of Done

Success criteria must be:
- observable;
- demonstrable;
- testable where possible;
- evidence-backed;
- related to actual project objectives.

Do not create generic success criteria that force unused capabilities.
A project without retrieval must not receive retrieval success criteria.
A project without evaluation must not receive evaluation success criteria.
-->

## 22.1 Success Evaluation Principle

<!--
Success must be demonstrated through working behaviour, persisted state, inspectable evidence,
automated tests where required, evaluation results where in scope, and deployment reproducibility where required.

The project must not be considered successful only because:
- containers start;
- a demo path looks plausible;
- a small number of manual examples appear reasonable;
- or a generative model produces a convincing answer (if applicable).

Technical availability and demonstration quality are necessary but not sufficient.
-->

## 22.2 End-to-End Lifecycle Success

<!-- Define the lifecycle that must complete without undocumented manual store edits. -->

## 22.3 Supported Input / Format Success

<!-- Only if applicable. -->

## 22.4 Canonical / Authoritative Data Preservation Success

<!-- Only if applicable. -->

## 22.5 Identity and Version Success

## 22.6 Processing / Workflow Control Success

## 22.7 Failure-Handling Success

## 22.8 Idempotency Success

<!-- Only where idempotency is required. -->

## 22.9 Verification Before Availability Success

## 22.10 Monitoring / Visibility Success

## 22.11 Governance / State-Control Success

<!-- Only if applicable. -->

## 22.12 Traceability Success

## 22.13 Primary Operation / Query Success

## 22.14 Result Inspectability Success

## 22.15 Evaluation Success

<!-- OPTIONAL / NOT APPLICABLE if no evaluation model. -->

## 22.16 Configuration Traceability Success

## 22.17 Observability Success

## 22.18 Auditability Success

## 22.19 Security Baseline Success

## 22.20 Deployment Reproducibility Success

## 22.21 Automated Testing Success

## 22.22 Scope-Control Success

## 22.23 Successful Demonstration Scenario

<!-- A concrete scenario that demonstrates project-level success with evidence. -->

## 22.24 Unsuccessful Project Conditions

<!-- Explicit conditions under which the project is NOT complete despite partial demos. -->

## 22.25 Project Success Evidence

<!-- Artifacts/evidence required at completion (logs, reports, test results, screenshots, IaC outputs, etc.). -->

## 22.26 Relationship to Intermediate Deliverables

## 22.27 Relationship to Definition of Done

<!--
Milestone DoD proves a slice or work item.
Project-level success criteria prove the release outcome.
-->

## 22.28 Final Completion Boundary

## 22.29 Project-Level Success Principle

<!--
Uploaded/received ≠ fully processed;
stored ≠ verified/available;
returned ≠ correct;
metric calculated ≠ reproducible comparison;
deployed ≠ successfully operated.
Define the distinctions that matter for this project and require evidence for each.
-->

---

# Appendix A — Population Checklist

<!--
Before treating this document as a completed project reference, confirm:
- Template Usage rules followed;
- Delivery Constraints filled or explicitly UNKNOWN;
- all 22 major chapters addressed or marked NOT APPLICABLE with reason;
- no section describes TARGET architecture as CURRENT;
- no invented stack, datastore, model, or cloud provider;
- optional capability sections enabled only when in scope;
- open decisions recorded only when real;
- success criteria match actual objectives.
-->

# Appendix B — Status Vocabulary

```text
CURRENT / IMPLEMENTED
APPROVED TARGET
DEFERRED / OPTIONAL
UNKNOWN / OPEN
NOT APPLICABLE (with reason)

Decision statuses:
OPEN
UNDER_INVESTIGATION
PROVISIONAL
ACCEPTED
DEFERRED
REJECTED
```
