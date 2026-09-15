# 04 — Code Map

## 1. Purpose

Semantic map of **existing** BatchLens Extract implementation.

Design documents [05](05_pipeline_contracts.md)–[08](08_check_selection_strategy.md) do **not** imply new implemented modules.

| Document | Owns |
|----------|------|
| [00](00_project_reference.md) | Product scope |
| [01](01_implementation_roadmap.md) | Milestones |
| [02](02_code_quality_standards.md) | Engineering standards |
| [03](03_common_handoff.md) | Current execution state and historical check results |
| [04](04_code_map.md) | Implemented responsibilities (this file) |

If this map conflicts with the repository, the repository wins and this map must be corrected.

---

## 2. Repository summary

| Field | Value |
|-------|-------|
| Application | BatchLens Extract (`batchlens-extract`) |
| Runtime | Python 3.11 |
| Framework | FastAPI + Pydantic Settings |
| Package root | `src/app` |
| Entry point | `app.main:app` / `create_app` |
| Tests | `tests/` |
| Containers | `Dockerfile`, `docker-compose.yaml` |
| Durable product/job persistence | NONE |
| In-memory configuration state | `Settings` cache + `app.state.settings` |
| Product document routes | NONE |
| Optional provider asset | OpenAI wrapper (unwired) |

```text
src/app/
├── api/system.py
├── llm/                   optional async OpenAI wrapper + provider
├── exceptions.py
├── settings.py
├── logging_config.py
└── main.py

tests/
├── llm/
├── test_application.py
├── test_settings.py
└── test_system_endpoints.py

scripts/   quality and Docker helpers
.ai/       00–08 project documentation
```

---

## 3. Capability index

| Capability | Status | Primary implementation | Primary tests |
|------------|--------|------------------------|---------------|
| Application factory | CURRENT | `src/app/main.py` | `tests/test_application.py` |
| System API | CURRENT | `src/app/api/system.py` | `tests/test_system_endpoints.py` |
| Configuration | CURRENT | `src/app/settings.py` | `tests/test_settings.py` |
| Logging setup | CURRENT | `src/app/logging_config.py` | via app factory tests |
| LLM invocation (optional) | CURRENT (unwired) | `src/app/llm/openai_wrapper.py` | `tests/llm/test_openai_wrapper.py` |
| OpenAI client construction | CURRENT (unwired) | `src/app/llm/openai_provider.py` | `tests/llm/test_openai_provider.py` |
| Application exceptions | CURRENT | `src/app/exceptions.py` | LLM tests |
| Document pipeline / UI / persistence / auth / AWS | NOT_IMPLEMENTED | — | — |

---

## 4. Capability profiles

### 4.1 Application factory

**Status:** CURRENT

Creates FastAPI app with injected or default settings; configures logging; registers system routes. Does not construct external clients or workers.

| Path | Symbols |
|------|---------|
| `src/app/main.py` | `create_app`, `app` |

**In-memory state:** `app.state.settings` holds the resolved `Settings` for that app instance.

---

### 4.2 System API

**Status:** CURRENT

| Path | Endpoints |
|------|-----------|
| `src/app/api/system.py` | `/health`, `/ready`, `/version` |

`/ready` = foundation readiness (configured environment + version), not document-processing or AWS readiness.

Historical smoke results belong in [03](03_common_handoff.md).

---

### 4.3 Configuration

**Status:** CURRENT

| Path | Symbols |
|------|---------|
| `src/app/settings.py` | `Settings`, `get_settings` |

`APP_ENV`, `APP_VERSION`, and `LOG_LEVEL` are **defaulted configuration fields**. They may be overridden via environment variables; they are **not** variables the user must always supply.

Optional OpenAI fields: `OPENAI_API_KEY` (optional), `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`. Absence of the key must not prevent app start.

`get_settings()` is an in-memory LRU-cached default provider. That is configuration state, not durable product/job persistence.

