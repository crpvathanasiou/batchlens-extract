# 03 — Common Project Handoff

## 1. Purpose

This is the **single shared operational handoff for Cursor-assisted implementation**.

Its purpose is to let a new Cursor session reconstruct enough project context to continue safely without relying on old conversation context or local code intuition alone.

This file must answer:

```text
What project are we building?
What is the current delivery boundary?
What are the important limitations / constraints?
Where are we in the roadmap?
What requirement / use case / component does the current work implement?
What task / subtask are we executing?
Which code areas are involved?
Which engineering standards apply?
What is factually complete?
What has been verified?
What remains incomplete?
What is the exact next approved action?
What must not be done next?
```

This handoff is **not** a replacement for the project documentation.

Cursor must inspect the actual project and use the long-lived Markdown files as the authoritative semantic context.

---

## 2. Mandatory Cursor Re-Orientation

At the start of a new Cursor Agent session, or after substantial context growth:

```text
1. Inspect the full repository.
2. Understand the repository structure at a high level.
3. Prioritize the long-lived project Markdown documents.
4. Reconstruct the project purpose, architecture, delivery plan, engineering standards,
   current implementation state, and code ownership.
5. Inspect source code and tests relevant to the active work item.
6. Confirm the exact next approved action from this handoff.
7. Only then modify code.
```

Do **not** infer project architecture from source code alone.

Existing code may contain:

- legacy or example implementation;
- transitional structure;
- incomplete milestone work;
- accepted technical debt;
- deferred capabilities;
- code that is correct locally but not authoritative for future architecture.

Use:

```text
Project Markdown references
+ this handoff
+ Code Map
+ actual repository evidence
```

before implementation decisions.

---

## 3. Long-Lived Project Documents

Cursor must understand what each long-lived project document owns.

| Document / Source | Primary Responsibility |
|---|---|
| `00_project_reference.md` | Project-wide WHAT / WHY: problem, goals, scope, users, functional areas, use cases, system context, logical components, data/domain concepts, cross-cutting requirements, deployment direction, project-level success criteria |
| `01_implementation_roadmap.md` | Delivery decomposition: milestones, sequencing, dependencies, priorities, task/subtask breakdown when useful, milestone Definition of Done, completion evidence |
| `02_code_quality_standards.md` | HOW implementation must be engineered: Python, Pydantic, async, SOLID/DI, FastAPI, errors, guardrails, logging, security, testing, Ruff, Pyright, Docker, CI, AI-assisted engineering |
| `03_common_handoff.md` | Current continuation state: active work, cross-references, limitations, blockers, evidence, exact next action |
| `04_code_map.md` | WHERE implementation lives: modules/files, responsibilities, contracts, important dependencies, tests, implementation status |
| Git / repository | Factual implementation and publication state: branch, HEAD, committed/uncommitted state, working tree, actual code |

### 3.1 Authority Rule

Use this reasoning order:

```text
WHY / WHAT must exist?
→ 00_project_reference.md

WHEN / IN WHAT ORDER?
→ 01_implementation_roadmap.md

HOW must it be engineered?
→ 02_code_quality_standards.md

WHERE is it implemented?
→ 04_code_map.md + repository inspection

WHERE ARE WE NOW / WHAT MAY HAPPEN NEXT?
→ 03_common_handoff.md

WHAT FACTUALLY EXISTS?
→ Git + repository
```

If this handoff conflicts with an authoritative source, correct the handoff.

Do not silently reinterpret the authoritative source from local code.

---

## 4. State Semantics

Use status terms deliberately.

### 4.1 Delivery Status

```text
PLANNED
READY
IN_PROGRESS
BLOCKED
DONE
DEFERRED
```

`DONE` means the applicable milestone Definition of Done has passed.

### 4.2 Implementation / Review State

```text
IMPLEMENTED
→ intended code/document change exists

VERIFIED
→ required evidence was executed and passed

APPROVED
→ explicit review / governance decision exists
```

These states are independent.

Example:

```text
IMPLEMENTED / VERIFIED / NOT YET COMMITTED
```

### 4.3 Git Truth

Git is authoritative for:

- current branch;
- `HEAD`;
- commit hashes;
- committed vs uncommitted state;
- working-tree state;
- pushed / remote state when verified.

Never infer:

```text
IMPLEMENTED = COMMITTED
VERIFIED    = COMMITTED
APPROVED    = COMMITTED
COMMITTED   = PUSHED
```

