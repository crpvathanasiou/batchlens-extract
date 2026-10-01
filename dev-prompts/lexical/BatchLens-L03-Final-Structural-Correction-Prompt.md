# BatchLens — L03 final structural fail-closed correction

The bounded streaming correction is substantially correct, but L03 is **not user-accepted yet**. Make only the focused structural-validation fix below, with regressions and accurate handoff evidence. Preserve the current streaming/digest API, accepted L01/L02 contracts, and reviewed HTML renderer. No L04 work.

## Independently reproduced findings

The corrected `html_reader.py` now rejects the previously reported missing `data-node-id` on `<p>`/`<td>` inside an article and source nodes outside pages. I reran it against the supplied reviewed HTML v1 export: **18 pages, 728 blocks**, completed, SHA-256 `e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`. This is a programmatic scratch smoke check, not Cursor's full quality gate or manual highlighting acceptance.

Four small malformed inputs are still accepted as complete:

1. An unmarked `<h3>Source heading</h3>` directly inside `section.page` (outside `article.element`) produces zero blocks. The producer's page label is marked `data-generated="true"`; unmarked heading content must not silently disappear.
2. `<article class="element" data-kind="text" data-element-id="a">Important source text</article>` produces zero blocks. The renderer puts source text in a child `p data-node-id`; bare text in the article is invalid source-bearing structure.
3. `<article class="element" data-kind="text" data-element-id="a"><img data-node-id="a" alt="source"></article>` produces zero blocks because void tags bypass provenance checks. An unsupported tag carrying `data-node-id` must fail, including a void tag.
4. `<article class="element" data-kind="table" data-element-id="a"><table data-table-id="different">...<td data-node-id="c" ...>source</td>...</table></article>` produces a cell with `table_id="different"`, even though the renderer's table ID is the owning article's catalogue `data-element-id`. This is false ownership evidence.

## Required change

- Validate the producer's source structure before marking a page complete. Inside a physical page, ungenerated source-bearing `p`/`h2`/`h3`/`h4`/`footer`/`td`/`th` outside an `article.element` must fail with a stable structured read error; the v1 producer renders such blocks under an article. Keep the renderer's generated `Page N` heading excluded, and allow ordinary structural whitespace/markup outside articles.
- Non-whitespace bare text directly within a source `article.element` (or other malformed source-bearing wrapper) must fail instead of being dropped. Ordinary whitespace between child tags is valid. Avoid rejecting source text inside a correctly opened node.
- Check `data-node-id` before returning early for void tags. A source-bearing unsupported tag must fail; no silent omission. Preserve `<br>` handling in a valid source node and normal void tags in the document head.
- Validate that a source `<table data-table-id>` belongs to its enclosing `article.element` and that its ID equals the owning `data-element-id`; cells must not be attributed to an unrelated table. Preserve nested child articles and valid empty cells.
- For these malformed cases, ensure the iterator cannot reach `completed=True` or expose finalized `validated_input`. Do not alter producer markup or fabricate missing IDs.

Add one focused regression per reproduced case, plus a renderer-backed positive test for generated page labels, source headings, captions, cells, and nesting. Recheck the existing streaming before-EOF and digest tests. Run focused reader tests, combined lexical tests, and `scripts/quality.ps1`; report actual results. Update `.ai/03_common_handoff.md` and `.ai/05_pipeline_contracts.md` only if the documented fail-closed behavior or results change; avoid broad documentation rewrites. If a reviewed HTML v1 export is unavailable in your workspace, record that plainly and do not claim my scratch check as yours.

Return changed files, error codes for the four cases, tests/gates, and remaining limits. **Stop after this L03 correction and await review/explicit acceptance.**
