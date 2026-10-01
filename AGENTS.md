# AGENTS.md

BatchLens Extract prepares pharmaceutical manufacturing PDFs into evidence-preserving reviewed documents, lexical extraction results, and extraction-result review—then source-linked structured recipe data.

## Read first

1. [`.ai/03_common_handoff.md`](.ai/03_common_handoff.md) — current execution state and next action
2. [`.ai/00_project_reference.md`](.ai/00_project_reference.md) — product purpose, two-leg model, boundaries
3. [`.ai/04_code_map.md`](.ai/04_code_map.md) — where code and responsibilities live
4. Task-relevant remaining `.ai/` files listed in `00` (do not reread all nine for a small edit)
5. For Stage 4 work, also read:
   - [`docs/BatchLens-Stage4-Page-Classification-Overview-EN.md`](docs/BatchLens-Stage4-Page-Classification-Overview-EN.md)
   - [`docs/BatchLens-Stage4-Detailed-Local-Guide-EN.md`](docs/BatchLens-Stage4-Detailed-Local-Guide-EN.md)

## Authority

- Repository code and tests are the source of truth for implementation.
- Existing local-harness / manual-acceptance evidence is the source of truth for manually verified behaviour.
- `.ai/00` explains why and what. `.ai/01` explains order and milestones. `.ai/02` explains how work must be performed. `.ai/04` explains where code lives. `.ai/03` is the cross-session restart anchor.
- This file is a navigation layer only. Do not treat it as a second handoff, roadmap, or code map. Do not duplicate Stage 4 technical detail here; use `.ai/03` and the two Stage 4 documents above.

## Hard boundaries

- Do not change conversion, Textractor, review, API, storage, frontend, Docker, AWS/IAM, or test behaviour unless the task explicitly requires it.
- Do not claim 21 CFR Part 11 compliance, production qualification, or real AWS integration without separate validation evidence.
- Document-review approval is not batch release or a regulatory electronic signature.
- Stages 1, 2, and 3 are **locked baselines**. Do not reopen, redesign, or weaken them without a separately authorized task.
- **Stage 3 — Extraction Review Workspace** (U1–U3 local slice) is **implemented**, **test-verified**, and **manually verified** under `src/app/extraction_review/`, local harness routes, and the Vue extraction-review workspace: current-state contracts/transitions; one `current-review.json` per `local_job_id`; U2 approved-document selection and local Stage 2/L13 jobs; local UI/API open/edit/save/TXT/approve with per-run isolation. Stage 2 remains the independent Lexical Extraction Engine. Stage 1 document approval is unchanged. Stage 3’s single final human action remains **Approve extraction result**. Not in that mini-project / still deferred: production API mount/auth, duplicate-upload/fingerprint/reuse workflows, SQLite review store, LLM entity extraction, graph/association work, automatic approval, or review/approval history.
- **Stage 4 — Page Classification and Extraction Routing** local MVP is **implemented**, **test-verified**, and has **recorded local** end-to-end acceptance (configured OpenAI classification plus classified **Extract All** on the extraction-review harness). That is not a production mount/authentication or model-quality guarantee. Principal code: `src/app/page_classification/`, `src/app/extraction_review/stage4_local.py`, classified Extract All in `local_jobs.py`, harness API routes, and the Vue extraction-review workspace.
  - Input is only Stage 1 approved/reviewed HTML v1 and existing reviewed-document/page provenance. Do not invent a new PDF/page identity or rewrite reviewed HTML bytes.
  - Three locked structured classifier calls per page through the existing `app.llm` wrapper. Do not redesign the wrapper or add another client, provider abstraction, model-selection framework, vision path, or prompt framework without separate authorization.
  - Locked contracts: fixed labels/prompts/schemas; quote and reason 1–240 characters; order-independent label/evidence validation with evidence matched by its own `label`; application-only `OTHER_UNCLASSIFIED`.
  - Source-aware evidence validation proves location, not semantic correctness. Page-local exact identifiers use `id`, `data-node-id`, `data-element-id`, or `data-table-id`. Unverified evidence is preserved, requires review, and does not independently exclude a page.
  - Current-state-only local classification per reviewed-HTML identity; bounded diagnostic bundles; no classifier history, approval, editing, retry UI, SQLite classification store, generic queue, or cross-process locking. The worker guard is in-process per data directory only.
  - **Extract All** maps to existing Stage 2 `full` only for classifier-eligible pages via the narrow optional allow-list. Absent an allow-list, Stage 2 behavior is unchanged. Classified jobs keep an immutable classification snapshot and Stage 2 restriction provenance.
  - Classification status, per-page extraction eligibility, Stage 2 processing/publication status, and Stage 3 final human approval stay distinct. Classification labels are informational and do not change **Approve extraction result**.
  - The local Stage 3/4 workspace is not production-mounted/authenticated. Do not add classifier approvals, page approvals, automatic approval, classifier-label editing, LLM entity extraction, graph/association/recipe logic, or audit/history features without a separately authorized task.
- Pharmaceutical recipe assembly, the rules/Audit layer, and the audit ledger are not implemented.

## Evidence vocabulary

Use these labels exactly and do not promote one to another without evidence:

- **implemented** — code exists in this repository
- **test-verified** — automated tests or recorded quality gates passed
- **manually verified** — recorded local/human acceptance for that specific behaviour
- **unverified** — not proven by code tests, local acceptance, or live integration

## After an accepted change

Update the existing `.ai` documents that own the changed facts. Do not create a parallel documentation system.
