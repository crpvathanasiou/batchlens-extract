"""Pure merge, source-validation, and eligibility rule tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.page_classification.contracts import (
    OTHER_UNCLASSIFIED,
    CallOutcome,
    PageInputBinding,
)
from app.page_classification.page_input import get_prepared_page, prepare_reviewed_document
from app.page_classification.rules import (
    decide_extraction_eligibility,
    failed_call,
    merge_page_classification,
    missing_call,
    validate_call_response,
    validate_source_evidence,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"


@pytest.fixture
def page2(tmp_path: Path) -> Any:
    path = tmp_path / "reviewed.html"
    path.write_bytes(FIXTURE.read_bytes())
    return get_prepared_page(prepare_reviewed_document(path), 2)


def _evidence(label: str, quote: str, element_id: str | None = None) -> dict[str, object]:
    return {
        "label": label,
        "quote": quote,
        "reason": f"Criterion for {label}.",
        "element_id": element_id,
    }


def _call(
    binding: PageInputBinding,
    call_id: int,
    *,
    labels: list[str] | None = None,
    status: str = "ok",
    evidence: list[dict[str, object]] | None = None,
) -> CallOutcome:
    labels = [] if labels is None else labels
    if evidence is None:
        evidence = [_evidence(label, "Sodium Chloride") for label in labels]
    return validate_call_response(
        binding,
        call_id,  # type: ignore[arg-type]
        {"labels": labels, "status": status, "evidence": evidence},
    )


def _triple(
    binding: PageInputBinding,
    one: CallOutcome | None = None,
    two: CallOutcome | None = None,
    three: CallOutcome | None = None,
) -> tuple[CallOutcome, CallOutcome, CallOutcome]:
    return (
        one if one is not None else missing_call(binding, 1),
        two if two is not None else missing_call(binding, 2),
        three if three is not None else missing_call(binding, 3),
    )


def test_unverified_identifier_keeps_labels_needs_review_and_extraction_eligibility(
    page2: Any,
) -> None:
    binding = page2.binding
    merged = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS"],
                evidence=[
                    _evidence(
                        "BILL_OF_MATERIALS",
                        "Sodium Chloride",
                        "no-such-identifier",
                    )
                ],
            ),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    assert merged.kind == "needs_review"
    assert merged.requires_review is True
    assert merged.source_validation.has_unverified is True
    assert [item.label for item in merged.labels] == ["BILL_OF_MATERIALS"]
    assert merged.labels[0].quote == "Sodium Chloride"
    assert merged.labels[0].element_id == "no-such-identifier"
    assert merged.labels[0].evidence_verification == "unverified"
    assert "not found" in (merged.labels[0].evidence_verification_reason or "")
    eligibility = decide_extraction_eligibility(merged)
    assert eligibility.eligible_for_extraction is True
    assert eligibility.excluded_by_policy is False


def test_ambiguous_identifier_keeps_extraction_eligibility(page2: Any) -> None:
    binding = page2.binding
    page2_mut = page2.model_copy(
        update={
            "ambiguous_element_ids": frozenset({"materials-table"}),
            "element_text_by_id": {
                key: value
                for key, value in page2.element_text_by_id.items()
                if key != "materials-table"
            },
        }
    )
    merged = merge_page_classification(
        page2_mut,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS"],
                evidence=[_evidence("BILL_OF_MATERIALS", "Sodium Chloride", "materials-table")],
            ),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    assert merged.requires_review is True
    assert merged.labels[0].evidence_verification == "unverified"
    assert "ambiguous" in (merged.labels[0].evidence_verification_reason or "")
    assert decide_extraction_eligibility(merged).eligible_for_extraction is True


def test_out_of_order_evidence_associates_by_label_not_position(page2: Any) -> None:
    binding = page2.binding
    labels = ["EQUIPMENT_LIST", "BILL_OF_MATERIALS"]
    evidence = [
        _evidence("BILL_OF_MATERIALS", "Sodium Chloride", "materials-table"),
        _evidence("EQUIPMENT_LIST", "Mixer MX-01", "equipment-table"),
    ]
    assert [item["label"] for item in evidence] != labels
    merged = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, labels=labels, evidence=evidence),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    by_label = {item.label: item for item in merged.labels}
    assert by_label["BILL_OF_MATERIALS"].quote == "Sodium Chloride"
    assert by_label["BILL_OF_MATERIALS"].element_id == "materials-table"
    assert by_label["EQUIPMENT_LIST"].quote == "Mixer MX-01"
    assert by_label["EQUIPMENT_LIST"].element_id == "equipment-table"
    assert [item.label for item in merged.labels] == [
        "BILL_OF_MATERIALS",
        "EQUIPMENT_LIST",
    ]


def test_missing_failed_invalid_independently_keep_provisional_findings(page2: Any) -> None:
    binding = page2.binding
    valid = _call(
        binding,
        1,
        labels=["BILL_OF_MATERIALS", "EQUIPMENT_LIST"],
        evidence=[
            _evidence("BILL_OF_MATERIALS", "Sodium Chloride", "materials-table"),
            _evidence("EQUIPMENT_LIST", "Mixer MX-01", "equipment-table"),
        ],
    )
    for other in (
        missing_call(binding, 2),
        failed_call(binding, 2, reason="provider refusal"),
        validate_call_response(
            binding, 2, {"labels": ["NOT_A_LABEL"], "status": "ok", "evidence": []}
        ),
    ):
        merged = merge_page_classification(
            page2,
            (valid, other, missing_call(binding, 3)),
        )
        assert merged.kind == "incomplete"
        assert merged.is_provisional is True
        assert [item.label for item in merged.labels] == [
            "BILL_OF_MATERIALS",
            "EQUIPMENT_LIST",
        ]
        assert merged.applied_other_unclassified is False
        eligibility = decide_extraction_eligibility(merged)
        assert eligibility.eligible_for_extraction is True
        assert eligibility.excluded_by_policy is False


def test_needs_review_with_and_without_labels(page2: Any) -> None:
    binding = page2.binding
    with_labels = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, status="needs_review", labels=["BILL_OF_MATERIALS"]),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    assert with_labels.kind == "needs_review"
    assert with_labels.requires_review is True
    assert [item.label for item in with_labels.labels] == ["BILL_OF_MATERIALS"]
    assert decide_extraction_eligibility(with_labels).eligible_for_extraction is True

    without = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, status="needs_review", labels=[]),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    assert without.kind == "needs_review"
    assert without.labels == ()
    assert without.applied_other_unclassified is False


def test_all_empty_and_mixed_empty_ok(page2: Any) -> None:
    binding = page2.binding
    all_empty = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, status="empty"),
            _call(binding, 2, status="empty"),
            _call(binding, 3, status="empty"),
        ),
    )
    assert all_empty.kind == "empty"
    assert all_empty.labels == ()
    assert all_empty.applied_other_unclassified is False
    assert decide_extraction_eligibility(all_empty).eligible_for_extraction is True

    mixed = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, status="empty"),
            _call(
                binding,
                2,
                labels=["PROCESS_EXECUTION_RECORD"],
                evidence=[_evidence("PROCESS_EXECUTION_RECORD", "Mixer")],
            ),
            _call(binding, 3, status="ok"),
        ),
    )
    assert mixed.kind == "needs_review"
    assert mixed.requires_review is True
    assert [item.label for item in mixed.labels] == ["PROCESS_EXECUTION_RECORD"]
    assert mixed.applied_other_unclassified is False


def test_all_ok_nonempty_union_and_application_fallback(page2: Any) -> None:
    binding = page2.binding
    completed = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS", "EQUIPMENT_LIST"],
                evidence=[
                    _evidence("BILL_OF_MATERIALS", "Sodium Chloride", "materials-table"),
                    _evidence("EQUIPMENT_LIST", "Mixer", "equipment-table"),
                ],
            ),
            _call(binding, 2, labels=[]),
            _call(
                binding,
                3,
                labels=["COVER_PAGE"],
                evidence=[_evidence("COVER_PAGE", "Sodium Chloride")],
            ),
        ),
    )
    assert completed.kind == "completed"
    assert [item.label for item in completed.labels] == [
        "BILL_OF_MATERIALS",
        "EQUIPMENT_LIST",
        "COVER_PAGE",
    ]
    assert [item.call_id for item in completed.labels] == [1, 1, 3]
    assert completed.applied_other_unclassified is False

    fallback = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1, labels=[]),
            _call(binding, 2, labels=[]),
            _call(binding, 3, labels=[]),
        ),
    )
    assert fallback.kind == "needs_review"
    assert fallback.applied_other_unclassified is True
    assert [item.label for item in fallback.labels] == [OTHER_UNCLASSIFIED]
    assert fallback.labels[0].provenance == "application_fallback"
    assert fallback.labels[0].quote is None
    assert decide_extraction_eligibility(fallback).eligible_for_extraction is True


def test_source_mismatch_alone_and_with_incompleteness(page2: Any) -> None:
    binding = page2.binding
    bad = _call(
        binding,
        1,
        labels=["BILL_OF_MATERIALS"],
        evidence=[_evidence("BILL_OF_MATERIALS", "missing-quote-text")],
    )
    alone = merge_page_classification(
        page2,
        _triple(binding, bad, _call(binding, 2), _call(binding, 3)),
    )
    assert alone.requires_review is True
    assert alone.source_validation.has_unverified is True
    assert alone.labels[0].quote == "missing-quote-text"
    assert alone.labels[0].evidence_verification == "unverified"
    assert decide_extraction_eligibility(alone).eligible_for_extraction is True

    combined = merge_page_classification(
        page2,
        _triple(binding, bad, missing_call(binding, 2), _call(binding, 3)),
    )
    assert combined.kind == "incomplete"
    assert combined.requires_review is True
    assert combined.source_validation.has_unverified is True
    assert combined.is_provisional is True


def test_exclusion_policy_examples(page2: Any) -> None:
    binding = page2.binding

    toc_only = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1),
            _call(binding, 2),
            _call(
                binding,
                3,
                labels=["TABLE_OF_CONTENTS"],
                evidence=[_evidence("TABLE_OF_CONTENTS", "Sodium Chloride")],
            ),
        ),
    )
    toc_decision = decide_extraction_eligibility(toc_only)
    assert toc_decision.eligible_for_extraction is False
    assert toc_decision.excluded_by_policy is True

    cover_and_bom = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS"],
                evidence=[_evidence("BILL_OF_MATERIALS", "Sodium Chloride")],
            ),
            _call(binding, 2),
            _call(
                binding,
                3,
                labels=["COVER_PAGE"],
                evidence=[_evidence("COVER_PAGE", "Mixer")],
            ),
        ),
    )
    assert decide_extraction_eligibility(cover_and_bom).eligible_for_extraction is True

    signature_and_process = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1),
            _call(
                binding,
                2,
                labels=["PROCESS_EXECUTION_RECORD"],
                evidence=[_evidence("PROCESS_EXECUTION_RECORD", "Mixer")],
            ),
            _call(
                binding,
                3,
                labels=["SIGNATURE_APPROVAL"],
                evidence=[_evidence("SIGNATURE_APPROVAL", "Sodium Chloride")],
            ),
        ),
    )
    assert decide_extraction_eligibility(signature_and_process).eligible_for_extraction is True


def test_mismatched_page_bindings_rejected(page2: Any, tmp_path: Path) -> None:
    path = tmp_path / "reviewed.html"
    path.write_bytes(FIXTURE.read_bytes())
    page1 = get_prepared_page(prepare_reviewed_document(path), 1)
    with pytest.raises(ValueError, match="binding"):
        merge_page_classification(
            page2,
            _triple(
                page1.binding,
                _call(page1.binding, 1),
                _call(page1.binding, 2),
                _call(page1.binding, 3),
            ),
        )


def test_stable_material_equipment_independence(page2: Any) -> None:
    binding = page2.binding
    only_material = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS"],
                evidence=[_evidence("BILL_OF_MATERIALS", "Sodium Chloride")],
            ),
            _call(binding, 2),
            _call(binding, 3),
        ),
    )
    only_equipment = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["EQUIPMENT_LIST"],
                evidence=[_evidence("EQUIPMENT_LIST", "Mixer")],
            ),
            _call(binding, 2),
            _call(binding, 3),
        ),
    )
    both = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS", "EQUIPMENT_LIST"],
                evidence=[
                    _evidence("BILL_OF_MATERIALS", "Sodium Chloride"),
                    _evidence("EQUIPMENT_LIST", "Mixer"),
                ],
            ),
            _call(binding, 2),
            _call(binding, 3),
        ),
    )
    assert [item.label for item in only_material.labels] == ["BILL_OF_MATERIALS"]
    assert [item.label for item in only_equipment.labels] == ["EQUIPMENT_LIST"]
    assert [item.label for item in both.labels] == ["BILL_OF_MATERIALS", "EQUIPMENT_LIST"]


def test_revalidation_of_constructed_model_instances(page2: Any) -> None:
    binding = page2.binding
    valid = _call(binding, 1, labels=[])
    assert valid.response is not None
    again = validate_call_response(binding, 1, valid.response)
    assert again.availability == "valid"
    valid.response.labels.append("BILL_OF_MATERIALS")  # type: ignore[arg-type]
    broken = validate_call_response(binding, 1, valid.response)
    assert broken.availability == "invalid"


def test_source_validation_preserves_original_evidence_fields(page2: Any) -> None:
    binding = page2.binding
    outcome = _call(
        binding,
        1,
        labels=["BILL_OF_MATERIALS"],
        evidence=[
            {
                "label": "BILL_OF_MATERIALS",
                "quote": "No Such Quote",
                "reason": "Keep this reason.",
                "element_id": "materials-table",
            }
        ],
    )
    source = validate_source_evidence(
        page2, (outcome, missing_call(binding, 2), missing_call(binding, 3))
    )
    item = source.items[0]
    assert item.verification == "unverified"
    assert item.quote == "No Such Quote"
    assert item.reason == "Keep this reason."
    assert item.element_id == "materials-table"
    assert outcome.availability == "valid"


def test_merge_cannot_bypass_source_validation(page2: Any) -> None:
    import inspect

    binding = page2.binding
    mismatched = _call(
        binding,
        1,
        labels=["BILL_OF_MATERIALS"],
        evidence=[_evidence("BILL_OF_MATERIALS", "missing-quote-text")],
    )
    outcomes = _triple(binding, mismatched, _call(binding, 2), _call(binding, 3))
    assert "source_validation" not in inspect.signature(merge_page_classification).parameters
    fake = type(
        "Fake",
        (),
        {
            "binding": binding,
            "items": (),
            "has_unverified": False,
            "requires_review": False,
        },
    )()
    bypass_kwargs: dict[str, Any] = {"source_validation": fake}
    with pytest.raises(TypeError):
        merge_page_classification(page2, outcomes, **bypass_kwargs)
    merged = merge_page_classification(page2, outcomes)
    assert merged.source_validation.has_unverified is True
    assert merged.requires_review is True
    assert merged.kind == "needs_review"
    assert decide_extraction_eligibility(merged).eligible_for_extraction is True
    assert decide_extraction_eligibility(merged).excluded_by_policy is False


def test_duplicate_or_missing_call_slots_rejected(page2: Any) -> None:
    binding = page2.binding
    duplicate = (
        _call(binding, 1),
        _call(binding, 1),
        _call(binding, 3),
    )
    with pytest.raises(ValueError, match="exactly one outcome"):
        validate_source_evidence(page2, duplicate)
    with pytest.raises(ValueError, match="exactly one outcome"):
        merge_page_classification(page2, duplicate)

    missing_slot = (
        _call(binding, 1),
        _call(binding, 2),
        _call(binding, 2),
    )
    with pytest.raises(ValueError, match="exactly one outcome"):
        validate_source_evidence(page2, missing_slot)
    with pytest.raises(ValueError, match="exactly one outcome"):
        merge_page_classification(page2, missing_slot)


def test_automatic_source_validation_still_allows_completed_and_excluded(
    page2: Any,
) -> None:
    binding = page2.binding
    completed = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(
                binding,
                1,
                labels=["BILL_OF_MATERIALS"],
                evidence=[_evidence("BILL_OF_MATERIALS", "Sodium Chloride")],
            ),
            _call(binding, 2),
            _call(binding, 3),
        ),
    )
    assert completed.kind == "completed"
    assert completed.source_validation.has_unverified is False
    assert decide_extraction_eligibility(completed).eligible_for_extraction is True

    excluded = merge_page_classification(
        page2,
        _triple(
            binding,
            _call(binding, 1),
            _call(binding, 2),
            _call(
                binding,
                3,
                labels=["TABLE_OF_CONTENTS"],
                evidence=[_evidence("TABLE_OF_CONTENTS", "Sodium Chloride")],
            ),
        ),
    )
    assert excluded.kind == "completed"
    assert excluded.source_validation.has_unverified is False
    decision = decide_extraction_eligibility(excluded)
    assert decision.eligible_for_extraction is False
    assert decision.excluded_by_policy is True
