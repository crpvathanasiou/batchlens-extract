# BatchLens — Stage 1 documentation task

Write a clear, high-level document describing the **currently implemented Stage 1: PDF conversion to HTML, human review, and approval** in this repository.

This is a documentation-only task. Inspect the implementation, then write the document. Do not implement features, redesign the workflow, or produce an implementation plan. No intermediate understanding-report or approval round is needed.

## Audience, language, and length

The primary reader is another LLM, such as ChatGPT, entering a new session without this conversation. The document must be a self-contained stage overview that establishes what Stage 1 does, its boundaries, the order of execution, the role of human review, and the artifacts passed to the next stage. It should also be readable by the product owner. Write a description of the current system, not instructions for the receiving LLM to implement it.

- Write the entire document in **English**, using clear, precise language and consistent terminology. Briefly explain project-specific terms on first use; assume no previous session context.
- Target **2–3 ordinary A4 pages**, approximately **900–1,200 English words**. Markdown does not have fixed pagination; use the word range as a practical guide. Do not produce a half-page summary or an extensive technical specification.
- Use connected paragraphs, short headings, and one numbered workflow. Use a small table only if it clarifies the outputs.
- Explain behavior and purpose. Include exact artifact names and essential identity/status terms when they prevent ambiguity for a consuming LLM. Avoid code listings, commands, API route inventories, class/function explanations, full schemas, and implementation internals.

## Ground the document in the repository

Follow the repository instructions, including applicable `AGENTS.md` files. Use the following explicit reading order. The supplied code map is a navigation aid; repository code is authoritative for implemented behavior. Current handoff records establish reported acceptance status; passing tests or human approval must not be inferred from code existence.

### A. Read the project anchors first

1. `.ai/03_common_handoff.md` — current state, recorded checks, acceptance, and remaining work.
2. `.ai/00_project_reference.md` — purpose, stage boundaries, and product terminology.
3. `.ai/04_code_map.md` — code locations and responsibilities. The supplied attachment `04_code_map(1).md` is a copy of this map, not a new repository path.
4. `.ai/01_implementation_roadmap.md` — only the conversion, review, and history sections needed to distinguish completed work from plans.
5. `.ai/02_code_quality_standards.md` — applicable documentation/work rules.

List the remaining files in `.ai/` and consult relevant pipeline, security, evaluation, or check-selection sections only when needed to resolve a Stage 1 question. Do not treat future design described there as implemented functionality.

### B. Verify the Stage 1 behavior in these files

| Area | Files to consult | What to establish |
|---|---|---|
| Conversion | `src/app/document_conversion/contracts.py`, `adapter.py`, `provider.py`, `aws.py`, `textractor_renderer.py`, `tolerance.py` (all under that same directory) | OCR/conversion responsibilities, canonical document, original HTML, warnings, and preserved source content. |
| Job lifecycle and entry | `src/app/document_jobs/service.py`, `worker.py`, `contracts.py`; `src/app/api/documents.py` | How a PDF enters, processing order, job states, partial results, and original artifacts. |
| Review semantics | `src/app/document_review/README.md`, `contracts.py`, `mapping.py`, `service.py`, `rendering.py`; `src/app/api/document_reviews.py` | Editing boundaries, canonical reviewed content, saves, decisions, page/document approval, export, and reviewed HTML provenance. |
| Save reliability and history | `src/app/document_review/operations.py`, `history.py`, `history_jsonl.py`, `storage.py` | Persisted revisions versus derived history, repeated saves, conflict handling, and which actions are traceable. Explain only their user-visible consequences. |
| User interface | `frontend/src/state.ts`, `pendingSave.ts`, `mapping.ts`, `extensions.ts`, and the relevant files in `frontend/src/components/` | What the user actually sees and can do; navigation, text editing, findings, save recovery, and approval controls. |
| Local versus production wiring | `tests/document_review/local_harness.py`, `local_store.py`; `src/app/document_jobs/composition.py`, `auth.py`; `src/app/document_review/composition.py`; `src/app/main.py` | Real application behavior reused by the harness, substituted local services, and production integration boundaries. |

Read relevant sections rather than copying these files into the document. If a path has moved, locate its current equivalent using the code map and repository search; do not invent missing modules.

### C. Cross-check behavior and the handoff boundary

