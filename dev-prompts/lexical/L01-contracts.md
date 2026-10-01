# BatchLens — L01: Evidence, Result, and Execution-Outcome Contracts

## 1. Authorization and stop boundary

The user has accepted the Understanding Report and the revised Gate B plan (L01–L14). Implement **L01 only**, including its focused tests, serialization example, and relevant repository documentation updates.

The collaboration sequence remains: one bounded Cursor implementation → user/GPT review → corrections if necessary → explicit user acceptance → next task. Approval of the plan is not authorization to implement all tasks.

Inspect the local repository, briefly state your intended L01 changes, then implement this authorized task. Stop after its completion report. Do not implement L02 or prepare subsequent implementation work.

## 2. Accepted baseline and authority

Repository: `C:\Users\User\batchlens-extract`.

The inspected project contains conversion, document review, reviewed HTML rendering, and the standalone flat-SQLite preparation utility. The lexical engine was unimplemented at handoff. Verify the actual working tree before editing; preserve unrelated changes. If lexical files already exist, inspect them rather than overwriting or assuming their status.

Reviewed HTML v1 is the sole document-text input. The existing four-table, read-only SQLite snapshot is the runtime knowledge input. PDF/document JSON remain upstream artifacts. No knowledge preparation or reimport is required.

Prior reports record 270 passing Python tests after preparation corrections. This is historical evidence, not a result from your execution or a required test-count target.

The following accepted decisions override conflicting older handoff details:

- One deterministic extraction pipeline. The user selects presets/components and fuzzy ON/OFF; fuzzy defaults OFF.
- Normalization, boundaries, source fields, and value rules are fixed internal V1 rules. No user-selectable algorithm/profile/field switches or configurable lexical-policy framework.
- Parameter names, units, and values are independently evidenced outputs. Number–unit grouping is allowed; semantic entity associations are not.
- The fixed field selection in section 6 applies. Do not reintroduce equipment brand/model or Greek-column extraction.
- Successful partial extraction may be published with completed components and an explicit partial status. Interrupted/failed artifact publication must not claim completed publication.

Use `implemented`, `test-verified`, `manually verified`, and `unverified` accurately. L01 establishes contracts, not a working extractor or completed publication mechanism.

## 3. Read before editing

Read the following task-relevant material:

1. `AGENTS.md` and current `.ai/03_common_handoff.md`.
2. `.ai/00_project_reference.md`, `.ai/04_code_map.md`, and relevant typing, Pydantic, errors, testing, and documentation sections of `.ai/02_code_quality_standards.md`.
3. `.ai/05_pipeline_contracts.md` for evidence, ambiguity, lifecycle meanings, and boundaries; apply the accepted narrower lexical scope above.
4. `docs/FLAT_SQLITE_CONTRACT.md`.
5. `src/app/document_review/rendering.py` and its attribute contract in `src/app/document_review/README.md`.
6. Relevant models in `src/app/document_conversion/contracts.py`, `src/app/document_review/contracts.py`, plus `src/app/exceptions.py` for conventions. Reuse suitable conventions, not infrastructure-coupled review models.
7. `pyproject.toml`, `pyrightconfig.json`, and `scripts/quality.ps1`.

The supplied technical handoff revision 2 and revised plan are supporting references when available locally; do not assume they have been copied into a repository path. This prompt contains the L01-specific authorization and corrections. The large SQLite, original CSVs, PDF, and real HTML are not needed to execute L01's contract tests.

## 4. Deliverable and permitted changes

Create:

- `src/app/lexical_extraction/__init__.py` — minimal package, no import-time I/O or initialization.
- `src/app/lexical_extraction/contracts.py` — cohesive typed contracts, enums, and small pure contract validators.
- `tests/lexical_extraction/test_contracts.py` — meaningful public-contract tests.
- `examples/lexical_extraction/result-example.json` — compact valid synthetic serialization example.

A minimal `tests/lexical_extraction/__init__.py` is permitted only if the repository's test/package conventions require it.

Update only relevant facts in:

- `.ai/03_common_handoff.md` — L01 implementation/checks, remaining limitations, awaiting user acceptance.
- `.ai/04_code_map.md` — new module and tests.
- `.ai/05_pipeline_contracts.md` — settled lexical record/status/evidence contracts.
- `.ai/01_implementation_roadmap.md` — a concise L01 progress update if needed; do not rewrite the broader roadmap.

Do not change dependencies, existing application modules, existing tests, renderer/review behavior, source catalogues, or snapshot artifacts. Do not add another specification/history document. Keep documentation concise and avoid copying this prompt across files.

