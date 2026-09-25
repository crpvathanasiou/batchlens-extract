"""Reviewed HTML provenance attributes."""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

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
from app.document_review.contracts import (
    CatalogueNode,
    PageState,
    RequestedChange,
    ReviewError,
    ReviewRevision,
)
from app.document_review.mapping import apply_changes, build_catalogue
from app.document_review.rendering import render_reviewed_html

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
LEGACY_MARKUP = (
    '<!doctype html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    "<title>Reviewed document</title><style>"
    "body{font-family:system-ui,sans-serif;margin:2rem;color:#18202a}"
    ".summary,.limitation{padding:1rem;margin-bottom:1rem;background:#eef3f8}"
    ".limitation{background:#fff0d5}.page{break-after:page;margin:2rem 0}"
    "table{border-collapse:collapse;width:100%}td,th{border:1px solid #777;padding:.4rem}"
    "p,h2,h3,h4,td,th,footer{white-space:pre-wrap}</style></head><body>"
    '<header class="summary"><h1>Reviewed document</h1>'
    f"<p>Revision: {REVISION_ID}</p><p>Not approved</p></header>"
    '<aside class="limitation">Partial conversion: source evidence may be incomplete.</aside>'
    '<main><section class="page" id="source-page-3" data-page="3"><h2>Page 3</h2>'
    '<article class="element" data-kind="table">'
    "<p>Caption &amp; &quot;quote&quot; &lt;b&gt;x&lt;/b&gt;<br>Line</p>"
    "<h4>Title α</h4><table><tbody><tr>"
    '<th rowspan="1" colspan="1" data-row="1" data-column="1"></th>'
    '<td rowspan="2" colspan="1" data-row="1" data-column="2">A &amp; B</td></tr><tr>'
    '<td rowspan="1" colspan="1" data-row="2" data-column="1">nested &quot;cell&quot;</td>'
    "</tr></tbody></table>"
    '<article class="element" data-kind="section_heading"><h3>Child heading</h3></article>'
    "<footer>Footer</footer></article>"
    '<article class="element" data-kind="title"><h2>Same words</h2></article>'
    '<article class="element" data-kind="text"><p>Same words</p></article>'
    "</section></main></body></html>"
)
_PROVENANCE_ATTR = re.compile(
    r"\s+data-(?:review-html-version|job-id|review-revision-id|review-generation|"
    r"conversion-status|element-id|node-id|table-id|source-id|generated)=\"[^\"]*\""
)


class _Nodes(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str], str]] = []
        self._stack: list[tuple[str, dict[str, str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._stack:
            self._stack[-1][2].append("\n")
            return
        if tag in {"meta", "link", "img", "input"}:
            return
        self._stack.append((tag, {key: value or "" for key, value in attrs}, []))

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1][2].append(data)

    def handle_endtag(self, tag: str) -> None:
        opened, attributes, parts = self._stack.pop()
        assert opened == tag
        self.tags.append((tag, attributes, "".join(parts)))


def _parse(html: str) -> list[tuple[str, dict[str, str], str]]:
    parser = _Nodes()
    parser.feed(html)
    return parser.tags


def _by_id(
    tags: list[tuple[str, dict[str, str], str]], attribute: str, node_id: str
) -> tuple[str, dict[str, str], str]:
    matches = [item for item in tags if item[1].get(attribute) == node_id]
    assert len(matches) == 1
    return matches[0]


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
                        kind="title", text="Same words", references=(Reference(block_id="e1"),)
                    ),
                    Element(kind="text", text="Same words", references=()),
                ),
            ),
        ),
    )


def _revision(
    document: Document,
    *,
    job_id: str = "job-1",
    generation: int = 4,
    catalogue_nodes: tuple[CatalogueNode, ...] | None = None,
) -> ReviewRevision:
    catalogue = build_catalogue(document, BASELINE)
    if catalogue_nodes is not None:
        catalogue = catalogue.model_copy(update={"nodes": catalogue_nodes})
    return ReviewRevision(
        job_id=job_id,
        owner="alice",
        revision_id=REVISION_ID,
        generation=generation,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        actor="alice",
        baseline=BASELINE,
        accepted_source=SOURCE,
        raw=RAW,
        document=document,
        catalogue=catalogue,
        pages=(PageState(page_number=3, content_hash="page-hash"),),
        findings=(),
        action="DRAFT_SAVED",
    )


def _node(revision: ReviewRevision, path: str) -> CatalogueNode:
    matches = [node for node in revision.catalogue.nodes if node.path == path]
    assert len(matches) == 1
    return matches[0]


