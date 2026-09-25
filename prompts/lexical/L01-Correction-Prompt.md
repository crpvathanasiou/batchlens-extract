# BatchLens — L01 focused contract corrections

Implement only the corrections below to the existing L01 contracts, their tests, the synthetic example, and relevant L01 documentation. This is a correction of the current task, not acceptance of L01 or authorization to start L02.

## Baseline and scope

L01 currently contains record contracts and pure validators. Parsing, normalization, search, value parsing, preset resolution, aggregation, run execution, monitoring, and publication remain unimplemented. Preserve that boundary and all existing application behavior.

The independent review inspected the supplied contracts, complete tests, package initializers, synthetic example, and documentation changes. It reproduced all **12** focused tests using Pydantic 2.12.5 on Python 3.12; the supplied synthetic JSON example validated and round-tripped through the current public boundary. The reported Windows quality gate and 282-test result were not independently rerun. Additional direct validation probes exposed the inconsistencies below.

Read `AGENTS.md`, current `.ai/03_common_handoff.md`, the current lexical contracts/tests/example, and relevant project quality conventions before editing. Preserve unrelated working-tree changes. Do not assume a supporting technical handoff is available locally; the corrections are specified here.

Permitted changes remain:

- `src/app/lexical_extraction/contracts.py` and the existing minimal package initializer only if needed.
- `tests/lexical_extraction/test_contracts.py` and its existing package initializer only if needed.
- `examples/lexical_extraction/result-example.json`.
- Relevant L01 facts in `.ai/01_implementation_roadmap.md`, `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md`.
- `pyrightconfig.json` and only other files that actually contain the five obsolete script references listed in section 7.

Do not add dependencies or change existing application modules/tests, renderer behavior, database preparation, snapshots, configuration loaders, or other task boundaries. Use small concrete validators; no new framework or production whole-run container.

## 1. Make value evidence internally coherent

The current block validator checks each supplied span independently, but accepts contradictory records. Reproduced examples include:

- Block `120 rpm`, expression span `[0,7)` / `120 rpm`, but `raw_expression="999 kg"` and `source_unit_spelling="kg"` while the unit span is `[4,7)` / `rpm`.
- Block `120 kg and rpm`, expression span `[0,3)` / `120`, with its unit span `[11,14)` / `rpm` outside the expression.
- Number span `[0,3)` and unit span `[4,7)`, but a number–unit group's own span is only `[0,3)`.

Correct the record invariants:

- Every value form's `raw_expression` equals its main span's `matched_text`.
- Source unit spelling and unit span are coherent: where a source unit is recorded, both are present and spelling equals the unit span's original text. Legitimately unitless forms remain valid.
- Constituent unit spans and any number–unit group belong inside the enclosing expression. A group's number and unit spans belong inside its group span; duplicate representations of that unit agree.
- Nested span text agrees with the corresponding parent-span slice. The supplied block remains the authority for checking absolute bounds and original text.
- `UnitMention` itself validates literal/span equality, so it is valid independently of an enclosing `UnitOccurrence`.

Keep all offsets absolute, half-open Unicode code-point positions. Do not normalize, parse numeric strings, infer associations, convert units, or fill missing data. Preserve overlaps between independent occurrences. These are structural and literal consistency checks, not a value parser.

Add negative regressions for the reproduced cases and positive coverage for valid nested Unicode spans, standalone units, and valid unitless values.

## 2. Require source-backed dictionary occurrences and honest method evidence

`DictionaryOccurrence` currently accepts no candidates, leaving a reported dictionary match with no supporting term, source row, or matching method. It also accepts an `exact` equipment candidate with `matched_term="Mixer"` against document text `water`.

- Require at least one source-backed candidate for a finalized dictionary occurrence. Missing native IDs remain valid: a source-row-only candidate or generic cue still supplies actual catalogue provenance. Do not introduce placeholder IDs or discard ambiguous alternatives.
- For `exact` candidate evidence, require the matched dictionary term to equal the occurrence's original literal. A differing term must not be reported as exact.
- If fuzzy evidence repeats the dictionary term, require it to agree with the candidate's matched term.
- Do not implement normalization or edit-distance computation to validate other methods. Document what those records assert and what still requires the future matcher.

Test rejection of empty candidate lists and contradictory exact evidence. Retain acceptance of source-only material records, generic cues, multiple candidates, and properly labelled normalized-exact records.

## 3. Preserve combined preset selections in run provenance

The singular optional `RunProvenance.preset` cannot preserve a request selecting both `materials` and `equipment`. Storing only their resolved components loses the user's original selection.

Represent a collection of requested presets separately from directly requested components and already resolved components. Use the smallest clear contract change; update its consumers, tests, and example. Preserve the supplied selection rather than resolving it in a validator.

Approved presets are exactly:

- `unit_operations`
- `unit_operations_with_steps`
- `materials`
- `materials_with_quantities`
- `equipment`
- `equipment_with_parameters`
- `full`

Independent component vocabulary remains `unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`, `quantity_expressions`, and `parameter_value_expressions`.

“With” means co-execution, not association or required child data. Component-only requests remain representable. Do not implement preset expansion, component unions, configuration loading, or dispatch; those remain L02/later work.

