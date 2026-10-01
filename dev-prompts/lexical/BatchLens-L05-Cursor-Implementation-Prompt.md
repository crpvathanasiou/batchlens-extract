# BatchLens — L05: Fixed V1 Source-Field Mapping

## 1. Authorization and stop boundary

L01 contracts, L02 configuration, L03 reviewed HTML reader, and the corrected L04 read-only flat snapshot reader are **user-accepted**. Implement **L05 only**: a small, explicit mapping from L04 flat `SourceRow` values to eligible V1 search-term records and source references for the independently executable lexical components. Add meaningful tests and update the current handoff/code map.

Stop after the L05 completion report. Do not implement document matching, Aho–Corasick, normalization, offset mapping, fuzzy distance, number/value parsing, occurrence aggregation, runner/CLI, monitoring, or publication. Do not start L06.

## 2. Accepted baseline and inspection

Repository: `C:\Users\User\batchlens-extract`. Inspect the actual working tree. The supplied L04 correction reported 40 focused snapshot tests, 97 combined lexical tests, a passing 367-test quality gate, and a successful read-only production preflight/small-page smoke. These are **reported** baseline facts; give your own results for this task.

Read `AGENTS.md`, current `.ai/03_common_handoff.md`, relevant `.ai/02_code_quality_standards.md`, `.ai/01_implementation_roadmap.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and `docs/FLAT_SQLITE_CONTRACT.md`. Inspect `src/app/lexical_extraction/knowledge_snapshot.py`, `contracts.py`, `configuration.py`, and their focused tests. Review actual source headers, `record_type`/`Index this row`/`Match policy` values, and representative rows from the **existing read-only snapshot** when available. Use bounded single-table reads or small grouped queries for these concrete interpretation questions; do not rescan or rebuild the full database just to demonstrate the mapper.

The older flat contract preserves source columns but contains historical search-field suggestions for equipment/UO. The locked selection below supersedes those suggestions. Do not modify the published snapshot or its historical contract. The older lexical handoff's suggestion to search brand/model/Greek fields is likewise superseded.

## 3. Small mapper boundary

Create one focused mapping module (for example, `src/app/lexical_extraction/field_mapping.py`) with **explicit per-table logic over the shared L04 `SourceRow`**. Expose a narrow pure row-to-zero-or-more-term function and, if useful, a small iterator that requests only tables needed by selected components from an already validated L04 handle. Use compact transient records: original literal term, component/term role, source table and field, source `row_id`, optional `lexical_term_id`, snapshot reference where needed, and the selected native IDs/display/qualification/traceability required to resolve a later candidate. Do not accumulate a global vocabulary, copy every source column into final results, create a persistent index, build a generic field-selection framework, or construct three separate engines.

The mapper does **not** create L01 `FdaEmaMaterialCandidate`/other final candidates or `DictionaryOccurrence`: those require real match evidence, original document spans, and aggregation. It may carry a small fixed internal term-role/boundary hint so the later matcher can apply whole-code UNII and conservative unit token handling. These rules are fixed V1 internals, **not user-facing configuration**. Preserve separate source rows and multiple same-spelling candidates; do not deduplicate distinct references by name.

Blank or whitespace-only source search cells do not become terms. Preserve the source spelling of eligible cells rather than altering it to a normalized comparison key. Empty optional IDs/aliases remain absent in the compact interpretation, but the corresponding usable naming row is not discarded. No language detector or new Materials alias language filter is authorized; the supplied Materials datasets are reported to contain no Greek aliases. Dedicated equipment/UO Greek columns remain excluded.

## 4. Locked V1 mapping

| Source | Eligible search expressions / component | Display, identity, qualification and source reference |
|---|---|---|
| `materials_fda_ema` | `material_name` and `alias_name` → `materials`; `UNII` → `materials` with **whole-code** boundary and no fuzzy | Display `material_name`; keep UNII and SMS_ID as separate optional identities; `alias_type`; `row_id`, `lexical_term_id`, `source`. No CAS_NUMBER or SMS_ID search. |
| `materials_chebi` | `material_name` and `alias_name` → `materials` | Display `material_name`; optional CHEBI_ID identity; preserve `alias_type` including exact versus related synonym distinction; `row_id`, `lexical_term_id`, `source`, `source_version`, `source_record`. No CAS_NUMBER or CHEBI_ID search; no cross-source entity merge. |
| `equipment` | `Equipment type (EN)` → `equipment`; `Operating parameter (EN)` → `parameter_names`; eligible atomic `Unit` spelling → `units` | Equipment type identity `equipment_type_id`; parameter identity `parameter_id` plus catalogue equipment scope only; `row_id`, `Source / section`. A parameter term does not assert a detected equipment mention. No Greek columns, Brand / Manufacturer, Model, manufacturer_id, model_id, or Published range as search/business terms. |
| `unit_operations` | `Search term (EN)` → `unit_operations` only when `Index this row` authorizes that lexical expression; independently eligible `Process step (EN)` → `process_steps` | UO display `Canonical unit operation` and `Unit operation (EN)`; identity `Operation ID`. Step identity `process_step_id`; preserve `record_type`, `Match policy`, `Term relation`, `Operation role`, original `Index this row`; `row_id`, `lexical_term_id`, `Provenance / source`, and for steps `Source / supporting evidence`. No Greek, purpose, relationship, operation A/B, or inference-rule search. |

Interpret `Index this row` as the source's explicit TRUE/FALSE flag for **UO search expressions**; a nonempty `FALSE` is not active. Do not apply that flag to suppress a separately eligible `Process step (EN)` label. Preserve match-policy distinctions such as `direct_candidate`, `context_required`, `step_cue_only`, `support_only`, and `inspection_only`, without promoting support/inspection content into a direct UO candidate. Generic/step-cue rows may lack `Operation ID`; do not invent one or attach a document operation. A row may contribute both independently selected term roles where eligible. If the local snapshot contains additional flag/policy/record-type values whose meaning is not established by the agreed V1 contract, report their bounded observed values and the specific ambiguity rather than silently treating unknown values as `TRUE` or fabricating policy semantics.

Equipment `Unit` is a possible **unit vocabulary** source, not a parameter value or an equipment identity. Apply a small fixed conservative token-eligibility rule so descriptive text, placeholders, ranges and composite prose do not become unit spellings. Preserve the original cell for traceability where a unit is eligible; do not generate a parameter name from a unit. The later value-recognition task will also provide a small fixed vocabulary for material quantities; Equipment.Unit alone is not complete for that purpose. Do not parse numerical expressions in L05.

Preserve alternative parameter records when one label maps to several equipment-scoped `parameter_id` values. Neither a parameter term nor a unit term creates equipment/parameter associations in document evidence. Catalogue repetition is source provenance, not multiple asserted document occurrences.

## 5. Permitted changes and tests

Create `src/app/lexical_extraction/field_mapping.py` and `tests/lexical_extraction/test_field_mapping.py` (names may match the repository's convention). Add only minimal public re-exports if needed. Update concise L05 state and contracts in `.ai/03_common_handoff.md` (execution-state anchor), `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and `.ai/01_implementation_roadmap.md` when relevant. Record L04 as user-accepted. Do not change L01–L04, producer, database, CSVs, snapshot companions, CLI, or unrelated application behavior unless a concrete incompatibility blocks L05; explain it and stop rather than silently redesigning an accepted contract.

