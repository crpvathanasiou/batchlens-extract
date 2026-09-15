"""Index first, then normalize ownership, tables and declared layout order."""

from collections import deque

from app.document_conversion.contracts import (
    Cell,
    Content,
    ConversionError,
    ConversionLimits,
    Document,
    Element,
    Page,
    Source,
    Warning,
)
from app.document_conversion.provider import Analysis, Block, parse_analysis


class Normalizer:
    def __init__(self, analysis: Analysis, limits: ConversionLimits) -> None:
        self.analysis = analysis
        self.limits = limits
        self.blocks = {b.id: b for b in analysis.blocks}
        if len(self.blocks) != len(analysis.blocks):
            raise ConversionError("DUPLICATE_BLOCK_ID")
        self.warnings: set[tuple[str, tuple[str, ...], tuple[int, ...]]] = set()
        self.pages = {b.id: b.page for b in analysis.blocks}
        self.used: set[str] = set()
        self.table_owned: set[str] = set()
        self.table_cache: dict[str, Element] = {}
        self._resolve_pages()

    def warn(self, code: str, *ids: str, pages: tuple[int, ...] = ()) -> None:
        self.warnings.add((code, tuple(ids), pages))

    def _resolve_pages(self) -> None:
        queue = deque(b.id for b in self.analysis.blocks if b.page is not None)
        while queue:
            parent = self.blocks[queue.popleft()]
            for rid in parent.ids("CHILD", "MERGED_CELL", "TABLE_TITLE", "TABLE_FOOTER"):
                if rid not in self.blocks:
                    self.warn("MISSING_REFERENCE", parent.id, rid)
                elif self.pages[rid] is None:
                    self.pages[rid] = self.pages[parent.id]
                    queue.append(rid)
                elif self.pages[rid] != self.pages[parent.id]:
                    self.warn("CROSS_PAGE_RELATIONSHIP", parent.id, rid)
        # Infer an unassigned parent from consistently assigned supported children.
        # Require all extant children to have a page; conflicting pages remain unresolved.
        for _ in range(self.limits.max_relationship_depth):
            changed = False
            for b in self.blocks.values():
                if self.pages[b.id] is not None:
                    continue
                ids = b.ids("CHILD", "MERGED_CELL", "TABLE_TITLE", "TABLE_FOOTER")
                values = {self.pages[i] for i in ids if i in self.blocks}
                if len(values) == 1 and None not in values:
                    self.pages[b.id] = next(iter(values))
                    changed = True
            if not changed:
                break
        for b in sorted(self.blocks.values(), key=lambda b: b.id):
            if self.pages[b.id] is None:
                self.warn("UNRESOLVED_PAGE", b.id)
            for r in b.relationships:
                for rid in r.ids:
                    if rid not in self.blocks:
                        self.warn("MISSING_REFERENCE", b.id, rid)

    def descendants(self, block: Block, trail: tuple[str, ...] = ()) -> list[Block]:
        stack = [(block, trail)]
        seen: set[str] = set()
        result: list[Block] = []
        while stack:
            current, ancestors = stack.pop()
            if current.id in ancestors:
                self.warn("CYCLIC_RELATIONSHIP", current.id)
                continue
            if current.id in seen:
                continue
            if len(ancestors) >= self.limits.max_relationship_depth:
                raise ConversionError("RELATIONSHIP_DEPTH_LIMIT")
            seen.add(current.id)
            result.append(current)
            children = [
                self.blocks[rid]
                for rid in current.ids("CHILD", "MERGED_CELL", "TABLE_TITLE", "TABLE_FOOTER")
                if rid in self.blocks
            ]
            if current.kind == "MERGED_CELL":
                children.sort(key=lambda c: (c.row or 0, c.column or 0, c.id))
            stack.extend((child, (*ancestors, current.id)) for child in reversed(children))
        return result

    def content(self, block: Block, exclude: set[str] | None = None) -> Content:
        excluded: set[str] = exclude if exclude is not None else set()
        refs = [block.reference(self.pages[block.id])]
        if block.kind in {"CELL", "MERGED_CELL"}:
            refs.extend(
                b.reference(self.pages[b.id])
                for b in self.descendants(block)
                if b.kind in {"CELL", "MERGED_CELL"}
            )
        words: list[str] = []
        selections: list[str] = []
        seen: set[str] = set()
        leaves = [b for b in self.descendants(block) if b.kind in {"WORD", "SELECTION_ELEMENT"}]
        # Saved responses sometimes omit word relationships. Preserve standalone LINE text.
        if not leaves:
            leaves = [b for b in self.descendants(block) if b.text]
            leaves = [
                b
                for b in leaves
                if not any(x in self.blocks and self.blocks[x].text for x in b.ids("CHILD"))
            ]
        for leaf in leaves:
            if self.pages[leaf.id] != self.pages[block.id]:
                self.warn("CROSS_PAGE_CONTENT_NOT_IN_PARENT", block.id, leaf.id)
                continue
            if leaf.id in seen or leaf.id in excluded:
                continue
            seen.add(leaf.id)
            refs.append(leaf.reference(self.pages[leaf.id]))
            if leaf.selection is not None:
                selections.append(leaf.selection)
                words.append("[x]" if leaf.selection == "SELECTED" else "[ ]")
            elif leaf.text:
                words.append(leaf.text)
        # Deduplicate references, not text: identical words in distinct cells are legitimate.
        return Content.model_validate(
            {
                "text": " ".join(words),
                "references": list({r.block_id: r for r in refs}.values()),
                "selections": selections,
            }
        )

    def sort_key(self, block: Block) -> tuple[float, float, str]:
        box = block.geometry.box if block.geometry else None
        return (box.top if box else 2, box.left if box else 2, block.id)

    def table(self, block: Block) -> Element:
        children = [self.blocks[i] for i in block.ids("CHILD") if i in self.blocks]
        merged = [self.blocks[i] for i in block.ids("MERGED_CELL") if i in self.blocks]
        cells: list[Cell] = []
        covered: set[tuple[int, int]] = set()
        members = {i for m in merged for i in m.ids("CHILD")}
        for b in sorted(merged, key=lambda b: (b.row or 0, b.column or 0, b.id)) + sorted(
            (c for c in children if c.id not in members),
            key=lambda b: (b.row or 0, b.column or 0, b.id),
        ):
            if b.kind not in {"CELL", "MERGED_CELL"}:
                self.warn("UNSUPPORTED_TABLE_CHILD", b.id)
                continue
            if b.row is None or b.column is None:
                raise ConversionError("MISSING_CELL_COORDINATES")
            if (b.row + b.row_span - 1) * (b.column + b.column_span - 1) > (
                self.limits.max_table_positions
            ):
                raise ConversionError("TABLE_POSITION_LIMIT")
            positions = {
                (r, c)
                for r in range(b.row, b.row + b.row_span)
                for c in range(b.column, b.column + b.column_span)
            }
            if covered & positions:
                # A normal cell geometrically covered by a merge is not emitted twice.
                if b.kind == "CELL" and positions <= covered:
                    self.warn("MERGE_MEMBER_RELATIONSHIP_MISSING", b.id)
                    continue
                raise ConversionError("OVERLAPPING_TABLE_CELLS")
            covered |= positions
            content = self.content(b)
            types = tuple(sorted({t for d in self.descendants(b) for t in d.entity_types}))
            cells.append(
                Cell(
                    **content.model_dump(),
                    row=b.row,
                    column=b.column,
                    row_span=b.row_span,
                    column_span=b.column_span,
                    header="COLUMN_HEADER" in types,
                    entity_types=types,
                )
            )
        rows = max((c.row + c.row_span - 1 for c in cells), default=0)
        columns = max((c.column + c.column_span - 1 for c in cells), default=0)
        if rows * columns > self.limits.max_table_positions:
            raise ConversionError("TABLE_POSITION_LIMIT")
        for row in range(1, rows + 1):
            for col in range(1, columns + 1):
                if (row, col) not in covered:
                    self.warn("MISSING_CELL_POSITION", block.id)
                    cells.append(
                        Cell(
                            row=row,
                            column=col,
                            inferred_empty=True,
                            references=(block.reference(self.pages[block.id]),),
                        )
                    )

        cell_ids = {r.block_id for cell in cells for r in cell.references}

        def captions(kind: str) -> tuple[Content, ...]:
            return tuple(
                self.content(self.blocks[i], cell_ids) for i in block.ids(kind) if i in self.blocks
            )

        if not cells:
            self.warn("EMPTY_TABLE", block.id)
        return Element(
            kind="table",
            references=(block.reference(self.pages[block.id]),),
            cells=tuple(sorted(cells, key=lambda c: (c.row, c.column))),
            rows=rows,
            columns=columns,
            titles=captions("TABLE_TITLE"),
            footers=captions("TABLE_FOOTER"),
        )

    def element(self, b: Block, trail: tuple[str, ...] = ()) -> Element | None:
        if b.id in self.used:
            return None
        if trail and self.pages[b.id] != self.pages[trail[-1]]:
            self.warn("CROSS_PAGE_CONTENT_NOT_IN_PARENT", trail[-1], b.id)
            return None
        if b.id in trail:
            self.warn("CYCLIC_RELATIONSHIP", b.id)
            return None
        if len(trail) >= self.limits.max_relationship_depth:
            raise ConversionError("RELATIONSHIP_DEPTH_LIMIT")
        self.used.add(b.id)
        if b.kind == "TABLE":
            return self.table_cache[b.id]
        if b.kind == "LAYOUT_TABLE":
            # LAYOUT_TABLE can refer to TABLE directly or share WORDs through LINEs.
            ids = {d.id for d in self.descendants(b)}
            matches = [
                t
                for t in self.table_cache
                if t in ids
                or any(
                    d.id in ids and d.kind in {"WORD", "SELECTION_ELEMENT"}
                    for d in self.descendants(self.blocks[t])
                )
            ]
            nested: list[Element] = []
            for tid in sorted(matches, key=lambda t: self.sort_key(self.blocks[t])):
                e = self.element(self.blocks[tid], (*trail, b.id))
                if e is not None:
                    nested.append(e)
            remainder = self.content(b, self.table_owned | self.used)
            self.used.update(r.block_id for r in remainder.references)
            if not matches:
                self.warn("LAYOUT_TABLE_WITHOUT_TABLE", b.id)
            return Element(**remainder.model_dump(), kind="table_region", children=tuple(nested))
        if b.kind == "LAYOUT_LIST":
            nested = []
            for rid in b.ids("CHILD"):
                if rid in self.blocks:
                    e = self.element(self.blocks[rid], (*trail, b.id))
                    if e is not None:
                        nested.append(e)
            return Element(
                kind="list", references=(b.reference(self.pages[b.id]),), children=tuple(nested)
            )
        c = self.content(b, self.table_owned | (self.used - {b.id}))
        self.used.update(r.block_id for r in c.references)
        kind = {
            "LAYOUT_TITLE": "title",
            "LAYOUT_SECTION_HEADER": "section_heading",
            "LAYOUT_HEADER": "header",
            "LAYOUT_FOOTER": "footer",
            "LAYOUT_PAGE_NUMBER": "page_number",
            "LAYOUT_TEXT": "text",
            "LINE": "text",
            "WORD": "text",
            "SELECTION_ELEMENT": "text",
            "LAYOUT_FIGURE": "figure",
            "LAYOUT_KEY_VALUE": "key_value_region",
            "SIGNATURE": "signature",
        }.get(b.kind, "unsupported")
        if kind in {"figure", "signature", "unsupported", "key_value_region"}:
            self.warn("UNINTERPRETED_" + b.kind, b.id)
        if not c.text and kind == "text":
            return None
        return Element(**c.model_dump(), kind=kind)

    def convert(self, source: Source) -> Document:
        for b in sorted(self.blocks.values(), key=lambda b: b.id):
            if b.kind == "TABLE" and self.pages[b.id] is not None:
                self.table_cache[b.id] = self.table(b)
                self.table_owned.update(d.id for d in self.descendants(b))
        page_numbers = sorted({n for n in self.pages.values() if n is not None})
        declared = self.analysis.metadata.pages
        if declared and declared > self.limits.max_pages:
            raise ConversionError("PAGE_LIMIT")
        if declared:
            page_numbers = sorted(set(page_numbers) | set(range(1, declared + 1)))
        if not page_numbers:
            raise ConversionError("NO_RESOLVED_PAGES")
        if len(page_numbers) > self.limits.max_pages:
            raise ConversionError("PAGE_LIMIT")
        pages: list[Page] = []
        for number in page_numbers:
            blocks = [b for b in self.analysis.blocks if self.pages[b.id] == number]
            layouts = [b for b in blocks if b.kind.startswith("LAYOUT_")]
            nested_ids = {i for b in layouts for i in b.ids("CHILD")}
            roots = [b for b in layouts if b.id not in nested_ids]
            order = "textract_layout" if roots else "geometry_fallback"
            if not roots:
                self.warn("GEOMETRY_ORDER_NOT_MULTICOLUMN_RELIABLE", pages=(number,))
            elements: list[Element] = []
            for b in roots:
                e = self.element(b)
                if e is not None:
                    elements.append(e)
            fallback = [b for b in blocks if b.kind in {"TABLE", "LINE", "SIGNATURE"}]
            if roots and any(b.id not in self.used and b.kind == "TABLE" for b in fallback):
                self.warn("UNPLACED_TABLE_APPENDED", pages=(number,))
            for b in sorted(fallback, key=self.sort_key):
                e = self.element(b)
                if e is not None:
                    elements.append(e)
            for b in sorted(blocks, key=self.sort_key):
                if b.kind in {"WORD", "SELECTION_ELEMENT"} and (
                    b.id not in self.used and b.id not in self.table_owned
                ):
                    self.warn("ORPHAN_CONTENT_APPENDED", b.id)
                    e = self.element(b)
                    if e is not None:
                        elements.append(e)
                elif b.kind not in {
                    "PAGE",
                    "TABLE",
                    "CELL",
                    "MERGED_CELL",
                    "WORD",
                    "LINE",
                    "SELECTION_ELEMENT",
                    "TABLE_TITLE",
                    "TABLE_FOOTER",
                    "SIGNATURE",
                } and not b.kind.startswith("LAYOUT_"):
                    self.warn("UNSUPPORTED_BLOCK_TYPE", b.id)
                    e = self.element(b)
                    if e is not None:
                        elements.append(e)
            if not elements:
                self.warn("PAGE_WITHOUT_CONTENT", pages=(number,))
            pages.append(Page(number=number, elements=tuple(elements), reading_order=order))
        for warning in self.analysis.warnings:
            self.warn("AWS_" + warning.code, pages=warning.pages)
        if self.analysis.status == "PARTIAL_SUCCESS":
            self.warn("PARTIAL_ANALYSIS")
        return Document(
            source=source,
            status="PARTIAL_SUCCESS" if self.analysis.status == "PARTIAL_SUCCESS" else "SUCCEEDED",
            provider_model_version=self.analysis.model_version,
            declared_pages=declared,
            pages=tuple(pages),
            warnings=tuple(
                Warning(code=c, block_ids=i, pages=p) for c, i, p in sorted(self.warnings)
            ),
        )


def convert_textract(
    response: object,
    source: Source,
    limits: ConversionLimits | None = None,
) -> Document:
    """Convert a complete saved response, with no clients, network or credentials."""
    resolved = limits or ConversionLimits()
    analysis = parse_analysis(response)
    if analysis.status not in {"SUCCEEDED", "PARTIAL_SUCCESS"}:
        raise ConversionError("ANALYSIS_" + analysis.status)
    if analysis.next_token:
        raise ConversionError("PAGINATION_INCOMPLETE")
    if not analysis.blocks:
        raise ConversionError("EMPTY_ANALYSIS")
    if len(analysis.blocks) > resolved.max_blocks:
        raise ConversionError("BLOCK_LIMIT")
    return Normalizer(analysis, resolved).convert(source)