---

# PART A — PROJECT ORIENTATION SNAPSHOT

## 5. Project Snapshot

Keep this section intentionally compact.

### Project / Assignment

**Name:** fastapi-prod-starter-v2-slim (generic production FastAPI starter)

**One-sentence purpose:** Reusable FastAPI foundation with optional async OpenAI LLM capability.

### Primary End-to-End Outcome

```text
Starter boots without OpenAI; when OPENAI_API_KEY is configured, callers can compose
create_async_openai_client + AsyncOpenAIWrapper for async plain-text / structured LLM calls.
```

### Current Delivery Boundary

**Must exist now:**

- FastAPI system endpoints and settings
- Reusable async LLM wrapper + OpenAI provider construction + proving unit tests

**Not part of the current delivery:**

- LLM routes wired into `create_app`
- Real network smoke as part of default pytest
- Assignment-specific product domain features

### Major System Boundaries / Components

```text
Caller / test / future feature
→ AsyncOpenAIWrapper (orchestration, guardrails, retries)
→ injected async client protocol
→ create_async_openai_client (AsyncOpenAI construction from settings/env)
→ OpenAI API (only when a real key and live call are used)
```

**Major components:**

- FastAPI application factory (`app.main`)
- Settings (`app.settings`)
- LLM package (`app.llm`)

### Primary Project Reference

For the full project model, Cursor must read:

```text
00_project_reference.md
```

Do not duplicate the complete project reference here.

---

## 6. Current Limitations, Hard Constraints, and Accepted Trade-Offs

Record only limitations that can materially affect implementation decisions.

Prefer **5–10 concise items maximum**.

| Limitation / Constraint / Trade-Off | Implementation Impact | Authoritative Source |
|---|---|---|
| LLM is a reusable asset, not required to boot the API | Do not construct OpenAI clients inside `create_app` unless a future milestone explicitly activates LLM | this handoff / M1 DoD |
| Wrapper must not own `AsyncOpenAI` / API key reading | Inject client via DI; use `create_async_openai_client` for real clients | M1 architectural requirement |
| Async-only LLM path | No sync OpenAI client, no `to_thread` / executors | M1 architectural requirement |
| Default pytest must not call OpenAI | Use fake injected clients only | M1 tests |
| No commit / push without authorization | Leave working tree for review | user instruction |

Examples of the correct level:

```text
- No durable queue is part of the approved current delivery.
  → Do not introduce a queue to solve local background-processing convenience.

- Current persistence is intentionally limited.
  → Do not treat it as production durability or invent a new persistence layer.

- Authentication is outside the current delivery boundary.
  → Do not add authentication middleware during unrelated API work.
```

Do not use this section for:

- the complete backlog;
- every non-goal;
- every technical debt item;
- all deferred capabilities;
- detailed architectural rationale.

Use exact references to `00_project_reference.md` for full context.

---

## 7. Project-Wide Invariants Relevant to Implementation

Record only the small set of global rules that local changes must not violate.

Prefer **5–10 items maximum**.

- Dependency direction: wrapper orchestration → injected client protocol; provider owns AsyncOpenAI construction.
- Settings may expose optional `OPENAI_*` values; absence of key must not prevent app start.
- Reuse the existing async OpenAI wrapper before rewriting.
- Starter remains generic — no assignment-specific domain leakage in reusable assets.
- Secrets stay in env / `.env` (gitignored); never hard-code API keys.

**Authoritative sources:**

```text
01_implementation_roadmap.md → M1
02_code_quality_standards.md → async / DI / LLM reuse guidance
04_code_map.md → LLM Invocation capability
```

---

# PART B — ACTIVE WORK TRACEABILITY

## 8. Fast Restart Summary

| Item | Current State |
|---|---|
| Project / assignment | fastapi-prod-starter-v2-slim — reusable FastAPI + optional LLM |
| Current milestone | M1 — Reusable async LLM wrapper |
| Current task / work item | Establish reusable async OpenAI wrapper in the starter |
| Current subtask / step | COMPLETE — awaiting review |
| Status | DONE / VERIFIED / NOT COMMITTED |
| Requirement / use-case anchor in `00` | Reusable OpenAI LLM asset (starter capability) |
| Roadmap anchor in `01` | M1 |
| Relevant standards in `02` | Async, SOLID/DI, guardrails, LLM reuse, testing |
| Code-map anchor in `04` | LLM Invocation / OpenAI provider |
| Last closed boundary | M1 LLM capability validated |
| Primary blocker | NONE |
| Exact next approved action | Human review of the LLM capability; no commit/push yet |
| Critical prohibition | Do not commit, push, or force OpenAI at app boot |
| Last updated / verified at | 2026-08-16 |

