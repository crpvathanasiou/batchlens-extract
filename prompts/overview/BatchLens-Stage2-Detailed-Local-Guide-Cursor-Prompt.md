# BatchLens Stage 2 — Detailed documentation and local execution guide

## Task and deliverable

Create `docs/BatchLens-Stage2-Detailed-Local-Guide-EN.md`: a self-contained **English** technical explanation and practical local execution guide for the implemented Stage 2 lexical extraction engine.

The primary audience is another LLM, such as ChatGPT, starting a new session, and the developer using that LLM to understand and run this stage. Explain the actual implementation, not a proposed architecture. The accepted Stage 2 overview remains the short introduction; this document explains local prerequisites, configuration, execution sequence, evidence/artifacts, verification, and recovery in more detail.

This is a documentation-only task. Proceed directly from repository inspection to the completed document. Do not create an implementation plan or another approval round.

## Current authority and baseline

L01–L13 of the lexical extraction engine are implemented, test-verified by recorded quality gates, and **user-accepted**. `.ai/03_common_handoff.md` may still say that L13 awaits user acceptance because it predates the final decision. For this documentation task, the user-accepted L13 state is authoritative. Do not alter `.ai/` merely to reconcile that historical wording.

## Hard scope: local lexical execution only

- The document must contain **no AWS discussion, deployment instructions, service topology, credentials, account setup, cloud execution alternatives, or remote-service commands**.
- Describe the local engine only: reviewed HTML v1, a configured local read-only flat SQLite snapshot, YAML execution configuration, the callable runner/CLI, filesystem artifacts, and local inspection/verification.
- The input prerequisite is a reviewed HTML v1 file supplied by the Stage 1 approval/export workflow. Stage 2 validates the HTML v1 structural/provenance contract; it does not independently query a review store to prove human approval. Do not present a PDF, a raw conversion HTML, or a review JSON as a substitute lexical input.
- Do not treat this guide as an Extraction Review Workspace guide. There is currently no Stage 2 review/edit/approval UI, no local extraction-review harness, no LLM/vector execution, no graph, and no association logic.
- Do not redesign matching, configuration, results, persistence, or safety boundaries. Do not imply that a lexical mention proves a manufacturing action or pharmaceutical truth.
- Make no application changes. Do not install/update dependencies, rebuild the snapshot, run the extractor, execute tests, alter local inputs/results, or modify user data while writing this document. Commands are documented for later execution, not executed by this task.

## Read these sources

Follow applicable `AGENTS.md` instructions. Paths below are repository-relative. Use the current repository, not an attachment's archive layout. Locate renamed equivalents if needed; report missing essentials rather than inventing behavior.

### 1. Project anchors and accepted overview

Read in this order:

1. `AGENTS.md`, then `.ai/03_common_handoff.md`: current/historical lexical evidence, exact acceptance boundary, recorded quality gates, real-input measurement and protected data paths.
2. `.ai/00_project_reference.md`: product purpose and stage boundaries.
3. `.ai/04_code_map.md`: lexical module locations and responsibilities.
4. `.ai/01_implementation_roadmap.md`: lexical milestones only, to distinguish completed work from later work.
5. `.ai/02_code_quality_standards.md`: applicable work/documentation rules.
6. `.ai/05_pipeline_contracts.md`, `.ai/06_security_and_data_handling.md`, and `.ai/07_extraction_evaluation.md`: only the relevant lexical input/output, data handling, and evaluation facts.
7. The accepted `BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`. Search by filename if it is not under `docs/`; an attachment may have a suffixed name. Preserve it. Its broader context does not override this task’s local-only scope.

The detailed guide complements `.ai/`: it consolidates the facts needed to run and diagnose Stage 2 locally. Do not duplicate general coding standards, the roadmap, or the chronological handoff log.

### 2. Implementation sources

