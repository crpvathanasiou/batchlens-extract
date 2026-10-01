# BatchLens — L05 focused term-eligibility correction

L05 is implemented and test-verified according to the supplied Cursor report, but it is **not user-accepted**. Correct only the three term-eligibility problems below in `field_mapping.py`, with focused regressions and concise documentation. Preserve L01–L04, the existing snapshot, the read-only streaming mapper, and all agreed V1 field selections. Stop before L06.

## Independently reproduced findings

Using the supplied mapper and synthetic L04 `SourceRow` records:

1. FDA/EMA `material_name="Water", UNII="N/A"` produces a `UNII` search term `"N/A"` with `boundary_hint="whole_code"`. The source string must remain intact in L04, but a known unavailable-ID marker must not become a chemical code mention in a document. Keep the usable `material_name` term and source `row_id`.
2. UO `Index this row="TRUE", Match policy="novel_policy", record_type="unit_operation"` produces a normal `unit_operation` term with the source `Operation ID`. The mapper has an explicit fallback that promotes unrecognized policy text to a direct candidate. That contradicts the rule to report unknown policy/record-type meanings rather than invent semantics.
3. `fuzzy_allowed=True` is set unconditionally on equipment types, parameter names and UO/step terms, including phrases and short words such as `Impeller speed` and `Pump`. L01 fuzzy evidence is limited to an explicitly eligible **single alphabetic word of at least six Unicode code points**, edit distance at most one. The mapper should not mark terms eligible when they already fail that fixed shape/scope. This is an internal hint, not an extra user switch; L05 still does not calculate fuzzy distance.

I have not independently rerun the full repository gate or the production 441 MB snapshot check. Cursor reported 28 focused tests, 125 combined lexical tests, and 395 total passing tests before this correction.

## Required correction

- Define a **small explicit code/identity availability rule** for the UNII search field and optional native ID attributes. Exclude exact, case-insensitive known unavailable markers such as `N/A`, `NA`, `unknown`, and `None` from **code search**; do not apply that rule to Materials names or aliases or add a language filter. Do not discard a naming row when its native ID is unavailable. Retain the original source cell in the immutable L04 row/snapshot, traceable by `row_id`. Avoid speculative broad cleaning or splitting identifiers. Keep real UNII codes as original literal terms with whole-code boundaries and no fuzzy.
- Make UO policy/record-type interpretation explicit and fail closed for unrecognized nonempty values on a row that would otherwise emit a UO search term. Use a bounded mapper error or equally explicit diagnostic rather than emitting a direct UO candidate or silently treating unknown as a known generic cue. Preserve the separate process-step rule: `Index this row=FALSE` does not suppress an independently eligible `Process step (EN)` term. The five observed V1 policies and two observed record types must continue to work according to their current documented roles. Do not alter the published source rows or decide a new policy for unknown values.
- Derive `fuzzy_allowed` conservatively from the fixed V1 restrictions: at minimum require an explicitly eligible natural-language role and a single alphabetic word of length ≥6; chemicals/chemical IDs and unit spellings remain false, as do phrases, short abbreviations, and code-like strings. Be conservative with context-required, support, inspection and generic cues; do not broaden fuzzy scope or add configuration. Test both a genuinely eligible single word and ineligible phrases/short words. The later matcher remains responsible for the actual optional fuzzy calculation and evidence.

## Focused verification

Extend `tests/lexical_extraction/test_field_mapping.py` with:

1. `UNII="N/A"` (and the chosen exact unavailable markers) yielding a usable material name but no UNII code term or fabricated native identity; a real UNII remains whole-code. An alias with literal `N/A`, if present as supplied text, must not be removed by an identifier-only rule.
2. Unknown UO `Match policy` and unknown `record_type` on otherwise active search rows giving an explicit error/diagnostic; known `direct_candidate`, `context_required`, `step_cue_only`, `support_only`, and `inspection_only` remaining distinct. Test independent process-step eligibility on `Index this row=FALSE`.
3. Fuzzy hints for eligible single-word equipment/UO terms versus `Pump`, `Impeller speed`, multiword process steps, UNII, Materials names, and units; no fuzzy distance or L01 match record generated.

If the real snapshot is locally available, report a bounded count/spot check for unavailable marker values in UNII and rerun a small read-only mapping smoke. Do **not** run full Materials matching or rewrite data. Run focused mapper tests, combined lexical tests, and `scripts/quality.ps1`, reporting actual results. Update `.ai/03_common_handoff.md` and `.ai/05_pipeline_contracts.md` only to reflect the corrected eligibility and checks; retain L05 as awaiting user acceptance.

Return changed files, corrected rules, test/gate evidence, any production observations, and remaining limitations. **Stop after this focused L05 correction; do not start L06.**
