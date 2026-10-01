# BatchLens — L11 focused correction: fuzzy evidence validation and resource test

## Accepted baseline and scope

L01–L10 are user-accepted. L11 is implemented and test-verified but **not yet user-accepted**. Correct the two concrete L11 review findings below. Read `AGENTS.md`, current `.ai/03_common_handoff.md`, and the current `fuzzy_matching.py`, `dictionary_matcher.py`, `dictionary_aggregation.py`, `comparison.py`, `field_mapping.py`, and `tests/lexical_extraction/test_fuzzy_matching.py` before editing. Use the repository versions, including any changes after the supplied review copies.

Do not start L12. Preserve L11's fixed one-edit rule, eligibility, OFF default, shard/replay lifecycle, exact/normalized behavior, accepted L01–L10 behavior, and L02 configuration.

## 1. Reject malformed or boundary-invalid fuzzy raw discoveries

The L08 aggregation adapter currently recomputes Levenshtein distance for an incoming `RawDiscovery(method="fuzzy")`, but distance 1 alone does not establish an eligible **document word**. For dictionary term `Filter`, `Fil ter` and `Filter!` are each one inserted character away, yet neither is one alphabetic observed word. A forged `Presure` span inside `xPresure` also fails the default word boundary despite its distance 1 from `Pressure`. The matcher normally filters these; aggregation must not turn an injected raw discovery into valid L01 fuzzy evidence.

At the existing fuzzy validation boundary, require the normalized observed comparison text to be **one alphabetic word** with the allowed one-edit length relative to the eligible source key. Reject punctuation, embedded whitespace, and other non-word comparison text. During block replay, where the actual block is available, require the fuzzy span to satisfy the source term's fixed L06 boundary against `block.text`, in addition to the existing literal slice equality. Use the existing comparison/boundary helpers; no new matching profile or framework. Preserve valid Unicode casefold and normalization-unit projection, and keep bounded `DictionaryAggregationError` / `SafeStructuredError` failures with no completed coverage. Treat `edit_distance` as an exact integer 1 if this is not already enforced (a boolean must not pass as 1).

Add focused regressions using synthetic source rows and a replay block: forged `Fil ter`, `Filter!`, and `Presure` inside `xPresure` fail without `coverage`, while a genuine `Presure` block yields `FuzzyEvidence(edit_distance=1)` and exact original offsets. Confirm that ordinary matcher output still aggregates normally and exact/normalized evidence is unchanged. Do not broaden this correction into revalidating all pre-existing non-fuzzy raw-discovery methods.

## 2. Make the signature-resource test meaningful

The current `max_term_codepoints_per_shard=20` failure case can fail on the **base reference alone**, so it does not prove that fuzzy deletion signatures are charged. Add a test with a limit **above** the exact-only reference cost but **below** the same reference plus its fuzzy signature cost. Show that `fuzzy_enabled=False` completes under that limit and `fuzzy_enabled=True` fails explicitly (`OVERSIZED_TERM` or the repository's defined finite resource error), without returning partial success. Retain the existing shard multiset and cleanup checks. No hardware RAM probe or dynamic shard sizing.

## Verification and stop

Limit production edits to the smallest L11 fuzzy/aggregation validation change; update `tests/lexical_extraction/test_fuzzy_matching.py` and concise `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` entries as needed. Run focused L11 tests, all `tests/lexical_extraction/`, and `scripts/quality.ps1`; report actual outputs, changed files, and the exact accepted/rejected cases. If current code already rejects a case, demonstrate it with a regression instead of rewriting it.

Mark L11 **awaiting user acceptance** and **stop**. Do not implement L12, runner/CLI, publication, UI, or unrelated changes.
