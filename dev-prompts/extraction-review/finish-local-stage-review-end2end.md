# Finish the local Stage 3 MVP end-to-end path

This task closes the missing runnable path for the already implemented Stage 3 Extraction Review Workspace.

Do not redesign Stage 1, Stage 2, U1, U2, or the existing Stage 3 UI/API. Do not add documentation updates, SQLite, history, revisions, extra approvals, queues, authentication, graph work, LLM work, or production deployment.

Read first:

- `AGENTS.md`
- `.ai/02_code_quality_standards.md`
- `.ai/03_common_handoff.md`
- existing `src/app/extraction_review/`, its tests, and `tests/extraction_review/local_harness.py`
- the existing frontend entry point and `ExtractionReviewWorkspace.vue`.

## The only goal

A user must be able to run one local command which:

1. Selects one approved/reviewed HTML document.
2. Executes the existing U2 lexical job for it.
3. Waits for the job to reach a terminal state.
4. Starts the existing Stage 3 local UI.
5. Opens the selected document with its findings and highlights.

The user must not create job JSON files manually or run Python service methods interactively.

## Required command

Extend the existing Stage 3 local harness, rather than creating another tool.

Support this workflow:

```powershell
poetry run python -m tests.extraction_review.local_harness `
  --data-dir <local-data-dir> `
  --approved-documents-root <approved-root> `
  --job-id <job-id> `
  --review-revision-id <review-revision-id> `
  --config <existing-lexical-config.yaml> `
  --action full `
  --run-extraction
```

Keep existing harness behaviour when `--run-extraction` is absent: it opens already completed jobs from the supplied `data-dir`.

The approved document remains in the existing required location:

```text
<approved-root>/<job-id>/<review-revision-id>/document.html
```

Never copy, rewrite, or modify this HTML.

## `--run-extraction` behaviour

Implement only this small orchestration in the local harness:

- Validate the selected approved document through the existing U2.1 registry.
- Submit exactly one existing U2.2 `LocalLexicalJobService` job using:
  - the supplied approved-document root,
  - supplied `job_id` and `review_revision_id`,
  - supplied existing lexical config,
  - selected existing action (`full`, `unit_operations_with_steps`, `materials_with_quantities`, or `equipment_with_parameters`),
  - fuzzy disabled by default.
- Wait with a simple bounded polling loop until the persisted job becomes `completed`, `failed`, or `interrupted`.
- On `completed`, close the U2 job service cleanly, then start the existing Stage 3 FastAPI/Vue harness using the same `data-dir` and approved root.
- On `failed`, `interrupted`, timeout, or user interruption, print a short truthful error and exit non-zero. Do not start the UI.
- Do not run two extraction workers concurrently. Reuse the existing U2.2 one-active-worker-per-data-directory behaviour.
- Print the exact final local URL and selected local job ID.

Do not add a second job UI, a queue, a database, or a new worker implementation.

## Keep the existing workspace behaviour

Once the browser opens, retain the existing minimal workspace exactly:

- HTML page left; current page’s findings right.
- Findings highlight/focus their evidence.
- Page navigation.
- All findings is read-only and navigates to the selected finding’s page.
- Add/edit/remove only on the current page.
- Save persists one current JSON state.
- One `Approve extraction result` action only.
- Effective Save after approval returns status to Not approved.

The existing frontend export must remain correct:

```ts
mountExtractionReviewWorkspace
```

The built bundle and the harness bootstrap must use the same name.

## Required tests and verification

Add only focused regression coverage for:

1. Harness argument validation: `--run-extraction` requires `--config`, `--job-id`, and `--review-revision-id`.
2. A successful submitted job is awaited, its service is closed, and then the UI app is created with the same paths.
3. Failed/interrupted/timed-out jobs do not start the UI and return non-zero.
4. Existing non-`--run-extraction` harness behaviour remains intact.
5. The built bundle still exports both `mountReviewWorkspace` and `mountExtractionReviewWorkspace`.

Then:

- build the frontend bundle;
- run the required Python and frontend checks;
- run `--help` and include the exact final PowerShell command template in the completion report;
- do not claim browser acceptance unless it was actually performed.

Run the required checks and stop with the completion report.