- Consult the relevant cases in `tests/document_review/test_backend_review.py`, `test_rendering.py`, `test_save_operations.py`, `test_local_harness.py`, `test_history_projection.py`, `test_history_jsonl.py`, and `test_local_history.py`, plus focused `frontend/tests/` cases where UI behavior needs confirmation.
- Locate conversion/job tests through the code map or repository search only where needed.
- For the downstream interface only, inspect `src/app/lexical_extraction/html_reader.py` and the reviewed-HTML input definitions in `src/app/lexical_extraction/contracts.py`. Establish what the next stage consumes and validates; do not document its matching or extraction logic.
- An artifact's provenance fields, its byte hash, and proof of human approval are different things. Describe only the guarantees the producer and consumer actually establish. Do not imply that metadata alone proves approval or that an exported JSON necessarily contains a persisted pointer to the exact HTML bytes.

Investigate only enough to establish the actual workflow. Do not scan unrelated extraction or knowledge-data components. Do not run conversion jobs, call paid services, change application code, or add tests for this task.

The following are questions to verify, **not facts to assume**:

- How is the original PDF supplied, and what actually performs text/table recognition and conversion? Mention the active service or tool briefly if relevant; distinguish available alternatives from the current path.
- Is the whole document converted before review? What page structure and connection to the original PDF are retained?
- What roles do the intermediate structured data and generated HTML play? Which representation is edited, saved, and exported?
- What can the reviewer view and correct? Are findings or suggestions shown, and what decisions does the user make about them?
- What happens when a draft is saved, the browser reloads, a page is approved, or approved content is edited again? State the actual approval-invalidation behavior and its scope.
- What conditions enable document approval and export? Are these one action or distinct steps in the current UI?
- Which revision is approved, which files are exported, and how are those files tied to the reviewed content?
- What history of changes, decisions, revisions, and approvals is actually retained? Do not infer capabilities from a planned observability feature.
- Which parts operate in the local review harness and which are integrated into the application? Do not present a local test path as a complete deployed product.

If a point is not established by available evidence, omit the unsupported detail or state the narrow limitation. Complete the document using what can be verified. Ask a question only if the repository is unavailable or a central ambiguity makes the description materially misleading.

## Required document structure

Use the title **“BatchLens — Stage 1: PDF Conversion, Human Review, and Approval”**.

### 1. Purpose and boundaries

Explain the problem Stage 1 solves and its start/end points. Make clear that conversion and document review prepare a reliable reviewed representation; they are distinct from later semantic or lexical extraction of materials, equipment, operations, and parameters.

### 2. Input and conversion

Describe what enters the stage and how the PDF becomes readable, reviewable content. Explain the role of HTML and any structured intermediate representation in plain language. Describe retained pages, text, and tables only to the extent implemented. Avoid promising perfect OCR or exact visual reproduction.

### 3. The user journey, step by step

Provide a numbered sequence from receiving the PDF to producing the approved output. For each step, explain briefly **what the system does, what the user does, and what allows the workflow to move forward**. Keep automatic conversion, review navigation, editing, saving, page approval, and final export distinguishable. Reflect the actual flow rather than imposing a new one.

### 4. What approval means

Explain draft versus approved content, page-level versus whole-document approval where implemented, what happens after an edit, and the conditions for final export. State plainly that document-review approval does not by itself constitute manufacturing batch release, regulatory approval, or validation of downstream extraction.

### 5. Saving and traceability

Describe what is preserved so work is not lost and reviewed versions remain identifiable. Explain, at a business level, which user actions and approvals can be traced. Do not claim a complete regulatory audit trail, electronic-signature system, immutable storage, or production security unless verified and necessary to this overview.

### 6. Outputs and handoff

Identify the actual final outputs, their purpose, and which reviewed artifact becomes the input to the next stage. Distinguish the original PDF, conversion artifacts, saved review state, and exported reviewed HTML/JSON as applicable. Do not imply every available export is a mandatory downstream input. Do not describe the next stage's algorithm.

### 7. Current completion boundary

Close with a short, concrete description of when Stage 1 is finished from the user's perspective. Include only material current limitations, such as a local-only entry point or missing integration, if verified. No roadmap or proposed enhancements.

## Deliverable and completion check

Create `docs/BatchLens-Stage1-Overview-EN.md`, or update that exact file if it already exists. Modify no other project files.

Before finishing, check that an LLM with no prior conversation can answer: What enters? What happens automatically and in what order? What does the human review and correct? What does Save preserve? How do conversion status and review approval differ? What happens after another edit? What comes out, what does the next stage consume, and when is Stage 1 complete? Clearly distinguish implemented behavior, recorded verification/acceptance, and remaining limitations without introducing a new status framework.

Keep an unobtrusive final source note naming at most 5–8 relevant repository files, outside the main narrative. Record the inspected commit if available and indicate whether local changes were present. Do not describe tests as executed unless you actually ran them; reading tests establishes expected behavior, not successful execution.

In your chat response, return only the document path, approximate word count, and any material uncertainty that remains. Do not paste a second long report or begin implementation.