Test lossless serialization of two selected presets, a component-only request, and separation of requested selections from resolved components.

## 4. Validate outcome coverage against the supplied resolved components

The current illustrative-result validator accepts a run resolving `materials` and `equipment` while reporting only `materials: completed`, with overall `completed`. It also accepts the selected equipment component explicitly marked `not_requested`.

Add a small reusable pure coherence check taking the existing run provenance and extraction outcome records:

- Every resolved component has exactly one outcome and cannot be `not_requested`.
- A component outside the resolved selection cannot claim executed work. It may be absent or explicitly `not_requested`.
- Existing per-component and overall outcome invariants still apply after this selection/coverage check.

Call this check from the illustrative validation boundary. It must also be usable independently, without loading pages, performing preset resolution, or implementing a runner.

Test missing selected outcomes, selected-but-not-requested outcomes, and unexpected executed components. Preserve valid completed-zero results, all-failed runs, and partial runs retaining completed components. Successful publication of a partial extraction remains valid; interrupted/failed publication still cannot carry a final-manifest success claim.

## 5. Complete the missing rule provenance

Value occurrences currently cannot record the fixed rule that recognized them, and run provenance has an internal-rules version but no rules hash.

- Give value-expression occurrences an explicit fixed V1 recognition-rule identity, with a small typed representation consistent with existing method/rule records. It must survive serialization for every supported value form. Do not introduce user-configurable parsing rules or require dictionary candidates for values.
- Add the internal-rules SHA-256 provenance field alongside the existing version, using the existing hash-validation convention. L01 only stores/validates a supplied digest; it must not implement hashing or invent a production digest. Clearly labelled synthetic fixture digests are appropriate for tests/example.

Test rule identity and rules-hash round trips and invalid hashes. Preserve existing HTML, snapshot, effective-configuration, engine, and dependency provenance. Do not weaken required validated-input metadata; pre-validation failures and missing OCR references remain valid under their existing distinct contracts.

## 6. Bound recorded fuzzy evidence without implementing fuzzy search

`FuzzyEvidence` currently accepts a missing distance or distance `999`. This cannot substantiate the restricted V1 rule, which reports an edit distance and permits at most one character edit for eligible words of at least six characters.

- Require a strict recorded integer edit distance bounded by the agreed maximum of one. Do not calculate the distance in L01.
- Do not treat an arbitrary phrase as approved fuzzy evidence. V1 has no approved phrase-alignment rule; keep phrase matches exact/normalized-exact and fuzzy evidence within the restricted eligible single-word scope.
- Check the simple recorded term eligibility constraints that can be established without a matcher. Keep chemicals, chemical identifiers, UNII, units, and codes outside fuzzy scope. Do not invent a semantic term-classification subsystem.
- Correct the existing test that uses `Impeller speed` as an accepted fuzzy phrase. Use a valid eligible single-word example for fuzzy record tests.

Test missing/out-of-range/coerced distance, short terms and phrases, a valid eligible record, and existing prohibited candidate categories. A passing contract check records a structurally valid claim; actual metric verification and matching remain future work. Fuzzy remains optional and OFF by default.

## 7. Remove obsolete script references

The following scripts have been removed from the repository and must no longer appear in project configuration or documentation:

- `merge_files.py`
- `merge_files1.py`
- `merge_files2.py`
- `extract_chebi_materials.py`
- `compare_material_names.py`

The review found their current references in `pyrightconfig.json` and `.ai/03_common_handoff.md`. Remove them from the Pyright `include` list and remove/update the obsolete missing-file-notice prose. Search the working tree before completing and remove every remaining reference to these exact names from tracked project files. Do not recreate the scripts or add compatibility placeholders.

This is repository housekeeping needed for a clean quality gate; it does not change the lexical engine architecture. The final report must name every file changed for this cleanup and report the search result.

## Verification, documentation, and completion evidence

Update the synthetic JSON example to exercise the corrected public validators and preserve its independent parameter/unit/value evidence and partial-extraction/completed-publication case. Keep it clearly synthetic. Do not fabricate output from the real reviewed document.

Run the focused lexical contract tests, then the existing repository quality gate using its supported environment. Report actual commands/results; do not weaken gates, target a historical test count, or edit unrelated files to obtain green output. Retain existing meaningful tests while correcting fixtures that assert invalid behavior.

Update only relevant documentation statements, including combined preset provenance, required fuzzy evidence, dictionary support, the new coherence guarantees, and removal of obsolete Pyright targets. Continue to distinguish implemented contracts from unimplemented runtime behavior and pending user acceptance.

Return:

1. Changed files and a concise explanation of each corrected invariant.
2. Public contract changes and which negative regressions now reject the previously accepted contradictions.
3. Actual focused-test and quality-gate results, with environment limitations if any.
4. The updated contracts, tests, and **the actual `result-example.json` file** for review, plus relevant documentation changes.
5. Exact post-change search evidence that none of the five obsolete script names remain in tracked project files.
6. Confirmation that runtime extraction/publication remains unimplemented and L02 was not started.

**Stop after these L01 corrections. Await review and explicit user acceptance. Do not start L02 or any later work item.**
