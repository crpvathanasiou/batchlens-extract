"""Deterministic script-free rendering of approved review revisions."""

from collections.abc import Mapping
from html import escape

from app.document_conversion.contracts import Content, Element
from app.document_review.contracts import (
    CatalogueNode,
    ReviewCatalogue,
    ReviewError,
    ReviewRevision,
)

_HTML_ATTRIBUTE_VERSION = "1"


def _attr(name: str, value: str) -> str:
    return f' {name}="{escape(value, quote=True)}"'


def _source_attr(content: Content) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for reference in content.references:
        if reference.block_id in seen:
            continue
        seen.add(reference.block_id)
        ordered.append(reference.block_id)
    if not ordered:
        return ""
    return _attr("data-source-id", " ".join(ordered))


def _text(content: Content, tag: str = "p", attributes: str = "") -> str:
    value = escape(content.text, quote=True).replace("\n", "<br>")
    return f"<{tag}{attributes}>{value}</{tag}>"


def _element_text_tag(kind: str) -> str:
    if kind == "title":
        return "h2"
    if kind == "section_heading":
        return "h3"
    return "p"


def _catalogue_index(catalogue: ReviewCatalogue) -> dict[tuple[int, str], CatalogueNode]:
    index: dict[tuple[int, str], CatalogueNode] = {}
    for node in catalogue.nodes:
        key = (node.page_number, node.path)
        if key in index:
            raise ReviewError("INVALID_REVIEW_STATE")
        index[key] = node
    return index


def _require(
    index: Mapping[tuple[int, str], CatalogueNode],
    page_number: int,
    path: str,
    kind: str,
) -> CatalogueNode:
    node = index.get((page_number, path))
    if node is None or node.kind != kind or node.page_number != page_number or node.path != path:
        raise ReviewError("INVALID_REVIEW_STATE")
    return node


def _element(
    element: Element,
    page_number: int,
    path: str,
    index: Mapping[tuple[int, str], CatalogueNode],
) -> str:
    node = _require(index, page_number, path, element.kind)
    kind = escape(element.kind, quote=True)
    heading = (
        "h3" if element.kind in {"TITLE", "SECTION_HEADER", "title", "section_heading"} else "h4"
    )
    parts = [
        f'<article class="element" data-kind="{kind}"{_attr("data-element-id", node.node_id)}>'
    ]
    if element.text:
        parts.append(
            _text(
                element,
                _element_text_tag(element.kind),
                _attr("data-node-id", node.node_id) + _source_attr(element),
            )
        )
    for title_index, title in enumerate(element.titles):
        title_node = _require(index, page_number, f"{path}.titles[{title_index}]", "TITLE")
        parts.append(
            _text(
                title,
                heading,
                _attr("data-node-id", title_node.node_id) + _source_attr(title),
            )
        )
    if element.cells:
        parts.append(f"<table{_attr('data-table-id', node.node_id)}><tbody>")
        row = 0
        for cell_index, cell in enumerate(element.cells):
            cell_node = _require(index, page_number, f"{path}.cells[{cell_index}]", "TABLE_CELL")
            if cell.row != row:
                if row:
                    parts.append("</tr>")
                parts.append("<tr>")
                row = cell.row
            tag = "th" if cell.header else "td"
            attributes = (
                f' rowspan="{cell.row_span}" colspan="{cell.column_span}"'
                f' data-row="{cell.row}" data-column="{cell.column}"'
                + _attr("data-node-id", cell_node.node_id)
                + _source_attr(cell)
            )
            parts.append(_text(cell, tag, attributes))
        if row:
            parts.append("</tr>")
        parts.append("</tbody></table>")
    parts.extend(
        _element(child, page_number, f"{path}.children[{child_index}]", index)
        for child_index, child in enumerate(element.children)
    )
    for footer_index, footer in enumerate(element.footers):
        footer_node = _require(index, page_number, f"{path}.footers[{footer_index}]", "FOOTER")
        parts.append(
            _text(
                footer,
                "footer",
                _attr("data-node-id", footer_node.node_id) + _source_attr(footer),
            )
        )
    parts.append("</article>")
    return "".join(parts)


def render_reviewed_html(revision: ReviewRevision) -> str:
    index = _catalogue_index(revision.catalogue)
    approval = revision.document_approval
    approved = (
        f"Approved by {escape(approval.actor)} at {escape(approval.at.isoformat())}"
        if approval
        else "Not approved"
    )
    limitation = (
        '<aside class="limitation" data-generated="true">'
        "Partial conversion: source evidence may be incomplete.</aside>"
        if revision.document.status == "PARTIAL_SUCCESS"
        else ""
    )
    pages = "".join(
        f'<section class="page" id="source-page-{page.number}" data-page="{page.number}">'
        f"<h2{_attr('data-generated', 'true')}>Page {page.number}</h2>"
        + "".join(
            _element(
                element,
                page.number,
                f"pages[{page.number}].elements[{element_index}]",
                index,
            )
            for element_index, element in enumerate(page.elements)
        )
        + "</section>"
        for page in revision.document.pages
    )
    css = (
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#18202a}"
        ".summary,.limitation{padding:1rem;margin-bottom:1rem;background:#eef3f8}"
        ".limitation{background:#fff0d5}.page{break-after:page;margin:2rem 0}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #777;padding:.4rem}"
        "p,h2,h3,h4,td,th,footer{white-space:pre-wrap}"
    )
    root = (
        "<html"
        + _attr("data-review-html-version", _HTML_ATTRIBUTE_VERSION)
        + _attr("data-job-id", revision.job_id)
        + _attr("data-review-revision-id", revision.revision_id)
        + _attr("data-review-generation", str(revision.generation))
        + _attr("data-conversion-status", revision.document.status)
        + ">"
    )
    return (
        "<!doctype html>" + root + '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Reviewed document</title><style>" + css + "</style></head><body>"
        f'<header class="summary"{_attr("data-generated", "true")}>'
        "<h1>Reviewed document</h1>"
        f"<p>Revision: {escape(revision.revision_id)}</p><p>{approved}</p></header>"
        + limitation
        + "<main>"
        + pages
        + "</main></body></html>"
    )
