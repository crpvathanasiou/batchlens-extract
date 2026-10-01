# BatchLens Stage 1 — Detailed documentation and local execution guide

## Task and deliverable

Create `docs/BatchLens-Stage1-Detailed-Local-Guide-EN.md`: a self-contained **English** technical explanation and practical local execution guide for Stage 1, covering conversion artifacts, human review, saving, history, approval, and approved exports.

The primary audience is another LLM, such as ChatGPT, starting a new session, and the developer using that LLM to understand and run this stage. Explain the actual implementation, not a proposed architecture. The accepted Stage 1 overview remains the short introduction; this new document explains the mechanisms, execution sequence, commands, expected results, and recovery procedures in more detail.

This is a documentation-only task. Proceed directly from repository inspection to the completed document. Do not create an implementation plan or another approval round.

## Hard scope: local execution only

- The document must contain **no AWS discussion, service topology, deployment instructions, credentials, account setup, or cloud execution alternatives**. This also applies to architecture diagrams and troubleshooting.
- Describe only the locally available path. If OCR must already have been performed, state that a saved OCR response is an input prerequisite. Do not present the local harness as a PDF OCR engine or imply that a PDF alone is sufficient.
- Exact local artifact names such as `textract.json`, parser/library names, and local command flags may be retained where necessary to run the code. Explain their local data-processing role without discussing their remote origin.
- Cover both supported local entry points: **A. saved OCR JSON → local conversion artifacts → review**, and **B. existing conversion artifacts → review**. Clearly identify their shared review workflow.
- Exclude lexical matching, extraction review UI, LLM processing, associations, knowledge-data preparation, and future feature design. Inspect the Stage 2 input boundary only to explain the handoff.
- Make no application changes. Do not install dependencies, rebuild assets, start servers, run conversion, execute tests, or modify user review data while writing this document. Commands are documented for later execution, not executed now.

## Read these sources

Follow applicable `AGENTS.md` instructions. Paths below are repository-relative. Use the current repository, not an attachment's archive layout. Locate renamed equivalents if needed; report missing essentials rather than inventing behavior.

### 1. Project anchors and accepted overview

Read in this order:

1. `.ai/03_common_handoff.md`: current and historical Stage 1 evidence, local commands, input sets, acceptance boundaries, and protected review directories. The opening section may concern another stage; find the Stage 1 sections.
2. `.ai/00_project_reference.md`: product purpose and stage boundaries.
3. `.ai/04_code_map.md`: component locations and responsibilities.
4. `.ai/01_implementation_roadmap.md`: relevant conversion/review/history milestones only.
5. `.ai/02_code_quality_standards.md`: applicable work and documentation rules, especially Documentation Standards and scope control.
6. Relevant sections of `.ai/05_pipeline_contracts.md` and `.ai/06_security_and_data_handling.md` only where needed for Stage 1 data semantics and local data handling. Future requirements are not implemented features.
7. The accepted `BatchLens-Stage1-Overview-EN.md`. Search by filename if it is not under `docs/`; an attachment may be named `BatchLens-Stage1-Overview-EN(1).md`. Preserve the accepted overview. Its broader context does not override this task's local-only scope.

The detailed guide complements `.ai/`: it joins the source-specific information into one runnable Stage 1 explanation. Do not duplicate the general coding standards, project roadmap, or chronological handoff log.

### 2. Implementation sources

| Area | Exact files or bounded directories to inspect |
|---|---|
| Local conversion | `src/app/document_conversion/__main__.py`, `adapter.py`, `contracts.py`, `provider.py`, `textractor_renderer.py`, `tolerance.py`, `README.md` — all under the same conversion directory. |
| Review contracts and behavior | `src/app/document_review/contracts.py`, `mapping.py`, `service.py`, `operations.py`, `rendering.py`, `README.md`. |
| History | `src/app/document_review/history.py`, `history_jsonl.py`; local persistence and rebuild behavior in `tests/document_review/local_store.py`. |
| Local composition | `tests/document_review/local_harness.py`, `local_store.py`; the routes mounted by the harness in `src/app/api/document_reviews.py` and relevant portions of `src/app/api/documents.py`. Inspect `src/app/document_jobs/contracts.py` for the job/artifact objects supplied by the harness, not for deployment. |
| Review UI | `frontend/src/api.ts`, `contracts.ts`, `state.ts`, `pendingSave.ts`, `mapping.ts`, `extensions.ts`; `frontend/src/components/ReviewWorkspace.vue`, `DocumentEditor.vue`, `FindingsPanel.vue`, `PdfPane.vue`. |
| Setup and build | `pyproject.toml`, relevant `poetry.lock` metadata, `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/README.md`; repository README and `examples/document_conversion/README.md` for local instructions if present. |
| Stage 2 boundary only | `src/app/lexical_extraction/html_reader.py` and reviewed-HTML input definitions in `src/app/lexical_extraction/contracts.py`. Do not follow the extraction pipeline beyond this boundary. |

