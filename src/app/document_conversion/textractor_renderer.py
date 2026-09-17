# ruff: noqa: E501
"""Render a saved AWS Textract response via Textractor's parsed object model.

This module is a production-integrated version of the proof-of-concept script
(textractor_to_html.py).  It intentionally uses Textractor's
Document/Page/Layout/Table objects.  It does not call AWS, invoke OCR, or
import the previous custom normaliser.

Changes from the standalone PoC (all integration-necessary):
- Removed CLI entry points (argparse, main, parse_arguments, load_document):
  callers own file I/O and argument parsing.
- load_document() responsibility moved to adapter.parse_textract_response().
- Added render_page_standalone() for individual page-NNNN.html artifacts.
- HTML title changed from "Textractor HTML comparison" to "Converted document"
  so production page artifacts carry a neutral title.
- All rendering logic (CSS, JavaScript, table/cell/layout traversal) is
  unchanged from the PoC.

Accepted PoC limitations (not fixed in this migration):
- Merged-cell reading order and within-cell line boundaries may be imperfect.
- Some table captions/headings appear twice (layout + direct table title).
- OCR symbols and undetected visual tables are not recovered.
- Checkbox-state detection: status_name contains("SELECTED") also matches
  "NOT_SELECTED"; both display as selected (☑). State is recorded correctly
  in the structured document.json via the adapter's separate mapping.
- Caption markup may be duplicated in some documents.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any, cast


def escaped(value: object) -> str:
    """Return source text escaped for use as HTML text or an attribute."""
    return html.escape(str(value), quote=True)


def entity_text(entity: Any) -> str:
    """Read text from a Textractor entity without normalising OCR content."""
    get_text = getattr(entity, "get_text", None)
    if callable(get_text):
        try:
            return str(get_text()).strip()
        except TypeError:
            # Textractor 1.10.0's TableFooter.get_text() can attempt to join
            # Word instances directly.  Its object-model children remain valid.
            pass
    children = getattr(entity, "children", ())
    child_text = [entity_text(child) for child in children]
    if child_text:
        return " ".join(text for text in child_text if text).strip()
    return str(getattr(entity, "text", "")).strip()


def checkbox_text(entity: Any) -> str:
    """Represent a Textract selection element visibly while preserving its state.

    Note (accepted PoC limitation): ``status_name`` contains("SELECTED") also
    matches "NOT_SELECTED", so both states display as selected (☑).  The correct
    state is recorded separately in the structured document.json via the adapter.
    """
    status = getattr(entity, "status", None)
    status_name = getattr(status, "name", str(status)).upper()
    return "☑" if "SELECTED" in status_name else "☐"


def cell_text(cell: Any) -> str:
    """Render cell children in Textractor order, keeping selection elements visible."""
    fragments: list[str] = []
    for child in cell.children:
        if child.__class__.__name__ == "SelectionElement":
            fragments.append(checkbox_text(child))
        else:
            text = entity_text(child)
            if text:
                fragments.append(text)
    return " ".join(fragments) if fragments else entity_text(cell)


def rendered_text(value: str) -> str:
    """Escape text and retain source-backed newlines when Textractor supplies them."""
    return "<br>".join(escaped(line) for line in value.splitlines()) or "&nbsp;"


def merged_anchor(cell: Any) -> tuple[int, int, int, int, tuple[str, ...]]:
    """Return the logical anchor/range for a normal or Textractor merged cell."""
    siblings = tuple(cell.siblings)
    if not siblings:
        return (
            cell.row_index,
            cell.col_index,
            cell.row_span,
            cell.col_span,
            (cell.id,),
        )
    rows = [sibling.row_index for sibling in siblings]
    columns = [sibling.col_index for sibling in siblings]
    return (
        min(rows),
        min(columns),
        max(rows) - min(rows) + 1,
        max(columns) - min(columns) + 1,
        tuple(sibling.id for sibling in siblings),
    )


def merged_cell_text(cell: Any) -> str:
    """Join a merged cell's constituent cells in physical row/column order."""
    siblings = tuple(cell.siblings)
    if not siblings:
        return cell_text(cell)
    return " ".join(
        text
        for sibling in sorted(siblings, key=lambda item: (item.row_index, item.col_index))
        if (text := cell_text(sibling))
    )


