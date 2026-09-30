"""Current-classification store persistence tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.page_classification.contracts import (
    ClassificationProgress,
    CompletedPageClassificationResult,
    CurrentClassificationState,
    EligibilityDecision,
    EvidenceValidationItem,
    MergedLabelFinding,
    PersistedCallOutcome,
    SourceEvidenceValidation,
    persist_call_outcome,
)
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.rules import validate_call_response
from app.page_classification.store import (
    CLASSIFICATIONS_DIR_NAME,
    CURRENT_CLASSIFICATION_FILENAME,
    PageClassificationStore,
    PageClassificationStoreError,
    derive_reviewed_html_identity_key,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"
FIXED_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


def _prepare(tmp_path: Path, *, alternate_revision: bool = False) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "reviewed.html"
    if alternate_revision:
        text = FIXTURE.read_text(encoding="utf-8").replace(
            "rev-page-class-1",
            "rev-page-class-2",
        )
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(FIXTURE.read_bytes())
    return prepare_reviewed_document(path)


def _empty_responses() -> tuple[Any, Any, Any]:
    empty: dict[str, object] = {"labels": [], "status": "empty", "evidence": []}
    return (
        MaterialEquipmentResponse.model_validate(empty),
        ProcessOperationsResponse.model_validate(empty),
        DocumentSupportingResponse.model_validate(empty),
    )


def _page_result(document: Any, page_number: int = 1) -> CompletedPageClassificationResult:
    page = next(item for item in document.pages if item.binding.page_number == page_number)
    binding = page.binding
    one, two, three = _empty_responses()
    outcomes = (
        persist_call_outcome(validate_call_response(binding, 1, one)),
        persist_call_outcome(validate_call_response(binding, 2, two)),
        persist_call_outcome(validate_call_response(binding, 3, three)),
    )
    source = SourceEvidenceValidation(
        binding=binding,
        items=(),
        has_unverified=False,
        requires_review=False,
    )
    eligibility = EligibilityDecision(
        binding=binding,
        eligible_for_extraction=True,
        reason="empty classification remains eligible",
        excluded_by_policy=False,
    )
    return CompletedPageClassificationResult(
        binding=binding,
        call_outcomes=outcomes,
        source_validation=source,
        kind="empty",
        labels=(),
        response_statuses=("empty", "empty", "empty"),
        reasons=("all three valid responses have status empty",),
        requires_review=False,
        is_provisional=False,
        applied_other_unclassified=False,
        eligibility=eligibility,
    )


def _rich_page_result(document: Any) -> CompletedPageClassificationResult:
    page = next(item for item in document.pages if item.binding.page_number == 2)
    binding = page.binding
    call1 = validate_call_response(
        binding,
        1,
        {
            "labels": ["BILL_OF_MATERIALS"],
            "status": "ok",
            "evidence": [
                {
                    "label": "BILL_OF_MATERIALS",
                    "quote": "Sodium Chloride",
                    "reason": "Materials table row.",
                    "element_id": "materials-table",
                }
            ],
        },
    )
    call2 = validate_call_response(
        binding,
        2,
        {"labels": [], "status": "ok", "evidence": []},
    )
    call3 = validate_call_response(
        binding,
        3,
        {"labels": [], "status": "ok", "evidence": []},
    )
    source = SourceEvidenceValidation(
        binding=binding,
        items=(
            EvidenceValidationItem(
                call_id=1,
                label="BILL_OF_MATERIALS",
                quote="Sodium Chloride",
                reason="Materials table row.",
                element_id="materials-table",
                verification="verified",
                verification_reason=None,
            ),
        ),
        has_unverified=False,
        requires_review=False,
    )
    eligibility = EligibilityDecision(
        binding=binding,
        eligible_for_extraction=True,
        reason="final labels are not exclusively exclusion labels; page remains eligible",
        excluded_by_policy=False,
    )
    return CompletedPageClassificationResult(
        binding=binding,
        call_outcomes=(
            persist_call_outcome(call1),
            persist_call_outcome(call2),
            persist_call_outcome(call3),
        ),
        source_validation=source,
        kind="completed",
        labels=(
            MergedLabelFinding(
                label="BILL_OF_MATERIALS",
                call_id=1,
                quote="Sodium Chloride",
                reason="Materials table row.",
                element_id="materials-table",
                provenance="call",
                evidence_verification="verified",
                evidence_verification_reason=None,
            ),
        ),
        response_statuses=("ok", "ok", "ok"),
        reasons=("all three responses are ok with a nonempty label union",),
        requires_review=False,
        is_provisional=False,
        applied_other_unclassified=False,
        eligibility=eligibility,
    )


def test_identity_key_deterministic_and_revision_sensitive(tmp_path: Path) -> None:
    first = _prepare(tmp_path / "a")
    again = _prepare(tmp_path / "b")
    other = _prepare(tmp_path / "c", alternate_revision=True)
    key_a = derive_reviewed_html_identity_key(first.reviewed_html)
    key_b = derive_reviewed_html_identity_key(again.reviewed_html)
    key_c = derive_reviewed_html_identity_key(other.reviewed_html)
    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64
    assert key_a.isalnum()
    store = PageClassificationStore(tmp_path / "data")
    path = store.current_path(first.reviewed_html)
    assert CLASSIFICATIONS_DIR_NAME in path.parts
    assert path.name == CURRENT_CLASSIFICATION_FILENAME
    assert key_a in path.parts
    other_path = store.current_path(other.reviewed_html)
    assert other_path != path
    assert key_c in other_path.parts


def test_atomic_write_and_validated_round_trip(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    page = _rich_page_result(document)
    state = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="completed",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=1,
            completed_pages=1,
            current_page_number=None,
        ),
        page_results=(page,),
        terminal_reason=None,
    )
    store.save(state)
    loaded = store.load(document.reviewed_html)
    assert loaded is not None
    assert loaded == state
    assert loaded.reviewed_html.html_sha256 == document.reviewed_html.html_sha256
    assert loaded.page_results[0].labels[0].label == "BILL_OF_MATERIALS"
    assert loaded.page_results[0].source_validation.items[0].verification == "verified"
    assert loaded.page_results[0].eligibility.eligible_for_extraction is True
    assert loaded.status == "completed"
    assert loaded.progress.completed_pages == 1


def test_empty_response_round_trip_preserves_call_schemas(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    page = _page_result(document, page_number=1)
    # Prove ambiguous unions would lose schema identity: all dumps look alike.
    dumped = [outcome.response for outcome in page.call_outcomes]
    assert dumped[0] == dumped[1] == dumped[2]
    state = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="completed",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=1,
            completed_pages=1,
            current_page_number=None,
        ),
        page_results=(page,),
        terminal_reason=None,
    )
    store.save(state)
    loaded = store.load(document.reviewed_html)
    assert loaded is not None
    restored: list[Any] = []
    for outcome in loaded.page_results[0].call_outcomes:
        assert isinstance(outcome, PersistedCallOutcome)
        runtime = validate_call_response(
            outcome.binding,
            outcome.call_id,
            outcome.response,
        )
        assert runtime.availability == "valid"
        assert runtime.response is not None
        restored.append(runtime.response)
    assert isinstance(restored[0], MaterialEquipmentResponse)
    assert isinstance(restored[1], ProcessOperationsResponse)
    assert isinstance(restored[2], DocumentSupportingResponse)
    assert [item.call_id for item in loaded.page_results[0].call_outcomes] == [1, 2, 3]


def test_missing_current_state_returns_none(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    assert store.load(document.reviewed_html) is None


def test_binding_mismatch_and_malformed_fail_closed(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    other = _prepare(tmp_path / "other", alternate_revision=True)
    store = PageClassificationStore(tmp_path / "data")
    path = store.current_path(document.reviewed_html)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PageClassificationStoreError):
        store.load(document.reviewed_html)

    path.write_text(
        json.dumps({"schema_version": "unknown", "status": "running"}),
        encoding="utf-8",
    )
    with pytest.raises(PageClassificationStoreError):
        store.load(document.reviewed_html)

    other_page = _page_result(other)
    other_state = CurrentClassificationState(
        reviewed_html=other.reviewed_html,
        status="completed",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=1,
            completed_pages=1,
            current_page_number=None,
        ),
        page_results=(other_page,),
    )
    path.write_text(
        json.dumps(other_state.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PageClassificationStoreError, match="binding"):
        store.load(document.reviewed_html)


def test_replace_current_state_creates_no_history(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    first = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="running",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=3,
            completed_pages=0,
            current_page_number=1,
        ),
    )
    store.save(first)
    second = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="completed",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=1,
            completed_pages=1,
            current_page_number=None,
        ),
        page_results=(_page_result(document),),
    )
    store.save(second)
    workspace = store.current_path(document.reviewed_html).parent
    names = sorted(path.name for path in workspace.iterdir())
    assert names == [CURRENT_CLASSIFICATION_FILENAME]
    loaded = store.load(document.reviewed_html)
    assert loaded is not None
    assert loaded.status == "completed"


def _write_completed_state_json(
    path: Path,
    document: Any,
    *,
    call_responses: tuple[dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    page = next(item for item in document.pages if item.binding.page_number == 1)
    binding_payload = page.binding.model_dump(mode="json")
    empty_source: dict[str, object] = {
        "binding": binding_payload,
        "items": [],
        "has_unverified": False,
        "requires_review": False,
    }
    eligibility: dict[str, object] = {
        "binding": binding_payload,
        "eligible_for_extraction": True,
        "reason": "empty classification remains eligible",
        "excluded_by_policy": False,
    }
    call_outcomes: list[dict[str, object]] = [
        {
            "binding": binding_payload,
            "call_id": call_id,
            "availability": "valid",
            "response": response,
            "failure_reason": None,
        }
        for call_id, response in zip((1, 2, 3), call_responses, strict=True)
    ]
    payload: dict[str, object] = {
        "schema_version": "batchlens.page-classification-current.v1",
        "classifier_policy_version": "batchlens.page-classification-policy.v1",
        "reviewed_html": document.reviewed_html.model_dump(mode="json"),
        "status": "completed",
        "created_at": FIXED_NOW.isoformat(),
        "updated_at": FIXED_NOW.isoformat(),
        "finished_at": FIXED_NOW.isoformat(),
        "progress": {
            "total_pages": 1,
            "completed_pages": 1,
            "current_page_number": None,
        },
        "page_results": [
            {
                "binding": binding_payload,
                "call_outcomes": call_outcomes,
                "source_validation": empty_source,
                "kind": "empty",
                "labels": [],
                "response_statuses": ["empty", "empty", "empty"],
                "reasons": ["all three valid responses have status empty"],
                "requires_review": False,
                "is_provisional": False,
                "applied_other_unclassified": False,
                "eligibility": eligibility,
            }
        ],
        "terminal_reason": None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_load_rejects_wrong_group_label_on_call_two(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    path = store.current_path(document.reviewed_html)
    empty: dict[str, object] = {"labels": [], "status": "empty", "evidence": []}
    wrong_group: dict[str, object] = {
        "labels": ["BILL_OF_MATERIALS"],
        "status": "ok",
        "evidence": [
            {
                "label": "BILL_OF_MATERIALS",
                "quote": "Sodium Chloride",
                "reason": "Wrong call group.",
                "element_id": None,
            }
        ],
    }
    _write_completed_state_json(path, document, call_responses=(empty, wrong_group, empty))
    with pytest.raises(PageClassificationStoreError):
        store.load(document.reviewed_html)
    with pytest.raises(PageClassificationStoreError):
        store.load_path(path)


def test_load_rejects_valid_response_missing_required_field(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    path = store.current_path(document.reviewed_html)
    empty: dict[str, object] = {"labels": [], "status": "empty", "evidence": []}
    missing_status: dict[str, object] = {"labels": [], "evidence": []}
    _write_completed_state_json(path, document, call_responses=(empty, missing_status, empty))
    with pytest.raises(PageClassificationStoreError):
        store.load(document.reviewed_html)
    with pytest.raises(PageClassificationStoreError):
        store.load_path(path)


def test_load_validates_empty_response_per_call_schema(tmp_path: Path) -> None:
    document = _prepare(tmp_path / "doc")
    store = PageClassificationStore(tmp_path / "data")
    path = store.current_path(document.reviewed_html)
    empty: dict[str, object] = {"labels": [], "status": "empty", "evidence": []}
    _write_completed_state_json(path, document, call_responses=(empty, empty, empty))
    loaded = store.load(document.reviewed_html)
    assert loaded is not None
    outcomes = loaded.page_results[0].call_outcomes
    assert [item.call_id for item in outcomes] == [1, 2, 3]
    restored = [
        validate_call_response(item.binding, item.call_id, item.response) for item in outcomes
    ]
    assert all(item.availability == "valid" for item in restored)
    assert isinstance(restored[0].response, MaterialEquipmentResponse)
    assert isinstance(restored[1].response, ProcessOperationsResponse)
    assert isinstance(restored[2].response, DocumentSupportingResponse)
    assert all(item.response is not None and item.response.status == "empty" for item in restored)
