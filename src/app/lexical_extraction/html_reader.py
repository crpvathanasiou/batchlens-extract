"""Reviewed HTML v1 reader and evidence mapping for lexical extraction.

Streams reviewed-HTML export bytes into L01 ``PageRecord`` / ``BlockEvidence``
records. Does not match terms, open SQLite, create files, or publish results.

Memory model for the production ``iter_pages`` path:
- the whole file is not retained as text;
- completed pages are emitted and released (not accumulated);
- retained state is the current page/block builders, a small decode/feed chunk,
  a short completed-page queue, and growing duplicate-identity sets for page
  numbers and node IDs (bounded by distinct IDs in the document, not by file
  size alone).

``data-source-id`` v1 interpretation splits the attribute on ASCII spaces into
ordered OCR references. Original OCR ``block_id`` values that themselves contain
spaces cannot be recovered from the joined attribute; that producer ambiguity is
documented and not silently repaired here.
"""

from __future__ import annotations

import codecs
import hashlib
from collections import deque
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Final

from app.lexical_extraction.configuration import EffectiveExecutionConfiguration
from app.lexical_extraction.contracts import (
    BlockEvidence,
    BlockRecord,
    CellGeometry,
    ConversionStatus,
    OcrReference,
    PageCoverage,
    PageEvidence,
    PageRecord,
    ReviewedHtmlV1Input,
    SafeStructuredError,
)

HTML_CONTRACT_VERSION: Final = 1
HTML_CONTRACT_VERSION_TEXT: Final = "1"
DEFAULT_READ_CHUNK_BYTES: Final = 65_536
_SOURCE_NODE_TAGS: Final = frozenset({"p", "h2", "h3", "h4", "td", "th", "footer"})
_SKIP_TAGS: Final = frozenset({"head", "style", "script", "nav"})
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
_ROOT_PROVENANCE_ATTRS: Final = frozenset(
    {
        "data-review-html-version",
        "data-job-id",
        "data-review-revision-id",
        "data-review-generation",
        "data-conversion-status",
    }
)
_PAGE_PROVENANCE_ATTRS: Final = frozenset({"id", "data-page", "class"})
_NODE_PROVENANCE_ATTRS: Final = frozenset(
    {
        "data-node-id",
        "data-source-id",
        "data-element-id",
        "data-kind",
        "data-table-id",
        "data-row",
        "data-column",
        "data-generated",
        "rowspan",
        "colspan",
        "class",
    }
)