```text
No database ≠ no state
```

---

### 4.4 Logging

| Path | Symbols |
|------|---------|
| `src/app/logging_config.py` | `configure_logging` |

---

### 4.5 Optional LLM asset

**Status:** CURRENT as reusable asset; **unwired** to product flows. Hardening/redesign **DEFERRED**.

| Path | Responsibility |
|------|----------------|
| `src/app/llm/openai_provider.py` | `create_async_openai_client` constructs `AsyncOpenAI` for the composition caller |
| `src/app/llm/openai_wrapper.py` | `AsyncOpenAIWrapper` accepts an **already constructed** injected client; orchestrates calls, retries, guardrails |
| `src/app/llm/guardrails.py` | Deterministic guardrails |
| `src/app/exceptions.py` | Typed errors used by the wrapper |

**Correct composition / dependency direction:**

```text
Composition caller (app code, script, or test)
→ create_async_openai_client(...) OR fake client
→ inject client into AsyncOpenAIWrapper
→ wrapper uses AsyncOpenAIClientProtocol methods (chat/completions)
```

The wrapper does **not** call the protocol to construct a client. The provider factory constructs the client; the wrapper consumes the injected client.

Implemented facilities (guardrails, retries, timeouts, typed results) exist in code and are covered by fake-based unit tests. Desired future correctness improvements remain deferred and must not be confused with current product extraction quality ([02](02_code_quality_standards.md) §32, [07](07_extraction_evaluation.md)).

**Tests:** `tests/llm/*` (no network). These do not establish extraction accuracy.

---

## 5. Cross-cutting maps

### Dependency direction (actual)

```text
main.py → settings, logging_config, api.system
api.system → settings via app.state
llm (optional) → exceptions + injected client; no product routes
```

### State

| Kind | Location | Notes |
|------|----------|-------|
| In-memory settings cache | `get_settings` LRU cache | Process-local |
| Per-app settings | `app.state.settings` | Set by `create_app` |
| Durable product/job state | NONE | No persistence layer |

### External integrations

| Provider | Status | Notes |
|----------|--------|-------|
| OpenAI | Optional asset | Only when a caller composes wrapper + real key; not required at boot; not in product document flows |

### Runtime entry points

| Purpose | Location |
|---------|----------|
| Local API | `.\scripts\dev.ps1` / uvicorn `app.main:app` |
| Quality | `.\scripts\quality.ps1` |
| Docker | `.\scripts\docker-up.ps1` / `docker compose` |

Command results: [03](03_common_handoff.md).

---

## 6. Change-impact notes

| If changing... | Also inspect... |
|----------------|-----------------|
| `create_app` / system routes | settings, endpoint tests, readiness semantics |
| Settings defaults/fields | `.env.example`, provider construction, settings tests |
| LLM wrapper | provider factory, injection contract, guardrails, exceptions, `tests/llm/*` |
| Docker/runtime | health/ready semantics, Compose, non-root user |

---

## 7. Known gaps (map-relevant)

| Gap | Status | Handling |
|-----|--------|----------|
| Document-processing pipeline | NOT_IMPLEMENTED | Design in M-Design → [05](05_pipeline_contracts.md) |
| Review/graph UI | NOT_IMPLEMENTED | Approved target |
| Persistence / auth / AWS topology | NOT_IMPLEMENTED | Open detail; AWS direction approved in [00](00_project_reference.md) |
| LLM wired to extraction | NOT_IMPLEMENTED | Hardening deferred |

---

## 8. Compact snapshot

```text
ENTRY → src/app/main.py::create_app
CURRENT → System API; Settings (in-memory); Logging; optional unwired LLM
STATE → in-memory config only; no durable product persistence
EXTERNAL IN PRODUCT FLOWS → NONE
TESTS → tests/test_*.py; tests/llm/* (not extraction accuracy)
GAP → no upload/OCR/extraction/review/graph implementation
```