If a genuine blocker requires changing an out-of-scope file, explain the exact blocker and stop before making that change. Ordinary naming choices within L01 do not require a new approval.

## 5. Contract responsibilities

Choose clear concrete model names. Use Pydantic v2 at validation/serialization boundaries and lightweight internal types where appropriate. Reject unknown business fields and unsafe coercions. Prefer explicit variants over one object with many unrelated nullable properties. Avoid broad dictionaries, generic plugin abstractions, and framework dependencies.

### 5.1 Evidence records

Represent:

- Validated input identity: require the exact HTML SHA-256, HTML contract version 1, and all root metadata mandated by the existing producer: `data-job-id`, `data-review-revision-id`, `data-review-generation`, and `data-conversion-status`. These fields must be present and valid in a successfully validated reviewed-HTML-v1 input record; do not make them optional under an "available metadata" rule. An external document ID may be absent; do not invent one.
- Page: positive physical page number, order and coverage information.
- Block: original nonempty node ID, structural kind, exact original text, page membership/order, optional owning element/table and cell geometry, and original ordered OCR references.
- Empty block text and missing OCR references are valid. Do not strip text, collapse whitespace, or inherit/fabricate references in a validator.
- Match location: zero-based half-open Unicode code-point offsets and nonempty original `matched_text`.

A failure occurring before successful input validation may have no validated input-provenance record. Represent that absence explicitly in the failure outcome, without fabricated job/revision/generation/conversion values or a placeholder validated-input object. Any already observed diagnostic information must not be promoted to validated input metadata. This does not weaken the required fields of the valid-input contract; missing OCR references remain valid as stated above.

Provide a small pure validation boundary that can check a match against its supplied block:

`0 <= start_char < end_char <= len(block.text)` and `block.text[start_char:end_char] == matched_text`.

A standalone match cannot establish slice correctness without the block; document that distinction. It may validate its own basic bounds/length. This is evidence validation, not normalization or HTML parsing.

Do not require loading a whole document/result tree to validate a block or match. Preserve different and overlapping spans. Do not add deduplication or sorting algorithms here; define their deterministic ordering fields/semantics for later implementation.

### 5.2 Dictionary candidates and mentions

Represent dictionary occurrences separately from their possible catalogue candidates. A span may have multiple candidates and multiple supporting source references.

Candidates retain:

- Supported entity/term role and separate identity namespaces.
- Existing native/scoped identifiers where available, without regeneration.
- Canonical display name when supplied; raw matched dictionary term and source field.
- Relevant alias relation, UO policy/role, and unresolved/ambiguity qualification.
- Snapshot/table/row/source-field references; `lexical_term_id` and source provenance fields when applicable.

Missing aliases or native IDs must not automatically invalidate a usable naming record. A source-record candidate is valid without a fabricated chemical/entity ID. Generic UO cues can have no operation ID.

A parameter candidate can carry the catalogue scope needed to distinguish equipment-scoped parameter IDs. That qualification is not an independently detected equipment mention or a document association.

Method records distinguish exact, normalized exact, and fuzzy evidence, with a fixed rule identity. Fuzzy records can represent dictionary term/edit distance for later use, but do not implement distance calculation. Fuzzy is not permitted for UNII, chemicals/chemical identifiers, or units under the accepted scope. Do not include probability/confidence claims.

### 5.3 Unit mentions and value expressions

A unit mention has its own literal text, span, controlled unit identity/spelling, rule, and vocabulary provenance where available. Unit provenance may identify the fixed vocabulary or an eligible `Equipment.Unit` source record. It must not populate a parameter name, `parameter_id`, or detected equipment identity.

A parameter-name mention needs no unit or value. A value expression needs no material/equipment/parameter parent. No model validator may fill missing values from catalogue metadata.

Represent the agreed value forms: scalar with unit, range, comparison, symmetric tolerance, controlled categorical expression, and explicitly cued unitless value. Preserve raw expression/spans, source unit spelling, and controlled unit representation where present. Preserve numeric ambiguity explicitly; do not fabricate a resolved number.

Use lossless decimal strings or a precisely specified Decimal-to-string boundary; reject non-finite numeric values and avoid float-based round trips. No parsing engine, unit conversion, plausibility correction, or physical acceptance rules in L01.

Number–unit grouping and the constituent unit span are syntactic evidence, not semantic association. The contracts must accommodate `Impeller speed`, `rpm`, `120 rpm`, and `Impeller speed: 120 rpm` without creating entity links. Shared applicability to quantity/parameter-value components must be representable without duplicating an occurrence by design.

### 5.4 Run provenance and execution outcomes