class ReviewedHtmlReadError(Exception):
    """Bounded reviewed-HTML read/validation failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


class ReviewedHtmlReader:
    """Page-oriented streaming reader for one reviewed HTML v1 document.

    ``open_reviewed_html`` opens the file path only. Root producer attributes are
    checked when the ``<html>`` start tag is parsed. A final
    ``ReviewedHtmlV1Input`` (including the SHA-256 of every byte parsed) is
    available only after ``iter_pages`` completes successfully and
    ``completed`` is True. Early iterator close or a late error leaves
    ``completed`` False and must not be treated as a finalized identity.
    """

    def __init__(
        self,
        path: Path,
        *,
        chunk_size: int = DEFAULT_READ_CHUNK_BYTES,
    ) -> None:
        if chunk_size < 1:
            raise ReviewedHtmlReadError("INVALID_ARGUMENT", "chunk_size must be positive")
        self._path = Path(path)
        self._chunk_size = chunk_size
        self._validated_input: ReviewedHtmlV1Input | None = None
        self._completed = False
        self._started = False
        self._failed = False
        self._bytes_consumed = 0

    @property
    def validated_input(self) -> ReviewedHtmlV1Input:
        if not self._completed or self._validated_input is None:
            raise ReviewedHtmlReadError(
                "INPUT_NOT_VALIDATED",
                "final reviewed HTML identity is available only after completed reading",
            )
        return self._validated_input

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def bytes_consumed(self) -> int:
        """Exact byte count hashed/parsed so far (test and progress aid)."""

        return self._bytes_consumed

    def iter_pages(self) -> Iterator[PageRecord]:
        if self._started:
            raise ReviewedHtmlReadError(
                "READER_REENTRY",
                "reviewed HTML pages may be iterated only once per reader",
            )
        self._started = True
        self._completed = False
        self._validated_input = None
        self._bytes_consumed = 0
        try:
            yield from self._stream_pages()
            self._completed = True
        except ReviewedHtmlReadError:
            self._failed = True
            self._completed = False
            self._validated_input = None
            raise
        except Exception as exc:
            self._failed = True
            self._completed = False
            self._validated_input = None
            raise ReviewedHtmlReadError(
                "MALFORMED_HTML",
                "reviewed HTML could not be parsed",
            ) from exc

    def read_all_pages(self) -> tuple[PageRecord, ...]:
        """Small/test convenience: materialize every page. Not the production path."""

        pages = tuple(self.iter_pages())
        if not self._completed:
            raise ReviewedHtmlReadError(
                "READ_INCOMPLETE",
                "page iteration did not complete successfully",
            )
        return pages

    def _stream_pages(self) -> Iterator[PageRecord]:
        completed_pages: deque[PageRecord] = deque()
        parser = _ReviewedHtmlParser(on_page=completed_pages.append)
        decoder = codecs.getincrementaldecoder("utf-8")()
        digest = hashlib.sha256()
        try:
            with self._path.open("rb") as handle:
                while True:
                    chunk = handle.read(self._chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    self._bytes_consumed += len(chunk)
                    try:
                        text = decoder.decode(chunk, final=False)
                    except UnicodeDecodeError as exc:
                        raise ReviewedHtmlReadError(
                            "INVALID_UTF8",
                            "reviewed HTML must be valid UTF-8",
                        ) from exc
                    try:
                        if text:
                            parser.feed(text)
                    except ReviewedHtmlReadError:
                        while completed_pages:
                            yield completed_pages.popleft()
                        raise
                    while completed_pages:
                        yield completed_pages.popleft()
                try:
                    tail = decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise ReviewedHtmlReadError(
                        "INVALID_UTF8",
                        "reviewed HTML must be valid UTF-8",
                    ) from exc
                try:
                    if tail:
                        parser.feed(tail)
                    parser.close()
                    parser.finish()
                except ReviewedHtmlReadError:
                    while completed_pages:
                        yield completed_pages.popleft()
                    raise
                while completed_pages:
                    yield completed_pages.popleft()
        except OSError as exc:
            raise ReviewedHtmlReadError(
                "HTML_READ_FAILED",
                f"cannot read reviewed HTML file: {self._path}",
            ) from exc
        except ReviewedHtmlReadError:
            raise
        root = parser.require_root_fields()
        self._validated_input = ReviewedHtmlV1Input(
            html_sha256=digest.hexdigest(),
            html_contract_version=HTML_CONTRACT_VERSION,
            job_id=root.job_id,
            review_revision_id=root.review_revision_id,
            review_generation=root.review_generation,
            conversion_status=root.conversion_status,
        )


def open_reviewed_html(
    path: Path,
    *,
    chunk_size: int = DEFAULT_READ_CHUNK_BYTES,
) -> ReviewedHtmlReader:
    """Open a reviewed HTML path for bounded page streaming."""

    return ReviewedHtmlReader(Path(path), chunk_size=chunk_size)


def open_reviewed_html_from_configuration(
    config: EffectiveExecutionConfiguration,
    *,
    chunk_size: int = DEFAULT_READ_CHUNK_BYTES,
) -> ReviewedHtmlReader:
    """Open the reviewed HTML path from an effective L02 configuration."""

    return open_reviewed_html(config.input.reviewed_html_path, chunk_size=chunk_size)


def parse_data_source_ids(attribute: str | None) -> tuple[OcrReference, ...]:
    """Split a producer ``data-source-id`` attribute into ordered OCR references.

    V1 joins original block IDs with ASCII spaces. IDs that themselves contain
    spaces are not reversibly recoverable from this attribute alone.
    """

    if attribute is None or attribute == "":
        return ()
    tokens = attribute.split(" ")
    if any(token == "" for token in tokens):
        raise ReviewedHtmlReadError(
            "INVALID_HTML_METADATA",
            "data-source-id contains an empty token",
        )
    return tuple(OcrReference(block_id=token, order=order) for order, token in enumerate(tokens))


class _RootFields:
    __slots__ = (
        "job_id",
        "review_revision_id",
        "review_generation",
        "conversion_status",
    )

    def __init__(
        self,
        *,
        job_id: str,
        review_revision_id: str,
        review_generation: int,
        conversion_status: ConversionStatus,
    ) -> None:
        self.job_id = job_id
        self.review_revision_id = review_revision_id
        self.review_generation = review_generation
        self.conversion_status = conversion_status


class _OpenTag:
    __slots__ = ("tag", "attrs", "generated", "skip")

    def __init__(self, tag: str, attrs: dict[str, str], *, generated: bool, skip: bool) -> None:
        self.tag = tag
        self.attrs = attrs
        self.generated = generated
        self.skip = skip


class _ArticleFrame:
    __slots__ = ("element_id", "kind")

    def __init__(self, element_id: str, kind: str) -> None:
        self.element_id = element_id
        self.kind = kind


class _NodeBuilder:
    __slots__ = ("tag", "attrs", "parts", "article", "table_id")

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        *,
        article: _ArticleFrame | None,
        table_id: str | None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str] = []
        self.article = article
        self.table_id = table_id


class _PageBuilder:
    __slots__ = ("page_number", "order", "blocks")

    def __init__(self, page_number: int, order: int) -> None:
        self.page_number = page_number
        self.order = order
        self.blocks: list[BlockRecord] = []


def _unique_attrs(
    attrs: list[tuple[str, str | None]],
    *,
    provenance_keys: frozenset[str],
    context: str,
) -> dict[str, str]:
    seen: dict[str, str] = {}
    for key, value in attrs:
        if key in seen:
            if key in provenance_keys:
                raise ReviewedHtmlReadError(
                    "DUPLICATE_HTML_ATTRIBUTE",
                    f"duplicate {context} attribute: {key}",
                )
            # Non-provenance duplicates still make producer markup ambiguous.
            raise ReviewedHtmlReadError(
                "DUPLICATE_HTML_ATTRIBUTE",
                f"duplicate {context} attribute: {key}",
            )
        seen[key] = value or ""
    return seen


class _ReviewedHtmlParser(HTMLParser):
    def __init__(self, *, on_page: Callable[[PageRecord], None]) -> None:
        super().__init__(convert_charrefs=True)
        self._on_page = on_page
        self.tag_stack: list[_OpenTag] = []
        self.article_stack: list[_ArticleFrame] = []
        self.table_stack: list[str] = []
        self.current_page: _PageBuilder | None = None
        self.current_node: _NodeBuilder | None = None
        self.seen_page_numbers: set[int] = set()
        self.seen_node_ids: set[str] = set()
        self.generated_depth = 0
        self.skip_depth = 0
        self.document_closed = False
        self.page_order = 0
        self.root_fields: _RootFields | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            attributes = _unique_attrs(
                attrs,
                provenance_keys=_ROOT_PROVENANCE_ATTRS,
                context="root",
            )
            self._capture_root(attributes)
            self.tag_stack.append(_OpenTag(tag, attributes, generated=False, skip=False))
            return

        if self.current_node is not None:
            if tag == "br":
                if self.generated_depth == 0 and self.skip_depth == 0:
                    self.current_node.parts.append("\n")
                return
            if tag in _VOID_TAGS:
                raise ReviewedHtmlReadError(
                    "UNSUPPORTED_SOURCE_ELEMENT",
                    f"unexpected void markup inside source block: {tag}",
                )
            raise ReviewedHtmlReadError(
                "UNSUPPORTED_SOURCE_ELEMENT",
                f"unexpected nested markup inside source block: {tag}",
            )

        if tag == "br":
            return

        provenance = _NODE_PROVENANCE_ATTRS | _PAGE_PROVENANCE_ATTRS
        if tag in _VOID_TAGS:
            void_attrs = _unique_attrs(attrs, provenance_keys=provenance, context=tag)
            if "data-node-id" in void_attrs:
                raise ReviewedHtmlReadError(
                    "UNSUPPORTED_SOURCE_ELEMENT",
                    f"unsupported source-bearing void tag: {tag}",
                )
            return

        attributes = _unique_attrs(attrs, provenance_keys=provenance, context=tag)
        generated = attributes.get("data-generated") == "true"
        skip = tag in _SKIP_TAGS
        entering_generated = generated or self.generated_depth > 0
        entering_skip = skip or self.skip_depth > 0

        self.tag_stack.append(_OpenTag(tag, attributes, generated=generated, skip=skip))
        if generated:
            self.generated_depth += 1
        if skip:
            self.skip_depth += 1

        if entering_generated or entering_skip:
            return

        if "data-node-id" in attributes and self.current_page is None:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "source data-node-id found outside section.page",
            )

        if tag == "section" and "page" in attributes.get("class", "").split():
            self._open_page(attributes)
            return

        if self.current_page is None:
            return

        if tag == "article" and "element" in attributes.get("class", "").split():
            self._open_article(attributes)
            return

        if tag == "table":
            self._open_table(attributes)
            return

        if tag in _SOURCE_NODE_TAGS:
            if not self.article_stack:
                raise ReviewedHtmlReadError(
                    "INVALID_PAGE_STRUCTURE",
                    f"source-bearing {tag} must be inside article.element",
                )
            if "data-node-id" not in attributes:
                raise ReviewedHtmlReadError(
                    "MISSING_STRUCTURAL_PROVENANCE",
                    f"source-bearing {tag} inside article.element requires data-node-id",
                )
            self._open_node(tag, attributes)
            return

        if "data-node-id" in attributes:
            self._open_node(tag, attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or tag == "br":
            return
        if not self.tag_stack:
            raise ReviewedHtmlReadError("MALFORMED_HTML", f"unexpected closing tag: {tag}")
        opened = self.tag_stack.pop()
        if opened.tag != tag:
            raise ReviewedHtmlReadError(
                "MALFORMED_HTML",
                f"mismatched HTML tags: expected {opened.tag}, found {tag}",
            )
        if opened.generated:
            self.generated_depth -= 1
        if opened.skip:
            self.skip_depth -= 1

        if opened.generated or opened.skip or self.generated_depth > 0 or self.skip_depth > 0:
            if tag == "html":
                self.document_closed = True
            return

        if self.current_node is not None and tag == self.current_node.tag:
            self._close_node()
            return

        if tag == "table":
            if not self.table_stack:
                raise ReviewedHtmlReadError("MALFORMED_HTML", "unexpected table close")
            self.table_stack.pop()
            return

        if tag == "article" and self.article_stack:
            if "element" in opened.attrs.get("class", "").split():
                self.article_stack.pop()
            return

        if tag == "section" and self.current_page is not None:
            if "page" in opened.attrs.get("class", "").split():
                self._close_page()
            return

        if tag == "html":
            self.document_closed = True

    def handle_data(self, data: str) -> None:
        if self.generated_depth > 0 or self.skip_depth > 0:
            return
        if self.current_node is not None:
            self.current_node.parts.append(data)
            return
        if self.current_page is not None and self.article_stack and data.strip():
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "bare source text inside article.element requires a data-node-id child",
            )

    def finish(self) -> None:
        if not self.document_closed:
            raise ReviewedHtmlReadError("TRUNCATED_HTML", "reviewed HTML document is truncated")
        if self.generated_depth != 0 or self.skip_depth != 0 or self.tag_stack:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "reviewed HTML nesting is unbalanced")
        if self.current_page is not None or self.current_node is not None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "reviewed HTML nesting is unbalanced")
        if self.root_fields is None:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "root html element with reviewed HTML attributes is required",
            )

    def require_root_fields(self) -> _RootFields:
        if self.root_fields is None:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "root html element with reviewed HTML attributes is required",
            )
        return self.root_fields

    def _capture_root(self, attributes: dict[str, str]) -> None:
        if self.root_fields is not None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "multiple root html elements")
        version = attributes.get("data-review-html-version")
        if version is None:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "data-review-html-version is required",
            )
        if version != HTML_CONTRACT_VERSION_TEXT:
            raise ReviewedHtmlReadError(
                "UNSUPPORTED_HTML_VERSION",
                f"unsupported data-review-html-version: {version!r}",
            )
        try:
            generation_text = attributes["data-review-generation"]
            generation = int(generation_text)
        except KeyError as exc:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "data-review-generation is required",
            ) from exc
        except ValueError as exc:
            raise ReviewedHtmlReadError(
                "INVALID_HTML_METADATA",
                "data-review-generation must be an integer",
            ) from exc
        if generation < 0:
            raise ReviewedHtmlReadError(
                "INVALID_HTML_METADATA",
                "data-review-generation must be non-negative",
            )
        try:
            status = ConversionStatus(attributes["data-conversion-status"])
        except KeyError as exc:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "data-conversion-status is required",
            ) from exc
        except ValueError as exc:
            raise ReviewedHtmlReadError(
                "INVALID_HTML_METADATA",
                "data-conversion-status must be SUCCEEDED or PARTIAL_SUCCESS",
            ) from exc
        try:
            job_id = attributes["data-job-id"]
            revision_id = attributes["data-review-revision-id"]
        except KeyError as exc:
            raise ReviewedHtmlReadError(
                "MISSING_HTML_METADATA",
                "required reviewed HTML producer attributes are missing",
            ) from exc
        if not job_id or not revision_id:
            raise ReviewedHtmlReadError(
                "INVALID_HTML_METADATA",
                "required reviewed HTML producer attributes are invalid",
            )
        self.root_fields = _RootFields(
            job_id=job_id,
            review_revision_id=revision_id,
            review_generation=generation,
            conversion_status=status,
        )

    def _open_page(self, attributes: dict[str, str]) -> None:
        if self.current_page is not None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "nested section.page is not supported")
        raw_page = attributes.get("data-page")
        if raw_page is None or raw_page == "":
            raise ReviewedHtmlReadError(
                "MISSING_STRUCTURAL_PROVENANCE",
                "section.page requires data-page",
            )
        try:
            page_number = int(raw_page)
        except ValueError as exc:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "data-page must be a positive integer",
            ) from exc
        if page_number < 1:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "data-page must be a positive integer",
            )
        expected_id = f"source-page-{page_number}"
        if attributes.get("id") != expected_id:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                f"page id must be {expected_id}",
            )
        if page_number in self.seen_page_numbers:
            raise ReviewedHtmlReadError(
                "DUPLICATE_PAGE",
                f"duplicate physical page number: {page_number}",
            )
        self.seen_page_numbers.add(page_number)
        self.current_page = _PageBuilder(page_number, order=self.page_order)
        self.page_order += 1

    def _close_page(self) -> None:
        if self.current_page is None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "page close without open page")
        if self.current_node is not None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "unclosed source node at page end")
        page = self.current_page
        self.current_page = None
        self._on_page(
            PageRecord(
                page=PageEvidence(
                    page_number=page.page_number,
                    order=page.order,
                    coverage=PageCoverage.COMPLETE,
                ),
                blocks=tuple(page.blocks),
            )
        )

    def _open_article(self, attributes: dict[str, str]) -> None:
        element_id = attributes.get("data-element-id")
        kind = attributes.get("data-kind")
        if not element_id or not kind:
            raise ReviewedHtmlReadError(
                "MISSING_STRUCTURAL_PROVENANCE",
                "article.element requires data-element-id and data-kind",
            )
        self.article_stack.append(_ArticleFrame(element_id, kind))

    def _open_table(self, attributes: dict[str, str]) -> None:
        if not self.article_stack:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "source table must be inside article.element",
            )
        table_id = attributes.get("data-table-id")
        if not table_id:
            raise ReviewedHtmlReadError(
                "MISSING_STRUCTURAL_PROVENANCE",
                "source table requires data-table-id",
            )
        owner_id = self.article_stack[-1].element_id
        if table_id != owner_id:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "data-table-id must equal owning article data-element-id",
            )
        self.table_stack.append(table_id)

    def _open_node(self, tag: str, attributes: dict[str, str]) -> None:
        if self.current_page is None:
            raise ReviewedHtmlReadError(
                "INVALID_PAGE_STRUCTURE",
                "source node found outside section.page",
            )
        if self.current_node is not None:
            raise ReviewedHtmlReadError(
                "UNSUPPORTED_SOURCE_ELEMENT",
                "nested data-node-id elements are not supported",
            )
        if tag not in _SOURCE_NODE_TAGS:
            raise ReviewedHtmlReadError(
                "UNSUPPORTED_SOURCE_ELEMENT",
                f"unsupported source-bearing tag: {tag}",
            )
        node_id = attributes.get("data-node-id")
        if not node_id:
            raise ReviewedHtmlReadError(
                "MISSING_STRUCTURAL_PROVENANCE",
                "data-node-id must be nonempty",
            )
        if node_id in self.seen_node_ids:
            raise ReviewedHtmlReadError(
                "DUPLICATE_NODE_ID",
                f"duplicate data-node-id: {node_id}",
            )
        article = self.article_stack[-1] if self.article_stack else None
        table_id = self.table_stack[-1] if self.table_stack else None
        if tag in {"td", "th"}:
            if table_id is None:
                raise ReviewedHtmlReadError(
                    "MISSING_STRUCTURAL_PROVENANCE",
                    "table cells require an enclosing data-table-id",
                )
            for required in ("data-row", "data-column", "rowspan", "colspan"):
                if required not in attributes or attributes[required] == "":
                    raise ReviewedHtmlReadError(
                        "MISSING_STRUCTURAL_PROVENANCE",
                        f"table cell requires {required}",
                    )
        self.seen_node_ids.add(node_id)
        self.current_node = _NodeBuilder(
            tag,
            attributes,
            article=article,
            table_id=table_id,
        )

    def _close_node(self) -> None:
        if self.current_node is None or self.current_page is None:
            raise ReviewedHtmlReadError("MALFORMED_HTML", "source node close without open node")
        builder = self.current_node
        self.current_node = None
        text = "".join(builder.parts)
        kind = _map_block_kind(builder.tag, builder.attrs, builder.article)
        element_id = builder.article.element_id if builder.article is not None else None
        table_id = builder.table_id if builder.tag in {"td", "th"} else None
        geometry = _cell_geometry(builder.attrs) if builder.tag in {"td", "th"} else None
        try:
            ocr_references = parse_data_source_ids(builder.attrs.get("data-source-id"))
        except ReviewedHtmlReadError:
            raise
        except Exception as exc:
            raise ReviewedHtmlReadError(
                "INVALID_HTML_METADATA",
                "data-source-id could not be interpreted",
            ) from exc
        block = BlockEvidence(
            node_id=builder.attrs["data-node-id"],
            kind=kind,
            text=text,
            page_number=self.current_page.page_number,
            order=len(self.current_page.blocks),
            element_id=element_id,
            table_id=table_id,
            cell_geometry=geometry,
            ocr_references=ocr_references,
        )
        self.current_page.blocks.append(BlockRecord(block=block, occurrences=()))


def _map_block_kind(tag: str, attrs: dict[str, str], article: _ArticleFrame | None) -> str:
    if tag in {"td", "th"}:
        return "TABLE_CELL"
    if tag == "footer":
        return "FOOTER"
    node_id = attrs["data-node-id"]
    if article is not None and node_id == article.element_id:
        return article.kind
    if tag in {"h2", "h3", "h4", "p"}:
        return "TITLE"
    raise ReviewedHtmlReadError(
        "UNSUPPORTED_SOURCE_ELEMENT",
        f"cannot map source tag to block kind: {tag}",
    )


def _cell_geometry(attrs: dict[str, str]) -> CellGeometry:
    try:
        return CellGeometry(
            row=int(attrs["data-row"]),
            column=int(attrs["data-column"]),
            row_span=int(attrs["rowspan"]),
            column_span=int(attrs["colspan"]),
        )
    except (KeyError, ValueError) as exc:
        raise ReviewedHtmlReadError(
            "INVALID_PAGE_STRUCTURE",
            "table cell geometry attributes are invalid",
        ) from exc
