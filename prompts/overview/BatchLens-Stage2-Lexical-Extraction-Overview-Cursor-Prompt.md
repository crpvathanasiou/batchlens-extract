# BatchLens — Stage 2 documentation task

Write a clear, high-level document describing the **currently implemented Stage 2: deterministic lexical extraction from an approved reviewed HTML document** in this repository.

This is a documentation-only task. Inspect the implementation and write the document. Do not implement features, redesign the engine, alter matching rules, create UI work, or produce an implementation plan. No intermediate understanding-report or approval round is needed.

## Current authority and baseline

L01–L13 of the lexical extraction engine are implemented, test-verified by recorded quality gates, and **user-accepted**. The current `.ai/03_common_handoff.md` may still say that L13 awaits acceptance because it predates the final user decision. For this task, the user-accepted L13 state is authoritative. Do not modify `.ai/` documents merely to reconcile that historical wording; this task changes only the requested overview document.

## Audience, language, and length

The primary reader is another LLM, such as ChatGPT, entering a new session without this conversation. The document must be a self-contained stage overview that establishes what Stage 2 consumes, what it deterministically produces, its evidence and provenance guarantees, its user-selectable execution scope, and its boundaries. It should also be readable by the product owner. Describe the current system, not instructions for the receiving LLM to implement it.

- Write the entire document in **English**, with clear, precise language and consistent terminology. Briefly explain project-specific terms on first use; assume no previous session context.
- Target **2–3 ordinary A4 pages**, approximately **1,000–1,300 English words**. Markdown does not have fixed pagination; use the word range as a practical guide. Do not produce a half-page summary or an extensive technical specification.
- Use connected paragraphs, short headings, one numbered workflow, and at most two small tables where they materially clarify execution choices or outputs.
- Explain user-visible behavior and purpose. Include exact artifact names and essential identity/status terms when they prevent ambiguity. Avoid code listings, commands, API-route inventories, class/function explanations, full schemas, algorithm pseudocode, and implementation internals.

## Ground the document in the repository

Follow the repository instructions, including applicable `AGENTS.md` files. The supplied code map is a navigation aid; repository code is authoritative for implemented behavior. Current handoff records establish reported acceptance and recorded checks; passing tests or human acceptance must not be inferred from code existence.

### A. Read the project anchors first

1. `AGENTS.md`, then `.ai/03_common_handoff.md` — current state, recorded checks, and lexical scope.
2. `.ai/00_project_reference.md` — product purpose, stage boundaries, and terminology.
3. `.ai/04_code_map.md` — lexical module locations and responsibilities.
4. `.ai/01_implementation_roadmap.md` — only the lexical stages needed to distinguish completed work from plans.
5. `.ai/02_code_quality_standards.md` — applicable documentation/work rules.
6. `.ai/05_pipeline_contracts.md` and `.ai/07_extraction_evaluation.md` — the approved pipeline/output contracts and recorded evaluation evidence.

List the remaining `.ai/` files and consult relevant security or data-handling guidance only where needed to resolve a Stage 2 question. Do not treat future UI, vector, LLM, graph, association, or orchestration design as implemented functionality.

### B. Verify the Stage 2 behavior in these files

Read relevant sections rather than copying them into the overview. If paths have moved, locate their current equivalent with the code map and repository search; do not invent missing modules.

| Area | Files to consult | What to establish |
|---|---|---|
| Input and evidence contracts | `src/app/lexical_extraction/contracts.py`, `html_reader.py`; relevant producer portions of `src/app/document_review/rendering.py` / `contracts.py` | The reviewed-HTML v1 boundary, validated producer metadata, pages/blocks, literal matched text, and code-point evidence offsets. |
| Execution configuration | `configuration.py`, `examples/lexical_extraction/execution-config.example.yaml` | The fixed presets/components, fuzzy setting, effective configuration and finite resource limits. |
| Knowledge snapshot and field scope | `knowledge_snapshot.py`, `field_mapping.py`; `.ai/05_pipeline_contracts.md`; `FLAT_SQLITE_CONTRACT.md` if supplied | The read-only flat SQLite boundary, fixed source mappings, source identities/traceability, and no database rebuild or mutation. |
| Deterministic matching | `comparison.py`, `dictionary_matcher.py`, `dictionary_aggregation.py`, `fuzzy_matching.py` | Exact/normalized-exact matching, fixed boundaries, ambiguity/overlap preservation, bounded processing, and restricted optional fuzzy behavior. |
| Independent values and units | `unit_value_rules.py`, `unit_aggregation.py`, `value_expressions.py`, `parameter_unit_value.py` | Independent parameter, unit, and value evidence; controlled value forms; no fabricated entity association. |
| Run and output | `runner.py`, `monitoring.py`, `publication.py`, `__main__.py` | Callable runner/CLI, outcomes, monitoring, partial-result behavior, final-manifest-last publication, and immutable artifacts. |

