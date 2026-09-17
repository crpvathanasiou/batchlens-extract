# BatchLens Extract

## Project Overview

BatchLens Extract is a pharmaceutical manufacturing-record digitization service.

It has two product legs: (1) evidence-preserving document preparation and review, which this
repository currently implements, and (2) pharmaceutical information extraction, which remains
future work. The intended later output includes materials, equipment, process steps, process
parameters, values, units, and source references back to the uploaded document.

The current implemented flow is:

```text
source PDF → Textract raw result → Textractor/conversion → canonical document.json + HTML
  → optional human review/revisions/approvals → reviewed HTML/JSON exports
```

Conversion uses AWS Textract, durable DynamoDB job state, versioned S3 artifacts, Cognito
ownership, and a Vue/TipTap/PDF.js review workspace. That composition exists in code and is not
claimed as production-qualified or live-AWS verified. Recipe extraction, graph visualization, and
a rules/Audit layer remain outside this slice. Document-review approval is not batch release or a
21 CFR Part 11 electronic signature.

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

The repository contains:

* FastAPI application built through a `create_app(settings)` factory under `src/app`
* validated Pydantic settings for `APP_ENV`, `APP_VERSION`, and `LOG_LEVEL`
* standard-library structured logging under the `app` namespace
* system endpoints: `/health`, `/ready`, and `/version`
* quality gates: Ruff lint, Ruff format, Pyright strict, and pytest
* Docker multi-stage image and single-service Docker Compose configuration
* optional reusable async OpenAI LLM wrapper under `src/app/llm`
* asynchronous PDF conversion with durable DynamoDB/S3/SQS state and Cognito ownership
* automatic original `document.json`/HTML delivery, explicitly unreviewed
* optional immutable review revisions, per-page approval, findings decisions, and reviewed exports
* a persistent AWS-free local acceptance harness using the actual review service and Vue bundle

## Requirements

* Python 3.11.x
* Poetry 2.2.1
* Node.js 22.12 or newer for the review frontend build (verified with 22.12.0)
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

Long-lived project documents live under `.ai/`. Start at `.ai/03_common_handoff.md`, then
`.ai/00_project_reference.md` and `.ai/04_code_map.md`. `AGENTS.md` is a short navigation layer
only.

These documents must distinguish implemented capabilities from approved target architecture and deferred work.

## Current Non-Goals

This review slice does not implement recipe extraction, graph visualization, batch release,
regulatory approval, 21 CFR Part 11 signatures, collaboration, an additional identity/database
service, or a persistent audit ledger.


## Optional asynchronous document conversion

The authorized PDF-to-HTML reference slice is integrated and disabled by default.
Start with [the component README](src/app/document_conversion/README.md),
[offline examples](examples/document_conversion/README.md),
and [the AWS operator guide](infra/document_conversion/AWS_SETUP.md).
See [VERIFICATION.md](VERIFICATION.md) for local checks and unperformed cloud/fidelity gates.
The existing optional LLM wrapper remains unchanged and unwired.

## Local document-review acceptance

The harness needs no AWS configuration, credentials, Cognito sign-in, worker, OCR run, or IAM
change. It reuses the real review service, API, validation, mapping, frontend bundle, and export
logic. It substitutes only identity (`local-test-reviewer`) and file-backed storage, binds to
localhost, and uses synthetic job `local-fexofenadine`. It reads the four supplied originals
without modifying them and stores generated review state under `.local-review-data/` (default
`.local-review-data/fexofenadine/`). It does not verify Cognito, DynamoDB conditionals, S3
versioning, or AWS deployment.

Local visual/functional acceptance of the behaviours listed in `.ai/03_common_handoff.md` is
complete. Unsaved browser edits are not promised to survive browser closure. Restart with the same
command and data directory. A changed input is rejected instead of resetting existing review
history. Use a different `--data-dir` when inputs change.

```powershell
Set-Location C:\Users\User\batchlens-extract
npm --prefix frontend ci
npm --prefix frontend run build
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-textractor-20260916-173938/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-textractor-20260916-173938/document.html" --data-dir ".local-review-data/fexofenadine" --port 8765
```

Open `http://127.0.0.1:8765/documents/local-review`. Saved revisions and exports survive browser
reload and process restart.

For production, enable the existing document feature and supply its documented `DOCUMENT_*`
configuration. The API role must receive the prepared review-prefix `s3:PutObject` template update
through the normal deployment workflow before deployed review saves can work. See
`src/app/document_review/README.md` and `infra/document_conversion/AWS_SETUP.md`.
