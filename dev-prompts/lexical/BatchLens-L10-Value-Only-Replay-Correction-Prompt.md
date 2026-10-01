# BatchLens — L10 final focused correction: value-only reviewed-HTML replay

L01–L09 are user-accepted. The corrected L10 stream, unit aggregation, and value rules are implemented/test-reported, but L10 is awaiting user acceptance. Fix **only** the value-only replay gap below; do not start L11 or change accepted L01–L09 behavior.

Read current `AGENTS.md`, `.ai/03_common_handoff.md`, `src/app/lexical_extraction/parameter_unit_value.py`, `dictionary_matcher.py` (`ReviewedHtmlBlockReplay`), `html_reader.py`, and their focused tests. Keep the existing bounded lockstep design and per-block resource limit.

When `quantity_expressions` or `parameter_value_expressions` runs **without** `parameter_names` or `units`, `iter_parameter_unit_value_block_records` accepts `expected_source_identity` for a fresh `ReviewedHtmlBlockReplay`. But `_iter_merged_blocks` reads `blocks.source_identity` while yielding the first block. A fresh replay raises `REPLAY_IDENTITY_UNPINNED` until a full successful pass completes; the supplied expected digest does not help. Thus direct value-only extraction from valid reviewed HTML fails despite an expected SHA-256.

Correct the value-only path so it streams blocks without an all-document buffer, permits exactly this unpinned-first-pass case when an expected full-file identity was supplied, and verifies the finalized replay identity **after full consumption** before publishing completed coverage. If the digest differs, reading fails, or iteration stops early, report an explicit failure/incomplete outcome with no completed coverage. If the replay was already pinned, keep the existing immediate identity checks. Do not mask any other `DictionaryMatchError`, weaken L03 final-digest semantics, or invent input metadata. Keep synthetic/static sources working.

Add a compact test using a valid synthetic reviewed HTML v1 file and a *fresh* `ReviewedHtmlBlockReplay`: a value-only request with the correct expected SHA-256 returns the expected original spans and completed coverage; a deliberately wrong expected digest cannot yield completed coverage. Also retain the existing multi-block/per-block-buffer and early-close regressions. Use the existing HTML test fixture conventions; no full production Materials rerun is needed.

Change only `parameter_unit_value.py`, focused L10 tests, and concise `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` facts if needed. Run focused L10 tests, combined lexical tests, and `scripts/quality.ps1`; report actual results and changed files. **Stop for L10 review; do not claim user acceptance or begin L11.**