| Area | Exact files or bounded directories to inspect |
|---|---|
| Contracts and input reader | `src/app/lexical_extraction/contracts.py`, `html_reader.py`, `comparison.py` |
| Configuration and CLI | `configuration.py`, `__main__.py`, `examples/lexical_extraction/execution-config.example.yaml`, `pyproject.toml`, relevant `poetry.lock` metadata |
| Snapshot and source terms | `knowledge_snapshot.py`, `field_mapping.py`, `docs/FLAT_SQLITE_CONTRACT.md` if present; otherwise locate the current flat-contract copy through `.ai/05` or repository search |
| Matching and aggregation | `dictionary_matcher.py`, `dictionary_aggregation.py`, `fuzzy_matching.py` |
| Units, values and parameters | `unit_value_rules.py`, `unit_aggregation.py`, `value_expressions.py`, `parameter_unit_value.py` |
| Runner, monitoring and publication | `runner.py`, `monitoring.py`, `publication.py` |
| Upstream boundary only | Relevant reviewed-HTML producer portions of `src/app/document_review/rendering.py` / `contracts.py`, plus the accepted Stage 1 overview. Do not document Stage 1 execution in detail. |
| Setup and repository instructions | `README.md`, `.gitignore`, any existing lexical README/examples, and the applicable root/package metadata |

### 3. Behavioral cross-checks

Read relevant tests rather than running them:

- `tests/lexical_extraction/test_contracts.py`, `test_configuration.py`, `test_html_reader.py`, `test_knowledge_snapshot.py`, and `test_field_mapping.py`.
- `tests/lexical_extraction/test_comparison.py`, `test_dictionary_matcher.py`, `test_dictionary_aggregation.py`, and `test_parameter_unit_value.py`.
- `tests/lexical_extraction/test_fuzzy_matching.py`, `test_runner.py`, `test_publication.py`, and `test_acceptance.py`.

Read enough of the tests to establish expected local behavior and safe failure boundaries. Code establishes implementation; tests establish expected behavior unless recorded execution evidence exists. The handoff records actual gates/acceptance. Do not claim a command or test was run during this documentation task. If evidence conflicts, report the narrow current uncertainty.

## Required sections

Use the title **“BatchLens — Stage 2: Detailed Design and Local Execution Guide”** and the following nine sections. Use clear prose, focused tables, and short code blocks. There is no two-page limit; include the detail needed to execute and diagnose the stage without reproducing source code or full schemas.

### 1. Scope and current status

State Stage 2’s purpose, local start/end boundary, and the distinction between **implemented**, **test-verified**, **user-accepted**, and unverified behavior. Explain what Stage 2 accepts and produces, and that it is a deterministic evidence extractor rather than a pharmaceutical validator, association engine, review UI, or LLM capability.

Explicitly separate the Stage 1 approval process from Stage 2 validation: local operational workflow supplies an approved reviewed HTML, while the engine validates the HTML v1 contract and records provenance. Document-review approval is not manufacturing batch release, downstream extraction approval, or a regulatory electronic signature.

### 2. Components and responsibilities

Show how configuration loading, reviewed-HTML reading, snapshot preflight, fixed field mapping, matching, aggregation, independent unit/value recognition, runner/monitoring, and filesystem publication cooperate. Provide a compact responsibility table with principal repository paths and one readable diagram only if it clarifies flow.

Explain the purpose of bounded shards, replay, temporary storage/spooling and configured finite limits at an operational level, without code walkthrough or claimed access to host-wide available RAM. The guide must state that resource limits are configured values; it must not say the engine sizes itself from automatic hardware memory detection.

### 3. Inputs, configuration, outputs, and local data boundaries

Provide a precise artifact/configuration table with: name, producer/owner, consumer, purpose, identity or validation behavior, read/write behavior, and whether it may contain protected content. Include at least:

- reviewed HTML v1 and its producer metadata/byte SHA-256;
- the flat snapshot directory (`knowledge.sqlite`, `manifest.json`, `validation_report.json`, and flat contract) and its read-only validation;
- YAML execution configuration, effective configuration digest, preset/component selection, fuzzy switch, input/snapshot/output paths, and finite resource limits;
- output run directory, component artifacts and final manifest;
- temporary publication/spool files and their cleanup behavior where verified.

Explain the actual YAML keys, valid types, relative-path behavior, defaults/maxima, override semantics, and validation failures only after verifying them in `configuration.py` and the example. Do not invent simplified fields or rely on a historical absolute snapshot path as a portable default.

Show the local directory relationships and require output to be outside the read-only snapshot. Explain which folders should stay Git-ignored, based on repository rules. Never recommend editing source HTML, snapshot contents, manifests or an old published run to force a result.

### 4. Execution flow in detail

