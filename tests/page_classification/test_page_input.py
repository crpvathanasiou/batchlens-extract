"""Prepared document / page-input foundation tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.lexical_extraction import html_reader as html_reader_module
from app.lexical_extraction.contracts import ConversionStatus, ReviewedHtmlV1Input
from app.page_classification.contracts import CallOutcome
from app.page_classification.page_input import (
    PageInputError,
    get_prepared_page,
    normalize_evidence_text,
    prepare_reviewed_document,
)
from app.page_classification.rules import (
    missing_call,
    validate_call_response,
    validate_source_evidence,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"


def _root(
    *,
    version: str = "1",
    job_id: str = "job-x",
    revision_id: str = "rev-x",
    generation: str = "1",
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
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body>'
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _write(path: Path, html: str) -> Path:
    path.write_bytes(html.encode("utf-8"))
    return path


def test_prepare_validates_once_then_page_lookup_reuses_prepared_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    opens = {"count": 0}
    real_open = html_reader_module.open_reviewed_html

    def counting_open(path: Path, *, chunk_size: int = 65_536) -> object:
        opens["count"] += 1
        return real_open(path, chunk_size=chunk_size)

    monkeypatch.setattr(html_reader_module, "open_reviewed_html", counting_open)
    # prepare_reviewed_document imports open_reviewed_html at module level; patch there too.
    import app.page_classification.page_input as page_input_module

    monkeypatch.setattr(page_input_module, "open_reviewed_html", counting_open)

    document = prepare_reviewed_document(html_path)
    assert opens["count"] == 1
    assert document.reviewed_html.job_id == "job-page-class-1"
    assert document.reviewed_html.review_revision_id == "rev-page-class-1"
    assert document.reviewed_html.review_generation == 2
    assert len(document.pages) == 3

    page1 = get_prepared_page(document, 1)
    page2 = get_prepared_page(document, 2)
    page3 = get_prepared_page(document, 3)
    assert opens["count"] == 1
    assert page1.binding.page_number == 1
    assert page1.binding.page_html_id == "source-page-1"
    assert page2.binding.page_html_id == "source-page-2"
    assert page3.binding.page_html_id == "source-page-3"
    assert page1.binding.reviewed_html == document.reviewed_html

    # Evidence checks also avoid reopening the document.
    outcomes = (
        validate_call_response(
            page2.binding,
            1,
            {
                "labels": ["BILL_OF_MATERIALS"],
                "status": "ok",
                "evidence": [
                    {
                        "label": "BILL_OF_MATERIALS",
                        "quote": "Sodium Chloride 4.67 kg",
                        "reason": "Material register row.",
                        "element_id": "materials-table",
                    }
                ],
            },
        ),
        missing_call(page2.binding, 2),
        missing_call(page2.binding, 3),
    )
    source = validate_source_evidence(page2, outcomes)
    assert source.items[0].verification == "verified"
    assert opens["count"] == 1


def test_complete_page_extraction_isolation_and_ordering(tmp_path: Path) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    document = prepare_reviewed_document(html_path)
    assert [page.binding.page_number for page in document.pages] == [1, 2, 3]

    page1 = get_prepared_page(document, 1)
    page2 = get_prepared_page(document, 2)
    page3 = get_prepared_page(document, 3)

    assert "Table of Contents" in page1.readable_text
    assert "Sodium Chloride" not in page1.readable_text
    assert "Signature Approval" not in page1.readable_text
    assert "<!-- page-one-comment -->" in page1.page_html_fragment
    assert "<script>ignored-on-page-1()</script>" in page1.page_html_fragment
    assert "ignored-on-page-1" not in page1.readable_text
    assert "script-noise" not in page1.readable_text

    assert "Sodium Chloride" in page2.readable_text
    assert "4.67 kg" in page2.readable_text
    assert "Mixer" in page2.readable_text
    assert "MX-01" in page2.readable_text
    assert "materials-table" in page2.page_html_fragment
    assert "equipment-table" in page2.page_html_fragment
    assert "<style>.page-local { display:none }</style>" in page2.page_html_fragment
    assert "display:none" not in page2.readable_text
    assert "Table of Contents" not in page2.readable_text
    assert "Signature Approval" not in page2.readable_text

    assert "Signature Approval block" in page3.readable_text
    assert "Sodium Chloride" not in page3.readable_text


def test_entities_whitespace_cells_and_element_text(tmp_path: Path) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    page2 = get_prepared_page(prepare_reviewed_document(html_path), 2)
    # Readable text preserves entities; evidence normalization decodes once.
    assert "A&amp;B café" in page2.readable_text
    assert "A&B café" not in page2.readable_text
    assert "second line" in page2.readable_text
    assert "Sodium Chloride" in page2.element_text_by_id["materials-table"]
    assert "4.67 kg" in page2.element_text_by_id["materials-table"]
    normalized = normalize_evidence_text(page2.readable_text)
    assert "A&B café" in normalized
    assert "Sodium Chloride 4.67 kg" in normalized
    assert normalize_evidence_text("A&amp;B   café") in normalize_evidence_text(
        page2.element_text_by_id["note-para"]
    )


def test_evidence_normalization_decodes_entities_exactly_once(tmp_path: Path) -> None:
    body = (
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="t1">'
        '<p id="once" data-node-id="t1">A&amp;B</p>'
        '<p id="twice" data-node-id="t2">A&amp;amp;B</p>'
        '<p id="spaces" data-node-id="t3">keep   &amp;   spaced</p>'
        "</article></section>"
    )
    page = get_prepared_page(
        prepare_reviewed_document(_write(tmp_path / "entities.html", _wrap(body))),
        1,
    )
    assert page.readable_text.count("A&amp;B") >= 1
    assert "A&amp;amp;B" in page.readable_text
    assert normalize_evidence_text(page.element_text_by_id["once"]) == "A&B"
    # Double-encoded source decodes once to A&amp;B, not A&B.
    assert normalize_evidence_text(page.element_text_by_id["twice"]) == "A&amp;B"
    assert normalize_evidence_text("A&amp;amp;B") == "A&amp;B"
    assert normalize_evidence_text("A&amp;B") == "A&B"
    assert normalize_evidence_text(page.element_text_by_id["spaces"]) == "keep & spaced"
    assert normalize_evidence_text("keep   &amp;   spaced") == "keep & spaced"

    binding = page.binding
    match_once = validate_call_response(
        binding,
        1,
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "A&amp;B",
                    "reason": "Ordinary entity quote.",
                    "element_id": "once",
                }
            ],
        },
    )
    assert (
        validate_source_evidence(
            page, (match_once, missing_call(binding, 2), missing_call(binding, 3))
        )
        .items[0]
        .verification
        == "verified"
    )

    # Quote that would only match after a second decode of the double-encoded span.
    false_double = validate_call_response(
        binding,
        1,
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "A&B",
                    "reason": "Would require a second decode of A&amp;amp;B.",
                    "element_id": "twice",
                }
            ],
        },
    )
    assert (
        validate_source_evidence(
            page, (false_double, missing_call(binding, 2), missing_call(binding, 3))
        )
        .items[0]
        .verification
        == "unverified"
    )

    true_double = validate_call_response(
        binding,
        1,
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "A&amp;amp;B",
                    "reason": "Matches after exactly one decode.",
                    "element_id": "twice",
                }
            ],
        },
    )
    assert (
        validate_source_evidence(
            page, (true_double, missing_call(binding, 2), missing_call(binding, 3))
        )
        .items[0]
        .verification
        == "verified"
    )


def test_page_fragment_uses_parser_span_not_string_search(tmp_path: Path) -> None:
    decoy = (
        '<!-- id="source-page-1" -->'
        "<script>var x = 'id=\"source-page-1\"';</script>"
        '<section class="page" id=\'source-page-1\' data-page="1">'
        '<article class="element" data-kind="text" data-element-id="outer">'
        '<section id="inner-section">'
        '<p id="inner-p" data-node-id="outer">Nested body</p>'
        "<!-- keep-comment -->"
        "<style>.x{}</style>"
        "<script>keep-script()</script>"
        "</section>"
        "</article></section>"
        '<section class="page" id="source-page-2" data-page="2">'
        '<article class="element" data-kind="text" data-element-id="other">'
        '<p data-node-id="other">Other page</p>'
        "</article></section>"
    )
    document = prepare_reviewed_document(_write(tmp_path / "spans.html", _wrap(decoy)))
    page1 = get_prepared_page(document, 1)
    page2 = get_prepared_page(document, 2)
    assert page1.binding.page_html_id == "source-page-1"
    assert "id='source-page-1'" in page1.page_html_fragment
    assert page1.page_html_fragment.startswith("<section")
    assert page1.page_html_fragment.endswith("</section>")
    assert "<!-- keep-comment -->" in page1.page_html_fragment
    assert "<style>.x{}</style>" in page1.page_html_fragment
    assert "<script>keep-script()</script>" in page1.page_html_fragment
    assert 'id="inner-section"' in page1.page_html_fragment
    assert "Nested body" in page1.readable_text
    assert "keep-comment" not in page1.readable_text
    assert "keep-script" not in page1.readable_text
    assert ".x{}" not in page1.readable_text
    assert "Other page" not in page1.readable_text
    assert "Other page" in page2.readable_text
    assert "Nested body" not in page2.readable_text
    # Decoy occurrences before the real section must not become the fragment.
    assert not page1.page_html_fragment.startswith("<!--")
    assert "<script>var x" not in page1.page_html_fragment


def test_provenance_and_hash_mismatch_rejected(tmp_path: Path) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    document = prepare_reviewed_document(html_path)
    wrong = document.reviewed_html.model_copy(update={"job_id": "other-job"})
    with pytest.raises(PageInputError, match="PROVENANCE_MISMATCH"):
        prepare_reviewed_document(html_path, expected=wrong)

    # Tamper after a successful identity would be caught by re-preparation.
    tampered = tmp_path / "tampered.html"
    payload = FIXTURE.read_bytes() + b" "
    tampered.write_bytes(payload)
    # Reader hashes the consumed bytes, so preparation of the tampered file succeeds
    # with a different digest; mismatch is against an expected prior identity.
    expected = ReviewedHtmlV1Input(
        html_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        html_contract_version=1,
        job_id="job-page-class-1",
        review_revision_id="rev-page-class-1",
        review_generation=2,
        conversion_status=ConversionStatus.SUCCEEDED,
    )
    with pytest.raises(PageInputError, match="PROVENANCE_MISMATCH"):
        prepare_reviewed_document(tampered, expected=expected)


def test_absent_page_and_duplicate_html_id_rejected(tmp_path: Path) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    document = prepare_reviewed_document(html_path)
    with pytest.raises(PageInputError, match="PAGE_NOT_FOUND"):
        get_prepared_page(document, 99)

    duplicate = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a">'
        '<p id="dup" data-node-id="a">one</p>'
        '<p id="dup" data-node-id="b">two</p>'
        "</article></section>"
    )
    with pytest.raises(PageInputError, match="DUPLICATE_HTML_ID"):
        prepare_reviewed_document(_write(tmp_path / "dup.html", duplicate))


def test_source_evidence_null_omitted_wrong_and_noncontaining_ids(
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    page2 = get_prepared_page(prepare_reviewed_document(html_path), 2)
    page3 = get_prepared_page(prepare_reviewed_document(html_path), 3)

    def outcome(payload: dict[str, object]) -> CallOutcome:
        return validate_call_response(page2.binding, 1, payload)

    present = outcome(
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "Sodium Chloride",
                    "reason": "Material name present.",
                    "element_id": None,
                }
            ],
        }
    )
    assert (
        validate_source_evidence(
            page2, (present, missing_call(page2.binding, 2), missing_call(page2.binding, 3))
        )
        .items[0]
        .verification
        == "verified"
    )

    omitted = {
        "labels": ["BILL_OF_MATERIALS"],
        "status": "ok",
        "evidence": [
            {
                "label": "BILL_OF_MATERIALS",
                "quote": "Sodium Chloride",
                "reason": "Material name present.",
            }
        ],
    }
    invalid = validate_call_response(page2.binding, 1, omitted)
    assert invalid.availability == "invalid"

    absent_quote = outcome(
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "Not on this page",
                    "reason": "Missing quote.",
                    "element_id": None,
                }
            ],
        }
    )
    unchecked = validate_source_evidence(
        page2, (absent_quote, missing_call(page2.binding, 2), missing_call(page2.binding, 3))
    )
    assert unchecked.items[0].verification == "unverified"
    assert unchecked.items[0].quote == "Not on this page"

    wrong_page_id = outcome(
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "Sodium Chloride",
                    "reason": "Uses id from another page.",
                    "element_id": "approval-block",
                }
            ],
        }
    )
    wrong = validate_source_evidence(
        page2, (wrong_page_id, missing_call(page2.binding, 2), missing_call(page2.binding, 3))
    )
    assert wrong.items[0].verification == "unverified"
    assert "approval-block" in (wrong.items[0].verification_reason or "")

    noncontaining = outcome(
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "Sodium Chloride",
                    "reason": "Wrong containing element.",
                    "element_id": "equipment-table",
                }
            ],
        }
    )
    bad_container = validate_source_evidence(
        page2, (noncontaining, missing_call(page2.binding, 2), missing_call(page2.binding, 3))
    )
    assert bad_container.items[0].verification == "unverified"

    # No case folding / fuzzy repair.
    cased = outcome(
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "sodium chloride",
                    "reason": "Case folded quote.",
                    "element_id": None,
                }
            ],
        }
    )
    assert (
        validate_source_evidence(
            page2, (cased, missing_call(page2.binding, 2), missing_call(page2.binding, 3))
        )
        .items[0]
        .verification
        == "unverified"
    )

    # Quote on page 3 id is not accepted for page 2 checks above; confirm page 3 has it.
    assert "approval-block" in page3.element_text_by_id


def test_mismatched_bindings_rejected_for_source_validation(tmp_path: Path) -> None:
    html_path = tmp_path / "reviewed.html"
    html_path.write_bytes(FIXTURE.read_bytes())
    document = prepare_reviewed_document(html_path)
    page1 = get_prepared_page(document, 1)
    page2 = get_prepared_page(document, 2)
    with pytest.raises(ValueError, match="binding"):
        validate_source_evidence(
            page1,
            (
                missing_call(page2.binding, 1),
                missing_call(page2.binding, 2),
                missing_call(page2.binding, 3),
            ),
        )