def render_table(table: Any) -> str:
    """Create semantic HTML from a Textractor Table, including merged-cell spans."""
    cells_by_position = {(cell.row_index, cell.col_index): cell for cell in table.table_cells}
    emitted_anchors: set[tuple[int, int]] = set()
    rows: list[str] = []

    for row_number in range(1, table.row_count + 1):
        cells: list[str] = []
        for column_number in range(1, table.column_count + 1):
            cell = cells_by_position.get((row_number, column_number))
            if cell is None:
                continue
            anchor_row, anchor_column, row_span, column_span, source_ids = merged_anchor(cell)
            anchor = (anchor_row, anchor_column)
            if anchor != (row_number, column_number) or anchor in emitted_anchors:
                continue
            emitted_anchors.add(anchor)
            tag = "th" if cell.is_column_header else "td"
            scope = ' scope="col"' if tag == "th" and row_span == 1 else ""
            row_span_attribute = f' rowspan="{row_span}"' if row_span > 1 else ""
            column_span_attribute = f' colspan="{column_span}"' if column_span > 1 else ""
            cells.append(
                f'<{tag} data-source-id="{escaped(" ".join(source_ids))}"{scope}'
                f"{row_span_attribute}{column_span_attribute}>"
                f"{rendered_text(merged_cell_text(cell))}</{tag}>"
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    title = entity_text(table.title) if table.title is not None else ""
    raw_footers: Any = getattr(table, "footers", [])
    footer_objects = cast(
        list[Any], raw_footers if isinstance(raw_footers, list) else [raw_footers]
    )
    footers: list[str] = [entity_text(f) for f in footer_objects if entity_text(f)]
    caption = f"<caption>{rendered_text(title)}</caption>" if title else ""
    footer_html = "".join(
        f'<div class="table-footer">{rendered_text(footer)}</div>' for footer in footers
    )
    return (
        f'<figure class="table-wrap" data-source-id="{escaped(table.id)}">{caption}'
        f'<table data-source-id="{escaped(table.id)}"><tbody>{"".join(rows)}</tbody></table>'
        f"{footer_html}</figure>"
    )


def layout_tag(layout: Any) -> str:
    """Map only Textract-recognised layout labels to semantic HTML tags."""
    mapping = {
        "LAYOUT_TITLE": "h1",
        "LAYOUT_SECTION_HEADER": "h2",
        "LAYOUT_HEADER": "header",
        "LAYOUT_FOOTER": "footer",
        "LAYOUT_PAGE_NUMBER": "p",
        "LAYOUT_LIST": "p",
    }
    return mapping.get(layout.layout_type, "p")


def layout_line_ids(layout: Any) -> set[str]:
    """Collect descendant line ids already represented by a layout object."""
    found: set[str] = set()
    for child in layout.children:
        if child.__class__.__name__ == "Line":
            found.add(str(child.id))
        if child.__class__.__name__ == "Layout":
            found.update(layout_line_ids(child))
    return found


def table_ids_from_layout(layout: Any) -> set[str]:
    """Return Table ids contained by a LAYOUT_TABLE object."""
    from textractor.entities.table import Table  # type: ignore[import-untyped]  # noqa: PLC0415

    return {str(child.id) for child in layout.children if isinstance(child, Table)}


def page_html(page: Any) -> str:
    """Render one physical Textract page, retaining all parsed tables exactly once."""
    layouts = sorted(page.layouts, key=lambda item: item.reading_order)
    rendered_table_ids: set[str] = set()
    represented_line_ids: set[str] = set()
    blocks: list[str] = []

    for layout in layouts:
        if layout.layout_type == "LAYOUT_TABLE":
            table_ids = table_ids_from_layout(layout)
            for table_id in table_ids:
                table = next(
                    (candidate for candidate in page.tables if candidate.id == table_id),
                    None,
                )
                if table is not None and table.id not in rendered_table_ids:
                    blocks.append(render_table(table))
                    rendered_table_ids.add(table.id)
            if not table_ids:
                represented_line_ids.update(layout_line_ids(layout))
                text = entity_text(layout)
                if text:
                    blocks.append(
                        f'<p class="geometry-fallback" data-source-id="{escaped(layout.id)}" '
                        f'data-layout-type="LAYOUT_TABLE">{rendered_text(text)}</p>'
                    )
            continue
        if layout.layout_type == "LAYOUT_FIGURE":
            continue
        text = entity_text(layout)
        represented_line_ids.update(layout_line_ids(layout))
        if text:
            tag = layout_tag(layout)
            blocks.append(
                f'<{tag} data-source-id="{escaped(layout.id)}" '
                f'data-layout-type="{escaped(layout.layout_type)}">{rendered_text(text)}</{tag}>'
            )

    # Some TABLE blocks have no LAYOUT_TABLE parent.  Place these after the
    # layout stream in top/left geometry order rather than dropping them.
    for table in sorted(page.tables, key=lambda item: (item.bbox.y, item.bbox.x)):
        if table.id not in rendered_table_ids:
            blocks.append(render_table(table))
            rendered_table_ids.add(table.id)

    # Preserve page lines not owned by a layout or a table.  This is an explicit
    # geometry fallback, not a reconstructed reading order.
    table_word_ids = {
        str(word.id) for table in page.tables for cell in table.table_cells for word in cell.words
    }
    fallback_lines = [
        line
        for line in page.lines
        if line.id not in represented_line_ids
        and not {str(word.id) for word in line.words}.issubset(table_word_ids)
    ]
    for line in sorted(fallback_lines, key=lambda item: (item.bbox.y, item.bbox.x)):
        text = entity_text(line)
        if text:
            blocks.append(
                f'<p class="geometry-fallback" data-source-id="{escaped(line.id)}">'
                f"{rendered_text(text)}</p>"
            )

    if not blocks:
        blocks.append(
            '<p class="empty-page">No text, table, or selection blocks were returned for this page.</p>'  # noqa: E501
        )
    return "\n".join(blocks)


def raw_table_count(response: dict[str, Any]) -> int:
    """Audit the saved response only; rendering itself uses Textractor objects."""
    blocks: list[Any] = response.get("Blocks", [])
    total: int = 0
    for b in blocks:
        if isinstance(b, dict) and b.get("BlockType") == "TABLE":  # type: ignore[reportUnknownMemberType]
            total += 1
    return total


def unrepresented_layout_table_count(document: Any) -> int:
    """Count layout-table regions that have no Textractor Table object to render."""
    return sum(
        layout.layout_type == "LAYOUT_TABLE" and not table_ids_from_layout(layout)
        for page in document.pages
        for layout in page.layouts
    )


# ---------------------------------------------------------------------------
# Shared CSS – used by both document_html() and render_page_standalone().
# ---------------------------------------------------------------------------
_SHARED_CSS = """\
:root { color-scheme: light; font-family: Arial, sans-serif; }
body { margin: 0; background: #eef1f4; color: #17212b; }
#controls { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; gap: .65rem; align-items: center; padding: .75rem 1rem; background: #17212b; color: white; }
button, select { font: inherit; padding: .35rem .55rem; }
#pages { max-width: 1100px; margin: 1rem auto; }
.source-page { display: none; box-sizing: border-box; min-height: 90vh; padding: 2rem; background: white; box-shadow: 0 2px 8px #0002; }
.source-page.active, #pages.show-all .source-page { display: block; margin-bottom: 1rem; }
.generated-page-label { margin: -1rem -1rem 1.25rem; padding: .5rem 1rem; background: #e7eef8; font-weight: 700; color: #1e4c82; }
header, footer { display: block; font-size: .88rem; color: #44515d; }
h1 { font-size: 1.45rem; } h2 { font-size: 1.15rem; } p { line-height: 1.42; }
.table-wrap { display: block; max-width: 100%; overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; width: max-content; min-width: 100%; }
td, th { border: 1px solid #63717f; padding: .35rem .5rem; vertical-align: top; text-align: left; white-space: pre-wrap; }
th { background: #e7eef8; } caption { caption-side: top; text-align: left; font-weight: 700; padding: .3rem 0; }
.table-footer { margin-top: .3rem; font-size: .9rem; }
.geometry-fallback { border-left: 3px solid #c9d4e0; padding-left: .55rem; }
.empty-page { color: #59636d; font-style: italic; }
details { max-width: 1100px; margin: .75rem auto; padding: 0 .75rem; }
.page-note { max-width: 1100px; margin: .5rem auto; padding: .5rem .75rem; background: #fff; border-left: 4px solid #1e4c82; font-size: .9rem; }
.partial-banner { max-width: 1100px; margin: .5rem auto; padding: .5rem .75rem; background: #fff8e6; border-left: 4px solid #996000; font-size: .9rem; }
.warn-list { max-width: 1100px; margin: .5rem auto; padding: .5rem .75rem; background: #fff8e6; border-left: 4px solid #996000; }
.warn-list h2 { margin-top: 0; font-size: 1rem; }
@media print { body { background: white; } #controls, details { display: none !important; } #pages { max-width: none; margin: 0; } .source-page, #pages.show-all .source-page { display: block !important; min-height: 0; box-shadow: none; break-after: page; page-break-after: always; } .source-page:last-child { break-after: auto; page-break-after: auto; } }\
"""


def _warning_item_html(code: str, pages: Sequence[int]) -> str:
    """Render one warning as an HTML list item; all dynamic values are escaped."""
    page_str = f" — pages: {escaped(', '.join(str(p) for p in sorted(pages)))}" if pages else ""
    if code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY":
        note = (
            " — Possible tolerance-symbol ambiguity. "
            "Check this value against the source PDF; the extracted text has not been changed."
        )
    else:
        note = ""
    return f"<li><code>{escaped(code)}</code>{page_str}{note}</li>"


def document_html(
    document: Any,
    raw_tables: int,
    status: str = "SUCCEEDED",
    warnings: Sequence[tuple[str, Sequence[int]]] = (),
) -> str:
    """Create one self-contained navigable HTML document.

    Args:
        document: Textractor Document object.
        raw_tables: raw TABLE block count from the saved response.
        status: document status string ("SUCCEEDED" or "PARTIAL_SUCCESS").
        warnings: sequence of (code, page_numbers) pairs for the Conversion
            notes section; all dynamic content is HTML-escaped.
    """
    pages = "\n".join(
        f'<section class="source-page" data-page="{number}" id="source-page-{number}">'
        f'<div class="generated-page-label">Generated source page {number} of {len(document.pages)}</div>'
        f"{page_html(page)}</section>"
        for number, page in enumerate(document.pages, start=1)
    )
    object_tables = sum(len(page.tables) for page in document.pages)
    layout_only_tables = unrepresented_layout_table_count(document)

    partial_banner = ""
    if status == "PARTIAL_SUCCESS":
        partial_banner = (
            '<div class="partial-banner" role="alert">'
            "<strong>Partial result.</strong> "
            "AWS Textract returned PARTIAL_SUCCESS — some pages may be missing or incomplete. "
            "See Conversion notes below for details."
            "</div>"
        )

    warnings_html = ""
    if warnings:
        items = "".join(_warning_item_html(code, pages) for code, pages in warnings)
        warnings_html = f"<p><strong>Warnings ({len(warnings)}):</strong></p><ul>{items}</ul>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Converted document</title>
<style>
{_SHARED_CSS}
</style>
</head>
<body>
<nav id="controls" aria-label="Source page navigation">
  <button id="previous" type="button">Previous</button>
  <button id="next" type="button">Next</button>
  <label>Page <select id="page-select">{"".join(f'<option value="{page}">{page}</option>' for page in range(1, len(document.pages) + 1))}</select></label>
  <span id="page-status" aria-live="polite"></span>
  <label><input id="show-all" type="checkbox"> Show all pages</label>
</nav>
{partial_banner}
<details><summary>Conversion notes</summary><p>Rendered from Textractor Document/Page/Layout/Table objects. The saved response contains {raw_tables} raw TABLE blocks and Textractor exposes {object_tables} page table objects. {layout_only_tables} LAYOUT_TABLE region(s) have no Textractor Table object, so their text is retained as a geometry-fallback paragraph rather than an HTML table. Tables not attached to a LAYOUT_TABLE are retained through a top/left geometry fallback. Lines not covered by a layout or table are also retained through that fallback. Figures have no semantic representation in this minimal HTML.</p>{warnings_html}</details>
<main id="pages">{pages}</main>
<script>
(() => {{
  const pages = [...document.querySelectorAll('.source-page')];
  const select = document.querySelector('#page-select');
  const status = document.querySelector('#page-status');
  const showAll = document.querySelector('#show-all');
  const container = document.querySelector('#pages');
  let current = 1;
  function render() {{
    const all = showAll.checked;
    container.classList.toggle('show-all', all);
    pages.forEach((page, index) => page.classList.toggle('active', index + 1 === current));
    select.value = String(current);
    status.textContent = `Page ${{current}} of ${{pages.length}}`;
    document.querySelector('#previous').disabled = current === 1;
    document.querySelector('#next').disabled = current === pages.length;
  }}
  document.querySelector('#previous').addEventListener('click', () => {{ current = Math.max(1, current - 1); render(); }});
  document.querySelector('#next').addEventListener('click', () => {{ current = Math.min(pages.length, current + 1); render(); }});
  select.addEventListener('change', () => {{ current = Number(select.value); render(); }});
  showAll.addEventListener('change', render);
  render();
}})();
</script>
</body>
</html>"""


def render_page_standalone(
    page: Any,
    page_number: int,
    total_pages: int,
    document_status: str,
    warning_codes: list[str],
) -> str:
    """Render a single page as a standalone HTML document for page-NNNN.html artifacts.

    Uses the same CSS and page_html() rendering as document_html(), but without
    the multi-page navigation controls.  Includes relevant warning codes for
    the page and document-level status context.
    """
    content = page_html(page)
    status_note = ""
    if document_status == "PARTIAL_SUCCESS":
        status_note = (
            '<div class="partial-banner">'
            "<strong>Partial result — document conversion status: PARTIAL_SUCCESS</strong>"
            "</div>"
        )
    warn_html = ""
    if warning_codes:
        items = "".join(f"<li><code>{escaped(code)}</code></li>" for code in warning_codes)
        warn_html = f'<div class="warn-list"><h2>Conversion notes</h2><ul>{items}</ul></div>'
    page_note = (
        f'<div class="page-note">Page {page_number} of {total_pages} — '
        "see document.html for navigation between pages.</div>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page {page_number} of {total_pages}</title>
<style>
{_SHARED_CSS}
</style>
</head>
<body>
{page_note}
{status_note}
{warn_html}
<div style="max-width:1100px;margin:1rem auto;padding:2rem;background:white;box-shadow:0 2px 8px #0002">
{content}
</div>
</body>
</html>"""
