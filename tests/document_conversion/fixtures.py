"""Synthetic provider-boundary dictionaries; contains no customer data."""

from typing import Any


def block(kind: str, ident: str, children: tuple[str, ...] = (), **fields: Any) -> dict[str, Any]:
    return {
        "Id": ident,
        "BlockType": kind,
        "Page": 1,
        "Relationships": [{"Type": "CHILD", "Ids": list(children)}] if children else [],
        **fields,
    }


def table_fixture() -> dict[str, Any]:
    blocks = [
        block("PAGE", "page", ("table", "layout")),
        block("LAYOUT_TABLE", "layout", ("table",)),
    ]
    cells: list[str] = []
    for row in range(1, 13):
        for col in range(1, 3):
            ident = f"c-{row}-{col}"
            cells.append(ident)
            text = f"{row * 10 + col}.00 mg"
            words = () if (row, col) == (3, 2) else ("w-" + ident,)
            blocks.append(
                block(
                    "CELL",
                    ident,
                    words,
                    RowIndex=row,
                    ColumnIndex=col,
                    EntityTypes=["COLUMN_HEADER"] if row == 1 else [],
                )
            )
            if words:
                blocks.append(block("WORD", words[0], Text=text))
    merged = block(
        "MERGED_CELL",
        "merged",
        ("c-1-1", "c-1-2"),
        RowIndex=1,
        ColumnIndex=1,
        RowSpan=1,
        ColumnSpan=2,
    )
    table = block("TABLE", "table", tuple(cells))
    table["Relationships"].insert(0, {"Type": "MERGED_CELL", "Ids": ["merged"]})
    blocks += [merged, table]
    return {"JobStatus": "SUCCEEDED", "DocumentMetadata": {"Pages": 1}, "Blocks": blocks}


def layout_fixture() -> dict[str, Any]:
    return {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 2},
        "Blocks": [
            block("PAGE", "p2", ("t2",), Page=2),
            block("LAYOUT_TEXT", "t2", ("l2",), Page=2),
            block("LINE", "l2", ("w2",), Page=2, Text="Page two"),
            block("WORD", "w2", Text="Page two", Page=2),
            block("PAGE", "p1", ("list", "fig")),
            block("LAYOUT_LIST", "list", ("item", "nested")),
            block("LAYOUT_TEXT", "item", ("line",)),
            block("LINE", "line", ("word", "check"), Text="<script>alert('x')</script> & 12.50 mg"),
            block("WORD", "word", Text="<script>alert('x')</script> & 12.50 mg"),
            block("SELECTION_ELEMENT", "check", SelectionStatus="SELECTED"),
            block("LAYOUT_LIST", "nested", ("item2",)),
            block("LAYOUT_TEXT", "item2", ("w3",)),
            block("WORD", "w3", Text="<script>alert('x')</script> & 12.50 mg"),
            block(
                "LAYOUT_FIGURE",
                "fig",
                Geometry={"BoundingBox": {"Left": 0.1, "Top": 0.4, "Width": 0.2, "Height": 0.3}},
            ),
        ],
    }
