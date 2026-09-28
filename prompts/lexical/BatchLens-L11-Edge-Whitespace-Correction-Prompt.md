# BatchLens — L11 final focused correction: edge whitespace in fuzzy evidence

L01–L10 are user-accepted; L11 remains awaiting acceptance. The earlier L11 correction is implemented and test-verified. Apply **only** this remaining fuzzy-validation correction, then stop before L12. Read current repository `AGENTS.md`, `.ai/03_common_handoff.md`, `src/app/lexical_extraction/{dictionary_aggregation,fuzzy_matching,comparison}.py`, and `tests/lexical_extraction/test_fuzzy_matching.py` before editing.

## Reproduced review finding from code inspection

`_validated_edit_distance` normalizes an incoming fuzzy `RawDiscovery.span.matched_text` with `strip_edges=True`. L06 consequently discards leading/trailing whitespace **inside the claimed matched span**. A forged discovery for source `Pressure` can claim block text/span `" Presure"` (or `"Presure "`): after trimming, `presure` is alphabetic and distance 1, and the external `default` boundary of the oversized span is valid. L07's real matcher emits only the word, but L08 must not publish the forged oversized span as fuzzy evidence. The newly tightened `recompute_fuzzy_distance` helper has the same edge-trimming behavior.

Require the **entire observed span** to be one alphabetic word after L06 comparison normalization, without removing characters from its edges. Keep the source-term normalization and accepted Unicode/casefold behavior. Reject leading/trailing spaces, tabs, and newlines inside a fuzzy `matched_text`, with bounded structured failure and no completed aggregation coverage. Keep `Fil ter`, `Filter!`, boundary-invalid interior words, strict integer distance, and genuine `Presure` behavior unchanged. Update the public recomputation helper consistently or remove it only if clearly unused and doing so preserves its intended public surface; prefer the smallest correction.

Add focused regressions for `" Presure"` and `"Presure "` against `Pressure` with blocks equal to the claimed spans, plus an original block `" Presure "` where the *inner* word span `[1, 8)` is a valid fuzzy hit. Test that invalid cases have no completed coverage, while the valid span retains exact original offsets and `FuzzyEvidence(edit_distance=1)`.

## Unit-rule clarification (no change requested)

Units remain **non-fuzzy under all configurations**. The user accepted existing V1 `normalized_exact`/casefold unit behavior with `atomic_unit` boundaries, including `120 RPM` → `rpm`; do not change L10 unit recognition, value parsing, fixed aliases, or the user-facing configuration. No new manual-review workflow is part of this correction.

Run focused L11 tests, `tests/lexical_extraction/`, and `scripts/quality.ps1`. Update concise `.ai/03_common_handoff.md` and `.ai/05_pipeline_contracts.md` statements only if necessary. Report actual results and changed files; leave L11 awaiting user acceptance. **Stop before L12.**