### C. Cross-check actual expected behavior and limits

- Consult relevant cases under `tests/lexical_extraction/`, especially contracts, configuration, HTML reader, knowledge snapshot, field mapping, matcher, aggregation, parameter/unit/value, fuzzy, runner, and publication tests. Reading tests establishes expected behavior; do not report them as executed by this task.
- Inspect the checked-in result example and, if supplied, a real L13 `manifest.json` and component artifacts only to understand the published shape and evidence. Do not alter them or claim pharmaceutical precision/recall from their existence.
- For the upstream interface only, inspect the reviewed-HTML producer contract enough to establish exactly what this stage consumes. Do not retell Stage 1 in depth.
- Do not run the full lexical extraction, rebuild the snapshot, write to the knowledge directory, call any external service, add tests, or change application code.

The following are questions to verify, **not facts to assume**:

- What is the exact document input, and which producer metadata must be present for a successfully validated input?
- Which local knowledge source is opened, what is its read-only/identity guarantee, and what is deliberately not done to it?
- Which selections can a user make in V1? Explain the seven presets and clarify that `with` means co-execution, not an inferred relationship.
- What is always deterministic and fixed internally versus user-selectable? State the fuzzy default and restrictions precisely enough to prevent unsafe interpretation.
- How are text matches, candidates, aliases, repetitions, overlaps, ambiguity, source references, pages, blocks, and offsets retained?
- How are materials, UOs/process steps, equipment/parameter names, units, and values handled without turning a mention into proof of a manufacturing relationship or execution?
- Which result states distinguish completed, partial, failed, and published output? What is a final manifest allowed to claim?
- What local interfaces actually exist today (callable runner/CLI/filesystem artifacts), and what user-facing review capability does **not** yet exist?
- What monitoring/provenance evidence exists, and which reported real-input measurements are historical recorded evidence rather than a test rerun in this task?

If a point is not established by available evidence, omit unsupported detail or state the narrow limitation. Ask a question only if the repository is unavailable or a central ambiguity would make the overview materially misleading.

## Required content and structure

Use the title **“BatchLens — Stage 2: Lexical Extraction Engine”**.

### 1. Purpose and boundaries

Explain why Stage 2 extracts candidate, source-linked evidence from a reviewed document, and make the start/end points clear. State that it is deterministic lexical extraction over an approved reviewed HTML v1 document and a read-only catalogue snapshot. Make equally clear that this stage does not make pharmaceutical truth claims, infer associations, prove manufacturing execution, perform semantic/vector/LLM retrieval, or provide the later human-review UI.

### 2. Inputs and safe preparation

Describe the reviewed HTML v1 input, its provenance metadata and exact-byte identity in plain language. Describe the read-only flat SQLite snapshot at a business level, including why the engine validates identity and does not import CSVs, normalize tables, rebuild catalogues, or write to the snapshot. Explain the distinction between the reviewed document's canonical JSON hash and the HTML-byte SHA-256 only if it is needed to avoid confusion.

### 3. The extraction workflow, step by step

Provide a numbered sequence from selecting a preset/configuration to published artifacts. For each step, explain briefly what the engine does, what remains fixed, what selection controls it, and what lets the work continue or fail safely. Keep the following stages distinguishable without excessive internal detail:

