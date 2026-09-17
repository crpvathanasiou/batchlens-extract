"""Conservative tolerance-symbol ambiguity detector.

Scans already-extracted text in a contracts.Document for expressions that may
represent ± tolerances but are written with a plain + sign.  Detection is
advisory only: source text, values and symbols are NEVER modified.

Rules (all must hold for a finding to be emitted):
1. An explicit tolerance cue word must appear in the same text element or cell.
   Recognised cues (case-insensitive): "tolerance", "allowable deviation",
   and the isolated abbreviation "Toler" or "Toler.".
2. A bare +<number> pattern must be present (decimal point or comma allowed,
   e.g. "+0.1", "+ 1,5", "+2.50").
3. Explicit ± expressions are excluded — the symbol already makes intent clear.
   ASCII "+/-" and "+ / -" with one following number are also not flagged:
   they are not a bare +<number> form and are not OCR ambiguity.
4. Explicit asymmetric expressions (+X / -Y, including optional % suffixes)
   are excluded — already expressed.
5. "mass", "weight", "target" and unit presence alone are NOT sufficient.

Detection scope:
- Element text (layout-extracted text blocks).
- Table cell text.
- Does NOT re-parse textract.json or call any external service.

Deduplication:
- Source identity is based on the frozenset of block_ids from the item's
  references.  A finding is suppressed only when its exact block_id set
  matches one already emitted.  Items with different block_ids are treated
  as potentially distinct source locations even when their text is identical.
  If no block_ids are available, the finding is always emitted.

Warning code: POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY
Pages: source page number of the matched text.
Block IDs: source reference block IDs from the matched element or cell.
"""

from __future__ import annotations

import re

from app.document_conversion.contracts import Document, Reference, Warning

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Explicit cue in the same text span. "toler" / "toler." is the isolated
# abbreviation only; (?!\w) rejects prefixes of longer words such as "tolerable".
_CUE = re.compile(
    r"\b(?:tolerance|allowable\s+deviation|toler\.?)(?!\w)",
    re.IGNORECASE,
)

# Already-explicit ± — suppress the finding; intent is clear.
_EXPLICIT_PM = re.compile(r"[±]")

# Explicit asymmetric: +X / -Y — already expressed; not ambiguous.
# Optional % after either number, e.g. "+0.1% / -0.2%".
_ASYMMETRIC = re.compile(r"\+\s*\d+[.,]?\d*\s*%?\s*/\s*-\s*\d+[.,]?\d*\s*%?")

# Ambiguous bare + before a decimal or integer (decimal separator: . or ,).
# Negative lookbehind excludes ± prefix so we don't double-match.
_PLUS_NUMBER = re.compile(r"(?<![±])\+\s*\d+(?:[.,]\d+)?")

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _is_ambiguous(text: str) -> bool:
    """Return True iff text satisfies all detector rules for an ambiguous expression."""
    if not _CUE.search(text):
        return False
    if _EXPLICIT_PM.search(text):
        return False
    if _ASYMMETRIC.search(text):
        return False
    return bool(_PLUS_NUMBER.search(text))


def _collect(
    text: str,
    page_num: int,
    refs: tuple[Reference, ...],
    seen_block_id_sets: set[frozenset[str]],
    out: list[Warning],
) -> None:
    """Append a Warning to *out* if *text* is ambiguous and refers to a new source region.

    Source identity is determined by the frozenset of block_ids drawn from
    *refs*.  A finding is suppressed only when its block_id set is identical
    to one already emitted.  Items with different block_ids are considered
    potentially distinct source locations and both are retained, even when
    their text is identical.  If no block_ids are available, the finding is
    always emitted (source identity cannot be established).
    """
    if not text:
        return
    block_ids = tuple(r.block_id for r in refs if r.block_id)
    if block_ids:
        key = frozenset(block_ids)
        if key in seen_block_id_sets:
            return
    if _is_ambiguous(text):
        if block_ids:
            seen_block_id_sets.add(frozenset(block_ids))
        out.append(
            Warning(
                code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY",
                pages=(page_num,),
                block_ids=block_ids,
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_tolerance_ambiguities(document: Document) -> list[Warning]:
    """Return advisory Warning objects for possible tolerance-symbol ambiguities.

    Scans all page elements and table cells in the structured document.
    Deduplication is by source region identity (frozenset of block_ids), not
    by text content.  Two items with the same text but different block_ids
    represent distinct source regions and each produces its own warning.

    Does not modify any field of *document*.  Provider status is unchanged.
    """
    out: list[Warning] = []
    seen_block_id_sets: set[frozenset[str]] = set()

    for page in document.pages:
        page_num = page.number
        for element in page.elements:
            # Top-level element text (layout block, text region, etc.)
            _collect(element.text, page_num, element.references, seen_block_id_sets, out)
            # Table cells
            for cell in element.cells:
                _collect(cell.text, page_num, cell.references, seen_block_id_sets, out)

    return out