Use `UNKNOWN`, `NONE`, or `NOT_APPLICABLE` rather than inventing values.

---

## 9. Active Work Hierarchy

### Milestone

**ID / Name:**

### Task / Work Item

**ID / Name:**

### Current Subtask / Step

**ID / Name:**

### Sibling Subtasks / Steps

Record the surrounding decomposition so Cursor understands what comes before and after the current local work.

1. ...
2. ...
3. ...

### Why This Work Exists

**Business / technical purpose:**

**Expected system / user outcome:**

---

## 10. Active Work → Project Reference Mapping

The current work must be traceable to the approved project model.

Use only applicable rows.

| Relationship | Exact Source |
|---|---|
| Project goal | `00_project_reference.md → §...` |
| MVP / delivery requirement | `00_project_reference.md → §...` |
| Functional area | `00_project_reference.md → §7...` |
| Core use case | `00_project_reference.md → §8...` |
| System boundary | `00_project_reference.md → §9...` |
| Logical component | `00_project_reference.md → §10...` |
| Domain / data concept | `00_project_reference.md → §11...` |
| Lifecycle / processing flow | `00_project_reference.md → §12 / §13...` |
| Configuration requirement | `00_project_reference.md → §16...` |
| Security / privacy requirement | `00_project_reference.md → §17...` |
| Observability requirement | `00_project_reference.md → §18...` |
| Failure / retry / idempotency rule | `00_project_reference.md → §19...` |
| Project success criterion | `00_project_reference.md → §22...` |

Important:

```text
00_project_reference.md
→ owns WHY / WHAT

01_implementation_roadmap.md
→ owns delivery decomposition / order
```

Task and subtask structure should not be moved into `00_project_reference.md` merely for convenience.

---

## 11. Active Work → Roadmap Mapping

```text
01_implementation_roadmap.md
→ <Milestone>
→ <Task / work item if used>
→ <Current subtask / step if used>
→ <Relevant milestone DoD gates>
```

### Current Milestone DoD Gates Relevant to This Work

- ...
- ...
- ...

Do not copy unrelated roadmap content.

---

## 12. Active Work → Code Map / Repository Mapping

| Code Area | Responsibility in Current Work | Code Map Source |
|---|---|---|
| | | `04_code_map.md → ...` |

### Relevant Tests

- ...

### Upstream Dependencies / Contracts

- ...

### Downstream Consumers / Effects

- ...

### What This Work Must Not Break

- ...

Cursor must still inspect the actual repository before modification.

The Code Map accelerates navigation; it does not replace repository verification.

---

## 13. Relevant Engineering Standards — Mandatory Re-Read

Before implementing or materially modifying the current work item, Cursor must re-read the relevant parts of:

```text
02_code_quality_standards.md
```

### Required Sections for Current Work

```text
02_code_quality_standards.md
→ §...
→ §...
→ §...
```

### Navigation Guide

| Work Area | Relevant Standards |
|---|---|
| General Python implementation | §3 Core Engineering Principles, §6 Python Standards, §18 Ruff, §19 Pyright |
| Pydantic / schemas / settings | §7 Pydantic v2 Standards, §11 Configuration Standards |
| Async / concurrency / external I/O | §8 Async Standards, §9 SOLID and Dependency Design, §12 Error Handling |
| FastAPI / API changes | §10 FastAPI Standards, §12 Error Handling, §13 Guardrails, §15 Security, §16 Testing |
| External provider / infrastructure adapter | §9 SOLID/DI, §12 Errors, §13 Guardrails, §14 Logging, §16 Testing |
| LLM / model work | §4 Technology Baseline, §7 Pydantic, §9 SOLID/DI, §13 Guardrails, §14 Observability, §15 Security, §16 Testing |
| Logging / telemetry | §14 Logging and Observability |
| Security-sensitive work | §13 Guardrails, §15 Security |
| Tests | §16 Testing |
| Docker / Compose | §20 Docker Standards |
| CI / optional project automation | §17 Static Quality Gates, §21 CI Standards, §30 Project-Wide Quality Gates |
| AI-assisted implementation workflow | §26 AI-Assisted Engineering Standards |

