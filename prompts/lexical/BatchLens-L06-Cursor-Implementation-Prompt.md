# BatchLens — L06: Fixed comparison normalization, source offsets, and boundaries

## Authorization and stop

L01–L05 are implemented, test-verified according to their completion reports, reviewed, and **user-accepted**. In particular, L05's bounded `FieldMappingError` correction is accepted. Implement **L06 only**: small, pure fixed-V1 helpers that prepare temporary comparison text for one L05 term or one L03 block, map comparison ranges back to original Unicode code-point offsets, and decide whether a prospective range respects the term's boundary role. Stop after the L06 completion report. Do not start L07.

Do **not** implement Aho–Corasick, sharding, scanning the SQLite snapshot or full document, candidate aggregation, L01 occurrences, fuzzy edit distance, value parsing, component orchestration, runner/CLI, monitoring, or publication in this task. There is still no manual extraction UI or runnable end-to-end extraction at L06.

## Inspect the accepted baseline

In `C:\Users\User\batchlens-extract`, read `AGENTS.md`, current `.ai/03_common_handoff.md`, relevant `.ai/02_code_quality_standards.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and the normalization/evidence sections of the lexical implementation handoff **if present**. Inspect `src/app/lexical_extraction/{contracts,field_mapping,html_reader,configuration}.py` and their focused tests. Do not assume the handoff file is present; the requirements in this prompt and the current repository contracts suffice. Keep the accepted public behavior and source files unchanged.

L03 `BlockEvidence.text` and L05 `EligibleSearchTerm.literal` retain original source spelling. L05 supplies `term_role`, `component`, and `boundary_hint` (`default`, `whole_code`, `atomic_unit`); `fuzzy_allowed` is only an internal hint. L01 `CharSpan` is zero-based, half-open in **original Python Unicode code points**, and `validate_match_against_block` requires literal slice equality. L02 does not offer profile or algorithm selectors.

## Deliverable and fixed rules

Create one focused module, for example `src/app/lexical_extraction/comparison.py`, with a narrow typed API for (1) normalizing an individual term, (2) normalizing a single block while retaining a comparison-to-original range map, and (3) validating/projecting a prospective comparison range to a literal original block slice after the correct boundary check. The comparison representation may be a small immutable record. It must be possible for L07 to consume it without re-normalizing a full document or guessing source offsets. No global term list, normalized snapshot, persistent index, or user-configurable policy.

Implement and document **fixed V1 internal rules** keyed by the actual L05 roles/hints, not an alternative search-profile framework:

- Natural-language labels (`equipment_type`, `parameter_name`, `unit_operation`, `generic_cue`, `process_step`): controlled Unicode composition/case folding and whitespace-run comparison. Keep meaningful hyphens, underscores, punctuation, and digits; multiword terms remain whole. Do not stem, transliterate Greek/Latin lookalikes, strip accents indiscriminately, join across unrelated blocks, or repair line-end hyphens/OCR mistakes.
- Materials names/aliases: a conservative fixed textual comparison with case handling and Unicode composition, **preserving** chemical punctuation, signs, digits, stereochemical notation, and source alias qualification. Make the exact transformation explicit in docs/tests; normalization is a search comparison, never an entity merge. Do not add a language filter or search excluded columns. Treat UNII (`whole_code`) separately: no fuzzy and no punctuation-stripping or digit substitution.
- Unit spellings (`atomic_unit`): preserve their meaningful symbols, slash compounds, superscripts, and punctuation. No fuzzy or conversion. Do not split a compound unit into shorter unit terms. The later value parser owns number–unit grouping.

Derive comparison text **and provenance of each resulting comparison code point** from the same operation. Handle case-fold expansion (`ß`→`ss`), composed versus decomposed accents, combining marks, supplementary characters, CR/LF and repeated whitespace. A valid returned original range must cover complete source normalization units and satisfy `block.text[start:end] == matched_text`; never use normalized indices as original offsets. Reject a prospective range that starts/ends in the middle of one expanded/composed source unit, rather than emitting a misleading partial original slice. Empty/whitespace-only comparison keys or otherwise unrepresentable terms must fail explicitly with a bounded diagnostic, not silently disappear.

Boundary rules are role-aware and fixed in code. Check both sides of the **original projected range**, with Unicode letters/combining marks/digits and meaningful connector characters handled intentionally. Natural and material terms must not match inside longer words/codes; UNII must use whole-code boundaries (including adjacent alphanumerics, `_`, and `-`), so a valid code is not found as a substring of a longer identifier. Units must not be matched as subparts of longer words or slash compounds; permit ordinary number-adjacent spellings such as `37°C` and `120rpm` when the complete unit token is present. Do not apply a universal `\b`/`isalnum()` test to all roles. If a concrete punctuation case makes one rule ambiguous, choose a conservative documented V1 rule and test it; do not infer a document association.

## Meaningful verification

Add `tests/lexical_extraction/test_comparison.py` with independent expectations for:

1. Case/Unicode composition and whitespace comparisons while retaining exact original block text; a match after combining marks, case-fold expansion, newlines, and supplementary Unicode projects to the right half-open code-point range. Explicitly reject partial expansion and off-by-one projections.
2. Term-role boundaries: embedded natural word, overlapping longer phrase (the boundary helper must not suppress a valid overlap), short UNII inside a longer alphanumeric or hyphen/underscore code versus isolated code, punctuation-bearing chemical names, `rpm` as a word versus `rpm/min`, and `°C`/`rpm` after a number. Preserve original matched text even when comparison text differs.
3. Empty/whitespace-only and malformed prospective ranges give stable explicit errors. Per-block work does not accumulate a document or dictionary; source L03/L05 objects remain unchanged. These are pure helper tests, **not** a fake Aho–Corasick or an end-to-end extraction test.

If the reviewed HTML v1 sample is locally present, an optional **read-only single-block** probe may exercise the helpers; state clearly whether it was performed. Do not claim that L06 measured full-Materials matching or memory. Run focused L06 tests, combined lexical tests, and `scripts/quality.ps1`; report actual results without targeting previous counts.

## Files and completion report

Permitted implementation changes: the new comparison module and focused test file, with only minimal package re-export if the repository convention requires it. Update `.ai/03_common_handoff.md` as the state anchor, `.ai/04_code_map.md` for the new module, and concise settled L06 rules in `.ai/05_pipeline_contracts.md` / `.ai/01_implementation_roadmap.md` where relevant. Record L05 as user-accepted. No changes to L01–L05 behavior, reviewed HTML producer, snapshot, configuration surface, or unrelated application paths.

Return the public helper signatures, fixed V1 comparison/boundary decisions, representative original-slice examples, changed files, focused/combined/full quality results, any remaining concrete limitation, and an explicit statement that matching and extraction remain unimplemented. **Stop and await L06 review and acceptance before L07.**