### 3. Behavioral cross-checks

Read the relevant tests rather than running them:

- `tests/document_review/test_backend_review.py`, `test_rendering.py`, `test_save_operations.py`, `test_review_context.py`, `test_local_harness.py`.
- `tests/document_review/test_history_projection.py`, `test_history_jsonl.py`, `test_local_history.py`.
- Relevant tests under `frontend/tests/` for editing, pending saves, findings, and UI state.
- Locate the focused conversion/CLI tests using the code map or repository search.

Code establishes implemented behavior; tests establish specified expectations unless execution evidence exists. The handoff records what was actually checked and accepted. Do not claim a check was run during this documentation task. If evidence conflicts, explain the narrow current uncertainty.

## Required sections

Use the title **“BatchLens — Stage 1: Detailed Design and Local Execution Guide”** and the following nine sections. Use clear prose, focused tables, and short code blocks. There is no two-page limit for this detailed document; include the detail needed to execute and diagnose the stage without reproducing source code or full schemas.

### 1. Scope and current status

State the purpose, prerequisites, local start/end boundaries, and the distinction between implemented, test-verified, and manually accepted behavior. Explain that the local path requires saved recognition data or existing conversion artifacts. Document approval concerns the reviewed content, not manufacturing release or downstream extraction approval.

### 2. Components and responsibilities

Show how the offline converter, canonical document, review service, browser editor, local file store, history projection, and export renderer cooperate. Provide a compact responsibility table with the principal repository paths and one readable diagram if useful. Distinguish actual local components from abstractions supplied by the harness. Do not give a file-by-file code walkthrough.

### 3. Inputs, outputs, and persisted data

Provide an artifact table: name, producer, consumer, purpose, whether it is original or reviewed, and when it is written. Include:

- Original PDF; saved OCR response; canonical `document.json`; unreviewed `document.html` and per-page HTML where generated.
- Review head, immutable revision envelopes, local input manifest/context sidecar, derived `history.jsonl`, and approved HTML/JSON.
- The browser's editing projection and pending-save record, distinguishing these from authoritative persisted reviewed content.

Explain actual local directory layout, identity binding, and reuse of a data directory. Read `local_store.py` for exact paths rather than copying nonlocal paths from other adapters. Never advise deleting history or changing source files to bypass an input mismatch.

### 4. Execution flow in detail

Trace both local entry paths through to exported approval. For each meaningful step state input, responsible component, operation, output/state, and the condition for proceeding.

Explicitly identify synchronous versus asynchronous activity and any actual parallelism. The current offline CLI's `write_outputs` processes and renders pages single-threaded; verify this in the checkout. Do not infer parallel execution from the compatibility `--page-workers` flag. Distinguish browser HTTP requests from background jobs; only describe a local worker if one is actually started by this path.

Include failure boundaries: conversion failure, input mismatch, invalid edit, publication conflict, blocked approval, and history rebuild failure after a committed state change. Explain what persists and what the user should do next.

### 5. Review, saves, and approvals

Explain text-only editing, protected structure, findings and allowed decisions, transient versus saved draft, page approvals, final document approval, and invalidation after edits.

Describe optimistic concurrency, same-operation retry, and pending-save recovery in plain technical English. Idempotent retry requires the same operation ID and matching fingerprint; it is not an unconditional guarantee for every repeated Save. Separate unsubmitted editor changes, submitted-but-uncertain saves, and confirmed committed state. Do not recommend blindly discarding uncertain changes.

Give a compact state/action table using actual implementation terms. Keep conversion status, review status, revision action, and approval metadata distinct.

### 6. History and monitoring

Explain what committed revisions record, what can be reconstructed, and what operational logs show. Document `history.jsonl` coverage, `CURRENT` / `STALE` / `INVALID_OR_MISSING`, startup rebuild, and the fact that this file is derived rather than authoritative, after verification in code.

Explain the local failure case where the head is committed but rebuilding history fails: an error response does not necessarily mean the save was not committed. Explain safe recovery using the existing mechanisms. Do not claim an available history screen or a complete regulatory audit system.

### 7. Local execution guide — Windows PowerShell

Give a practical, ordered runbook from repository root `C:\Users\User\batchlens-extract`, with explicit working directory for each command. Keep command groups to 1–3 commands per step. Each step needs prerequisites and an observable expected result.

