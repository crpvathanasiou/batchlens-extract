# BatchLens — L06 focused boundary correction

L01–L05 are user-accepted. L06 helpers are implemented and test-verified according to your report (17 focused, 153 lexical, 423 total tests), but L06 is **not user-accepted**. Correct only the false-positive boundary cases below; do not start L07, Aho–Corasick, matching, fuzzy, value parsing, aggregation, or a runner.

## Independently reproduced findings

With the supplied `comparison.py`, a shorter source-backed term projects to a valid `CharSpan` inside a distinct compound expression:

| Term / hint | Block text | Current outcome | Required outcome |
|---|---|---|---|
| `min` / `atomic_unit` | `min⁻¹` | accepted `[0,3)` | reject the shorter unit |
| `mL` / `atomic_unit` | `mL·min⁻¹` | accepted `[0,2)` | reject the shorter unit |
| `kg` / `atomic_unit` | `kg²` | accepted `[0,2)` | reject the shorter unit |
| `glucose` / `default` | `glucose-6-phosphate` | accepted `[0,7)` | reject the shorter material name |
| `water` / `default` | `water-soluble` | accepted `[0,5)` | reject the shorter material name |

The first three violate the L06 rule not to split atomic/compound units. The last two allow a material name inside a hyphen-connected chemical/expression, despite the agreed conservative word/code boundary. These are boundary errors, not offset errors: the returned slices are literal but describe the wrong lexical extent. I did not independently rerun Cursor's Windows quality gate or full snapshot here.

## Required correction

- Make the fixed `atomic_unit` boundary treat unit-continuation symbols as part of the token: at least `/`, middle dot `·`, hyphen, superscript signs and numeric characters (including category `No`, not just decimal `Nd`), plus letters/marks and connector punctuation. Reject shorter unit hits inside `min⁻¹`, `mL·min⁻¹`, `kg²`, and `rpm/min`. Preserve an eligible **complete** term such as `min⁻¹` or `mL/min`. Number-adjacent unit matches `37°C` and `120rpm` remain valid; allow left numeric adjacency for ordinary decimal digits (`Nd`) rather than treating a superscript from a compound unit as a fresh number boundary.
- Treat a hyphen directly adjacent to a prospective `default` hit as a word/code continuation. Reject `glucose` in `glucose-6-phosphate` and `water` in `water-soluble`; a full punctuation-bearing chemical name must still match as its own term. Preserve valid overlaps across real word separators (for example `granulation` and `wet granulation` at their respective boundaries). No stemming, chemical inference, language filter, or new user-facing profile setting.
- Keep comparison text, original Unicode offset projection, complete-unit alignment, `ComparisonError` behavior, L03/L05 source records, and existing accepted L01–L05 modules unchanged. Do not turn this into a general tokenizer.

## Tests, documentation, stop

Extend `tests/lexical_extraction/test_comparison.py` with cases through `project_against_block` or `project_comparison_range`, not only `respects_boundary`, for every reproduced rejection and the positive full-compound/number-adjacent/phrase-overlap cases. Check each accepted span against the original block slice. Update only `src/app/lexical_extraction/comparison.py`, the focused tests, and concise L06 boundary facts in `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` as needed.

One separate accuracy note: the documentation currently says **always NFC**, while the implementation normalizes a base plus nonzero-combining-mark unit, so adjacent Hangul Jamo `가` remains uncomposed although `unicodedata.normalize('NFC', '가') == '가'`. In this bounded pass, state the exact supported V1 composition scope accurately in the L06 docs; do not add a general Unicode segmentation framework as a side task. If the existing contract requires complete NFC across all scripts, report that concrete incompatibility for review instead of claiming it is implemented.

Run focused comparison tests, combined lexical tests, and `scripts/quality.ps1`. Return changed files, exact boundary rules, regression outcomes, quality-gate evidence, and any remaining Unicode normalization limitation. Keep L06 awaiting user review and explicit acceptance. **Stop before L07.**
