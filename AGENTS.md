# AGENTS.md

BatchLens Extract prepares pharmaceutical manufacturing PDFs into evidence-preserving reviewed documents and, later, source-linked structured recipe data.

## Read first

1. [`.ai/03_common_handoff.md`](.ai/03_common_handoff.md) — current execution state and next action
2. [`.ai/00_project_reference.md`](.ai/00_project_reference.md) — product purpose, two-leg model, boundaries
3. [`.ai/04_code_map.md`](.ai/04_code_map.md) — where code and responsibilities live
4. Task-relevant remaining `.ai/` files listed in `00` (do not reread all nine for a small edit)

## Authority

- Repository code and tests are the source of truth for implementation.
- Existing local-harness / manual-acceptance evidence is the source of truth for manually verified behaviour.
- `.ai/00` explains why and what. `.ai/01` explains order and milestones. `.ai/02` explains how work must be performed. `.ai/04` explains where code lives. `.ai/03` is the cross-session restart anchor.
- This file is a navigation layer only. Do not treat it as a second handoff, roadmap, or code map.

## Hard boundaries

- Do not change conversion, Textractor, review, API, storage, frontend, Docker, AWS/IAM, or test behaviour unless the task explicitly requires it.
- Do not claim 21 CFR Part 11 compliance, production qualification, or real AWS integration without separate validation evidence.
- Document-review approval is not batch release or a regulatory electronic signature.
- Pharmaceutical extraction, the rules/Audit layer, and the audit ledger are not implemented.

## Evidence vocabulary

Use these labels exactly and do not promote one to another without evidence:

- **implemented** — code exists in this repository
- **test-verified** — automated tests or recorded quality gates passed
- **manually verified** — recorded local/human acceptance for that specific behaviour
- **unverified** — not proven by code tests, local acceptance, or live integration

## After an accepted change

Update the existing `.ai` documents that own the changed facts. Do not create a parallel documentation system.