1. validated reviewed-HTML input and snapshot preflight;
2. fixed field selection and source-linked eligible terms;
3. normalized/exact dictionary discovery with correct boundaries and bounded memory;
4. preservation/aggregation of repeated, overlapping and ambiguous candidates;
5. independent unit/value/parameter evidence where selected;
6. outcomes, monitoring and filesystem publication.

### 4. What can be selected, and what matching means

Include one compact table for these approved presets:

| Preset | Requested components |
|---|---|
| `unit_operations` | Unit operations only |
| `unit_operations_with_steps` | Unit operations and process steps |
| `materials` | Materials only |
| `materials_with_quantities` | Materials, quantity expressions and units |
| `equipment` | Equipment only |
| `equipment_with_parameters` | Equipment, parameter names, parameter-value expressions and units |
| `full` | All V1 components |

Explain that presets are combinable and that extra components are co-executed rather than associated. State that the user may only select requested presets/components and fuzzy enabled/disabled; matching algorithms, normalization profiles, source-field mappings and individual matching switches are not user configuration.

Describe matching in plain language: V1 uses fixed exact and normalization-aware comparison/boundary rules. Fuzzy is optional and disabled by default; it is limited to a small natural-language scope and never applies to materials/chemicals, codes/UNII, generic cues, or units. Unit recognition must remain exact under its fixed V1 rules; a unit alone does not identify equipment, a parameter, or an operation.

### 5. Evidence, results, and traceability

Explain what a result preserves: original literal span, page/block/node, half-open Unicode code-point offsets in the block text, matching method, candidates/source rows, catalogue identifiers and qualification. State that repeated occurrences, alternative candidates and supporting row references remain visible for later review rather than being silently merged into a false certainty.

Explain the independent treatment of parameter names, units and values using a short natural-language example such as `Impeller speed: 120 rpm`. Do not imply a parameter-to-equipment or quantity-to-material association. Mention that spans are designed to support later highlighting, while a browser review UI has not yet been implemented.

### 6. Outcomes, publication, and observability

Describe component-level outcome status and the honest distinction between zero results, failed work and partial runs. State that successfully published partial extraction retains completed component artifacts with explicit partial status. A final manifest is written only for completed publication; failed/interrupted publication must not claim one.

Identify the actual published shape: a new run directory containing `artifacts/component-<name>.json` files and a final `manifest.json`, with identity/provenance, outcomes, monitoring and artifact hashes. Mention the callable runner and CLI as current technical interfaces, but do not present them as the future review UI.

At a business level, describe available observability: input/snapshot/config/rules identities, timings, component counts/outcomes, resource limits and platform-dependent peak process memory. If you include the recorded real-input `full` run, label it as historical evidence and preserve its scope: 18 pages/728 blocks, 169.257 seconds, and 506,093,568 reported peak bytes; it is neither pharmaceutical validation nor a test run performed for this documentation task.

### 7. Current completion boundary and next handoff

Close with a concise statement of when Stage 2 is complete today: it can validate approved reviewed HTML v1, run selected deterministic lexical components against the pinned read-only snapshot, and publish provenance-preserving artifacts. State the material current boundary: a user-facing extraction review workspace, approval/edit workflow for findings, LLM/vector extraction, graph, and association logic are not implemented by Stage 2 itself.

Do not write a roadmap or recommend implementation changes.

## Deliverable and completion check

Create `docs/BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`, or update that exact file if it already exists. Modify no other project files.

Before finishing, check that an LLM with no prior conversation can answer: What document and knowledge inputs are accepted? What does the user select? What is fixed versus configurable? What does a match prove and not prove? How are evidence and ambiguity retained? How are units and values handled? What is published, and what do completed/partial/failed publication mean? What does Stage 2 still not provide? Clearly distinguish implemented behavior, recorded verification/acceptance, and remaining limitations without inventing a new status framework.

Keep an unobtrusive final source note naming at most 6–9 relevant repository files, outside the main narrative. Record the inspected commit if available and whether local changes were present. Do not describe tests as executed unless you actually ran them; reading tests establishes expected behavior, not successful execution.

In your chat response, return only the document path, approximate word count, and any material uncertainty that remains. Do not paste a second long report or begin implementation.