The table is a navigation aid only.

The exact required sections for the active work must be listed above.

---

## 14. Local-Change Re-Orientation Rule

A small change can still create large architectural drift.

Before a material micro-correction:

```text
1. Re-read §8 Fast Restart Summary.
2. Re-read §9–§13 Active Work Traceability.
3. Re-open the exact `00_project_reference.md` anchors.
4. Re-open the relevant `02_code_quality_standards.md` sections.
5. Re-open the relevant `04_code_map.md` entries.
6. Inspect the affected source code and tests.
7. Check upstream / downstream contracts.
8. Make the smallest correct change consistent with the larger project.
9. Run applicable validation.
```

Do not treat a locally simple fix as an isolated coding exercise when it affects:

- public contracts;
- dependency direction;
- lifecycle/state;
- persistence semantics;
- security;
- idempotency;
- observability;
- provider boundaries;
- downstream behaviour.

---

# PART C — CURRENT EXECUTION STATE

## 15. Repository and Git Snapshot

Record the latest **observed** state.

| Field | Value |
|---|---|
| Repository | fastapi-prod-starter-v2-slim |
| Repository URL | NOT_VERIFIED (local workspace; `.git` absent / not verified) |
| Primary branch | NOT_VERIFIED |
| Active branch | NOT_VERIFIED |
| HEAD | NOT_VERIFIED |
| Observed remote / upstream state | NOT_VERIFIED |
| Working tree | Uncommitted LLM capability changes present |
| Last observed at | 2026-08-16 |
| Evidence source | local inspection |

Git state: NOT_VERIFIED as a formal git repository in this workspace; do not commit/push.

Useful evidence may include:

```text
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse --verify origin/main
```

If Git was not checked:

```text
Git state: NOT_VERIFIED
```

Do not present stale Git information as current fact.

---

## 16. Last Closed Boundary

| Field | Value |
|---|---|
| Boundary / milestone | M1 — Reusable async LLM wrapper |
| Outcome | Async LLM wrapper + OpenAI provider + tests + docs sync |
| Status | DONE / VERIFIED / NOT COMMITTED |
| Verification | poetry check, ruff, pyright, pytest (36 passed) |
| Git boundary, if verified | NONE — no commit authorized |
| Relevant evidence / reference | `01_implementation_roadmap.md` M1; `tests/llm/` |

If no formal Git boundary exists, state that explicitly.

---

## 17. Current Factual State

### Completed / Implemented

- Async LLM wrapper with guardrails, retries, timeouts, structured outputs
- OpenAI provider construction separated (`create_async_openai_client`)
- Optional OpenAI settings; app starts without key
- Unit tests with fake clients; provider construction smoke without network
- Docs updated: roadmap, handoff, code map

### Partially Complete

- NONE for M1

### Explicitly Not Implemented

- FastAPI routes that call the LLM
- Real OpenAI network smoke in default pytest
- Assignment-specific product domain features

### Materially Changed Files / Areas

```text
Created:
- src/app/exceptions.py
- src/app/llm/*
- tests/llm/*

Modified:
- src/app/settings.py
- pyproject.toml / poetry.lock
- .env.example
- .ai/01_implementation_roadmap.md
- .ai/03_common_handoff.md
- .ai/04_code_map.md
- tests/test_settings.py
```

---

## 18. Current Scope Boundary

### In Scope Now

- Review of completed M1 LLM capability

### Explicitly Out of Scope

- Commit / push
- Multi-provider infrastructure
- Wiring LLM into `create_app` without an approved milestone

### Deferred

- Live OpenAI smoke path as an automated test
- Application-level LLM endpoint composition

---

## 19. Latest Verification and Evidence

| Check / Command | Status | Evidence / Notes |
|---|---|---|
| pytest | PASS | 36 passed; no network LLM calls |
| Pyright | PASS | 0 errors |
| Ruff lint | PASS | |
| Ruff format check | PASS | |
| Docker build | NOT_RUN | not required for M1 |
| Integration / contract checks | NOT_APPLICABLE | |
| `git diff --check` | NOT_RUN | |
| Other | PASS | `poetry check`; importability of `app.llm` |

Use only applicable checks.

