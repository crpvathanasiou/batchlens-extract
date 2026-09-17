"""Synthetic Textract-compatible boundary dictionaries; contains no customer data.

All fixtures conform to the field requirements of Textractor 1.10.0's parser:
- PAGE blocks: must have Geometry (BoundingBox + Polygon) and must list all
  LAYOUT_*, LINE, and TABLE blocks on that page as direct CHILD relationships.
  WORD, CELL, MERGED_CELL, and SELECTION_ELEMENT are NOT direct PAGE children.
- LAYOUT_* blocks: require Confidence and Geometry.
- LINE blocks: require Confidence, Geometry, and Text.
- WORD blocks: require Confidence, Geometry, Text, and TextType ("PRINTED").
- TABLE/CELL: require Confidence, Geometry, and positional attributes.

These fixtures replace the previous low-level block dictionaries used with the
retired custom normaliser.  They produce equivalent structural scenarios through
Textractor's parsed object model.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_PAGE_GEO: dict[str, Any] = {
    "BoundingBox": {"Left": 0.0, "Top": 0.0, "Width": 1.0, "Height": 1.0},
    "Polygon": [
        {"X": 0.0, "Y": 0.0},
        {"X": 1.0, "Y": 0.0},
        {"X": 1.0, "Y": 1.0},
        {"X": 0.0, "Y": 1.0},
    ],
}


def _geo(y: float = 0.1, height: float = 0.05, left: float = 0.05) -> dict[str, Any]:
    """Return a minimal BoundingBox + Polygon geometry dict for a block."""
    right = left + 0.9
    bottom = y + height
    return {
        "BoundingBox": {"Left": left, "Top": y, "Width": 0.9, "Height": height},
        "Polygon": [
            {"X": left, "Y": y},
            {"X": right, "Y": y},
            {"X": right, "Y": bottom},
            {"X": left, "Y": bottom},
        ],
    }


def _word(ident: str, text: str, page: int = 1, y: float = 0.1) -> dict[str, Any]:
    """Create a WORD block with required Textractor fields."""
    return {
        "Id": ident,
        "BlockType": "WORD",
        "Text": text,
        "TextType": "PRINTED",
        "Confidence": 99.0,
        "Page": page,
        "Geometry": _geo(y),
        "Relationships": [],
    }


def _line(
    ident: str,
    text: str,
    word_ids: tuple[str, ...],
    page: int = 1,
    y: float = 0.1,
) -> dict[str, Any]:
    """Create a LINE block with required Textractor fields."""
    result: dict[str, Any] = {
        "Id": ident,
        "BlockType": "LINE",
        "Text": text,
        "Confidence": 99.0,
        "Page": page,
        "Geometry": _geo(y),
    }
    if word_ids:
        result["Relationships"] = [{"Type": "CHILD", "Ids": list(word_ids)}]
    else:
        result["Relationships"] = []
    return result


def _layout(
    kind: str,
    ident: str,
    child_ids: tuple[str, ...] = (),
    page: int = 1,
    y: float = 0.1,
) -> dict[str, Any]:
    """Create a LAYOUT_* block with required Textractor fields."""
    result: dict[str, Any] = {
        "Id": ident,
        "BlockType": kind,
        "Confidence": 99.0,
        "Page": page,
        "Geometry": _geo(y),
    }
    if child_ids:
        result["Relationships"] = [{"Type": "CHILD", "Ids": list(child_ids)}]
    else:
        result["Relationships"] = []
    return result


def _page_block(
    ident: str,
    child_ids: tuple[str, ...],
    page: int = 1,
) -> dict[str, Any]:
    """Create a PAGE block listing all LAYOUT_*, LINE, and TABLE children."""
    return {
        "Id": ident,
        "BlockType": "PAGE",
        "Page": page,
        "Geometry": _PAGE_GEO,
        "Relationships": [{"Type": "CHILD", "Ids": list(child_ids)}],
    }


# ---------------------------------------------------------------------------
# layout_fixture – 2-page document with lists and a figure
# ---------------------------------------------------------------------------


def layout_fixture() -> dict[str, Any]:
    """Two-page Textractor-compatible fixture.

    Page 1: LAYOUT_LIST containing text, nested LAYOUT_LIST, LAYOUT_FIGURE.
    Page 2: LAYOUT_TEXT with plain text.

    The LAYOUT_FIGURE generates an UNINTERPRETED_LAYOUT_FIGURE warning.
    The hostile text exercises HTML escaping.
    """
    hostile = "<script>alert('x')</script> & 12.50 mg"
    blocks: list[dict[str, Any]] = [
        # PAGE blocks — list ALL layout and line blocks on each page.
        _page_block("p1", ("list", "nested", "item", "item2", "fig", "line"), page=1),
        _page_block("p2", ("t2", "l2"), page=2),
        # Page 1 layouts
        _layout("LAYOUT_LIST", "list", ("item", "nested"), page=1, y=0.10),
        _layout("LAYOUT_TEXT", "item", ("line",), page=1, y=0.15),
        _layout("LAYOUT_LIST", "nested", ("item2",), page=1, y=0.25),
        _layout("LAYOUT_TEXT", "item2", ("w3",), page=1, y=0.25),
        _layout("LAYOUT_FIGURE", "fig", (), page=1, y=0.40),
        # Page 1 line + words
        _line("line", hostile, ("word",), page=1, y=0.15),
        _word("word", hostile, page=1, y=0.15),
        _word("w3", hostile, page=1, y=0.25),
        # Page 2 layout + line + word
        _layout("LAYOUT_TEXT", "t2", ("l2",), page=2, y=0.10),
        _line("l2", "Page two", ("w2",), page=2, y=0.10),
        _word("w2", "Page two", page=2, y=0.10),
    ]
    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 2},
        "Blocks": blocks,
    }


# ---------------------------------------------------------------------------
# table_fixture – 1-page document with a 2-column table + LAYOUT_TABLE
# ---------------------------------------------------------------------------


def block(
    block_type: str,
    ident: str,
    child_ids: tuple[str, ...] = (),
    *,
    Text: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """Create a minimal Textractor-compatible Textract block for stubbed AWS responses.

    Used by test_aws.py to build stub response payloads without depending on
    the higher-level layout/table fixture factories.
    """
    b: dict[str, Any] = {
        "BlockType": block_type,
        "Id": ident,
        "Page": page,
        "Geometry": _geo(),
        "Confidence": 99.0,
        "Relationships": [],
    }
    if child_ids:
        b["Relationships"] = [{"Type": "CHILD", "Ids": list(child_ids)}]
    if Text:
        b["Text"] = Text
    if block_type == "WORD":
        b["TextType"] = "PRINTED"
    if block_type == "PAGE":
        b["Geometry"] = _PAGE_GEO
        del b["Confidence"]
    return b


def table_fixture() -> dict[str, Any]:
    """One-page Textractor-compatible fixture with a 12-row × 2-column table.

    Row 1 is a merged header spanning both columns.  Row 3, column 2 is empty.
    The fixture is wrapped in a LAYOUT_TABLE so the table is rendered via the
    layout stream rather than the geometry fallback.
    """
    blocks: list[dict[str, Any]] = []
    cell_ids: list[str] = []
    word_blocks: list[dict[str, Any]] = []

    for row in range(1, 13):
        for col in range(1, 3):
            ident = f"c-{row}-{col}"
            cell_ids.append(ident)
            text = f"{row * 10 + col}.00 mg"
            word_id = f"w-{ident}"
            word_blocks.append(_word(word_id, text, page=1, y=0.05 + row * 0.05))
            is_empty = row == 3 and col == 2
            cell: dict[str, Any] = {
                "Id": ident,
                "BlockType": "CELL",
                "RowIndex": row,
                "ColumnIndex": col,
                "RowSpan": 1,
                "ColumnSpan": 1,
                "Confidence": 99.0,
                "Page": 1,
                "Geometry": _geo(y=0.05 + row * 0.05),
                "Relationships": ([] if is_empty else [{"Type": "CHILD", "Ids": [word_id]}]),
            }
            if row == 1:
                cell["EntityTypes"] = ["COLUMN_HEADER"]
            else:
                cell["EntityTypes"] = []
            blocks.append(cell)

    # Merged header cell: spans row 1, both columns.
    merged: dict[str, Any] = {
        "Id": "merged",
        "BlockType": "MERGED_CELL",
        "RowIndex": 1,
        "ColumnIndex": 1,
        "RowSpan": 1,
        "ColumnSpan": 2,
        "Confidence": 99.0,
        "Page": 1,
        "Geometry": _geo(y=0.05),
        "Relationships": [{"Type": "CHILD", "Ids": ["c-1-1", "c-1-2"]}],
        "EntityTypes": ["COLUMN_HEADER"],
    }
    blocks.append(merged)

    table: dict[str, Any] = {
        "Id": "table",
        "BlockType": "TABLE",
        "Confidence": 99.0,
        "EntityTypes": [],
        "Page": 1,
        "Geometry": _geo(y=0.05, height=0.65),
        "Relationships": [
            {"Type": "MERGED_CELL", "Ids": ["merged"]},
            {"Type": "CHILD", "Ids": cell_ids},
        ],
    }
    blocks.append(table)
    blocks.extend(word_blocks)

    # PAGE: lists TABLE and LAYOUT_TABLE as direct children.
    # (Cells and words are not direct PAGE children in real Textract.)
    layout_block = _layout("LAYOUT_TABLE", "layout", ("table",), page=1, y=0.04)
    blocks.append(layout_block)

    page_block = _page_block("page", ("layout", "table"), page=1)
    blocks.append(page_block)

    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 1},
        "Blocks": blocks,
    }
