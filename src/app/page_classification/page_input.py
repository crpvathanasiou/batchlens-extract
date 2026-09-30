"""Prepare a reviewed-HTML document once, then derive and look up page inputs.

Uses the existing reviewed-HTML v1 reader for complete-document validation.
Page fragments, readable text, and HTML-id maps are derived from the same
validated document bytes. Subsequent page selection does not revalidate.
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
    )

    def __init__(
        self,
        *,
        page_number: int,
        page_html_id: str,
        fragment: str,
        readable_text: str,
        element_text_by_id: dict[str, str],
    ) -> None:
        self.page_number = page_number
        self.page_html_id = page_html_id
        self.fragment = fragment
        self.readable_text = readable_text
        self.element_text_by_id = element_text_by_id


class _PageContentExtractor(HTMLParser):
    """Build readable page text, HTML-id maps, and exact section.page source spans.

    Entity references are preserved in readable text so evidence normalization
    performs exactly one decode pass later. Fragments are sliced from the
    original source using parser positions for the recognized section.page tags.
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
        self._id_stack: list[str | None] = []
        self._id_parts: dict[str, list[str]] = {}
        self._seen_ids: set[str] = set()
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
        if self._id_stack:
            self._id_stack.pop()
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
        self._id_stack = []
        self._id_parts = {}
        self._seen_ids = set()
        self._pending_separator = False
        self._pending_cell_space = False
        self._register_id(page_id)
        self._id_stack.append(page_id)

    def _enter_tag(self, tag: str, attr_map: dict[str, str]) -> None:
        if tag == "section":
            self._section_depth += 1
        if tag in _SKIP_READABLE_TAGS:
            self._skip_depth += 1
        element_id = attr_map.get("id") or None
        if element_id is not None:
            self._register_id(element_id)
        if tag not in _VOID_TAGS:
            self._id_stack.append(element_id)
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

    def _register_id(self, element_id: str) -> None:
        if element_id in self._seen_ids:
            self.error = PageInputError(
                "DUPLICATE_HTML_ID",
                f"duplicate HTML id on prepared page: {element_id}",
            )
            return
        self._seen_ids.add(element_id)
        self._id_parts.setdefault(element_id, [])

    def _active_ids(self) -> list[str]:
        return [item for item in self._id_stack if item is not None]

    def _append_raw(self, chunk: str) -> None:
        self._readable_parts.append(chunk)
        for active_id in self._active_ids():
            self._id_parts[active_id].append(chunk)

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
        self.pages.append(
            _ExtractedPage(
                page_number=self._page_number,
                page_html_id=self._page_html_id,
                fragment=fragment,
                readable_text="".join(self._readable_parts),
                element_text_by_id={
                    element_id: "".join(parts) for element_id, parts in self._id_parts.items()
                },
            )
        )
        self._capturing = False
        self._section_depth = 0
        self._page_number = None
        self._page_html_id = None
        self._start_offset = None
        self._readable_parts = []
        self._id_stack = []
        self._id_parts = {}
        self._seen_ids = set()


__all__ = [
    "PageInputError",
    "get_prepared_page",
    "normalize_evidence_text",
    "prepare_reviewed_document",
]