def test_document_metadata_comes_from_the_revision() -> None:
    document = _fixture_document().model_copy(update={"status": "SUCCEEDED"})
    revision = _revision(document, job_id='job "α" <id>', generation=9)
    html = render_reviewed_html(revision)
    root = next(item for item in _parse(html) if item[0] == "html")
    assert root[1] == {
        "data-review-html-version": "1",
        "data-job-id": 'job "α" <id>',
        "data-review-revision-id": REVISION_ID,
        "data-review-generation": "9",
        "data-conversion-status": "SUCCEEDED",
    }
    assert html.count("data-review-html-version") == 1
    assert "s3://" not in html
    assert revision.created_at.isoformat() not in html


def test_node_ids_match_catalogue_for_text_titles_cells_footers_and_repeats() -> None:
    revision = _revision(_fixture_document())
    tags = _parse(render_reviewed_html(revision))
    table = _node(revision, "pages[3].elements[0]")
    title = _node(revision, "pages[3].elements[0].titles[0]")
    empty_cell = _node(revision, "pages[3].elements[0].cells[0]")
    spanned = _node(revision, "pages[3].elements[0].cells[1]")
    lower = _node(revision, "pages[3].elements[0].cells[2]")
    child = _node(revision, "pages[3].elements[0].children[0]")
    footer = _node(revision, "pages[3].elements[0].footers[0]")
    first_repeat = _node(revision, "pages[3].elements[1]")
    second_repeat = _node(revision, "pages[3].elements[2]")

    article, article_attrs, _ = _by_id(tags, "data-element-id", table.node_id)
    assert article == "article"
    assert article_attrs["data-kind"] == "table"
    assert "data-node-id" not in article_attrs
    text = _by_id(tags, "data-node-id", table.node_id)
    assert text[0] == "p"
    assert text[2] == 'Caption & "quote" <b>x</b>\nLine'
    assert _by_id(tags, "data-node-id", title.node_id)[:1] == ("h4",)
    assert _by_id(tags, "data-node-id", title.node_id)[2] == "Title α"
    assert _by_id(tags, "data-table-id", table.node_id)[0] == "table"
    assert _by_id(tags, "data-node-id", child.node_id) == (
        "h3",
        {
            "data-node-id": child.node_id,
        },
        "Child heading",
    )
    assert _by_id(tags, "data-node-id", footer.node_id)[0] == "footer"
    assert first_repeat.node_id != second_repeat.node_id
    assert _by_id(tags, "data-node-id", first_repeat.node_id)[2] == "Same words"
    assert _by_id(tags, "data-node-id", second_repeat.node_id)[2] == "Same words"
    header = _by_id(tags, "data-node-id", empty_cell.node_id)
    assert header[0] == "th" and header[2] == ""
    assert header[1]["rowspan"] == "1" and header[1]["colspan"] == "1"
    assert header[1]["data-row"] == "1" and header[1]["data-column"] == "1"
    assert "data-source-id" not in header[1]
    cell = _by_id(tags, "data-node-id", spanned.node_id)
    assert cell[1]["rowspan"] == "2" and cell[1]["colspan"] == "1"
    assert _by_id(tags, "data-node-id", lower.node_id)[1]["data-row"] == "2"


def test_source_references_are_own_ids_deduped_without_parent_inheritance() -> None:
    revision = _revision(_fixture_document())
    tags = _parse(render_reviewed_html(revision))
    table = _node(revision, "pages[3].elements[0]")
    child = _node(revision, "pages[3].elements[0].children[0]")
    footer = _node(revision, "pages[3].elements[0].footers[0]")
    repeat = _node(revision, "pages[3].elements[1]")
    blank = _node(revision, "pages[3].elements[2]")
    assert _by_id(tags, "data-node-id", table.node_id)[1]["data-source-id"] == "blk a blk&b"
    assert (
        _by_id(tags, "data-node-id", _node(revision, "pages[3].elements[0].cells[1]").node_id)[1][
            "data-source-id"
        ]
        == "c1 c2"
    )
    assert (
        _by_id(tags, "data-node-id", _node(revision, "pages[3].elements[0].titles[0]").node_id)[1][
            "data-source-id"
        ]
        == "title-1"
    )
    assert "data-source-id" not in _by_id(tags, "data-node-id", child.node_id)[1]
    assert "data-source-id" not in _by_id(tags, "data-node-id", footer.node_id)[1]
    assert _by_id(tags, "data-node-id", repeat.node_id)[1]["data-source-id"] == "e1"
    assert "data-source-id" not in _by_id(tags, "data-node-id", blank.node_id)[1]


