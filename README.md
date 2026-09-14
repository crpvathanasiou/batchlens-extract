# BatchLens Extract

## Project Overview

BatchLens Extract is a pharmaceutical manufacturing-record digitization service.

Its product goal is to transform Master Batch Records (MBRs) and executed batch records into a structured, inspectable recipe representation. The intended output includes materials, equipment, process steps, process parameters, values, units, and source references back to the uploaded document.

The application foundation currently provides a production-oriented FastAPI baseline. Product capabilities such as document upload, PDF/OCR processing, extraction, review, graph visualization, persistence, authentication, and AWS deployment are planned work; they are not implemented yet.

## Product Direction

The planned BatchLens Extract workflow is:

```text
Manufacturing record PDF
    → document processing and extraction
    → structured recipe data
    → BOM / equipment reconciliation
    → source-linked JSON result
    → tabular and interactive recipe graph views
```

The system will support two usage modes:

* **Automatic mode:** returns the machine-generated result, including uncertainties and unresolved findings, without requiring human review.
* **Reviewed mode:** allows a user to inspect and correct extracted information before using the result downstream.

BatchLens Extract does not approve batch release and does not certify FDA, GMP, or overall regulatory compliance. A separate future product, **BatchLens Audit**, will evaluate structured recipe or batch data through deterministic and semantic checks.

## Current Scope

The current repository contains the application foundation only:

* FastAPI application built through a `create_app(settings)` factory under `src/app`
* validated Pydantic settings for `APP_ENV`, `APP_VERSION`, and `LOG_LEVEL`
* standard-library structured logging under the `app` namespace
* system endpoints: `/health`, `/ready`, and `/version`
* quality gates: Ruff lint, Ruff format, Pyright strict, and pytest
* Docker multi-stage image and single-service Docker Compose configuration
* optional reusable async OpenAI LLM wrapper under `src/app/llm`

## Requirements

* Python 3.11.x
* Poetry 2.2.1
* Docker Desktop for the container workflow

## Local Setup

From Windows PowerShell:

```powershell
poetry config virtualenvs.in-project true
poetry install
```

Create a local `.env` only when configuration values need to be overridden:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env` files or API keys.

## Environment Configuration

| Variable                 | Allowed values                                  | Default        |
| ------------------------ | ----------------------------------------------- | -------------- |
| `APP_ENV`                | `local`, `dev`, `staging`, `prod`               | `local`        |
| `APP_VERSION`            | Non-empty string                                | `0.1.0`        |
| `LOG_LEVEL`              | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO`         |
| `OPENAI_API_KEY`         | Optional                                        | None           |
| `OPENAI_MODEL`           | Model identifier                                | `gpt-4.1-mini` |
| `OPENAI_TIMEOUT_SECONDS` | Positive number                                 | `20.0`         |
| `OPENAI_MAX_RETRIES`     | Non-negative integer                            | `2`            |

Invalid application settings fail at startup.

## Run Locally

```powershell
.\scripts\dev.ps1
```

Or run Uvicorn directly:

```powershell
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Quality Checks

```powershell
.\scripts\lint.ps1
.\scripts\format-check.ps1
.\scripts\format.ps1
.\scripts\typecheck.ps1
.\scripts\test.ps1
.\scripts\quality.ps1
```

`quality.ps1` runs linting, formatting verification, type checking, and tests in sequence.

## Run with Docker

```powershell
.\scripts\docker-up.ps1
.\scripts\docker-down.ps1
```

Or run Docker Compose directly:

```powershell
docker compose up --build
docker compose down
```

The application is served on port `8000`.

## System Endpoints

| Endpoint       | Purpose                                                            |
| -------------- | ------------------------------------------------------------------ |
| `GET /health`  | Process liveness: `{"status": "ok"}`                               |
| `GET /ready`   | Current application-foundation readiness, environment, and version |
| `GET /version` | Configured application version                                     |
| `GET /docs`    | Interactive OpenAPI documentation                                  |

## Repository Documentation

Long-lived project documents live under `.ai/`:

* `00_project_reference.md`
* `01_implementation_roadmap.md`
* `02_code_quality_standards.md`
* `03_common_handoff.md`
* `04_code_map.md`

These documents must distinguish implemented capabilities from approved target architecture and deferred work.

## Current Non-Goals

The current baseline does not yet implement:

* PDF or scanned-document upload
* OCR, document parsing, or recipe extraction
* BOM or equipment-log identification and reconciliation
* structured recipe JSON output
* human review and correction workflows
* interactive recipe graph visualization
* regulatory audit checks
* persistence, queues, workers, authentication, authorization, or AWS infrastructure

These capabilities will be added through small, verified implementation milestones.