Represent schema/run identity, requested modes/components, resolved components, per-component and overall extraction outcomes, coverage/counts, safe structured errors, timings, and available measurements.

The approved preset vocabulary is complete here; no locally available supporting handoff is assumed. A preset is a named selection of independently executable components, not a component or a separate engine:

| Preset | Components requested |
|---|---|
| `unit_operations` | `unit_operations` (including applicable generic-cue roles) |
| `unit_operations_with_steps` | `unit_operations`, `process_steps` |
| `materials` | `materials` |
| `materials_with_quantities` | `materials`, `quantity_expressions`, `units` |
| `equipment` | `equipment` (catalogue equipment-type mentions) |
| `equipment_with_parameters` | `equipment`, `parameter_names`, `parameter_value_expressions`, `units` |
| `full` | Union of all components listed above |

Keep preset vocabulary distinct from component vocabulary even when a label is shared. Components are unit-operation mentions, process-step mentions, material mentions, equipment-type mentions, parameter-name mentions, unit mentions, quantity expressions, and parameter-value expressions. Their contracts support independent execution and combined requests. Shared recognition may serve more than one component without duplicating an occurrence.

“With” means co-execution only: no association, required child data, or catalogue-derived filling of missing document values. L01 may define the preset/component enums or literals needed by its records; actual preset expansion, union/deduplication, configuration loading, and dispatch remain L02/later work. Do not implement preset resolution in L01.


Preserve identities/hashes for input HTML, knowledge snapshot/database/manifest, effective configuration, internal V1 rules, and engine/dependency versions. Do not build YAML models, mode-resolution logic, hashing code, resource monitoring, or a generic configuration container here. L02 owns effective execution configuration. Input provenance follows section 5.1: valid-input metadata is required after successful input validation, while a pre-validation failure may lack a validated-input record. Optional unavailable measurements must not be reported as measured zero.

Use the agreed extraction meanings:

- `not_requested`: component was not selected.
- `completed`: requested coverage completed, including a legitimate zero-match result.
- `partial`: usable results remain, but some requested coverage is incomplete.
- `failed`: requested work failed; distinguish its errors/coverage from a successful empty result.

Retained completed component outcomes must coexist with overall `partial`. Context-required/ambiguous candidates are not themselves technical execution failures. An entirely failed requested run must not be called completed or partial merely because an empty container exists.

Keep artifact-publication outcome separate from extraction outcome. The contracts must express these valid/invalid combinations:

| Situation | Required meaning |
|---|---|
| Extraction completed, artifacts safely published | Completed extraction and completed publication |
| Some extraction work failed/incomplete, usable components safely published | Partial extraction and completed publication; final manifest is allowed |
| Artifact serialization/write/publish interrupted or failed | No final manifest claiming completed publication, regardless of extraction progress |

Model the relevant outcome/manifest records and coherence constraints only. Do not implement filesystem publication, atomic writes, retries, resume, or a run state machine. A contract cannot prove that files were actually written; L13 provides that operational guarantee.

### 5.5 Incremental validation and final JSON organization

The eventual result is organized as run → document → pages → blocks → matches. Define reusable record boundaries and ordering semantics that support this organization without requiring a monolithic Pydantic model containing every page, match, candidate, and reference in memory.

A small complete illustrative tree in the example is acceptable. Its validation should exercise the same reusable records and coherence checks. It must not introduce an alternative production contract or require whole-run materialization later. Validate records in bounded units; leave actual streaming, aggregation, and publication to their assigned tasks.

## 6. Fixed business-field boundary

Represent only the approved lexical business data and provenance. Do not copy every source column into arbitrary metadata.

| Table | Accepted fields/semantics |
|---|---|
| `materials_fda_ema` | Search fields: `material_name`, `alias_name`, `UNII`. Display: `material_name`. Separate identities: UNII and SMS_ID when available. Qualification: `alias_type`. Traceability: `row_id`, `lexical_term_id`, `source`. CAS_NUMBER/SMS_ID are not search fields. |
| `materials_chebi` | Search fields: `material_name`, `alias_name`. Display: `material_name`. Identity: CHEBI_ID. Qualification: `alias_type`, preserving exact/related distinctions. Traceability: `row_id`, `lexical_term_id`, `source`, `source_version`, `source_record`. CAS_NUMBER/CHEBI_ID are not search fields. |
| `equipment` | Equipment-name field: `Equipment type (EN)`; identity: `equipment_type_id`. Parameter field: `Operating parameter (EN)`; identity: `parameter_id`. Unit vocabulary field: `Unit`. Traceability: `row_id`, `Source / section`. No Greek, brand, manufacturer, model, manufacturer/model IDs, or Published range in matching/extracted business fields. Equipment denotes a catalogue type, not an installed asset. |
| `unit_operations` | UO search: `Search term (EN)`; displays: `Canonical unit operation`, `Unit operation (EN)`; identity: `Operation ID`. Step search: `Process step (EN)`; identity: `process_step_id`. Interpretation: `Index this row`, `Match policy`, `record_type`, `Term relation`, `Operation role`. Traceability: `row_id`, `lexical_term_id`, `Provenance / source`, plus `Source / supporting evidence` for steps. |