def test_generated_markers_skip_source_headings_and_footers() -> None:
    tags = _parse(render_reviewed_html(_revision(_fixture_document())))
    generated = [item for item in tags if item[1].get("data-generated") == "true"]
    assert [item[0] for item in generated] == ["header", "aside", "h2"]
    assert next(item[2] for item in tags if item[0] == "h1") == "Reviewed document"
    assert generated[1][2] == "Partial conversion: source evidence may be incomplete."
    assert generated[2][2] == "Page 3"
    source_heading = next(item for item in tags if item[0] == "h3")
    footer = next(item for item in tags if item[0] == "footer")
    assert "data-generated" not in source_heading[1]
    assert "data-generated" not in footer[1]
    assert "<script" not in render_reviewed_html(_revision(_fixture_document()))


def test_dynamic_text_and_attributes_stay_escaped() -> None:
    document = _fixture_document()
    injected = (
        document.pages[0]
        .elements[2]
        .model_copy(
            update={
                "text": "<>&\"'\n<script>",
                "references": (Reference(block_id='"><img onerror=1>'),),
            }
        )
    )
    page = document.pages[0].model_copy(
        update={"elements": (*document.pages[0].elements[:2], injected)}
    )
    revision = _revision(document.model_copy(update={"pages": (page,)}), job_id='a"b<c>&')
    html = render_reviewed_html(revision)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'data-source-id="&quot;&gt;&lt;img onerror=1&gt;"' in html
    assert 'data-job-id="a&quot;b&lt;c&gt;&amp;"' in html
    node = _node(revision, "pages[3].elements[2]")
    parsed = _by_id(_parse(html), "data-node-id", node.node_id)
    assert parsed[2] == "<>&\"'\n<script>"
    assert parsed[1]["data-source-id"] == '"><img onerror=1>'


def test_text_edit_keeps_node_identity_and_renders_current_text() -> None:
    document = _fixture_document()
    revision = _revision(document)
    target = _node(revision, "pages[3].elements[2]")
    updated, _changed = apply_changes(
        document,
        revision.catalogue,
        (RequestedChange(node_id=target.node_id, text="Corrected words"),),
    )
    edited = revision.model_copy(update={"document": updated})
    before = _by_id(_parse(render_reviewed_html(revision)), "data-node-id", target.node_id)
    after = _by_id(_parse(render_reviewed_html(edited)), "data-node-id", target.node_id)
    assert before[1]["data-node-id"] == after[1]["data-node-id"] == target.node_id
    assert before[2] == "Same words"
    assert after[2] == "Corrected words"
    assert target.baseline_text == "Same words"


def test_repeated_rendering_is_deterministic_and_does_not_mutate() -> None:
    revision = _revision(_fixture_document())
    snapshot = revision.model_dump(mode="json")
    first = render_reviewed_html(revision)
    second = render_reviewed_html(revision)
    assert first == second
    assert revision.model_dump(mode="json") == snapshot


def test_missing_or_ambiguous_catalogue_nodes_fail_and_empty_references_do_not() -> None:
    document = _fixture_document()
    revision = _revision(document)
    missing = revision.model_copy(
        update={"catalogue": revision.catalogue.model_copy(update={"nodes": ()})}
    )
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE") as missing_error:
        render_reviewed_html(missing)
    assert missing_error.value.code == "INVALID_REVIEW_STATE"
    assert missing_error.value.status == 409

    duplicate = revision.catalogue.nodes[0]
    ambiguous = revision.model_copy(
        update={
            "catalogue": revision.catalogue.model_copy(
                update={"nodes": (duplicate, *revision.catalogue.nodes)}
            )
        }
    )
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        render_reviewed_html(ambiguous)

    mismatched = revision.catalogue.nodes[0].model_copy(update={"kind": "OTHER"})
    incoherent = revision.model_copy(
        update={
            "catalogue": revision.catalogue.model_copy(
                update={"nodes": (mismatched, *revision.catalogue.nodes[1:])}
            )
        }
    )
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        render_reviewed_html(incoherent)

    empty = _revision(
        Document(
            source=document.source,
            status="SUCCEEDED",
            pages=(
                Page(
                    number=1,
                    reading_order="textract_layout",
                    elements=(Element(kind="text", text="Plain", references=()),),
                ),
            ),
        )
    )
    rendered = _parse(render_reviewed_html(empty))
    paragraph = next(item for item in rendered if item[0] == "p" and item[2] == "Plain")
    assert "data-source-id" not in paragraph[1]
    assert paragraph[1]["data-node-id"]


def test_visible_markup_matches_pre_attribute_rendering() -> None:
    html = render_reviewed_html(_revision(_fixture_document()))
    assert "data-element-id" in html and "data-node-id" in html and "data-table-id" in html
    assert _PROVENANCE_ATTR.sub("", html) == LEGACY_MARKUP
