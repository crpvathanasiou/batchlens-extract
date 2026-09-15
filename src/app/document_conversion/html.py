"""Script-free semantic projection; no pixel-perfect or token-budget claims."""

from concurrent.futures import ProcessPoolExecutor
from html import escape
from multiprocessing import get_context

from app.document_conversion.contracts import Cell, Content, Document, Element, Page, Warning


def anchor(page: int, block_id: str) -> str:
    # Hex encoding is injective, so hostile IDs cannot collide via sanitization.
    return f"p{page}-b{block_id.encode('utf-8').hex()}"


def attributes(content: Content, page: int, suffix: str = "") -> str:
    block_id = content.references[0].block_id
    return (
        f' id="{anchor(page, block_id)}{suffix}"'
        f' data-source-id="{escape(block_id, quote=True)}" data-page="{page}"'
    )


def render_cell(cell: Cell, page: int) -> str:
    tag = "th" if cell.header else "td"
    suffix = f"-r{cell.row}-c{cell.column}"
    attrs = attributes(cell, page, suffix)
    return (
        f'<{tag}{attrs} rowspan="{cell.row_span}" colspan="{cell.column_span}">'
        f"{escape(cell.text)}</{tag}>"
    )


def render_element(element: Element, page: int) -> str:
    attrs = attributes(element, page)
    text = escape(element.text)
    children = "".join(render_element(c, page) for c in element.children)
    if element.kind == "table":
        captions = "".join(
            f'<span{attributes(c, page, "-title")}>{escape(c.text)}</span>'
            for c in element.titles
            if c.text
        )
        rows = "".join(
            "<tr>" + "".join(render_cell(c, page) for c in element.cells if c.row == r) + "</tr>"
            for r in range(1, element.rows + 1)
        )
        footers = "".join(
            f'<p{attributes(c, page, "-footer")}>{escape(c.text)}</p>'
            for c in element.footers
            if c.text
        )
        caption = f"<caption>{captions}</caption>" if captions else ""
        return f"<div><table{attrs}>{caption}<tbody>{rows}</tbody></table>{footers}</div>"
    if element.kind == "list":
        return (
            f"<ul{attrs}>"
            + "".join("<li>" + render_element(c, page) + "</li>" for c in element.children)
            + "</ul>"
        )
    if element.kind in {"figure", "signature", "unsupported", "key_value_region"}:
        label = {
            "figure": "Figure: visual content not interpreted.",
            "signature": "Signature region: identity not interpreted.",
            "unsupported": "Unsupported source region.",
            "key_value_region": "Form region: field relationships not interpreted.",
        }[element.kind]
        return f"<figure{attrs}><figcaption>{label}</figcaption><p>{text}</p>{children}</figure>"
    tag = {
        "title": "h1",
        "section_heading": "h2",
        "header": "header",
        "footer": "footer",
        "table_region": "section",
    }.get(element.kind, "p")
    return f"<{tag}{attrs}>{text}{children}</{tag}>"


def page_fragment(page: Page) -> str:
    content = "".join(render_element(e, page.number) for e in page.elements)
    return f'<section id="page-{page.number}" data-page="{page.number}">{content}</section>'


def conversion_summary(
    status: str | None, warnings: tuple[Warning, ...], page: int | None = None
) -> str:
    summary = ""
    if status == "PARTIAL_SUCCESS":
        summary = (
            '<aside class="conversion-partial"><strong>Partial result — '
            "document conversion status: PARTIAL_SUCCESS</strong>"
            "<p>Some document content may be missing or incomplete.</p></aside>"
        )
    elif status is not None:
        summary = f"<p>Document conversion status: {escape(status)}</p>"
    visible = tuple(w for w in warnings if page is None or not w.pages or page in w.pages)
    if not visible:
        return summary
    items: list[str] = []
    for warning in visible:
        scope = (
            "Pages: " + ", ".join(str(number) for number in warning.pages)
            if warning.pages
            else "Document-level warning (no page assigned)"
        )
        blocks = (
            "<div>Block references: " + escape(", ".join(warning.block_ids)) + "</div>"
            if warning.block_ids
            else ""
        )
        items.append(
            f"<li><code>{escape(warning.code)}</code><div>{escape(scope)}</div>{blocks}</li>"
        )
    note = (
        "<p>Includes warnings for this page and document-level warnings without a page "
        "assignment. See document.html for the full warning summary.</p>"
        if page is not None
        else ""
    )
    return (
        summary
        + '<aside class="conversion-warnings"><h2>Conversion warnings</h2>'
        + note
        + "<ul>"
        + "".join(items)
        + "</ul></aside>"
    )


def wrap_html(content: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'\">"
        "<title>Converted document</title><style>"
        "body{font-family:system-ui,sans-serif;line-height:1.5;margin:2rem}"
        "table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #777;"
        "padding:.4rem;vertical-align:top}section[data-page]{margin-bottom:2rem}"
        ".conversion-partial,.conversion-warnings{border:1px solid #996000;"
        "border-left:5px solid #996000;background:#fff8e6;color:#503400;"
        "padding:1rem;margin-bottom:1.5rem;overflow-wrap:anywhere}"
        ".conversion-warnings h2{margin-top:0}.conversion-warnings li{margin:.75rem 0}"
        "</style></head><body>" + content + "</body></html>"
    )


def render_page(
    page: Page, document_status: str | None = None, warnings: tuple[Warning, ...] = ()
) -> str:
    return wrap_html(
        conversion_summary(document_status, warnings, page.number) + page_fragment(page)
    )


def render_pages(document: Document, page_workers: int = 1) -> dict[int, str]:
    """Optional real CPU processes. Submit only one bounded batch at a time."""
    if not 1 <= page_workers <= 4:
        raise ValueError("PAGE_WORKERS_MUST_BE_1_TO_4")
    pages = sorted(document.pages, key=lambda p: p.number)
    if page_workers == 1:
        return {p.number: render_page(p, document.status, document.warnings) for p in pages}
    output: dict[int, str] = {}
    with ProcessPoolExecutor(max_workers=page_workers, mp_context=get_context("spawn")) as pool:
        for start in range(0, len(pages), page_workers):
            batch = pages[start : start + page_workers]
            futures = [
                pool.submit(render_page, p, document.status, document.warnings) for p in batch
            ]
            output.update((p.number, f.result()) for p, f in zip(batch, futures, strict=True))
    return output


def render_document(document: Document) -> str:
    return wrap_html(
        conversion_summary(document.status, document.warnings)
        + "".join(page_fragment(p) for p in sorted(document.pages, key=lambda p: p.number))
    )