**Verified against branch / commit / working tree:** local working tree (uncommitted)

**Verification timestamp:** 2026-08-16

**Known baseline debt excluded from result:** Poetry `[tool.poetry.*]` deprecation warnings

Do not claim verification for code changed after the evidence was produced.

---

## 20. Known Issues / Baseline Debt

Record only issues relevant to current continuation, review, or delivery.

| Issue | Classification | Blocks Current Work? | Follow-Up |
|---|---|---|---|
| Poetry package metadata deprecation warnings on `poetry check` | pre-existing | NO | Optional future pyproject migration |

Keep pre-existing debt separate from regressions introduced by the current milestone.

Do not silently expand scope to repair unrelated debt.

---

## 21. Open Decisions and Questions

### Blocking Decisions

- `NONE`

### Non-Blocking Open Questions

- ...

### Working Assumptions

- ...

Keep these distinct:

```text
Approved Decision
≠ Working Assumption
≠ Open Question
≠ Future Idea
```

Unknown values remain `UNKNOWN`.

Do not resolve non-blocking questions speculatively.

---

## 22. Continuation-Impacting Blockers

**Current blockers:**

- `NONE`

A blocker belongs here only if it prevents safe continuation or the exact next approved action.

For a real blocker:

```text
Blocker:
Why it blocks:
Required resolution:
Owner / dependency:
```

---

## 23. Exact Next Approved Action

There must be **one primary next action**.

| Field | Value |
|---|---|
| Owner / actor | Reviewer |
| Action | Review the reusable async OpenAI wrapper; authorize commit only if accepted |
| Allowed scope | Review only — no further feature work unless requested |
| Required references to re-read first | `01` M1, `04` LLM capability, `src/app/llm/` |
| Expected evidence / exit condition | Review decision recorded; commit only if explicitly requested |

Prefer precise wording.

Good:

```text
Implement the current subtask only.

Before editing:
- re-read the listed `00` requirement/use-case/component anchors;
- re-read the listed `02` engineering standards;
- inspect the relevant `04` code-map entries and actual implementation.

Do not begin the sibling subtask.
```

Avoid:

```text
Continue work.
Improve the code.
Implement next task.
```

If no next action is approved:

```text
Next approved action: NONE — awaiting <specific decision / dependency>.
```

---

## 24. Following Action — Conditional

Optional.

Use only when the immediate follow-up is already clear and depends on Section 23 succeeding.

```text
If <current action succeeds>:
→ <next action>
```

Do not turn this into a second roadmap.

---

## 25. Forbidden / Unapproved Next Actions

- commit / push before explicit authorization
- wire LLM into `create_app` without an approved milestone
- add provider factories or multi-provider abstractions
- require a real OpenAI key for default tests or app startup

---

# PART D — ANTI-DRIFT AND HANDOFF MAINTENANCE

## 26. Anti-Drift Rules

### 26.1 Local Correctness Is Not Enough

Accept a change only when:

```text
Local correctness
+ project requirement alignment
+ architectural consistency
+ dependency-direction consistency
+ standards compliance
+ upstream/downstream compatibility
+ applicable validation
= acceptable change
```

### 26.2 Do Not Infer Architecture From Code Alone

Source code may represent:

- current implementation;
- incomplete work;
- transitional design;
- technical debt;
- examples;
- deferred cleanup.

Use the authoritative Markdown references before interpreting local implementation.

### 26.3 Re-Orient When the Work Area Changes

If work moves between areas such as:

```text
API
→ application/domain
→ external provider
→ persistence
→ LLM
→ testing
→ Docker
→ CI
```

re-read the newly relevant:

- `00` project anchors;
- `01` roadmap area;
- `02` quality standards;
- `04` Code Map entries.

### 26.4 Re-Orient After Long Agent Context

If the Cursor session becomes long, confused, or internally inconsistent:

```text
Update / reconcile this handoff
→ start a new Cursor session
→ inspect the project again
→ reload the controlled references
→ continue from the exact next approved action
```

### 26.5 Resolve Conflicts Explicitly

If:

```text
local implementation convenience
≠ approved project architecture / standards
```

local convenience must not silently win.

STOP only when:

- required information is genuinely unavailable;
- implementation conflicts materially with canonical architecture;
- required work would touch forbidden/out-of-scope files;
- an unresolved decision blocks safe implementation.

Otherwise proceed within the approved work item.

