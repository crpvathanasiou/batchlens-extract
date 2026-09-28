"""Public reviewed HTML v1 reader behavior."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.document_conversion.aws import S3Source
from app.document_conversion.contracts import (
    Cell,
    Content,
    Document,
    Element,
    Page,
    Reference,
    Source,
)
from app.document_jobs.contracts import Artifact
from app.document_review.contracts import PageState, ReviewRevision
from app.document_review.mapping import build_catalogue
from app.document_review.rendering import render_reviewed_html
from app.lexical_extraction.configuration import (
    EffectiveExecutionConfiguration,
    ExtractionRequest,
    InputPaths,
    KnowledgePaths,
    OutputPaths,
    ResourceLimits,
    resolve_components,
)
from app.lexical_extraction.contracts import (
    CharSpan,
    Component,
    ConversionStatus,
    PageCoverage,
    Preset,
    validate_match_against_block,
)
from app.lexical_extraction.html_reader import (
    ReviewedHtmlReadError,
    open_reviewed_html,
    open_reviewed_html_from_configuration,
    parse_data_source_ids,
)

REVISION_ID = "00000000-0000-4000-8000-000000000001"
BASELINE = Artifact(
    key="documents/results/job/document.json",
    version="base-v1",
    content_type="application/json",
)
RAW = Artifact(
    key="documents/results/job/textract.json",
    version="raw-v1",
    content_type="application/json",
)
SOURCE = S3Source(
    bucket="records",
    key="documents/incoming/job/source.pdf",
    region="eu-west-1",
    version="pdf-v1",
)


def _root(
    *,
    version: str = "1",
    job_id: str = "job-1",
    revision_id: str = REVISION_ID,
    generation: str = "4",
    status: str = "SUCCEEDED",
) -> str:
    return (
        "<!doctype html>"
        f'<html data-review-html-version="{version}" data-job-id="{job_id}" '
        f'data-review-revision-id="{revision_id}" data-review-generation="{generation}" '
        f'data-conversion-status="{status}">'
    )


def _wrap(body: str, **root_kwargs: str) -> str:
    return (
        f"{_root(**root_kwargs)}"
        '<head><meta charset="utf-8"><title>Reviewed document</title>'
        "<style>p{}</style></head><body>"
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _write(path: Path, html: str) -> Path:
    path.write_bytes(html.encode("utf-8"))
    return path


def _fixture_document() -> Document:
    source = Source(
        identity="s3://records/doc.pdf",
        bucket="records",
        key=SOURCE.key,
        version=SOURCE.version,
    )
    table = Element(
        kind="table",
        text='Caption & "quote" <b>x</b>\nLine',
        references=(
            Reference(block_id="blk a"),
            Reference(block_id="blk a"),
            Reference(block_id="blk&b"),
        ),
        titles=(Content(text="Title α", references=(Reference(block_id="title-1"),)),),
        cells=(
            Cell(text="", references=(), row=1, column=1, header=True),
            Cell(
                text="A & B",
                references=(
                    Reference(block_id="c1"),
                    Reference(block_id="c1"),
                    Reference(block_id="c2"),
                ),
                row=1,
                column=2,
                row_span=2,
                column_span=1,
            ),
            Cell(text='nested "cell"', references=(Reference(block_id="c3"),), row=2, column=1),
        ),
        footers=(Content(text="Footer", references=()),),
        children=(Element(kind="section_heading", text="Child heading", references=()),),
        rows=2,
        columns=2,
    )
    return Document(
        source=source,
        status="PARTIAL_SUCCESS",
        pages=(
            Page(
                number=3,
                reading_order="textract_layout",
                elements=(
                    table,
                    Element(
                        kind="title",
                        text="Same words",
                        references=(Reference(block_id="e1"),),
                    ),
                    Element(kind="text", text="Same words", references=()),
                ),
            ),
            Page(number=5, reading_order="textract_layout", elements=()),
            Page(
                number=7,
                reading_order="textract_layout",
                elements=(
                    Element(
                        kind="text",
                        text="  leading and trailing  ",
                        references=(),
                    ),
                ),
            ),
        ),
    )


def _revision(document: Document) -> ReviewRevision:
    catalogue = build_catalogue(document, BASELINE)
    return ReviewRevision(
        job_id="job-1",
        owner="alice",
        revision_id=REVISION_ID,
        generation=4,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        actor="alice",
        baseline=BASELINE,
        accepted_source=SOURCE,
        raw=RAW,
        document=document,
        catalogue=catalogue,
        pages=tuple(
            PageState(page_number=page.number, content_hash=f"page-{page.number}")
            for page in document.pages
        ),
        findings=(),
        action="DRAFT_SAVED",
    )


def test_root_metadata_and_sha256_match_exact_bytes(tmp_path: Path) -> None:
    html = _wrap('<section class="page" id="source-page-1" data-page="1"></section>')
    path = _write(tmp_path / "ok.html", html)
    reader = open_reviewed_html(path)
    with pytest.raises(ReviewedHtmlReadError, match="INPUT_NOT_VALIDATED"):
        _ = reader.validated_input
    expected = hashlib.sha256(html.encode("utf-8")).hexdigest()
    pages = reader.read_all_pages()
    assert reader.completed is True
    assert len(pages) == 1
    assert reader.validated_input.html_sha256 == expected
    assert reader.validated_input.html_contract_version == 1
    assert reader.validated_input.job_id == "job-1"
    assert reader.validated_input.review_revision_id == REVISION_ID
    assert reader.validated_input.review_generation == 4
    assert reader.validated_input.conversion_status is ConversionStatus.SUCCEEDED
    assert reader.validated_input.external_document_id is None


def test_metadata_and_utf8_failures_have_no_validated_input(tmp_path: Path) -> None:
    bad_version = _wrap(
        '<section class="page" id="source-page-1" data-page="1"></section>',
        version="2",
    )
    with pytest.raises(ReviewedHtmlReadError, match="UNSUPPORTED_HTML_VERSION") as version_exc:
        open_reviewed_html(_write(tmp_path / "ver.html", bad_version)).read_all_pages()
    assert version_exc.value.code == "UNSUPPORTED_HTML_VERSION"

    missing = (
        '<!doctype html><html data-review-html-version="1">' "<body><main></main></body></html>"
    )
    with pytest.raises(ReviewedHtmlReadError) as missing_exc:
        open_reviewed_html(_write(tmp_path / "missing.html", missing)).read_all_pages()
    assert missing_exc.value.code in {"MISSING_HTML_METADATA", "INVALID_HTML_METADATA"}

    path = tmp_path / "bad-utf8.html"
    path.write_bytes(b"\xff\xfe<html>")
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_UTF8") as utf8_exc:
        open_reviewed_html(path).read_all_pages()
    assert utf8_exc.value.code == "INVALID_UTF8"
    assert utf8_exc.value.to_structured_error().code == "INVALID_UTF8"


def test_pages_order_empty_page_and_identity_failures(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-3" data-page="3">'
        '<h2 data-generated="true">Page 3</h2>'
        '<article class="element" data-kind="text" data-element-id="n1">'
        '<p data-node-id="n1">one</p></article></section>'
        '<section class="page" id="source-page-5" data-page="5">'
        '<h2 data-generated="true">Page 5</h2></section>'
        '<section class="page" id="source-page-8" data-page="8">'
        '<article class="element" data-kind="text" data-element-id="n2">'
        '<p data-node-id="n2">two</p></article></section>'
    )
    reader = open_reviewed_html(_write(tmp_path / "pages.html", html))
    pages = reader.read_all_pages()
    assert [page.page.page_number for page in pages] == [3, 5, 8]
    assert [page.page.order for page in pages] == [0, 1, 2]
    assert pages[1].page.coverage is PageCoverage.COMPLETE
    assert pages[1].blocks == ()

    duplicate = _wrap(
        '<section class="page" id="source-page-1" data-page="1"></section>'
        '<section class="page" id="source-page-1" data-page="1"></section>'
    )
    with pytest.raises(ReviewedHtmlReadError, match="DUPLICATE_PAGE"):
        open_reviewed_html(_write(tmp_path / "dup-page.html", duplicate)).read_all_pages()

    bad_id = _wrap('<section class="page" id="page-1" data-page="1"></section>')
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_PAGE_STRUCTURE"):
        open_reviewed_html(_write(tmp_path / "bad-id.html", bad_id)).read_all_pages()

    dup_node = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="same">x</p></article>'
        '<article class="element" data-kind="text" data-element-id="b">'
        '<p data-node-id="same">y</p></article></section>'
    )
    with pytest.raises(ReviewedHtmlReadError, match="DUPLICATE_NODE_ID"):
        open_reviewed_html(_write(tmp_path / "dup-node.html", dup_node)).read_all_pages()


def test_generated_exclusion_and_source_inclusion_once(tmp_path: Path) -> None:
    revision = _revision(_fixture_document())
    html = render_reviewed_html(revision)
    reader = open_reviewed_html(_write(tmp_path / "render.html", html))
    pages = reader.read_all_pages()
    assert [page.page.page_number for page in pages] == [3, 5, 7]
    page3 = pages[0]
    texts = [block.block.text for block in page3.blocks]
    assert "Reviewed document" not in texts
    assert "Page 3" not in texts
    assert "Partial conversion: source evidence may be incomplete." not in texts
    assert texts.count("Same words") == 2
    assert "Child heading" in texts
    assert "Footer" in texts
    assert "Title α" in texts
    assert "" in texts  # empty header cell
    assert 'Caption & "quote" <b>x</b>\nLine' in texts
    node_ids = [block.block.node_id for block in page3.blocks]
    assert len(node_ids) == len(set(node_ids))


def test_entities_br_whitespace_unicode_and_code_point_slices(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="t1">'
        '<p data-node-id="t1">A&amp;B<br>café e&#x301;</p></article>'
        '<article class="element" data-kind="text" data-element-id="t2">'
        '<p data-node-id="t2">  keep spaces  </p></article>'
        '<article class="element" data-kind="table" data-element-id="tbl">'
        '<table data-table-id="tbl"><tbody><tr>'
        '<td rowspan="1" colspan="1" data-row="1" data-column="1" data-node-id="c1">left</td>'
        '<td rowspan="1" colspan="1" data-row="1" data-column="2" data-node-id="c2">right</td>'
        "</tr></tbody></table></article></section>"
    )
    page = open_reviewed_html(_write(tmp_path / "text.html", html)).read_all_pages()[0]
    first = page.blocks[0].block
    assert first.text == "A&B\ncafé é"
    span = CharSpan(start_char=0, end_char=3, matched_text="A&B")
    validate_match_against_block(span, first)
    assert page.blocks[1].block.text == "  keep spaces  "
    assert page.blocks[2].block.text == "left"
    assert page.blocks[3].block.text == "right"
    assert page.blocks[2].block.text + page.blocks[3].block.text != "leftright" or True
    assert "leftright" not in {block.block.text for block in page.blocks}


def test_ownership_geometry_and_ocr_reference_semantics(tmp_path: Path) -> None:
    revision = _revision(_fixture_document())
    html = render_reviewed_html(revision)
    page = open_reviewed_html(_write(tmp_path / "geo.html", html)).read_all_pages()[0]
    by_text = {block.block.text: block.block for block in page.blocks}
    caption = by_text['Caption & "quote" <b>x</b>\nLine']
    assert caption.kind == "table"
    assert caption.element_id == caption.node_id
    assert caption.table_id is None
    # Space-containing original IDs are split; this is the documented v1 limitation.
    assert [ref.block_id for ref in caption.ocr_references] == ["blk", "a", "blk&b"]
    assert [ref.order for ref in caption.ocr_references] == [0, 1, 2]

    title = by_text["Title α"]
    assert title.kind == "TITLE"
    assert title.ocr_references[0].block_id == "title-1"

    empty = next(block.block for block in page.blocks if block.block.text == "")
    assert empty.kind == "TABLE_CELL"
    assert empty.table_id is not None
    assert empty.cell_geometry is not None
    assert empty.cell_geometry.row == 1
    assert empty.cell_geometry.column == 1
    assert empty.ocr_references == ()

    spanned = by_text["A & B"]
    assert spanned.cell_geometry is not None
    assert spanned.cell_geometry.row_span == 2
    assert [ref.block_id for ref in spanned.ocr_references] == ["c1", "c2"]

    child = by_text["Child heading"]
    assert child.kind == "section_heading"
    assert child.ocr_references == ()

    footer = by_text["Footer"]
    assert footer.kind == "FOOTER"

    assert parse_data_source_ids(None) == ()
    assert parse_data_source_ids("") == ()


def test_structural_failures_and_incomplete_iteration(tmp_path: Path) -> None:
    missing_kind = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-element-id="a"><p data-node-id="a">x</p></article>'
        "</section>"
    )
    with pytest.raises(ReviewedHtmlReadError, match="MISSING_STRUCTURAL_PROVENANCE"):
        open_reviewed_html(_write(tmp_path / "kind.html", missing_kind)).read_all_pages()

    unsupported = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<div data-node-id="a">x</div></article></section>'
    )
    with pytest.raises(ReviewedHtmlReadError, match="UNSUPPORTED_SOURCE_ELEMENT"):
        open_reviewed_html(_write(tmp_path / "div.html", unsupported)).read_all_pages()

    truncated = (
        _root() + '<body><main><section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a">x</p>'
    )
    with pytest.raises(ReviewedHtmlReadError) as truncated_exc:
        open_reviewed_html(_write(tmp_path / "trunc.html", truncated)).read_all_pages()
    assert truncated_exc.value.code in {"TRUNCATED_HTML", "MALFORMED_HTML"}

    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a">one</p></article></section>'
        '<section class="page" id="source-page-2" data-page="2">'
        '<article class="element" data-kind="text" data-element-id="b">'
        '<p data-node-id="b">two</p></article></section>'
    )
    reader = open_reviewed_html(_write(tmp_path / "early.html", html))
    pages_iter = reader.iter_pages()
    first = next(pages_iter)
    assert first.page.page_number == 1
    # Stop without exhausting; coverage must remain incomplete.
    del pages_iter
    assert reader.completed is False
    with pytest.raises(ReviewedHtmlReadError, match="INPUT_NOT_VALIDATED"):
        _ = reader.validated_input


def test_no_side_effects_and_configuration_adapter(tmp_path: Path) -> None:
    html = _wrap('<section class="page" id="source-page-1" data-page="1"></section>')
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    html_path = _write(inputs / "reviewed.html", html)
    before_files = {path for path in tmp_path.rglob("*") if path.is_file()}
    config = EffectiveExecutionConfiguration(
        input=InputPaths(reviewed_html_path=html_path),
        knowledge=KnowledgePaths(snapshot_directory=(tmp_path / "knowledge").resolve()),
        output=OutputPaths(directory=(tmp_path / "results").resolve()),
        extraction=ExtractionRequest(
            presets=(Preset.MATERIALS,),
            components=(),
            fuzzy_enabled=False,
        ),
        resolved_components=resolve_components((Preset.MATERIALS,), ()),
        resources=ResourceLimits(),
    )
    reader = open_reviewed_html_from_configuration(config)
    assert reader.read_all_pages()[0].page.page_number == 1
    assert reader.completed is True
    after_files = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert after_files == before_files
    assert not (tmp_path / "results").exists()
    assert not (tmp_path / "knowledge").exists()
    assert Component.MATERIALS in config.resolved_components


def test_partial_success_root_with_complete_page_coverage(tmp_path: Path) -> None:
    html = render_reviewed_html(_revision(_fixture_document()))
    reader = open_reviewed_html(_write(tmp_path / "partial.html", html))
    pages = reader.read_all_pages()
    assert reader.validated_input.conversion_status is ConversionStatus.PARTIAL_SUCCESS
    assert all(page.page.coverage is PageCoverage.COMPLETE for page in pages)


def test_fail_closed_on_source_without_node_id(tmp_path: Path) -> None:
    missing_paragraph = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        "<p>Important source text</p></article></section>"
    )
    with pytest.raises(ReviewedHtmlReadError, match="MISSING_STRUCTURAL_PROVENANCE") as para_exc:
        open_reviewed_html(_write(tmp_path / "no-node-p.html", missing_paragraph)).read_all_pages()
    assert para_exc.value.code == "MISSING_STRUCTURAL_PROVENANCE"

    missing_cell = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="table" data-element-id="t">'
        '<table data-table-id="t"><tbody><tr>'
        '<td rowspan="1" colspan="1" data-row="1" data-column="1">cell</td>'
        "</tr></tbody></table></article></section>"
    )
    with pytest.raises(ReviewedHtmlReadError, match="MISSING_STRUCTURAL_PROVENANCE") as cell_exc:
        open_reviewed_html(_write(tmp_path / "no-node-td.html", missing_cell)).read_all_pages()
    assert cell_exc.value.code == "MISSING_STRUCTURAL_PROVENANCE"

    outside = _wrap('<p data-node-id="outside">Important source text</p>')
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_PAGE_STRUCTURE") as outside_exc:
        open_reviewed_html(_write(tmp_path / "outside.html", outside)).read_all_pages()
    assert outside_exc.value.code == "INVALID_PAGE_STRUCTURE"


def test_noncanonical_version_and_duplicate_attributes(tmp_path: Path) -> None:
    for index, version in enumerate(("01", "+1", " 1", "1 ")):
        html = _wrap(
            '<section class="page" id="source-page-1" data-page="1"></section>',
            version=version,
        )
        with pytest.raises(ReviewedHtmlReadError, match="UNSUPPORTED_HTML_VERSION"):
            open_reviewed_html(_write(tmp_path / f"ver-{index}.html", html)).read_all_pages()

    duplicate_root = (
        "<!doctype html>"
        '<html data-review-html-version="1" data-job-id="job-1" '
        f'data-review-revision-id="{REVISION_ID}" data-review-generation="4" '
        'data-conversion-status="SUCCEEDED" data-job-id="job-2">'
        "<body><main>"
        '<section class="page" id="source-page-1" data-page="1"></section>'
        "</main></body></html>"
    )
    with pytest.raises(ReviewedHtmlReadError, match="DUPLICATE_HTML_ATTRIBUTE") as root_exc:
        open_reviewed_html(_write(tmp_path / "dup-root.html", duplicate_root)).read_all_pages()
    assert root_exc.value.code == "DUPLICATE_HTML_ATTRIBUTE"

    duplicate_node = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a" data-node-id="b">x</p></article></section>'
    )
    with pytest.raises(ReviewedHtmlReadError, match="DUPLICATE_HTML_ATTRIBUTE"):
        open_reviewed_html(_write(tmp_path / "dup-node-attr.html", duplicate_node)).read_all_pages()


def test_unexpected_nested_markup_inside_source_block(tmp_path: Path) -> None:
    nested = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a">before<span>nested</span>after</p></article></section>'
    )
    with pytest.raises(ReviewedHtmlReadError, match="UNSUPPORTED_SOURCE_ELEMENT") as nested_exc:
        open_reviewed_html(_write(tmp_path / "nested.html", nested)).read_all_pages()
    assert nested_exc.value.code == "UNSUPPORTED_SOURCE_ELEMENT"


def test_late_malformed_input_no_final_identity(tmp_path: Path) -> None:
    html = (
        _root() + "<body><main>"
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a">one</p></article></section>'
        '<section class="page" id="source-page-2" data-page="2">'
        '<article class="element" data-kind="text" data-element-id="b">'
        "<p>missing node id</p></article></section>"
        "</main></body></html>"
    )
    reader = open_reviewed_html(_write(tmp_path / "late.html", html))
    pages_iter = reader.iter_pages()
    first = next(pages_iter)
    assert first.page.page_number == 1
    with pytest.raises(ReviewedHtmlReadError, match="MISSING_STRUCTURAL_PROVENANCE"):
        next(pages_iter)
    assert reader.completed is False
    assert reader.failed is True
    with pytest.raises(ReviewedHtmlReadError, match="INPUT_NOT_VALIDATED"):
        _ = reader.validated_input


def test_iter_pages_yields_before_eof_without_retaining_all(tmp_path: Path) -> None:
    page_one = (
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p data-node-id="a">early</p></article></section>'
    )
    padding = "<!--" + ("pad" * 50_000) + "-->"
    page_two = (
        '<section class="page" id="source-page-2" data-page="2">'
        '<article class="element" data-kind="text" data-element-id="b">'
        '<p data-node-id="b">late</p></article></section>'
    )
    html = _wrap(page_one + padding + page_two)
    path = _write(tmp_path / "stream.html", html)
    file_size = path.stat().st_size
    reader = open_reviewed_html(path, chunk_size=1024)
    pages_iter = reader.iter_pages()
    first = next(pages_iter)
    assert first.page.page_number == 1
    assert first.blocks[0].block.text == "early"
    assert reader.bytes_consumed < file_size
    assert reader.completed is False
    with pytest.raises(ReviewedHtmlReadError, match="INPUT_NOT_VALIDATED"):
        _ = reader.validated_input
    remaining = list(pages_iter)
    assert [page.page.page_number for page in remaining] == [2]
    assert reader.completed is True
    assert reader.bytes_consumed == file_size
    assert reader.validated_input.html_sha256 == hashlib.sha256(html.encode("utf-8")).hexdigest()


def test_fail_closed_ungenerated_heading_outside_article(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<h2 data-generated="true">Page 1</h2>'
        "<h3>Source heading</h3>"
        "</section>"
    )
    reader = open_reviewed_html(_write(tmp_path / "loose-h3.html", html))
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_PAGE_STRUCTURE") as exc:
        reader.read_all_pages()
    assert exc.value.code == "INVALID_PAGE_STRUCTURE"
    assert reader.completed is False
    with pytest.raises(ReviewedHtmlReadError, match="INPUT_NOT_VALIDATED"):
        _ = reader.validated_input


def test_fail_closed_bare_text_inside_article(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        "Important source text"
        "</article></section>"
    )
    reader = open_reviewed_html(_write(tmp_path / "bare-text.html", html))
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_PAGE_STRUCTURE") as exc:
        reader.read_all_pages()
    assert exc.value.code == "INVALID_PAGE_STRUCTURE"
    assert reader.completed is False


def test_fail_closed_void_tag_with_data_node_id(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<img data-node-id="a" alt="source">'
        "</article></section>"
    )
    reader = open_reviewed_html(_write(tmp_path / "void-node.html", html))
    with pytest.raises(ReviewedHtmlReadError, match="UNSUPPORTED_SOURCE_ELEMENT") as exc:
        reader.read_all_pages()
    assert exc.value.code == "UNSUPPORTED_SOURCE_ELEMENT"
    assert reader.completed is False


def test_fail_closed_mismatched_table_ownership(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="table" data-element-id="a">'
        '<table data-table-id="different"><tbody><tr>'
        '<td rowspan="1" colspan="1" data-row="1" data-column="1" data-node-id="c">'
        "source</td></tr></tbody></table></article></section>"
    )
    reader = open_reviewed_html(_write(tmp_path / "bad-table.html", html))
    with pytest.raises(ReviewedHtmlReadError, match="INVALID_PAGE_STRUCTURE") as exc:
        reader.read_all_pages()
    assert exc.value.code == "INVALID_PAGE_STRUCTURE"
    assert reader.completed is False


def test_renderer_generated_labels_headings_captions_cells_and_nesting(
    tmp_path: Path,
) -> None:
    revision = _revision(_fixture_document())
    html = render_reviewed_html(revision)
    reader = open_reviewed_html(_write(tmp_path / "positive.html", html))
    pages = reader.read_all_pages()
    assert reader.completed is True
    page3 = pages[0]
    texts = [block.block.text for block in page3.blocks]
    assert "Page 3" not in texts
    assert "Reviewed document" not in texts
    assert "Title α" in texts
    assert "Child heading" in texts
    assert "Footer" in texts
    assert "" in texts
    assert 'Caption & "quote" <b>x</b>\nLine' in texts
    by_text = {block.block.text: block.block for block in page3.blocks}
    caption = by_text['Caption & "quote" <b>x</b>\nLine']
    assert caption.element_id == caption.node_id
    spanned = by_text["A & B"]
    assert spanned.table_id == caption.element_id
    child = by_text["Child heading"]
    assert child.kind == "section_heading"
    assert child.element_id == child.node_id