Use synthetic `SourceRow` fixtures based on the exact four fixed headers to test:

1. Every permitted field yields the correct component, source field and original literal; every expressly excluded field yields none. Component-only selection scans only its required tables/roles, while shared equipment rows can produce separate equipment/parameter/unit terms when those components are requested.
2. FDA/EMA UNII versus SMS_ID namespaces, whole-code term role and no fuzzy; ChEBI related versus exact alias qualification; blank alias/native ID with usable name; no cross-catalogue merge or CAS search.
3. Equipment type versus parameter versus unit independence, several scoped parameter candidates sharing a label, no brand/model/Greek/range term, and no filling document values from catalogue context. Non-atomic unit strings/placeholders stay ineligible under the documented fixed rule.
4. UO TRUE/FALSE and unknown flags, direct/context/generic/support/inspection policy distinctions, independently eligible step label on an inactive UO lexical row, missing operation/step IDs, preserved source qualifiers, and repeated flat rows retained as separate source references.
5. Unicode, source whitespace, `FALSE` and `N/A` literal preservation where relevant; deterministic per-row term order; bounded row-by-row iteration without a global term list; no matching, normalized spans, or L01 candidate fabrication.

When the production snapshot is locally available, perform a **bounded read-only mapping smoke check**: representative rows from all four tables and a small grouped view of the UO flag/policy/record-type vocabulary. Report source-value findings and resulting term-role examples without exposing large result sets or asserting pharmaceutical correctness. Do not perform the agreed full-Materials time/peak-memory measurement yet: it belongs **after matching and aggregation work**, not to this field mapper. If the snapshot is unavailable, distinguish that from synthetic test verification.

Run focused mapper tests, the combined lexical suite, and `scripts/quality.ps1`; report actual results. Do not weaken gates or aim at a historical count.

## 6. Definition of Done and stop

L05 is complete when the later shared matcher can consume a deterministic, row-streamed set of source-backed eligible terms for any independent component, with the exact fixed V1 field boundaries and qualifications above, without treating catalogue metadata as document evidence or changing the flat snapshot.

Return exact changed files; mapper input/output and fixed eligibility rules; any bounded production source-value findings; focused/full-gate evidence; documentation state and remaining limits. **Stop after L05. Await review and explicit user acceptance before L06 work or prompts.**