Trace one local request from YAML to final artifact. For each meaningful step state input, responsible component, operation, output/state, and condition for proceeding:

1. YAML parse, overrides, preset resolution and effective digest;
2. reviewed HTML v1 validation, page/block streaming and exact HTML identity;
3. snapshot preflight, identity verification and read-only connection;
4. selected table/field eligibility, fixed comparison/boundary preparation, bounded sharded/replayed match discovery;
5. deterministic aggregation and independent parameter/unit/value work;
6. component/run outcomes, monitoring, staging, artifact publication and final-manifest-last sealing.

Explain the actual sequential/independent component boundaries and any permitted partial completion. Do not infer background execution: the current runner/CLI is a local callable/command boundary, not a user-facing job service. Distinguish early pre-validation failure, component failure, partial extraction, publication failure, generator interruption, snapshot/input identity change, and zero matches. Explain what is retained, what is not finally published, and the safe next action.

### 5. Selection, matching, and interpretation rules

Give a compact table of all seven accepted presets and their requested components:

| Preset | Requested components |
|---|---|
| `unit_operations` | Unit operations only |
| `unit_operations_with_steps` | Unit operations and process steps |
| `materials` | Materials only |
| `materials_with_quantities` | Materials, quantity expressions and units |
| `equipment` | Equipment only |
| `equipment_with_parameters` | Equipment, parameter names, parameter-value expressions and units |
| `full` | All V1 components |

Explain that `with` means co-execution, not a relationship, and that presets/components are combinable. Clearly identify user-selectable controls: requested presets/components, `fuzzy_enabled`, paths and finite resource settings. State that matching algorithm choices, normalization profiles, search field mapping, term-type rules and individual method switches are fixed V1 behavior.

Explain the high-level fixed behavior for materials, UO/process steps, equipment/parameters, units and values. Preserve key boundaries:

- no cross-source material merging based only on names;
- a generic cue does not gain an invented operation ID;
- a parameter name does not identify equipment or fill in a unit/value;
- values/units come from the document, not catalogue ranges;
- a unit alone does not identify a parameter, equipment or operation;
- no association or proof of process execution is inferred.

Describe exact/normalization-aware matching and restrictions in operational language. Fuzzy defaults off, is tightly limited to eligible one-word natural-language terms, and never applies to materials/chemicals, codes/UNII, generic cues, abbreviations, phrases, or units. Units use their fixed V1 exact/normalization-aware token and boundary rules, including accepted case/token variants, but never fuzzy matching. Do not re-specify the entire source-field schema or every regular expression.

### 6. Evidence, artifacts, and result interpretation

Explain page/block/node identity, original matched literal, half-open Unicode code-point offsets, matching method/provenance and catalogue candidate/source traceability. State that dictionary occurrences retain dictionary method/candidates; independently recognized units and values retain their own rule/recognition provenance and are not necessarily dictionary matches.

Explain repetition, overlap, ambiguity, supporting row references, candidate qualification, zero-result components and partial runs. Use one concise natural-language example such as `Impeller speed: 120 rpm` to show independent parameter name, unit and value evidence. Do not turn the example into a semantic association.

Document the published JSON layout at a navigational level: run ID directory, `artifacts/component-<name>.json`, component/page/block records, and final `manifest.json`. Explain how an operator can use the manifest’s artifact hashes/sizes and HTML/snapshot/config/rules identities to inspect a run. Do not expose full schemas or recommend manual artifact editing.

Flag the browser boundary accurately: offsets are Unicode code points, whereas a later browser highlighter must convert safely to its text/DOM representation. This guide does not implement that UI work.

### 7. Local execution guide — Windows PowerShell

Give a practical, ordered runbook from repository root `C:\Users\User\batchlens-extract`, with explicit working directory for every command. Keep command groups to 1–3 commands per step. Every step needs prerequisites and an observable expected result.

Cover:

1. Verify the repository’s Python/Poetry requirement and local dependency readiness from project configuration. Separate initial locked install from an ordinary run; do not prescribe upgrades.
2. Define task-specific PowerShell variables for the **already approved** reviewed HTML input, flat snapshot directory, a new local output directory and working YAML file. Validate each required path before running. Do not reuse protected broad directories or define reserved environment variables.
3. Create a working configuration by copying the current example or show a minimal verified equivalent. Explain every path that must be changed. Preserve the existing example and make output a newly created local directory outside the snapshot. Do not assume the sample relative paths point to real data.
4. Explain the four common first-run selections by using the exact current configuration syntax: `Extract UOs` → `unit_operations_with_steps`; `Extract Materials` → `materials_with_quantities`; `Extract Equipment` → `equipment_with_parameters`; `Extract All` → `full`. State that this is a local configuration choice, not a UI that already exists.
5. Show the exact inspected CLI invocation, including the supported optional override syntax only if verified. Explain expected exit codes, stdout summary, expected duration warning (the historical 18-page full run was about 169 seconds), and what output directory is created. Do not state that the CLI supports flags which the code does not expose.
6. Give read-only checks for the new `manifest.json`, component artifact presence/hash, run status/outcomes, and input/snapshot identity. Use built-in PowerShell commands or the repository’s supported reader only after verifying actual artifact field names. A successful final manifest must not be treated as human approval or pharmaceutical validation.
7. Explain normal stop/restart/re-run behavior: do not alter an existing run; create a new run directory, retain prior runs, and use a new output/run for a different input or selection. If publication failed, explain that no final manifest claims completed publication.

Use a currently coherent sample set only if it exists in the checkout. Historical paths in `.ai/03_common_handoff.md` are leads, not proof that they exist now. If sample data is absent, use clearly marked replacement variables and state required files. Do not fabricate a successful execution. Document commands but do not execute this runbook during the task.

### 8. Manual verification and troubleshooting

Provide a compact action/expected-result checklist that a developer can perform later:

- validate a reviewed HTML v1 and the configured snapshot without modifying either;
- run a small selected preset and inspect output/manifest;
- run `full` only when resources/time are acceptable;
- verify a documented span against the source block text and distinguish lexical evidence from a true manufacturing claim;
- inspect a zero-result component versus a failed component;
- verify a published partial run versus a failed/interrupted publication;
- rerun with a separate output and compare recorded identities/results appropriately.

Troubleshooting should map symptom → likely cause → read-only check → safe next action. Cover invalid configuration, missing/unreadable reviewed HTML, producer metadata/version failure, snapshot preflight/sidecar/WAL refusal, output-inside-snapshot refusal, identity changes while reading/replay, oversized resource limit/term failures, component partial failure, missing final manifest, and misleading assumptions about no-match versus no-execution.

Do not include destructive reset commands, snapshot repairs, database modification, or a full internal error catalogue. Do not treat a possible fuzzy match, an alias, or a catalogue candidate as confirmation that it is correct for the document.

### 9. Handoff to the next capability

Explain what a completed Stage 2 run hands off: immutable component artifacts, final manifest, exact source HTML identity, snapshot/config/rules provenance, and evidence spans. State plainly that the current handoff is to the later Extraction Review Workspace, where a human may inspect/highlight/edit/approve findings; no such workspace is implemented by Stage 2 itself.

Do not define future UI contracts, LLM behavior, association rules, graph semantics, or a product roadmap. Finish with concrete completion criteria for a local Stage 2 run and the limits of its current evidence claim.

## Completion and file boundaries

Create or update only `docs/BatchLens-Stage2-Detailed-Local-Guide-EN.md`. Leave the accepted overview, `.ai/`, source code, tests, dependencies, generated artifacts, SQLite snapshot, reviewed HTML inputs and existing outputs unchanged. This document is a stage-specific companion, not a new authority replacing current code or handoff.

Add a short source/verification note with inspected commit and working-tree state, key paths consulted, date of inspection, and any material unverified commands or missing local inputs. Do not turn this into a second long report.

Before finishing, confirm:

- An LLM without prior context can explain and safely follow the complete local Stage 2 flow.
- All nine sections are present and there is no AWS/deployment discussion.
- Commands match current configuration/CLI/publication definitions and use coherent, safe local paths.
- The guide does not promise a PDF-only input, human approval, automatic hardware-memory sizing, UI review, pharmaceutical validation, associations, or lossless semantic interpretation.
- The snapshot remains read-only, historic runs are retained, and incomplete publication never appears as a completed final manifest.
- The document distinguishes current implementation, recorded acceptance/verification, historical measurements, and instructions not executed in this documentation task.

Return the document path, approximate word count, and only material unresolved limitations. Do not begin implementation or execute the documented workflow.