Cover:

1. Verify Python/Poetry and Node versions from repository configuration, and identify whether dependencies/static assets are already ready. Separate first-time setup, rebuilding after frontend changes, and ordinary restart. Prefer the repository's locked installation route; do not prescribe dependency upgrades.
2. Define task-specific PowerShell variables for input paths, conversion output, review data directory, and port. Avoid reserved variables. Validate path existence and keep one consistent input set through all commands.
3. **Path A — offline conversion:** show the exact existing CLI syntax. The inspected CLI accepts `offline <response> --output <directory> --source-id <identity>`; verify it. It reads the supplied OCR response and writes canonical JSON, full HTML, and per-page HTML. It does **not** create another raw `textract.json` in that output directory; pass the original response path to the harness. If source identity or response completeness needs preparation, explain the real requirement without inventing data.
4. **Path B — existing artifacts:** show how to skip conversion and supply the PDF, canonical JSON, raw OCR response, and original HTML directly. Do not substitute the approved review JSON for the bare conversion `Document` input.
5. Build frontend assets when needed, then show the full verified harness command with `--source`, `--document`, `--textract`, `--html`, `--data-dir`, and `--port`. Confirm flags in `local_harness.py` and show the corresponding localhost URL.
6. Complete review, save, approve pages, approve/export, and locate/download the resulting files. Include a small read-only HTTP or file check where it makes success observable.
7. Stop and restart normally, preserve inputs and review state, and distinguish resuming the same review from initializing an independent review. Use one harness process per writable data directory. An unused port must be checked, not assumed.

Use a currently coherent sample set if it exists. Historical sample paths in `.ai/03_common_handoff.md` are useful leads, not proof that files exist today. Preserve existing user review directories. Use an explicitly new directory for the worked test example, and show separately how to resume existing work with its original inputs.

If sample inputs are absent, supply clearly marked replacement variables and state the required files. Do not fabricate a successful startup. Document commands, but do not execute this runbook during the task. Include no deployment or remote-service commands.

### 8. Manual verification and troubleshooting

Provide a compact action/expected-result checklist: open PDF and converted content, edit/save/reload, approve a page, edit again and observe invalidation, block incomplete final approval, complete review/export, confirm the correction in both outputs, and restart with retained state. Only exercise findings if the selected sample contains them; absence of a particular warning is not automatically a UI failure.

Include a separate two-tab stale-revision/conflict check and a bounded pending-save recovery check in an isolated review directory. Describe how to observe the behavior without altering application code or deleting recovery evidence. Clearly mark these as procedures to perform, not completed checks.

Troubleshooting should map symptom → likely cause → read-only check → safe next action. Cover missing/stale frontend assets, occupied port, inconsistent inputs, page-count mismatch, unresolved findings, stale approvals, conflicts, uncertain save outcome, and missing/stale history. Use actual error codes only after verifying them. Do not include a full error catalogue or destructive reset instructions.

### 9. Handoff to Stage 2

Explain the reviewed HTML v1 contract, revision/job/generation metadata, page/node/source identifiers, and the exact artifact the consumer reads. Show a short representative metadata excerpt if useful, not a complete schema.

Distinguish canonical document hash, page/region hashes, and SHA-256 of the actual HTML bytes. Explain that identifying a revision is not independently proving human approval.

Verify the export ordering in `ReviewService.approve`: the downloadable JSON may contain `exports: null`, while the final persisted review envelope contains export pointers. Do not describe them as byte-identical files or imply the downloadable JSON independently proves the exact HTML-byte link. Finish with concrete completion criteria for the local stage, without starting Stage 2 execution.

## Completion and file boundaries

Create or update only `docs/BatchLens-Stage1-Detailed-Local-Guide-EN.md`. Leave the accepted overview, `.ai/`, source code, tests, dependencies, generated assets, and local review state unchanged. This document is a stage-specific companion, not a new authority replacing the current code or handoff.

Add a short source/verification note with inspected commit and working-tree state, the key paths consulted, the date of inspection, and any material unverified commands or missing inputs. Do not turn this into a second long report.

Before finishing, confirm:

- An LLM without prior context can explain and follow the complete local flow.
- All nine sections are present, and there is no AWS/deployment discussion.
- Commands match the current CLI/build/harness definitions and use coherent inputs.
- The guide does not promise PDF-only local OCR, automatic approval, or lossless recognition.
- Existing review state is preserved and uncertain saves are handled conservatively.
- The document distinguishes implementation evidence, historical acceptance, and instructions not executed in this task.

Return the document path, approximate word count, and only material unresolved limitations. Do not begin implementation or execute the documented workflow.