Do not merge FDA/EMA and ChEBI candidates by spelling/CAS. No new language-filter subsystem may delete existing Materials aliases. `Index this row` governs the UO lexical expression and must not become a blanket gate on an independently eligible step label. Preserve unresolved source policy meanings without turning them into verified process facts.

L01 represents these distinctions. L05 implements field selection/eligibility; L06–L07 implement UNII whole-code boundaries and matching. Do not pull that runtime work into this task.

## 7. Required tests and serialization example

Test public behavior, including:

1. Valid source-record-only material, SMS-only identity, separate FDA/EMA and ChEBI candidates, and generic cue without operation ID.
2. Related synonym and context-required qualifications surviving JSON round trip.
3. Multiple equipment-scoped parameter alternatives without a detected equipment association.
4. Independent parameter name, standalone unit, value/unit expression, and cued unitless value. Reject prohibited unit-to-entity business fields through the typed boundary.
5. Exact original slices containing Greek, a combining-mark sequence, newline, and supplementary Unicode. Reject negative/reversed/out-of-range spans and mismatched literal text. No normalization implementation is needed.
6. Empty block text and missing OCR references accepted; invalid required identities/geometry rejected where the contract requires them. A validated-input record missing any producer-mandated root metadata is rejected; a pre-validation failure without a validated-input record is accepted without fabricated metadata.
7. Lossless decimal serialization, numerical ambiguity representation, and non-finite rejection.
8. Completed-zero versus not-requested versus failed; completed component retained within a partial overall result; ambiguity alone does not require technical failure.
9. Published partial outcome accepted; final-manifest success claim paired with failed/interrupted publication rejected.
10. Unknown fields/unsupported versions and unsafe coercions rejected. Serializing fixed records twice produces the same semantic content and preserves evidence exactly.
11. The checked-in JSON example validates through the public record/coherence boundaries and survives round trip without altered text/identities.

Use a compact synthetic example with honest fixture identities. It should demonstrate independent parameter/unit/value evidence and an explicit partial outcome retaining completed work. Do not invent real extraction results from the uploaded document, and do not implement a matcher to create the fixture.

## 8. Explicit exclusions

No execution YAML loader, user-configurable policy, HTML reader, database access, term reader, normalization algorithm, Aho–Corasick, value parser, fuzzy search, aggregation spool, runner, CLI, monitoring implementation, or artifact publication.

No source-database writes, CSV ingestion, API/UI/storage changes, LLM/RAG/embeddings, semantic associations, catalogue correction, deployment, commit, or push. Do not start subsequent tasks to make the contracts appear operational.

## 9. Verification and Definition of Done

Run the focused new tests, then applicable repository Ruff check, format check, Pyright, and pytest gates using the supported local environment and existing commands (`scripts/quality.ps1` where appropriate). Do not weaken checks or edit unrelated files to achieve a green result. Report any pre-existing/environment failure precisely and distinguish it from an L01 regression. No frontend/Docker/AWS acceptance is required for this isolated contracts task.

L01 is technically complete only when:

- Typed contracts express the agreed evidence, candidates, independent units/values, provenance, extraction outcomes, and publication distinction.
- Original-text span checks and contract coherence are covered by meaningful executed tests.
- The example is valid and synthetic; incremental record use does not require a full result tree.
- Changes stay within the allowed scope and relevant documentation records the actual implementation/checks.
- Applicable quality results are reported honestly. A blocked required gate remains an unresolved acceptance item.

Documentation must state that parsing, search, real-data performance, monitoring, and publication behavior remain unimplemented/unverified. Do not mark user acceptance complete yourself.

## 10. Completion report and stop

Return:

1. Concise change summary and exact changed files.
2. Public model/validator inventory with purpose and key input/output invariants.
3. How independent units/values, missing identities, ambiguous candidates, Unicode spans, and partial-versus-publication outcomes are represented.
4. Serialization-example path and validation result.
5. Actual test/gate commands, results/counts, and precise failures or environment blocks.
6. Any material contract interpretation chosen within this scope and remaining limitations.

**Stop after L01. Await review and explicit user acceptance. Do not implement L02 or any later work item.**
