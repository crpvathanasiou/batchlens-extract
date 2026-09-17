"""Thin integration adapter: Textractor object model → application contracts.

This module bridges the Textractor library (amazon-textract-textractor==1.10.0)
and the existing application infrastructure.  It owns:

* Response validation (delegating to provider.parse_analysis for status,
  pagination and block-count limits – those guards remain unchanged).
* Parsing via Textractor's parse() into its Document/Page/Layout/Table objects.
* Mapping from Textractor objects to the contracts.Document structured contract
  for document.json serialisation, in the same traversal order as the HTML
  renderer so that both outputs are consistent.
* Rendering delegation to textractor_renderer for full-document and per-page
  HTML artifacts.

Public API used by service.py and __main__.py:
    convert_and_render(response, source, limits) -> ConversionResult
    render_full_document_html(result) -> str
    render_individual_pages(result) -> dict[int, str]

Accepted PoC limitations (not fixed here; noted for completeness):
- Merged-cell reading order and within-cell line boundaries may be imperfect.
- Some table captions/headings appear twice in the structured output.
- LAYOUT_FIGURE blocks are silently skipped in HTML; the adapter generates
  UNINTERPRETED_LAYOUT_FIGURE warnings for consumers that track these.
- Checkbox-state HTML uses the PoC's checkbox_text() which renders NOT_SELECTED
  as ☑; the structured document.json records the correct state separately.
- OCR symbols and undetected visual tables are not recovered.

No parallel processing: render_individual_pages() is always single-threaded.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any, Literal

from textractor.parsers.response_parser import (  # type: ignore[import-untyped]
    parse as textractor_parse,  # pyright: ignore[reportUnknownVariableType]
)

from app.document_conversion.contracts import (
    Box,
    Cell,
    Content,
    ConversionError,
    ConversionLimits,
    Document,
    Element,
    Page,
    Point,
    Reference,
    Source,
    Warning,
)
from app.document_conversion.provider import Analysis, Block, parse_analysis
from app.document_conversion.textractor_renderer import (
    document_html,
    entity_text,
    layout_line_ids,
    merged_anchor,
    merged_cell_text,
    raw_table_count,
    render_page_standalone,
    table_ids_from_layout,
)
from app.document_conversion.tolerance import detect_tolerance_ambiguities

# ---------------------------------------------------------------------------
# Structured result container
# ---------------------------------------------------------------------------


class ConversionResult:
    """Holds the parsed outputs from a single Textract response.

    ``document`` is the structured contracts.Document suitable for
    document.json serialisation.  ``textractor_doc`` is the Textractor
    Document object used by the rendering functions; callers should access
    it only via render_full_document_html() and render_individual_pages().
    """

    def __init__(
        self,
        document: Document,
        textractor_doc: Any,  # textractor.entities.document.Document – untyped library
        raw_tables: int,
    ) -> None:
        self.document = document
        self.textractor_doc: Any = textractor_doc  # untyped library object; rendering use only
        self.raw_tables = raw_tables


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_box(entity: Any) -> Box | None:
    """Extract a contracts.Box from a Textractor entity's bbox, or None."""
    bbox = getattr(entity, "bbox", None)
    if bbox is None:
        return None
    try:
        return Box(
            left=float(bbox.x),
            top=float(bbox.y),
            width=float(bbox.width),
            height=float(bbox.height),
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _safe_poly(entity: Any) -> tuple[Point, ...]:
    """Extract polygon points from a Textractor entity, or empty tuple."""
    polygon = getattr(entity, "polygon", None)
    if not polygon:
        return ()
    try:
        return tuple(Point(x=float(p.x), y=float(p.y)) for p in polygon)
    except (AttributeError, TypeError, ValueError):
        return ()


def _make_ref(entity: Any, page_number: int) -> Reference:
    """Create a contracts.Reference from a Textractor entity."""
    return Reference(
        block_id=str(entity.id),
        page=page_number,
        confidence=getattr(entity, "confidence", None),
        box=_safe_box(entity),
        polygon=_safe_poly(entity),
    )


_LAYOUT_KIND: dict[str, str] = {
    "LAYOUT_TITLE": "title",
    "LAYOUT_SECTION_HEADER": "section_heading",
    "LAYOUT_HEADER": "header",
    "LAYOUT_FOOTER": "footer",
    "LAYOUT_PAGE_NUMBER": "page_number",
}


def _cell_selection_state(
    entity: Any,
) -> Literal["SELECTED", "NOT_SELECTED"] | None:
    """Return the correct selection state from a Textractor SelectionElement."""
    status = getattr(entity, "status", None)
    if status is None:
        return None
    name = getattr(status, "name", str(status)).upper()
    if name == "SELECTED":
        return "SELECTED"
    if name == "NOT_SELECTED":
        return "NOT_SELECTED"
    return None


def _map_cell(cell_entity: Any, page_number: int) -> Cell:
    """Map one logical cell (possibly merged) to a contracts.Cell."""
    anchor_row, anchor_col, row_span, col_span, source_ids = merged_anchor(cell_entity)
    text = merged_cell_text(cell_entity)

    # Collect selection states from all sibling cells' children.
    siblings = tuple(cell_entity.siblings)
    target_cells = siblings if siblings else (cell_entity,)
    selections: list[Literal["SELECTED", "NOT_SELECTED"]] = []
    for sibling_cell in target_cells:
        for child in sibling_cell.children:
            if child.__class__.__name__ == "SelectionElement":
                state = _cell_selection_state(child)
                if state is not None:
                    selections.append(state)

    refs: tuple[Reference, ...] = tuple(
        Reference(block_id=sid, page=page_number) for sid in source_ids
    )
    return Cell(
        text=text,
        references=refs,
        selections=tuple(selections),
        row=anchor_row,
        column=anchor_col,
        row_span=row_span,
        column_span=col_span,
        header=bool(getattr(cell_entity, "is_column_header", False)),
    )


def _map_table(table_entity: Any, page_number: int) -> Element:
    """Map a Textractor Table object to a contracts.Element(kind='table')."""
    cells_by_position = {(c.row_index, c.col_index): c for c in table_entity.table_cells}
    emitted_anchors: set[tuple[int, int]] = set()
    cells: list[Cell] = []

    for row_number in range(1, table_entity.row_count + 1):
        for col_number in range(1, table_entity.column_count + 1):
            cell_entity = cells_by_position.get((row_number, col_number))
            if cell_entity is None:
                continue
            anchor_row, anchor_col, _rs, _cs, _ids = merged_anchor(cell_entity)
            anchor = (anchor_row, anchor_col)
            if anchor != (row_number, col_number) or anchor in emitted_anchors:
                continue
            emitted_anchors.add(anchor)
            cells.append(_map_cell(cell_entity, page_number))

    # Title and footers
    titles: tuple[Content, ...] = ()
    title_obj = getattr(table_entity, "title", None)
    if title_obj is not None:
        title_text = entity_text(title_obj)
        if title_text:
            titles = (
                Content(
                    text=title_text,
                    references=(Reference(block_id=str(table_entity.id), page=page_number),),
                ),
            )

    footers_raw = getattr(table_entity, "footers", [])
    footer_objects: list[Any] = footers_raw if isinstance(footers_raw, list) else [footers_raw]  # type: ignore[reportUnknownVariableType]
    footers: tuple[Content, ...] = tuple(
        Content(
            text=entity_text(f),
            references=(Reference(block_id=str(table_entity.id), page=page_number),),
        )
        for f in footer_objects
        if entity_text(f)
    )

    ref = _make_ref(table_entity, page_number)
    return Element(
        kind="table",
        references=(ref,),
        cells=tuple(cells),
        rows=table_entity.row_count,
        columns=table_entity.column_count,
        titles=titles,
        footers=footers,
    )


def _map_page(
    textractor_page: Any,
    page_number: int,
    figure_block_ids: list[str],
) -> tuple[Page, list[str]]:
    """Map one Textractor Page to contracts.Page using the same traversal as page_html().

    Returns (page, new_figure_ids) where new_figure_ids are figure block IDs
    found on this page (for warning generation).
    """
    layouts: list[Any] = sorted(textractor_page.layouts, key=lambda item: item.reading_order)
    rendered_table_ids: set[str] = set()
    represented_line_ids: set[str] = set()
    elements: list[Element] = []
    new_figure_ids: list[str] = []

    for layout in layouts:
        if layout.layout_type == "LAYOUT_TABLE":
            t_ids = table_ids_from_layout(layout)
            for t_id in t_ids:
                table_obj = next(
                    (t for t in textractor_page.tables if t.id == t_id),
                    None,
                )
                if table_obj is not None and table_obj.id not in rendered_table_ids:
                    elements.append(_map_table(table_obj, page_number))
                    rendered_table_ids.add(table_obj.id)
            if not t_ids:
                # LAYOUT_TABLE with no associated Table object – retain as text.
                represented_line_ids.update(layout_line_ids(layout))
                text = entity_text(layout)
                if text:
                    elements.append(
                        Element(
                            kind="table_region",
                            text=text,
                            references=(_make_ref(layout, page_number),),
                        )
                    )
            continue

        if layout.layout_type == "LAYOUT_FIGURE":
            # Figures have no semantic representation; emit a warning block_id.
            new_figure_ids.append(str(layout.id))
            continue

        text = entity_text(layout)
        represented_line_ids.update(layout_line_ids(layout))
        if text:
            kind = _LAYOUT_KIND.get(layout.layout_type, "text")
            elements.append(
                Element(
                    kind=kind,
                    text=text,
                    references=(_make_ref(layout, page_number),),
                )
            )

    # Tables without a LAYOUT_TABLE parent: geometry order.
    for table_obj in sorted(textractor_page.tables, key=lambda t: _sort_key(t)):
        if table_obj.id not in rendered_table_ids:
            elements.append(_map_table(table_obj, page_number))
            rendered_table_ids.add(table_obj.id)

    # Lines not covered by any layout or table: geometry fallback.
    table_word_ids: set[str] = {
        str(word.id)
        for table_obj in textractor_page.tables
        for cell in table_obj.table_cells
        for word in cell.words
    }
    fallback_lines = [
        line
        for line in textractor_page.lines
        if line.id not in represented_line_ids
        and not {str(word.id) for word in line.words}.issubset(table_word_ids)
    ]
    for line in sorted(fallback_lines, key=_sort_key):
        text = entity_text(line)
        if text:
            elements.append(
                Element(
                    kind="text",
                    text=text,
                    references=(_make_ref(line, page_number),),
                )
            )

    has_layouts = bool(layouts)
    reading_order: Literal["textract_layout", "geometry_fallback"] = (
        "textract_layout" if has_layouts else "geometry_fallback"
    )
    mapped_page = Page(
        number=page_number,
        elements=tuple(elements),
        reading_order=reading_order,
    )
    return mapped_page, new_figure_ids


def _sort_key(entity: Any) -> tuple[float, float]:
    """Geometry sort key (top, left); falls back to (2.0, 2.0) if bbox absent."""
    bbox = getattr(entity, "bbox", None)
    if bbox is None:
        return (2.0, 2.0)
    try:
        return (float(bbox.y), float(bbox.x))
    except (AttributeError, TypeError, ValueError):
        return (2.0, 2.0)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _build_structured_document(
    textractor_doc: Any,
    analysis: Analysis,
    source: Source,
) -> Document:
    """Map the Textractor Document object model to contracts.Document.

    Traversal order mirrors page_html() in textractor_renderer exactly so that
    document.json content and ordering are consistent with the HTML output.
    """
    pages: list[Page] = []
    all_figure_ids: list[str] = []

    for page_number, textractor_page in enumerate(textractor_doc.pages, start=1):
        mapped_page, new_figure_ids = _map_page(textractor_page, page_number, all_figure_ids)
        pages.append(mapped_page)
        all_figure_ids.extend(new_figure_ids)

    # Warnings from the raw response.
    raw_warnings: list[Warning] = []
    for w in analysis.warnings:
        raw_warnings.append(Warning(code="AWS_" + w.code, pages=w.pages))

    # Operational status warning.
    if analysis.status == "PARTIAL_SUCCESS":
        raw_warnings.append(Warning(code="PARTIAL_ANALYSIS"))

    # Figure blocks are silently skipped in HTML rendering; record each one
    # with UNINTERPRETED_LAYOUT_FIGURE so consumers can track coverage.
    for fig_id in all_figure_ids:
        raw_warnings.append(Warning(code="UNINTERPRETED_LAYOUT_FIGURE", block_ids=(fig_id,)))

    status: Literal["SUCCEEDED", "PARTIAL_SUCCESS"] = (
        "PARTIAL_SUCCESS" if analysis.status == "PARTIAL_SUCCESS" else "SUCCEEDED"
    )
    return Document(
        source=source,
        status=status,
        provider_model_version=analysis.model_version,
        declared_pages=analysis.metadata.pages,
        pages=tuple(pages),
        warnings=tuple(raw_warnings),
    )


def _check_relationship_graph(blocks: tuple[Block, ...], max_depth: int) -> None:
    """Detect cycles and chains exceeding max_depth before Textractor parsing.

    Uses Kahn's topological sort (BFS) to detect cycles and simultaneously
    compute the longest-path depth from any root.  Raises:
      ConversionError("CYCLIC_RELATIONSHIP") if the graph contains a cycle.
      ConversionError("RELATIONSHIP_DEPTH_EXCEEDED") if any path length > max_depth.

    CHILD and MERGED_CELL relationships are traversed; phantom IDs (referenced
    but not present as blocks) are ignored.  A legitimate large table does not
    trigger this check: table size uses RowIndex/ColumnIndex, not relationship depth.
    """
    all_ids: set[str] = {b.id for b in blocks}
    children: dict[str, list[str]] = {b.id: [] for b in blocks}
    in_degree: dict[str, int] = dict.fromkeys(all_ids, 0)

    for block in blocks:
        for rel in block.relationships:
            if rel.kind in ("CHILD", "MERGED_CELL"):
                for bid in rel.ids:
                    if bid in all_ids:
                        children[block.id].append(bid)
                        in_degree[bid] += 1

    # Kahn's BFS: longest path = max hop count from any root.
    queue: deque[str] = deque(bid for bid in all_ids if in_degree[bid] == 0)
    longest: dict[str, int] = dict.fromkeys(all_ids, 0)
    processed = 0

    while queue:
        node_id = queue.popleft()
        processed += 1
        for child_id in children[node_id]:
            child_depth = longest[node_id] + 1
            if child_depth > max_depth:
                raise ConversionError("RELATIONSHIP_DEPTH_EXCEEDED")
            if child_depth > longest[child_id]:
                longest[child_id] = child_depth
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    if processed != len(all_ids):
        # Kahn's invariant: unprocessed nodes participate in a cycle.
        raise ConversionError("CYCLIC_RELATIONSHIP")


def validate_textract_response(
    response: object,
    limits: ConversionLimits,
) -> tuple[Analysis, int]:
    """Validate status, pagination and block count.

    Returns (analysis, raw_table_count).
    Raises ConversionError with a safe code on any validation failure.
    Delegates to provider.parse_analysis for boundary validation; reuses the
    same limits contract as the retired normaliser.
    """
    analysis = parse_analysis(response)
    if analysis.status not in {"SUCCEEDED", "PARTIAL_SUCCESS"}:
        raise ConversionError("ANALYSIS_" + analysis.status)
    if analysis.next_token:
        raise ConversionError("PAGINATION_INCOMPLETE")
    if not analysis.blocks:
        raise ConversionError("EMPTY_ANALYSIS")
    if len(analysis.blocks) > limits.max_blocks:
        raise ConversionError("BLOCK_LIMIT")
    if analysis.metadata.pages and analysis.metadata.pages > limits.max_pages:
        raise ConversionError("PAGE_LIMIT")
    # Relationship safeguard: reject cycles and deep chains before Textractor parsing.
    _check_relationship_graph(analysis.blocks, limits.max_relationship_depth)
    raw: dict[str, Any] = response if isinstance(response, dict) else {}  # type: ignore[reportUnknownVariableType]
    tables = raw_table_count(raw)  # type: ignore[arg-type]
    return analysis, tables


def convert_and_render(
    response: object,
    source: Source,
    limits: ConversionLimits | None = None,
) -> ConversionResult:
    """Full conversion pipeline: validate → parse → map.

    Returns a ConversionResult that holds the structured document (document.json)
    and the internal Textractor Document for HTML rendering.  Callers pass the
    result to render_full_document_html() and render_individual_pages().

    No AWS calls, no file I/O; consumes the already-collected raw response dict.
    """
    resolved = limits or ConversionLimits()
    analysis, tables = validate_textract_response(response, resolved)
    textractor_doc = textractor_parse(response)  # type: ignore[arg-type]
    structured = _build_structured_document(textractor_doc, analysis, source)
    # Advisory tolerance-symbol detector: adds warnings without altering text or status.
    tolerance_warnings = detect_tolerance_ambiguities(structured)
    if tolerance_warnings:
        structured = structured.model_copy(
            update={"warnings": structured.warnings + tuple(tolerance_warnings)}
        )
    return ConversionResult(
        document=structured,
        textractor_doc=textractor_doc,
        raw_tables=tables,
    )


# ---------------------------------------------------------------------------
# Rendering entry points
# ---------------------------------------------------------------------------


def render_full_document_html(result: ConversionResult) -> str:
    """Return the complete navigable multi-page HTML string (document.html).

    Passes the structured document's status and warnings to the renderer so
    that PARTIAL_SUCCESS and AWS warnings appear in the full downloadable HTML,
    not only in document.json and individual page artifacts.
    """
    doc = result.document
    warning_pairs = [(w.code, list(w.pages)) for w in doc.warnings]
    return document_html(result.textractor_doc, result.raw_tables, doc.status, warning_pairs)


def render_individual_pages(result: ConversionResult) -> dict[int, str]:
    """Return per-page standalone HTML strings keyed by 1-based page number.

    Single-threaded; no parallel processing is introduced.
    page-NNNN.html artifacts are produced from the same Textractor objects and
    page_html() function used by document_html().
    """
    doc = result.textractor_doc
    structured = result.document
    total = len(doc.pages)
    output: dict[int, str] = {}
    for page_number, page in enumerate(doc.pages, start=1):
        # Collect warning codes relevant to this page number.
        codes: list[str] = [
            w.code for w in structured.warnings if not w.pages or page_number in w.pages
        ]
        output[page_number] = render_page_standalone(
            page,
            page_number,
            total,
            structured.status,
            codes,
        )
    return output


# ---------------------------------------------------------------------------
# Compatibility shim: JSON bytes → response dict (used by __main__ and tests)
# ---------------------------------------------------------------------------


def load_response(data: bytes) -> dict[str, object]:
    """Deserialise raw Textract JSON bytes; preserve the dict contract."""
    return json.loads(data)  # type: ignore[return-value]
