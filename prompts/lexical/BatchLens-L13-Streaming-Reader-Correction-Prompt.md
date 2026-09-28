# BatchLens — L13 focused streaming-reader correction

## Baseline and stop boundary

L01–L12 are user-accepted. L13 publication correction is implemented and reported as test-verified, but L13 is **not user-accepted**. Fix only the component-artifact reader defects below. Read the current repository `AGENTS.md`, `.ai/03_common_handoff.md`, `src/app/lexical_extraction/publication.py`, and `tests/lexical_extraction/test_publication.py`. Use current code, not historical uploaded copies. Keep the published component JSON schema, CLI exits, writer, manifest-last/partial semantics, output-path guard, and L01–L12 behavior unchanged. No review UI or later milestone.

## 1. Really bound the reader buffer

In `_iter_streamed_pages`, `buf` retains consumed characters and `index` keeps moving forward; `_fill()` appends to that same string. For a large artifact, the reader thus retains the entire previously parsed prefix even though it yields one block at a time. Compact/release consumed input after each complete header/page/block token, keeping only a bounded unread lookahead plus the current `BlockRecord` (or one unusually large block being decoded). Avoid copying a growing artifact prefix repeatedly. A test with many pages/blocks must demonstrate a bounded retained parser buffer or peak memory that does not scale with previously consumed records; testing that the first page arrives before EOF alone is insufficient.

## 2. Decode UTF-8 across byte chunks

`_fill()` and `_read_until_pages_array()` call `chunk.decode('utf-8')` independently. A valid multibyte character cut at `_READ_CHUNK` becomes a false decoding failure. Use one incremental UTF-8 decoder for the stream, including header and body; finish/validate it at EOF. Preserve source block text and half-open Unicode code-point offsets. Add a deterministic test that forces a Greek/combining/supplementary character across the byte-chunk boundary in a published artifact, reads it successfully, and checks its exact span/text. Invalid UTF-8 must fail with a bounded explicit reader error.

## 3. Reject truncated or malformed final JSON

`_iter_streamed_pages` currently returns as soon as it sees the `]` closing `pages`; it does not require the enclosing `}`, EOF, or agreement with the header's `page_count`. Make the streaming parser validate the complete versioned JSON envelope and the actual page count. Enforce separators between pages/blocks and block-to-page ownership; reject leading/trailing/missing commas, truncated closing bytes, trailing non-whitespace data, and an incorrect page count. Error codes should be safe/structured rather than leaking document content. Tests must show that an artifact truncated directly after the pages array and an artifact with an extra/missing page are rejected after full consumption. This reader may be used independently of manifest hash verification, so it must not silently accept invalid JSON.

## 4. Make partial page consumption honest

`StreamedComponentPage.iter_blocks()` currently sets `_drained=True` in `finally` even when its generator is closed before reaching the end. Then `view.drain()` skips remaining blocks and the next page may parse from the wrong position. Either reliably drain on early close or fail explicitly on advancing with an incomplete page; do not claim the page was drained. Cover a caller consuming one block of a multi-block page, closing that iterator, then requesting the next page. Preserve the simple one-shot page API and cleanup of the underlying file handle.

## Verification

Keep existing L13 tests passing, including first-page-before-EOF, 120-block page, exact `locate_hit`, short write, path guard, partial publication, hash checks, and prior-run preservation. Add focused regressions for the four issues above. Run `tests/lexical_extraction/test_publication.py`, `tests/lexical_extraction/`, and `scripts/quality.ps1`; report actual results. A repeat of the 169.257 s production run is optional; its earlier result remains historical evidence for older code and cannot verify this reader. Update `.ai/03_common_handoff.md` and the relevant concise reader contract in `.ai/05_pipeline_contracts.md` if behavior changes. Report the exact bounded-buffer approach, UTF-8 and malformed/truncated outcomes, iterator cleanup behavior, and remaining limits. **Stop for L13 user review; do not advance to review UI or semantic/LLM work.**
