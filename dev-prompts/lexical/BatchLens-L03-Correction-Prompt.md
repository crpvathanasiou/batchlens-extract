# BatchLens — L03 focused correction: bounded reading and fail-closed source evidence

L03 is **not accepted yet**. Correct only the concrete reader gaps below, add meaningful regression tests, update the L03 handoff evidence, and stop. Do not implement L04, matching, SQLite access, values, CLI, publication, or unrelated review UI changes. Preserve the accepted L01/L02 contracts and the reviewed HTML producer.

## Evidence from independent review

Inspection of the supplied `html_reader.py` shows that `open_reviewed_html()` calls `Path.read_bytes()` and decodes the entire HTML, `_extract_root_attributes()` parses that string, and `_iter_page_records()` parses it again into `parser.pages` before yielding any page. Thus the normal `iter_pages()` path retains the whole input and all `PageRecord`s; its page-oriented signature does not bound memory by page as required. Keep `read_all_pages()` only as an explicitly small/test convenience if useful; the production path must not use it.

I separately ran the reader against an available reviewed HTML v1 sample: it completed with **18 physical pages and 728 source blocks**, SHA-256 `e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`. This is a programmatic parser smoke check in the GPT scratch workspace, not Cursor's full gate or manual highlighting acceptance; do not claim the sample is in your workspace.

These minimal inputs were **accepted as complete** by the supplied reader despite losing source evidence:

- `section.page > article.element > <p>Important source text</p>` with no `data-node-id`: one page, zero blocks.
- A table `<td>` with source text and the normal geometry but no `data-node-id`: one page, zero blocks.
- A source `<p data-node-id="outside">Important source text</p>` outside any `section.page`: zero pages, successful completion.

The root version is currently parsed with `int(...)`, so `data-review-html-version="01"` can be accepted as version 1. The producer's v1 attribute is exactly `"1"`. The parser also ignores duplicate HTML attributes when it builds a `dict`; a duplicate provenance attribute should not silently choose one value.

## Required corrections

1. Implement an actually **bounded page-reading path**. Parse the file in finite chunks with incremental UTF-8 decoding and a real HTML parser; emit/release completed pages in DOM order without retaining the entire HTML text or a growing list of all `PageRecord`s. A retained current page, current source block, small chunk/queue, and bounded identity sets for duplicate detection are acceptable. Document the remaining per-page/per-block and identity-set memory limits honestly. Do not replace the reader with a generic streaming framework.

2. SHA-256 must cover the **exact bytes parsed**. Make the `validated_input` and `completed` semantics explicit under streaming: required root metadata is checked before its evidence is used, but no final `ReviewedHtmlV1Input` with an exact whole-file digest and no successful-completion claim is available until all bytes and the closing structure validate. An interrupted consumer or late error must not yield a finalized identity or complete claim. You may adjust the L03 public reader API/tests to express this cleanly; do not weaken L01's required metadata or invent a digest. If you choose two passes, verify that the second pass consumed the same bytes before finalizing identity.

3. Fail closed on **source-bearing content that would otherwise be silently omitted**. In a non-generated `article.element` inside a physical page, `p`, `h2`, `h3`, `h4`, `footer`, `td`, and `th` containing source text (including valid empty table cells) require producer provenance and must become one block or produce a structured input error. Require cell ownership/geometry and preserve nested articles, table captions, headings, footers and valid empty blocks. A source `data-node-id` outside `section.page`, unsupported source-bearing element, or unexpected markup inside a source block must not be ignored or flattened as though it were valid producer markup. Do not reject ordinary structural tags or whitespace outside source blocks, and keep `data-generated="true"` subtrees excluded.

4. Require the exact root version string `"1"`; reject `"01"`, `"+1"`, or whitespace variants. Detect duplicate attributes that affect the root identity or page/block provenance instead of taking the last dictionary value. Return stable `ReviewedHtmlReadError`/structured errors for these malformed inputs; avoid leaking a raw parser/Pydantic error. Preserve legitimate absent OCR references and the documented `data-source-id` whitespace ambiguity without changing renderer/L01.

## Regression checks

Extend `tests/lexical_extraction/test_html_reader.py` with focused assertions for each reproduced omission, source text outside a page, noncanonical version, duplicate provenance attributes, and unexpected nested source markup. Verify early iterator close and late malformed input leave `completed` false and no final validated-input digest. Prove the normal `iter_pages()` path can yield an early page **before reaching EOF**, and that it does not retain all pages or the entire file (for example, with an instrumented bounded reader or a suitably large synthetic export; avoid brittle timing-only tests). Preserve the existing successful renderer-backed cases, including page order, text and `<br>`, Unicode spans, ownership, empty cells, generated exclusion, and OCR references.

If you can access a newly exported reviewed HTML v1 file locally, run a read-only smoke check with counts/hash and representative text slices; otherwise explicitly mark that part unverified. Do not substitute original-conversion `document.html`.

Run focused reader tests, combined lexical tests, and `scripts/quality.ps1` in the supported environment. Report actual commands and results; no historical test count is a target. Update `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and the concise L03 roadmap status only as needed to describe the corrected API, validation/completion behavior, memory limits, verification, and remaining scope. Do not state that L03 was user-accepted.

## Completion report and stop

Return changed files, the corrected reader API and its bounded-memory/final-digest semantics, the explicit errors for each reproduced case, tests and gate results, any real-sample check, and unresolved limitations. **Stop after this L03 correction; await review and explicit acceptance.**
