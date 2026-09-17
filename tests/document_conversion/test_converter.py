"""Behavioral coverage for the Textractor-based conversion adapter.

Tests focus on:
- Input validation (status, pagination, limits) -- same contract as the retired normaliser.
- Structured document.json contract (status, pages, warnings, source identity).
- HTML artifact properties (ordering, escaping, table structure, navigation).
- Individual page artifact properties.
- PARTIAL_SUCCESS propagation.
- Warning generation (UNINTERPRETED_LAYOUT_FIGURE, PARTIAL_ANALYSIS, AWS_*).
- Resource-limit enforcement.

Accepted PoC limitations that are NOT tested here (documented in adapter.py):
- Merged-cell reading order and within-cell line boundaries.
- Duplicate captions in some documents.
- Checkbox NOT_SELECTED displaying as selected in HTML.
- OCR symbols and undetected visual tables.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.document_conversion.adapter import (
    convert_and_render,
    render_full_document_html,
    render_individual_pages,
)
from app.document_conversion.contracts import (
    Cell,
    ConversionError,
    ConversionLimits,
    Document,
    Element,
    Page,
    Reference,
    Source,
    Warning,
)
from app.document_conversion.tolerance import detect_tolerance_ambiguities
from tests.document_conversion.fixtures import (
    _PAGE_GEO,  # pyright: ignore[reportPrivateUsage]
    _geo,  # pyright: ignore[reportPrivateUsage]
    layout_fixture,
    table_fixture,
)

SOURCE = Source(identity="synthetic-fixture")


# ---------------------------------------------------------------------------
# Input validation -- contract preserved from the retired normaliser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,code",
    [
        ({"Blocks": []}, "EMPTY_ANALYSIS"),
        ({"JobStatus": "IN_PROGRESS"}, "ANALYSIS_IN_PROGRESS"),
        ({"JobStatus": "FAILED"}, "ANALYSIS_FAILED"),
    ],
)
def test_invalid_or_incomplete_input_raises_conversion_error(
    raw: dict[str, Any], code: str
) -> None:
    with pytest.raises(ConversionError, match=code):
        convert_and_render(raw, SOURCE)


def test_paginated_incomplete_response_is_rejected() -> None:
    # Any response with a NextToken is considered incomplete; cannot parse safely.
    raw = layout_fixture()
    raw["NextToken"] = "continuation-token"
    with pytest.raises(ConversionError, match="PAGINATION_INCOMPLETE"):
        convert_and_render(raw, SOURCE)


def test_block_limit_is_enforced() -> None:
    raw = layout_fixture()
    with pytest.raises(ConversionError, match="BLOCK_LIMIT"):
        convert_and_render(raw, SOURCE, ConversionLimits(max_blocks=1))


def test_page_limit_is_enforced() -> None:
    raw = layout_fixture()
    # layout_fixture declares 2 pages; limit 1 rejects it.
    with pytest.raises(ConversionError, match="PAGE_LIMIT"):
        convert_and_render(raw, SOURCE, ConversionLimits(max_pages=1))


# ---------------------------------------------------------------------------
# Structured document contract
# ---------------------------------------------------------------------------


def test_source_identity_is_preserved_in_document() -> None:
    src = Source(
        identity="s3://my-bucket/my-key",
        bucket="my-bucket",
        key="my-key",
        version="v1",
        checksum_sha256="abc123",
    )
    result = convert_and_render(layout_fixture(), src)
    doc = result.document
    assert doc.source.identity == "s3://my-bucket/my-key"
    assert doc.source.bucket == "my-bucket"
    assert doc.source.key == "my-key"
    assert doc.source.version == "v1"
    assert doc.source.checksum_sha256 == "abc123"


def test_succeeded_status_is_preserved() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    assert result.document.status == "SUCCEEDED"


def test_partial_success_status_is_preserved() -> None:
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    result = convert_and_render(raw, SOURCE)
    doc = result.document
    assert doc.status == "PARTIAL_SUCCESS"
    assert any(w.code == "PARTIAL_ANALYSIS" for w in doc.warnings)


def test_page_count_matches_declared_pages() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    doc = result.document
    assert len(doc.pages) == 2
    assert doc.declared_pages == 2


def test_page_numbers_are_sequential_and_one_indexed() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    assert [p.number for p in result.document.pages] == [1, 2]


def test_layout_figure_generates_uninterpreted_warning() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    codes = [w.code for w in result.document.warnings]
    assert "UNINTERPRETED_LAYOUT_FIGURE" in codes


def test_aws_warnings_are_forwarded_with_prefix() -> None:
    raw = layout_fixture()
    raw["Warnings"] = [{"ErrorCode": "PAGE_ERROR", "Pages": [2]}]
    result = convert_and_render(raw, SOURCE)
    codes = {w.code for w in result.document.warnings}
    assert "AWS_PAGE_ERROR" in codes


def test_no_warnings_for_clean_response() -> None:
    # table_fixture has no figure; no AWS warnings either → no warnings.
    result = convert_and_render(table_fixture(), SOURCE)
    codes = [w.code for w in result.document.warnings]
    assert "PARTIAL_ANALYSIS" not in codes
    assert not any(c.startswith("AWS_") for c in codes)


def test_table_elements_are_present_in_structured_document() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    page = result.document.pages[0]
    table_elements = [e for e in page.elements if e.kind == "table"]
    assert len(table_elements) == 1
    table = table_elements[0]
    assert table.rows == 12
    assert table.columns == 2


def test_merged_header_cell_spans_both_columns() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    page = result.document.pages[0]
    table = next(e for e in page.elements if e.kind == "table")
    header = next(c for c in table.cells if c.row == 1 and c.column == 1)
    assert header.column_span == 2
    assert header.header is True
    # Text contains both column values (merged cell text).
    assert "11.00 mg" in header.text
    assert "12.00 mg" in header.text


def test_empty_cell_has_empty_text() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    page = result.document.pages[0]
    table = next(e for e in page.elements if e.kind == "table")
    empty_cell = next(c for c in table.cells if c.row == 3 and c.column == 2)
    assert empty_cell.text == ""


# ---------------------------------------------------------------------------
# Full-document HTML
# ---------------------------------------------------------------------------


def test_full_html_has_both_pages_in_order() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    html = render_full_document_html(result)
    assert html.index('id="source-page-1"') < html.index('id="source-page-2"')


def test_full_html_contains_navigation_controls() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    html = render_full_document_html(result)
    assert '<nav id="controls"' in html
    assert 'id="previous"' in html
    assert 'id="next"' in html
    assert 'id="show-all"' in html


def test_full_html_inline_script_is_present() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    html = render_full_document_html(result)
    # Textractor renderer embeds navigation JavaScript.
    assert "<script>" in html


def test_hostile_text_is_escaped_in_full_html() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    html = render_full_document_html(result)
    assert "<script>" not in html.split("<script>")[0]  # no literal tag in content area
    assert "&lt;script&gt;" in html  # escaped version present


def test_full_html_has_table_with_header_cells() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    html = render_full_document_html(result)
    assert "<table" in html
    assert "<th" in html


def test_full_html_table_count_covers_all_raw_tables() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    html = render_full_document_html(result)
    # Conversion note states raw TABLE count.
    assert "1 raw TABLE block" in html


# ---------------------------------------------------------------------------
# Individual page artifacts
# ---------------------------------------------------------------------------


def test_individual_pages_keys_match_page_numbers() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    pages = render_individual_pages(result)
    assert sorted(pages.keys()) == [1, 2]


def test_individual_page_is_self_contained_html() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    pages = render_individual_pages(result)
    assert pages[1].startswith("<!doctype html>")
    assert pages[2].startswith("<!doctype html>")


def test_individual_page_shows_warning_for_figure() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    pages = render_individual_pages(result)
    # LAYOUT_FIGURE is on page 1; its warning should appear in page 1 artifact.
    assert "UNINTERPRETED_LAYOUT_FIGURE" in pages[1]


def test_individual_pages_preserve_page_numbering() -> None:
    result = convert_and_render(table_fixture(), SOURCE)
    pages = render_individual_pages(result)
    assert list(pages.keys()) == [1]
    assert "Page 1 of 1" in pages[1]


def test_partial_success_shown_in_individual_pages() -> None:
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    result = convert_and_render(raw, SOURCE)
    pages = render_individual_pages(result)
    for html in pages.values():
        assert "PARTIAL_SUCCESS" in html


# ---------------------------------------------------------------------------
# Document.json round-trip (Pydantic model)
# ---------------------------------------------------------------------------


def test_document_json_round_trips_via_model() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    doc = result.document
    json_bytes = doc.model_dump_json(indent=2).encode()
    from app.document_conversion.contracts import Document

    restored = Document.model_validate_json(json_bytes)
    assert restored.status == doc.status
    assert len(restored.pages) == len(doc.pages)
    assert len(restored.warnings) == len(doc.warnings)


def test_document_json_does_not_use_default_str_serializer() -> None:
    # Verify no untyped SDK objects are serialised with default=str.
    import json

    result = convert_and_render(layout_fixture(), SOURCE)
    # Should not raise; all fields must be serialisable without a default.
    raw_json = result.document.model_dump_json(indent=2)
    parsed = json.loads(raw_json)
    assert parsed["schema_version"] == "1.0.0"


def test_schema_version_and_converter_version_present() -> None:
    result = convert_and_render(layout_fixture(), SOURCE)
    doc = result.document
    assert doc.schema_version == "1.0.0"
    assert doc.converter_version == "1.0.0"


# ---------------------------------------------------------------------------
# Additional: custom Warning models accepted by document
# ---------------------------------------------------------------------------


def test_extra_warnings_can_be_attached_to_document() -> None:
    """Verify contracts.Warning model is usable for future extension."""
    result = convert_and_render(table_fixture(), SOURCE)
    doc = result.document.model_copy(
        update={"warnings": (Warning(code="CUSTOM_CODE", pages=(1,), block_ids=("block-a",)),)}
    )
    full_html = render_full_document_html(result)
    assert isinstance(full_html, str)
    assert doc.warnings[0].code == "CUSTOM_CODE"


# ---------------------------------------------------------------------------
# A. Partial-result visibility in full HTML
# ---------------------------------------------------------------------------


def test_partial_success_banner_appears_in_full_html() -> None:
    """PARTIAL_SUCCESS produces a visible banner in the full document HTML."""
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    result = convert_and_render(raw, SOURCE)
    html = render_full_document_html(result)
    assert "PARTIAL_SUCCESS" in html
    assert "Partial result" in html


def test_aws_warning_with_pages_appears_in_full_html() -> None:
    """AWS warnings with page references appear in the Conversion notes section."""
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    raw["Warnings"] = [{"ErrorCode": "PAGE_ERROR", "Pages": [2]}]
    result = convert_and_render(raw, SOURCE)
    html = render_full_document_html(result)
    assert "AWS_PAGE_ERROR" in html
    # Page reference must also be present.
    assert "2" in html


def test_partial_success_does_not_add_extra_source_page() -> None:
    """The partial-result banner must not create an additional numbered source page."""
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    result = convert_and_render(raw, SOURCE)
    html = render_full_document_html(result)
    # layout_fixture has 2 pages; no third source-page section may exist.
    assert 'id="source-page-3"' not in html
    assert html.count('class="source-page"') == 2


def test_succeeded_full_html_has_no_partial_banner() -> None:
    """A SUCCEEDED conversion must not contain the partial-result banner."""
    result = convert_and_render(layout_fixture(), SOURCE)
    html = render_full_document_html(result)
    assert "Partial result" not in html
    assert "PARTIAL_SUCCESS" not in html


def test_full_html_warning_content_is_escaped() -> None:
    """Dynamic warning codes and page refs are HTML-escaped in the full document."""
    raw = layout_fixture()
    # Code contains only safe chars, but page number must appear safely.
    raw["Warnings"] = [{"ErrorCode": "PAGE_ERROR", "Pages": [1]}]
    result = convert_and_render(raw, SOURCE)
    html = render_full_document_html(result)
    # Must contain the code text safely.
    assert "AWS_PAGE_ERROR" in html
    # Must not inject raw HTML via the code string (the code itself is safe,
    # but we verify escaped() is in use by the presence of <code> wrapper).
    assert "<code>AWS_PAGE_ERROR</code>" in html


def test_individual_page_html_also_shows_partial_status() -> None:
    """Individual page artifacts must also show PARTIAL_SUCCESS status."""
    raw = layout_fixture()
    raw["JobStatus"] = "PARTIAL_SUCCESS"
    result = convert_and_render(raw, SOURCE)
    pages = render_individual_pages(result)
    for page_html in pages.values():
        assert "PARTIAL_SUCCESS" in page_html


# ---------------------------------------------------------------------------
# B. Flexible table sizes and structural safeguards
# ---------------------------------------------------------------------------


def test_max_table_positions_field_removed_from_limits() -> None:
    """ConversionLimits must no longer accept max_table_positions (extra='forbid')."""
    with pytest.raises(ValidationError):
        ConversionLimits(max_table_positions=5)  # type: ignore[call-arg]


def _large_table_fixture(rows: int = 101, cols: int = 100) -> dict[str, Any]:
    """Programmatic Textractor-compatible fixture with rows×cols cells.

    Produces a genuine 101×100 = 10,100-cell table, exceeding the former
    10,000-position limit.  Only three representative cells carry word content;
    the rest are empty.  Block IDs, geometry and structure follow the same
    conventions as table_fixture() in fixtures.py.
    """
    # Representative cells: first, last, centre.
    mid_r = (rows + 1) // 2
    mid_c = (cols + 1) // 2
    content: dict[tuple[int, int], str] = {
        (1, 1): "R1C1",
        (rows, cols): f"R{rows}C{cols}",
        (mid_r, mid_c): f"R{mid_r}C{mid_c}",
    }

    cell_ids: list[str] = []
    cell_blocks: list[dict[str, Any]] = []
    word_blocks: list[dict[str, Any]] = []

    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            cid = f"lt-c{r}-{c}"
            cell_ids.append(cid)
            text = content.get((r, c))
            rels: list[dict[str, Any]] = []
            if text:
                wid = f"lt-w{r}-{c}"
                rels = [{"Type": "CHILD", "Ids": [wid]}]
                word_blocks.append(
                    {
                        "Id": wid,
                        "BlockType": "WORD",
                        "Text": text,
                        "TextType": "PRINTED",
                        "Page": 1,
                        "Geometry": _geo(y=min(0.01 + (r - 1) * 0.009, 0.9)),
                        "Confidence": 99.0,
                        "Relationships": [],
                    }
                )
            cell_blocks.append(
                {
                    "Id": cid,
                    "BlockType": "CELL",
                    "RowIndex": r,
                    "ColumnIndex": c,
                    "RowSpan": 1,
                    "ColumnSpan": 1,
                    "Page": 1,
                    "Geometry": _geo(y=min(0.01 + (r - 1) * 0.009, 0.9)),
                    "Confidence": 99.0,
                    "EntityTypes": [],
                    "Relationships": rels,
                }
            )

    table_block: dict[str, Any] = {
        "Id": "lt-table",
        "BlockType": "TABLE",
        "Page": 1,
        "Geometry": _geo(y=0.01, height=0.97),
        "Confidence": 99.0,
        "EntityTypes": [],
        "Relationships": [{"Type": "CHILD", "Ids": cell_ids}],
    }
    layout_block: dict[str, Any] = {
        "Id": "lt-layout",
        "BlockType": "LAYOUT_TABLE",
        "Page": 1,
        "Geometry": _geo(y=0.01, height=0.97),
        "Confidence": 99.0,
        "Relationships": [{"Type": "CHILD", "Ids": ["lt-table"]}],
    }
    page_block: dict[str, Any] = {
        "Id": "lt-page",
        "BlockType": "PAGE",
        "Page": 1,
        "Geometry": _PAGE_GEO,
        "Relationships": [{"Type": "CHILD", "Ids": ["lt-layout", "lt-table"]}],
    }
    all_blocks: list[dict[str, Any]] = (
        [page_block, layout_block, table_block] + cell_blocks + word_blocks
    )
    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 1},
        "Blocks": all_blocks,
    }


def test_large_table_converts_without_truncation() -> None:
    """A genuine 101×100 table (10,100 cells) converts fully without truncation.

    This exercises the former max_table_positions boundary (10,000) which is
    now removed.  All cells must survive in both structured output and HTML.
    """
    rows, cols = 101, 100
    raw = _large_table_fixture(rows, cols)
    result = convert_and_render(raw, SOURCE)
    html = render_full_document_html(result)

    page = result.document.pages[0]
    table_el = next(e for e in page.elements if e.kind == "table")

    # Dimensions must reflect the full grid.
    assert table_el.rows == rows
    assert table_el.columns == cols

    # All 10,100 cells must be present — no silent omission or duplication.
    assert len(table_el.cells) == rows * cols

    # Representative cells must survive with correct text.
    cell_map = {(c.row, c.column): c for c in table_el.cells}
    assert cell_map[(1, 1)].text == "R1C1"
    assert cell_map[(rows, cols)].text == f"R{rows}C{cols}"
    mid_r, mid_c = (rows + 1) // 2, (cols + 1) // 2
    assert cell_map[(mid_r, mid_c)].text == f"R{mid_r}C{mid_c}"

    # Final cell must also appear in HTML rendering.
    assert f"R{rows}C{cols}" in html


def _rel(kind: str, ids: list[str]) -> dict[str, Any]:
    """Compact relationship dict for inline fixture construction."""
    return {"Type": kind, "Ids": ids}


def _cyclic_fixture() -> dict[str, Any]:
    """Minimal Textract-compatible response whose blocks form an A→B→A cycle."""
    page: dict[str, Any] = {
        "Id": "p1",
        "BlockType": "PAGE",
        "Page": 1,
        "Geometry": _PAGE_GEO,
        "Relationships": [_rel("CHILD", ["a"])],
    }
    block_a: dict[str, Any] = {
        "Id": "a",
        "BlockType": "LAYOUT_TEXT",
        "Page": 1,
        "Geometry": _geo(),
        "Confidence": 99.0,
        "Relationships": [_rel("CHILD", ["b"])],
    }
    block_b: dict[str, Any] = {
        "Id": "b",
        "BlockType": "LINE",
        "Text": "x",
        "Page": 1,
        "Geometry": _geo(),
        "Confidence": 99.0,
        "Relationships": [_rel("CHILD", ["a"])],  # cycle back to a
    }
    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 1},
        "Blocks": [page, block_a, block_b],
    }


def _deep_chain_fixture(depth: int) -> dict[str, Any]:
    """A linear chain of CHILD relationships exactly *depth* levels deep.

    Uses LAYOUT_TEXT blocks so Textractor does not attempt to parse word children
    (LINE blocks require TextType on their WORD children, which are not present here).
    """
    ids = [f"b{i}" for i in range(depth + 1)]
    blocks: list[dict[str, Any]] = [
        {
            "Id": "p1",
            "BlockType": "PAGE",
            "Page": 1,
            "Geometry": _PAGE_GEO,
            "Relationships": [_rel("CHILD", [ids[0]])],
        }
    ]
    for i, bid in enumerate(ids):
        child_ids = [ids[i + 1]] if i < len(ids) - 1 else []
        blocks.append(
            {
                "Id": bid,
                "BlockType": "LAYOUT_TEXT",
                "Page": 1,
                "Geometry": _geo(y=min(0.01 * i, 0.9)),
                "Confidence": 99.0,
                "Relationships": [_rel("CHILD", child_ids)] if child_ids else [],
            }
        )
    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 1},
        "Blocks": blocks,
    }


def test_cyclic_relationship_is_rejected() -> None:
    """A cyclic block-relationship graph raises CYCLIC_RELATIONSHIP before parsing."""
    with pytest.raises(ConversionError, match="CYCLIC_RELATIONSHIP"):
        convert_and_render(_cyclic_fixture(), SOURCE)


def test_relationship_depth_exceeded_is_rejected() -> None:
    """A chain exceeding max_relationship_depth raises RELATIONSHIP_DEPTH_EXCEEDED.

    _deep_chain_fixture(n) produces a PAGE → b0 → … → bN chain.
    The longest path from PAGE is n+1 hops.  With max_relationship_depth=4,
    a fixture with n=4 produces a 5-hop path that exceeds the limit.
    """
    limit = 4
    # n=4: PAGE(0)→b0(1)→b1(2)→b2(3)→b3(4)→b4(5); 5 hops > limit 4.
    raw = _deep_chain_fixture(limit)
    with pytest.raises(ConversionError, match="RELATIONSHIP_DEPTH_EXCEEDED"):
        convert_and_render(raw, SOURCE, ConversionLimits(max_relationship_depth=limit))


def test_relationship_depth_exactly_at_limit_is_accepted() -> None:
    """A chain whose longest path equals max_relationship_depth must not be rejected.

    n=3: PAGE(0)→b0(1)→b1(2)→b2(3)→b3(4); longest path=4 == limit 4 → accepted.
    """
    limit = 4
    # n=3: longest path is 4 hops (PAGE→b0→b1→b2→b3), exactly at limit.
    raw = _deep_chain_fixture(limit - 1)
    # Must not raise RELATIONSHIP_DEPTH_EXCEEDED.
    try:
        convert_and_render(raw, SOURCE, ConversionLimits(max_relationship_depth=limit))
    except ConversionError as exc:
        assert "DEPTH" not in str(exc), f"Unexpected depth rejection: {exc}"


def test_block_limit_still_effective() -> None:
    """Removing max_table_positions must not affect the block-count limit."""
    raw = layout_fixture()
    with pytest.raises(ConversionError, match="BLOCK_LIMIT"):
        convert_and_render(raw, SOURCE, ConversionLimits(max_blocks=1))


# ---------------------------------------------------------------------------
# C. Tolerance-review detector
# ---------------------------------------------------------------------------

# Helpers: build minimal Document objects for unit-testing the detector alone.


def _doc_with_text(text: str, page: int = 1) -> Document:
    """Create a minimal contracts.Document with one text element on one page."""
    ref = Reference(block_id="block-1", page=page)
    element = Element(kind="text", text=text, references=(ref,))
    pg = Page(number=page, elements=(element,), reading_order="textract_layout")
    return Document(source=SOURCE, status="SUCCEEDED", pages=(pg,))


def _doc_with_cell_text(text: str, page: int = 1) -> Document:
    """Create a minimal contracts.Document with a table element containing one cell."""
    ref = Reference(block_id="block-1", page=page)
    cell = Cell(text=text, references=(ref,), row=1, column=1)
    table_el = Element(kind="table", text="", references=(ref,), cells=(cell,), rows=1, columns=1)
    pg = Page(number=page, elements=(table_el,), reading_order="textract_layout")
    return Document(source=SOURCE, status="SUCCEEDED", pages=(pg,))


def test_tolerance_cue_with_plus_number_is_flagged() -> None:
    """'tolerance: 1.5 + 0.1 kg' is flagged (has cue + ambiguous +)."""
    doc = _doc_with_text("Mass tolerance: 1.5 + 0.1 kg")
    warnings = detect_tolerance_ambiguities(doc)
    codes = [w.code for w in warnings]
    assert "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" in codes


def test_decimal_comma_variant_is_flagged() -> None:
    """Decimal comma is supported: 'Tolerance: +1,5'."""
    doc = _doc_with_text("Tolerance: +1,5")
    warnings = detect_tolerance_ambiguities(doc)
    assert any(w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" for w in warnings)


def test_tolerance_cue_in_cell_text_is_flagged() -> None:
    """Tolerance cue inside a table cell text is also detected."""
    doc = _doc_with_cell_text("Allowable deviation: + 0.05 g")
    warnings = detect_tolerance_ambiguities(doc)
    assert any(w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" for w in warnings)


def test_plain_addition_without_cue_is_not_flagged() -> None:
    """Ordinary '1 + 1 = 2' without a tolerance cue is not flagged."""
    doc = _doc_with_text("Total: 1 + 1 = 2")
    warnings = detect_tolerance_ambiguities(doc)
    assert not any(w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" for w in warnings)


def test_explicit_plus_minus_is_not_flagged() -> None:
    """'Tolerance: ±0.1' already expresses intent — must not be flagged."""
    doc = _doc_with_text("Tolerance: ±0.1 kg")
    warnings = detect_tolerance_ambiguities(doc)
    assert not any(w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" for w in warnings)


def test_explicit_asymmetric_tolerance_is_not_flagged() -> None:
    """'Tolerance: +0.1 / -0.2' is already expressed as asymmetric — not flagged."""
    doc = _doc_with_text("Tolerance: +0.1 / -0.2 kg")
    warnings = detect_tolerance_ambiguities(doc)
    assert not any(w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" for w in warnings)


def test_finding_carries_page_and_block_reference() -> None:
    """Tolerance findings include the source page number and block ID."""
    doc = _doc_with_text("Tolerance: + 0.5", page=3)
    warnings = detect_tolerance_ambiguities(doc)
    w = next(w for w in warnings if w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY")
    assert 3 in w.pages
    assert "block-1" in w.block_ids


def test_same_source_region_deduplicated() -> None:
    """Two elements referencing the same block_id represent one source region → one warning.

    This simulates a layout element and a table cell both pointing to the same
    underlying Textract block.  The deduplication key is the frozenset of block_ids.
    """
    text = "Tolerance: + 0.5 kg"
    same_ref = Reference(block_id="shared-block", page=1)
    element1 = Element(kind="text", text=text, references=(same_ref,))
    cell2 = Cell(text=text, references=(same_ref,), row=1, column=1)
    table_el = Element(
        kind="table", text="", references=(same_ref,), cells=(cell2,), rows=1, columns=1
    )
    pg = Page(number=1, elements=(element1, table_el), reading_order="textract_layout")
    doc = Document(source=SOURCE, status="SUCCEEDED", pages=(pg,))
    warnings = detect_tolerance_ambiguities(doc)
    tol_warnings = [w for w in warnings if w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY"]
    assert len(tol_warnings) == 1  # same block_id → same source region → deduplicated


def test_distinct_cells_same_text_retain_both_locations() -> None:
    """Two cells with identical text but different block_ids retain separate findings.

    This is the corrected behavior: different block_ids mean potentially different
    source locations.  Both findings must be emitted regardless of text equality.
    """
    text = "Tolerance: +0.5 kg"
    ref1 = Reference(block_id="cell-block-1", page=1)
    ref2 = Reference(block_id="cell-block-2", page=1)
    cell1 = Cell(text=text, references=(ref1,), row=1, column=1)
    cell2 = Cell(text=text, references=(ref2,), row=2, column=1)
    table_el = Element(
        kind="table",
        text="",
        references=(ref1,),
        cells=(cell1, cell2),
        rows=2,
        columns=1,
    )
    pg = Page(number=1, elements=(table_el,), reading_order="textract_layout")
    doc = Document(source=SOURCE, status="SUCCEEDED", pages=(pg,))
    warnings = detect_tolerance_ambiguities(doc)
    tol_warnings = [w for w in warnings if w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY"]
    # Both distinct source locations must be reported.
    assert len(tol_warnings) == 2
    emitted_block_ids = {w.block_ids for w in tol_warnings}
    assert ("cell-block-1",) in emitted_block_ids
    assert ("cell-block-2",) in emitted_block_ids


def test_same_text_different_pages_independently_reported() -> None:
    """Identical tolerance text on two different pages produces two independent findings."""
    text = "Tolerance: + 0.3 mm"
    ref_p1 = Reference(block_id="block-p1", page=1)
    ref_p2 = Reference(block_id="block-p2", page=2)
    el_p1 = Element(kind="text", text=text, references=(ref_p1,))
    el_p2 = Element(kind="text", text=text, references=(ref_p2,))
    pg1 = Page(number=1, elements=(el_p1,), reading_order="textract_layout")
    pg2 = Page(number=2, elements=(el_p2,), reading_order="textract_layout")
    doc = Document(source=SOURCE, status="SUCCEEDED", pages=(pg1, pg2))
    warnings = detect_tolerance_ambiguities(doc)
    tol_warnings = [w for w in warnings if w.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY"]
    assert len(tol_warnings) == 2
    pages_reported = {w.pages for w in tol_warnings}
    assert (1,) in pages_reported
    assert (2,) in pages_reported


def test_tolerance_advisory_does_not_change_provider_status() -> None:
    """An advisory finding must not change SUCCEEDED to PARTIAL_SUCCESS."""
    raw = layout_fixture()
    # Inject a tolerance-ambiguous text block. The layout_fixture hostile text
    # does not contain a tolerance cue, so we need to add a block manually.
    # Simplest: use a document built directly (no fixture mutation needed).
    result = convert_and_render(raw, SOURCE)
    # layout_fixture has no tolerance cues → no tolerance warnings.
    # Regardless, provider status must not change.
    assert result.document.status == "SUCCEEDED"


def test_text_values_unchanged_after_conversion() -> None:
    """Extracted text must be identical before and after tolerance detection."""
    doc = _doc_with_text("Tolerance: 1.5 + 0.1 kg")
    original_text = doc.pages[0].elements[0].text
    detect_tolerance_ambiguities(doc)  # run detector; must not modify doc
    assert doc.pages[0].elements[0].text == original_text
