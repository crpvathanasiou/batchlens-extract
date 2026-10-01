"""Prepare a reviewed-HTML document once, then derive and look up page inputs.

Uses the existing reviewed-HTML v1 reader for complete-document validation.
Page fragments, readable text, and page-local identifier maps are derived from
the same validated document bytes. Subsequent page selection does not
revalidate.
"""

from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Final

from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.lexical_extraction.html_reader import open_reviewed_html
from app.page_classification.contracts import (
    PageInputBinding,
    PreparedDocument,
    PreparedPageInput,
)

_SKIP_READABLE_TAGS: Final = frozenset({"script", "style"})
_VOID_TAGS: Final = frozenset(
    {
        "br",
        "meta",
        "link",
        "img",
        "input",
        "hr",
        "area",
        "base",
        "col",
        "embed",
        "source",
        "wbr",
    }
)
_BLOCK_SEPARATOR_TAGS: Final = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "ul",
        "ol",
        "br",
    }
)
_CELL_TAGS: Final = frozenset({"td", "th"})
_WHITESPACE_RE: Final = re.compile(r"\s+")
_SUPPORTED_IDENTIFIER_ATTRS: Final = (
    "id",
    "data-node-id",
    "data-element-id",
    "data-table-id",
)


class PageInputError(Exception):
    """Deterministic page-input preparation or lookup failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def prepare_reviewed_document(
    path: Path,
    *,
    expected: ReviewedHtmlV1Input | None = None,
) -> PreparedDocument:
    """Validate one reviewed-HTML document once and derive all prepared pages.

    Completes the existing reviewed-HTML v1 validation path before returning.
    Does not persist temporary results or invent page identities.
    """

    resolved = Path(path)
    reader = open_reviewed_html(resolved)
    for _page in reader.iter_pages():
        pass
    if not reader.completed:
        raise PageInputError(
            "READ_INCOMPLETE",
            "reviewed HTML validation did not complete successfully",
        )
    validated = reader.validated_input
    document_bytes = resolved.read_bytes()
    digest = hashlib.sha256(document_bytes).hexdigest()
    if digest != validated.html_sha256:
        raise PageInputError(
            "HTML_HASH_MISMATCH",
            "validated HTML identity does not match the prepared document bytes",
        )
    if expected is not None and validated != expected:
        raise PageInputError(
            "PROVENANCE_MISMATCH",
            "reviewed-document provenance does not match the expected identity",
        )

    html_text = document_bytes.decode("utf-8")
    pages = _derive_prepared_pages(html_text, validated)
    return PreparedDocument(reviewed_html=validated, pages=pages)


def get_prepared_page(document: PreparedDocument, page_number: int) -> PreparedPageInput:
    """Select one already-prepared page by its existing page number."""

    if page_number < 1:
        raise PageInputError("INVALID_PAGE_NUMBER", "page_number must be a positive integer")
    matches = [page for page in document.pages if page.binding.page_number == page_number]
    if not matches:
        raise PageInputError("PAGE_NOT_FOUND", f"prepared page not found: {page_number}")
    if len(matches) > 1:
        raise PageInputError(
            "AMBIGUOUS_PAGE_IDENTITY",
            f"ambiguous prepared page identity: {page_number}",
        )
    return matches[0]


def normalize_evidence_text(value: str) -> str:
    """Apply exactly one HTML-entity decode, then collapse whitespace.

    Prepared page/element text is stored without prior entity decoding, so the
    same helper is used for page text, element text, and quote text.
    """

    return _collapse_whitespace(html.unescape(value))


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _derive_prepared_pages(
    html_text: str,
    validated: ReviewedHtmlV1Input,
) -> tuple[PreparedPageInput, ...]:
    extractor = _PageContentExtractor(html_text)
    extractor.feed(html_text)
    extractor.close()
    if extractor.error is not None:
        raise extractor.error
    if not extractor.pages:
        raise PageInputError("NO_PAGES", "reviewed HTML contains no section.page elements")

    prepared: list[PreparedPageInput] = []
    seen_numbers: set[int] = set()
    seen_html_ids: set[str] = set()
    for page in extractor.pages:
        if page.page_number in seen_numbers:
            raise PageInputError(
                "AMBIGUOUS_PAGE_IDENTITY",
                f"duplicate page number in prepared document: {page.page_number}",
            )
        if page.page_html_id in seen_html_ids:
            raise PageInputError(
                "AMBIGUOUS_PAGE_IDENTITY",
                f"duplicate page HTML id in prepared document: {page.page_html_id}",
            )
        seen_numbers.add(page.page_number)
        seen_html_ids.add(page.page_html_id)
        binding = PageInputBinding(
            reviewed_html=validated,
            page_number=page.page_number,
            page_html_id=page.page_html_id,
        )
        prepared.append(
            PreparedPageInput(
                binding=binding,
                page_html_fragment=page.fragment,
                readable_text=page.readable_text,
                element_text_by_id=dict(page.element_text_by_id),
                ambiguous_element_ids=frozenset(page.ambiguous_element_ids),
            )
        )
    return tuple(prepared)


def _source_offset(source: str, line: int, column: int) -> int:
    if line < 1:
        return 0
    offset = 0
    current_line = 1
    while current_line < line:
        next_break = source.find("\n", offset)
        if next_break < 0:
            return len(source)
        offset = next_break + 1
        current_line += 1
    return min(len(source), offset + column)


def _end_tag_exclusive_offset(source: str, end_tag_start: int) -> int:
    closer = source.find(">", end_tag_start)
    if closer < 0:
        raise PageInputError(
            "MALFORMED_PAGE",
            "could not locate end of section.page closing tag",
        )
    return closer + 1


class _ExtractedPage:
    __slots__ = (
        "page_number",
        "page_html_id",
        "fragment",
        "readable_text",
        "element_text_by_id",
        "ambiguous_element_ids",
    )

    def __init__(
        self,
        *,
        page_number: int,
        page_html_id: str,
        fragment: str,
        readable_text: str,
        element_text_by_id: dict[str, str],
        ambiguous_element_ids: frozenset[str],
    ) -> None:
        self.page_number = page_number
        self.page_html_id = page_html_id
        self.fragment = fragment
        self.readable_text = readable_text
        self.element_text_by_id = element_text_by_id
        self.ambiguous_element_ids = ambiguous_element_ids


class _IdentifiedElement:
    """One DOM element that carries at least one supported identifier attribute."""

    __slots__ = ("node_id", "parent_node_id", "values", "is_article_wrapper", "parts")

    def __init__(
        self,
        *,
        node_id: int,
        parent_node_id: int | None,
        values: frozenset[str],
        is_article_wrapper: bool,
    ) -> None:
        self.node_id = node_id
        self.parent_node_id = parent_node_id
        self.values = values
        self.is_article_wrapper = is_article_wrapper
        self.parts: list[str] = []


def _identifier_values(attr_map: dict[str, str]) -> frozenset[str]:
    return frozenset(
        value for attr in _SUPPORTED_IDENTIFIER_ATTRS if (value := attr_map.get(attr, "")) != ""
    )


def _is_article_wrapper(tag: str, attr_map: dict[str, str]) -> bool:
    return tag == "article" and "element" in attr_map.get("class", "").split()


def _is_wrapper_content_pair(first: _IdentifiedElement, second: _IdentifiedElement) -> bool:
    if first.is_article_wrapper and not second.is_article_wrapper:
        return second.parent_node_id == first.node_id
    if second.is_article_wrapper and not first.is_article_wrapper:
        return first.parent_node_id == second.node_id
    return False


def _resolve_identifier_maps(
    identified: dict[int, _IdentifiedElement],
) -> tuple[dict[str, str], frozenset[str]]:
    by_value: dict[str, list[_IdentifiedElement]] = {}
    for element in identified.values():
        for value in element.values:
            by_value.setdefault(value, []).append(element)

    resolved: dict[str, str] = {}
    ambiguous: set[str] = set()
    for value, elements in by_value.items():
        if len(elements) == 1:
            resolved[value] = "".join(elements[0].parts)
            continue
        if len(elements) == 2 and _is_wrapper_content_pair(elements[0], elements[1]):
            wrapper = elements[0] if elements[0].is_article_wrapper else elements[1]
            resolved[value] = "".join(wrapper.parts)
            continue
        ambiguous.add(value)
    return resolved, frozenset(ambiguous)


class _PageContentExtractor(HTMLParser):
    """Build readable page text, identifier maps, and exact section.page source spans.

    Entity references are preserved in readable text so evidence normalization
    performs exactly one decode pass later. Fragments are sliced from the
    original source using parser positions for the recognized section.page tags.
    Identifier lookup accepts exact values from id, data-node-id,
    data-element-id, and data-table-id without failing the page on duplicates.
    """

    def __init__(self, source: str) -> None:
        # Keep entities intact in handle_data / handle_*ref so callers can apply
        # exactly one html.unescape during evidence normalization.
        super().__init__(convert_charrefs=False)
        self._source = source
        self.pages: list[_ExtractedPage] = []
        self.error: PageInputError | None = None
        self._capturing = False
        self._section_depth = 0
        self._page_number: int | None = None
        self._page_html_id: str | None = None
        self._start_offset: int | None = None
        self._readable_parts: list[str] = []
        self._skip_depth = 0
        self._next_node_id = 0
        self._open_nodes: list[tuple[int, _IdentifiedElement | None]] = []
        self._identified: dict[int, _IdentifiedElement] = {}
        self._pending_separator = False
        self._pending_cell_space = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.error is not None:
            return
        attr_map = {key: ("" if value is None else value) for key, value in attrs}
        if not self._capturing:
            if tag == "section" and "page" in attr_map.get("class", "").split():
                self._open_page(attr_map)
            return
        self._enter_tag(tag, attr_map)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.handle_starttag(tag, attrs)
            return
        if tag in _VOID_TAGS:
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.error is not None or not self._capturing:
            return
        if tag in _VOID_TAGS:
            return
        if tag in _SKIP_READABLE_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._open_nodes:
            self._open_nodes.pop()
        if tag in _BLOCK_SEPARATOR_TAGS:
            self._pending_separator = True
            self._pending_cell_space = False
        if tag == "section":
            self._section_depth -= 1
            if self._section_depth <= 0:
                self._close_page()

    def handle_data(self, data: str) -> None:
        if self.error is not None or not self._capturing or self._skip_depth > 0:
            return
        if not data:
            return
        self._emit_text(data)

    def handle_entityref(self, name: str) -> None:
        if self.error is not None or not self._capturing or self._skip_depth > 0:
            return
        self._emit_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.error is not None or not self._capturing or self._skip_depth > 0:
            return
        self._emit_text(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def _open_page(self, attr_map: dict[str, str]) -> None:
        raw_page = attr_map.get("data-page", "")
        page_id = attr_map.get("id", "")
        if not raw_page:
            self.error = PageInputError(
                "MISSING_PAGE_NUMBER",
                "section.page requires data-page",
            )
            return
        try:
            page_number = int(raw_page)
        except ValueError:
            self.error = PageInputError(
                "INVALID_PAGE_NUMBER",
                "data-page must be a positive integer",
            )
            return
        if page_number < 1:
            self.error = PageInputError(
                "INVALID_PAGE_NUMBER",
                "data-page must be a positive integer",
            )
            return
        if not page_id:
            self.error = PageInputError(
                "MISSING_PAGE_HTML_ID",
                "section.page requires an HTML id",
            )
            return
        line, column = self.getpos()
        self._capturing = True
        self._section_depth = 1
        self._page_number = page_number
        self._page_html_id = page_id
        self._start_offset = _source_offset(self._source, line, column)
        self._readable_parts = []
        self._skip_depth = 0
        self._next_node_id = 0
        self._open_nodes = []
        self._identified = {}
        self._pending_separator = False
        self._pending_cell_space = False
        self._push_element("section", attr_map)

    def _enter_tag(self, tag: str, attr_map: dict[str, str]) -> None:
        if tag == "section":
            self._section_depth += 1
        if tag in _SKIP_READABLE_TAGS:
            self._skip_depth += 1
        if tag not in _VOID_TAGS:
            self._push_element(tag, attr_map)
        if self._skip_depth > 0:
            return
        if tag == "br":
            self._append_raw("\n")
            self._pending_separator = False
            self._pending_cell_space = False
            return
        if tag in _CELL_TAGS:
            self._pending_cell_space = True
            return
        if tag in _BLOCK_SEPARATOR_TAGS:
            self._pending_separator = True
            self._pending_cell_space = False

    def _push_element(self, tag: str, attr_map: dict[str, str]) -> None:
        parent_node_id = self._open_nodes[-1][0] if self._open_nodes else None
        values = _identifier_values(attr_map)
        node_id = self._alloc_node_id()
        identified: _IdentifiedElement | None = None
        if values:
            identified = _IdentifiedElement(
                node_id=node_id,
                parent_node_id=parent_node_id,
                values=values,
                is_article_wrapper=_is_article_wrapper(tag, attr_map),
            )
            self._identified[node_id] = identified
        self._open_nodes.append((node_id, identified))

    def _alloc_node_id(self) -> int:
        node_id = self._next_node_id
        self._next_node_id += 1
        return node_id

    def _append_raw(self, chunk: str) -> None:
        self._readable_parts.append(chunk)
        for _node_id, identified in self._open_nodes:
            if identified is not None:
                identified.parts.append(chunk)

    def _emit_text(self, data: str) -> None:
        prefix = ""
        if self._pending_separator and self._readable_parts:
            prefix = "\n"
        elif self._pending_cell_space and self._readable_parts:
            prefix = " "
        self._pending_separator = False
        self._pending_cell_space = False
        self._append_raw(f"{prefix}{data}")

    def _close_page(self) -> None:
        if self._page_number is None or self._page_html_id is None or self._start_offset is None:
            self.error = PageInputError("MALFORMED_PAGE", "page close without open page")
            self._capturing = False
            return
        line, column = self.getpos()
        end_tag_start = _source_offset(self._source, line, column)
        try:
            end_offset = _end_tag_exclusive_offset(self._source, end_tag_start)
        except PageInputError as exc:
            self.error = exc
            self._capturing = False
            return
        fragment = self._source[self._start_offset : end_offset]
        element_text_by_id, ambiguous_element_ids = _resolve_identifier_maps(self._identified)
        self.pages.append(
            _ExtractedPage(
                page_number=self._page_number,
                page_html_id=self._page_html_id,
                fragment=fragment,
                readable_text="".join(self._readable_parts),
                element_text_by_id=element_text_by_id,
                ambiguous_element_ids=ambiguous_element_ids,
            )
        )
        self._capturing = False
        self._section_depth = 0
        self._page_number = None
        self._page_html_id = None
        self._start_offset = None
        self._readable_parts = []
        self._open_nodes = []
        self._identified = {}


__all__ = [
    "PageInputError",
    "get_prepared_page",
    "normalize_evidence_text",
    "prepare_reviewed_document",
]
