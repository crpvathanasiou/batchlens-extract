"""Meaningful normalization and inert-HTML regression coverage."""

import re
from copy import deepcopy
from html.parser import HTMLParser
from random import Random
from typing import Any

import pytest

from app.document_conversion import (
    ConversionError,
    Source,
    convert_textract,
    render_document,
    render_pages,
)
from app.document_conversion.contracts import ConversionLimits, Warning
from app.document_conversion.html import page_fragment
from tests.document_conversion.fixtures import block, layout_fixture, table_fixture

SOURCE = Source(identity="synthetic-fixture")


class Capture(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.ids.extend(value for key, value in attrs if key == "id" and value is not None)


def test_numeric_rows_merged_headers_empty_alignment_and_values() -> None:
    doc = convert_textract(table_fixture(), SOURCE)
    table = doc.pages[0].elements[0].children[0]
    assert [c.row for c in table.cells] == [1] + [r for r in range(2, 13) for _ in range(2)]
    assert table.cells[0].column_span == 2 and table.cells[0].header
    assert table.cells[0].text == "11.00 mg 12.00 mg"
    assert next(c for c in table.cells if c.row == 3 and c.column == 2).text == ""
    assert next(c for c in table.cells if c.row == 12 and c.column == 2).text == "122.00 mg"
    html = render_document(doc)
    assert len(re.findall(r"\b11\.00 mg\b", html)) == 1
    assert html.index("21.00 mg") < html.index("101.00 mg")
    assert 'colspan="2"' in html and "<th" in html and "-r12-c2" in html


def test_unrelated_provider_block_order_does_not_change_projection() -> None:
    response = table_fixture()
    original = convert_textract(response, SOURCE)
    blocks: list[dict[str, Any]] = response["Blocks"]
    layouts = [b for b in blocks if b["BlockType"].startswith("LAYOUT_")]
    others = [b for b in blocks if not b["BlockType"].startswith("LAYOUT_")]
    Random(13).shuffle(others)
    response["Blocks"] = others + layouts
    assert convert_textract(response, SOURCE) == original
    assert render_document(convert_textract(response, SOURCE)) == render_document(original)


def test_nested_list_selection_hostile_text_figures_and_page_order() -> None:
    doc = convert_textract(layout_fixture(), SOURCE)
    assert [p.number for p in doc.pages] == [1, 2]
    listing = doc.pages[0].elements[0]
    assert listing.kind == "list" and listing.children[1].kind == "list"
    assert listing.children[0].selections == ("SELECTED",)
    html = render_document(doc)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert html.count("12.50 mg") == 2  # Same text at distinct source locations survives.
    assert html.index('id="page-1"') < html.index('id="page-2"')
    capture = Capture()
    capture.feed(html)
    assert len(capture.ids) == len(set(capture.ids))
    assert any(w.code == "UNINTERPRETED_LAYOUT_FIGURE" for w in doc.warnings)
    assert doc.pages[0].elements[1].references[0].box is not None
    assert render_pages(doc, 2) == render_pages(doc, 1)


def test_partial_line_overlap_preserves_non_table_words() -> None:
    raw = table_fixture()
    raw["Blocks"] += [
        block("LAYOUT_TEXT", "outside", ("mixed",)),
        block("LINE", "mixed", ("w-c-2-1", "outside-word")),
        block("WORD", "outside-word", Text="retain this note"),
    ]
    html = render_document(convert_textract(raw, SOURCE))
    assert len(re.findall(r"\b21\.00 mg\b", html)) == 1
    assert html.count("retain this note") == 1


def test_missing_reference_page_resolution_partial_warnings_and_fallback() -> None:
    raw = {
        "JobStatus": "PARTIAL_SUCCESS",
        "DocumentMetadata": {"Pages": 2},
        "Warnings": [{"ErrorCode": "PAGE_ERROR", "Pages": [2]}],
        "Blocks": [
            block("PAGE", "p1", ("line",)),
            {
                "Id": "line",
                "BlockType": "LINE",
                "Text": "keep",
                "Relationships": [{"Type": "CHILD", "Ids": ["missing"]}],
            },
            {"Id": "orphan", "BlockType": "WORD", "Text": "unknown page"},
        ],
    }
    doc = convert_textract(raw, SOURCE)
    assert doc.pages[0].elements[0].text == "keep"
    codes = {w.code for w in doc.warnings}
    assert {
        "MISSING_REFERENCE",
        "UNRESOLVED_PAGE",
        "AWS_PAGE_ERROR",
        "PARTIAL_ANALYSIS",
        "PAGE_WITHOUT_CONTENT",
        "GEOMETRY_ORDER_NOT_MULTICOLUMN_RELIABLE",
    } <= codes
    assert doc.status == "PARTIAL_SUCCESS"


@pytest.mark.parametrize(
    "raw,code",
    [
        ({"Blocks": []}, "EMPTY_ANALYSIS"),
        ({"JobStatus": "IN_PROGRESS"}, "ANALYSIS_IN_PROGRESS"),
        ({"JobStatus": "FAILED"}, "ANALYSIS_FAILED"),
        ({"Blocks": [block("WORD", "a")], "NextToken": "next"}, "PAGINATION_INCOMPLETE"),
    ],
)
def test_invalid_or_incomplete_input_is_not_success(raw: dict[str, Any], code: str) -> None:
    with pytest.raises(ConversionError, match=code):
        convert_textract(raw, SOURCE)


def test_declared_layout_order_and_deterministic_reconversion() -> None:
    raw = layout_fixture()
    assert (
        convert_textract(raw, SOURCE).model_dump_json()
        == convert_textract(deepcopy(raw), SOURCE).model_dump_json()
    )
    raw["Blocks"] = [
        block("LAYOUT_TEXT", "right", ("r",)),
        block("WORD", "r", Text="first by layout"),
        block("LAYOUT_TEXT", "left", ("l",)),
        block("WORD", "l", Text="second by layout"),
    ]
    assert [e.text for e in convert_textract(raw, SOURCE).pages[0].elements] == [
        "first by layout",
        "second by layout",
    ]


def test_bad_grid_and_resource_limits_fail_without_truncation() -> None:
    raw = table_fixture()
    with pytest.raises(ConversionError, match="BLOCK_LIMIT"):
        convert_textract(raw, SOURCE, ConversionLimits(max_blocks=1))
    with pytest.raises(ConversionError, match="TABLE_POSITION_LIMIT"):
        convert_textract(raw, SOURCE, ConversionLimits(max_table_positions=2))


def test_rowspan_and_parent_page_inference_preserve_cell_sources() -> None:
    raw = table_fixture()
    cells = [b for b in raw["Blocks"] if b["Id"] == "table"][0]
    cells.pop("Page")
    cells["Relationships"][0]["Ids"].append("vertical")
    raw["Blocks"].append(
        block(
            "MERGED_CELL",
            "vertical",
            ("c-3-1", "c-2-1"),
            RowIndex=2,
            ColumnIndex=1,
            RowSpan=2,
            ColumnSpan=1,
        )
    )
    doc = convert_textract(raw, SOURCE)
    table = doc.pages[0].elements[0].children[0]
    merged = next(c for c in table.cells if c.row == 2 and c.column == 1)
    assert merged.row_span == 2 and merged.text == "21.00 mg 31.00 mg"
    assert {"vertical", "c-2-1", "c-3-1"} <= {r.block_id for r in merged.references}
    assert not any(c.row == 3 and c.column == 1 for c in table.cells)
    assert 'rowspan="2"' in render_document(doc)
    assert not any(w.code == "UNRESOLVED_PAGE" and "table" in w.block_ids for w in doc.warnings)


def test_table_title_shared_with_merged_header_is_not_duplicated() -> None:
    raw = table_fixture()
    table = next(b for b in raw["Blocks"] if b["Id"] == "table")
    table["Relationships"].append({"Type": "TABLE_TITLE", "Ids": ["title"]})
    raw["Blocks"].append(block("TABLE_TITLE", "title", ("w-c-1-1",)))
    html = render_document(convert_textract(raw, SOURCE))
    assert len(re.findall(r"\b11\.00 mg\b", html)) == 1


@pytest.mark.parametrize("status", ["SUCCEEDED", "PARTIAL_SUCCESS"])
def test_warning_summary_preserves_codes_references_and_document_content(status: str) -> None:
    doc = convert_textract(table_fixture(), SOURCE).model_copy(
        update={
            "status": status,
            "warnings": (
                Warning(code="UNKNOWN_FUTURE_CODE", pages=(1, 99), block_ids=("table", "cell")),
                Warning(code="UNASSIGNED", block_ids=("orphan",)),
            ),
        }
    )
    html = render_document(doc)
    assert "Conversion warnings" in html
    assert "UNKNOWN_FUTURE_CODE" in html and "Pages: 1, 99" in html
    assert "Block references: table, cell" in html
    assert "UNASSIGNED" in html and "Document-level warning (no page assigned)" in html
    assert "Block references: orphan" in html
    assert f"document conversion status: {status}".lower() in html.lower()
    assert ("Partial result" in html) == (status == "PARTIAL_SUCCESS")
    assert page_fragment(doc.pages[0]) in html


def test_page_warnings_keep_explicit_scope_and_partial_context_in_both_render_modes() -> None:
    doc = convert_textract(layout_fixture(), SOURCE).model_copy(
        update={
            "status": "PARTIAL_SUCCESS",
            "warnings": (
                Warning(code="FIRST_PAGE_ONLY", pages=(1,)),
                Warning(code="SECOND_PAGE_ONLY", pages=(2,)),
                Warning(code="MULTIPLE_PAGES", pages=(1, 2)),
                Warning(code="UNASSIGNED", block_ids=("unplaced",)),
                Warning(code="UNAVAILABLE_PAGE_ONLY", pages=(99,)),
            ),
        }
    )
    pages = render_pages(doc)
    assert render_pages(doc, 2) == pages
    for number, html in pages.items():
        assert "Partial result" in html and "PARTIAL_SUCCESS" in html
        assert "Conversion warnings" in html
        assert "UNASSIGNED" in html and "Document-level warning (no page assigned)" in html
        assert "Block references: unplaced" in html
        assert "MULTIPLE_PAGES" in html and "Pages: 1, 2" in html
        assert "UNAVAILABLE_PAGE_ONLY" not in html
        assert ("FIRST_PAGE_ONLY" in html) == (number == 1)
        assert ("SECOND_PAGE_ONLY" in html) == (number == 2)
        assert "document.html for the full warning summary" in html
        assert page_fragment(doc.pages[number - 1]) in html
    full = render_document(doc)
    assert "UNAVAILABLE_PAGE_ONLY" in full and "Pages: 99" in full


def test_warning_values_are_escaped_in_full_and_page_html() -> None:
    doc = convert_textract(table_fixture(), SOURCE).model_copy(
        update={
            "warnings": (
                Warning(
                    code='<script>alert("code")</script>',
                    pages=(1,),
                    block_ids=('<img src=x onerror="alert(1)">', "a&b"),
                ),
            ),
        }
    )
    for html in [render_document(doc), *render_pages(doc).values()]:
        capture = Capture()
        capture.feed(html)
        assert "script" not in capture.tags and "img" not in capture.tags
        assert "&lt;script&gt;alert(&quot;code&quot;)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;, a&amp;b" in html
        assert "Content-Security-Policy" in html and "default-src 'none'" in html


@pytest.mark.parametrize("status", ["SUCCEEDED", "PARTIAL_SUCCESS"])
def test_no_warning_output_preserves_content_without_quality_claims(status: str) -> None:
    doc = convert_textract(table_fixture(), SOURCE).model_copy(
        update={"status": status, "warnings": ()}
    )
    for html in [render_document(doc), *render_pages(doc).values()]:
        assert "Conversion warnings" not in html
        assert ("Partial result" in html) == (status == "PARTIAL_SUCCESS")
        assert page_fragment(doc.pages[0]) in html
        assert all(word not in html.lower() for word in ("verified", "accurate", "approved"))


def test_page_without_matching_warnings_retains_partial_document_status() -> None:
    doc = convert_textract(layout_fixture(), SOURCE).model_copy(
        update={
            "status": "PARTIAL_SUCCESS",
            "warnings": (Warning(code="SECOND_PAGE_ONLY", pages=(2,)),),
        }
    )
    page = render_pages(doc)[1]
    assert "Partial result" in page and "PARTIAL_SUCCESS" in page
    assert "Conversion warnings" not in page and "SECOND_PAGE_ONLY" not in page
