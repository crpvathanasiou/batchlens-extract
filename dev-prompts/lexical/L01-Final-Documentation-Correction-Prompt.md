# BatchLens — L01 final documentation-boundary correction

L01 contracts and their correction pass are implemented and test-verified. This prompt authorizes only the small correction below. It does not authorize L02 or any parser, matcher, mapping reader, configuration, database, runner, monitoring, or publication work.

## Problem to correct

`05_pipeline_contracts.md` currently says, in its L01 candidate paragraph, that the fixed V1 boundary has “no Greek, brand, model, CAS search, or published range.” In that wording, “no Greek” incorrectly applies to the FDA/EMA and ChEBI Materials datasets.

The accepted field decision is narrower:

- `materials_fda_ema` searches only `material_name`, `alias_name`, and `UNII`; `CAS_NUMBER` and `SMS_ID` are not search fields.
- `materials_chebi` searches only `material_name` and `alias_name`; `CAS_NUMBER` and `CHEBI_ID` are not search fields.
- These Material selections are column-level V1 rules. They do **not** introduce a language filter or authorize deleting/excluding existing Material aliases because of their language.
- The exclusion of dedicated Greek fields, Brand / Manufacturer, Model, manufacturer/model IDs, and Published range applies to the equipment boundary; the dedicated Greek-field exclusion also applies to the Unit Operations boundary as already agreed.

## Authorized changes

Read `AGENTS.md`, current `.ai/03_common_handoff.md`, `.ai/05_pipeline_contracts.md`, and the current lexical contract tests first.

Change only:

- `.ai/05_pipeline_contracts.md` — replace the over-broad candidate-boundary sentence with concise, correct table-specific wording consistent with the rules above. Do not copy the full specification into this document.
- `tests/lexical_extraction/test_contracts.py` — add one focused contract regression showing that a valid FDA/EMA or ChEBI `alias_name` candidate with non-English/Greek text is accepted as source data. Keep the test about absence of a language filter; it must not imply that L01 performs search or language detection.
- `.ai/03_common_handoff.md` only if a one-line L01 state clarification is necessary to keep the restart anchor accurate.

Do not change `contracts.py` unless the focused test reveals an actual existing language restriction. Do not alter the JSON example, source field literals, fuzzy eligibility, the fixed equipment/UO exclusions, the flat snapshot, or any non-L01 application code.

## Verification and report

Run the focused lexical contract tests and the existing repository quality gate. Report exact commands and actual results. State the exact files changed and confirm that no new language-filter behavior was added.

Stop after this correction. L01 remains awaiting user acceptance; do not start L02.
