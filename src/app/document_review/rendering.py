"""Deterministic script-free rendering of approved review revisions."""

from html import escape

from app.document_conversion.contracts import Content, Element
from app.document_review.contracts import ReviewRevision


def _text(content: Content, tag: str = "p", attributes: str = "") -> str:
    value = escape(content.text, quote=True).replace("\n", "<br>")
    return f"<{tag}{attributes}>{value}</{tag}>"


def _element_text_tag(kind: str) -> str:
    if kind == "title":
        return "h2"
    if kind == "section_heading":
        return "h3"
    return "p"


def _element(element: Element) -> str:
    kind = escape(element.kind, quote=True)
    heading = (
        "h3" if element.kind in {"TITLE", "SECTION_HEADER", "title", "section_heading"} else "h4"
    )
    parts = [f'<article class="element" data-kind="{kind}">']
    if element.text:
        parts.append(_text(element, _element_text_tag(element.kind)))
    parts.extend(_text(title, heading) for title in element.titles)
    if element.cells:
        parts.append("<table><tbody>")
        row = 0
        for cell in element.cells:
            if cell.row != row:
                if row:
                    parts.append("</tr>")
                parts.append("<tr>")
                row = cell.row
            tag = "th" if cell.header else "td"
            attributes = (
                f' rowspan="{cell.row_span}" colspan="{cell.column_span}"'
                f' data-row="{cell.row}" data-column="{cell.column}"'
            )
            parts.append(_text(cell, tag, attributes))
        if row:
            parts.append("</tr>")
        parts.append("</tbody></table>")
    parts.extend(_element(child) for child in element.children)
    parts.extend(_text(footer, "footer") for footer in element.footers)
    parts.append("</article>")
    return "".join(parts)


def render_reviewed_html(revision: ReviewRevision) -> str:
    approval = revision.document_approval
    approved = (
        f"Approved by {escape(approval.actor)} at {escape(approval.at.isoformat())}"
        if approval
        else "Not approved"
    )
    limitation = (
        '<aside class="limitation">Partial conversion: source evidence may be incomplete.</aside>'
        if revision.document.status == "PARTIAL_SUCCESS"
        else ""
    )
    pages = "".join(
        f'<section class="page" id="source-page-{page.number}" data-page="{page.number}">'
        f"<h2>Page {page.number}</h2>"
        + "".join(_element(element) for element in page.elements)
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
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Reviewed document</title><style>"
        + css
        + '</style></head><body><header class="summary"><h1>Reviewed document</h1>'
        f"<p>Revision: {escape(revision.revision_id)}</p><p>{approved}</p></header>"
        + limitation
        + "<main>"
        + pages
        + "</main></body></html>"
    )