---

## 27. Handoff Compression Rules

The handoff must preserve enough context for safe continuation without becoming a duplicate of the project references.

Prefer:

```text
short current summary
+ exact source anchor
+ current implementation impact
```

over copying authoritative content.

Guidelines:

- project snapshot: concise;
- limitations: preferably 5–10 items maximum;
- project-wide invariants: preferably 5–10 items maximum;
- current-work mappings: only applicable references;
- evidence: latest relevant evidence only;
- blockers: current blockers only;
- next action: one primary action;
- remove stale state instead of accumulating history.

Do not turn the handoff into:

- a second `00_project_reference.md`;
- a second roadmap;
- a second Code Quality manual;
- a full Code Map;
- a Git history;
- a conversation diary.

---

## 28. Handoff Maintenance Rules

Maintain exactly one common handoff.

Update it when meaningful continuation information changes, including:

- milestone / task / subtask;
- active-work reference mapping;
- implementation status;
- verification result;
- blocker;
- scope boundary;
- exact next action;
- relevant Git state;
- materially relevant limitation or invariant.

Do not rewrite it after trivial edits with no continuation impact.

### Evidence Before Claims

Never promote an intended or reported result to `VERIFIED` without evidence.

### Keep Current State, Not History

Remove stale:

- next actions;
- old blockers;
- obsolete Git snapshots;
- old task context;
- superseded assumptions.

### Reference Instead of Duplicate

Use exact references to `00`, `01`, `02`, and `04`.

### Reconcile Near the End of Meaningful Work

When implementation and project documentation change in one work boundary:

```text
update authoritative source documents
→ verify implementation
→ reconcile Code Map when relevant
→ update handoff last
```

The handoff must represent the final continuation state.

---

## 29. End-of-Session / Boundary Checklist

Before ending a meaningful Cursor session, confirm:

### Orientation

- [ ] repository was inspected;
- [ ] long-lived Markdown documents were considered;
- [ ] project snapshot remains accurate;
- [ ] current limitations / constraints remain accurate;
- [ ] project-wide invariants remain accurate.

### Active Work

- [ ] milestone / task / subtask is correct;
- [ ] exact `00` anchors are listed;
- [ ] exact `01` roadmap anchor is listed;
- [ ] relevant `02` standards are listed;
- [ ] relevant `04` Code Map area is listed;
- [ ] upstream/downstream context is understood.

### Current State

- [ ] completed / partial / not-implemented state is current;
- [ ] scope boundary is explicit;
- [ ] verification evidence is current;
- [ ] baseline debt is separated from current regressions;
- [ ] blockers are current;
- [ ] one exact next approved action exists;
- [ ] forbidden actions are current;
- [ ] Git state is current when relevant.

### Drift Control

- [ ] no local implementation choice silently changed architecture;
- [ ] no unresolved assumption is presented as a decision;
- [ ] no deferred capability was introduced without approval;
- [ ] no unrelated cleanup widened scope;
- [ ] stale handoff information was removed.

---

## 30. Compact Continuation Summary

Keep this final block current.

```text
PROJECT / ASSIGNMENT
→ fastapi-prod-starter-v2-slim (generic FastAPI starter + optional LLM)

CURRENT LIMITATIONS / HARD CONSTRAINTS
→ LLM opt-in; wrapper does not own AsyncOpenAI/API key; async-only

ACTIVE REQUIREMENT / USE CASE IN 00
→ Reusable OpenAI LLM starter asset

CURRENT MILESTONE / TASK / SUBTASK IN 01
→ M1 Reusable async LLM wrapper — DONE

RELEVANT QUALITY STANDARDS IN 02
→ Async, DI, guardrails, LLM reuse, testing

RELEVANT CODE AREA IN 04
→ LLM Invocation / OpenAI provider (`src/app/llm/`)

STATUS
→ IMPLEMENTED / VERIFIED / NOT COMMITTED

CURRENT FACTUAL STATE
→ Wrapper + provider + settings + tests + docs updated

LATEST VERIFIED EVIDENCE
→ poetry/ruff/pyright/pytest PASS

BLOCKER
→ NONE

EXACT NEXT APPROVED ACTION
→ Human review; no commit/push

FORBIDDEN NEXT ACTION
→ commit/push; force OpenAI at app boot
```

This is a quick restart aid, not a replacement for the detailed sections above.
