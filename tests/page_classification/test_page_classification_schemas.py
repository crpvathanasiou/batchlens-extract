"""Response-contract tests only; no model calls or classification experiments."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.page_classification.page_classification_schemas import (
    DOCUMENT_SUPPORTING_LABELS,
    MATERIAL_EQUIPMENT_LABELS,
    PROCESS_OPERATIONS_LABELS,
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)

MODELS = (
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
    DocumentSupportingResponse,
)


def payload(labels: tuple[str, ...] | list[str] = (), status: str = "ok") -> dict[str, Any]:
    return {
        "labels": list(labels),
        "status": status,
        "evidence": [
            {
                "label": label,
                "quote": "Source text",
                "reason": "Supporting criterion.",
                "element_id": None,
            }
            for label in labels
        ],
    }


def test_both_critical_labels_are_accepted_together() -> None:
    raw = json.dumps(payload(["BILL_OF_MATERIALS", "EQUIPMENT_LIST"]))
    result = MaterialEquipmentResponse.model_validate_json(raw)
    assert result.labels == ["BILL_OF_MATERIALS", "EQUIPMENT_LIST"]


@pytest.mark.parametrize("model", MODELS)
def test_each_allowed_label_is_accepted_as_json_and_python(model: type[Any]) -> None:
    for label in model.LABEL_ORDER:
        data = payload([label])
        assert model.model_validate(data).labels == [label]
        result = model.model_validate_json(json.dumps(data))
        assert result.model_dump() == data


@pytest.mark.parametrize("model", MODELS)
def test_all_labels_in_prompt_order_are_accepted(model: type[Any]) -> None:
    data = payload(model.LABEL_ORDER)
    assert model.model_validate(data).model_dump() == data


@pytest.mark.parametrize("model", MODELS)
def test_nonadjacent_labels_in_prompt_order_are_accepted(model: type[Any]) -> None:
    labels = [model.LABEL_ORDER[0], model.LABEL_ORDER[-1]]
    assert model.model_validate(payload(labels)).labels == labels


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("status", ("ok", "empty", "needs_review"))
def test_empty_labels_are_valid_for_each_status(model: type[Any], status: str) -> None:
    result = model.model_validate_json(json.dumps(payload(status=status)))
    assert result.labels == []
    assert result.status == status


@pytest.mark.parametrize("model", MODELS)
def test_review_status_preserves_supported_labels(model: type[Any]) -> None:
    labels = [model.LABEL_ORDER[0]]
    result = model.model_validate(payload(labels, "needs_review"))
    assert result.labels == labels


@pytest.mark.parametrize("model", MODELS)
def test_empty_status_cannot_have_labels(model: type[Any]) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate_json(json.dumps(payload([model.LABEL_ORDER[0]], "empty")))
    assert error.value.errors()[0]["type"] == "empty_status_with_labels"


@pytest.mark.parametrize("model", MODELS)
def test_duplicate_labels_are_rejected_not_deduplicated(model: type[Any]) -> None:
    first = model.LABEL_ORDER[0]
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload([first, first]))
    assert error.value.errors()[0]["type"] == "duplicate_labels"


@pytest.mark.parametrize("model", MODELS)
def test_out_of_order_labels_are_rejected_not_sorted(model: type[Any]) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload(list(reversed(model.LABEL_ORDER))))
    assert error.value.errors()[0]["type"] == "label_order"


@pytest.mark.parametrize("target", MODELS)
def test_labels_from_every_other_call_are_rejected(target: type[Any]) -> None:
    for other in MODELS:
        if other is target:
            continue
        for label in other.LABEL_ORDER:
            with pytest.raises(ValidationError):
                target.model_validate_json(json.dumps(payload([label])))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("label", ("OTHER_UNCLASSIFIED", "NON_BATCH_RECORD", "UNKNOWN_LABEL"))
def test_fallback_old_name_and_unknown_label_are_rejected(model: type[Any], label: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload([label]))


@pytest.mark.parametrize("model", MODELS)
def test_label_case_and_whitespace_are_not_repaired(model: type[Any]) -> None:
    first = model.LABEL_ORDER[0]
    for label in (first.lower(), f" {first}", f"{first} "):
        with pytest.raises(ValidationError):
            model.model_validate(payload([label]))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("status", ("OK", "error", "unknown", " ok", "", None, 1, True))
def test_invalid_status_values_are_rejected(model: type[Any], status: object) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload(status=status))  # type: ignore[arg-type]


@pytest.mark.parametrize("model", MODELS)
def test_missing_fields_are_rejected(model: type[Any]) -> None:
    cases: list[dict[str, Any]] = [
        {},
        {"labels": []},
        {"status": "ok"},
        {"labels": [], "status": "ok"},
    ]
    for data in cases:
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize("model", MODELS)
def test_extra_fields_are_rejected(model: type[Any]) -> None:
    for key, value in (("confidence", 0.9), ("reason", "text"), ("page_id", "p1")):
        with pytest.raises(ValidationError):
            model.model_validate({**payload(), key: value})


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    "labels",
    (None, "BILL_OF_MATERIALS", {}, (), set[Any](), 3, True),
)
def test_labels_must_be_a_list_without_coercion(model: type[Any], labels: object) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload(), "labels": labels})


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("value", (None, 0, True, [], {}, b"BILL_OF_MATERIALS"))
def test_label_items_must_be_valid_strings(model: type[Any], value: object) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload(), "labels": [value]})


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    "raw",
    (
        '{"labels":[],"status":',
        '```json\n{"labels":[],"status":"ok"}\n```',
        'Here is the result: {"labels":[],"status":"ok"}',
        '{"labels":[],"status":"ok"} trailing text',
        "[]",
        "null",
    ),
)
def test_invalid_or_wrapped_json_is_rejected(model: type[Any], raw: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate_json(raw)


@pytest.mark.parametrize("model", MODELS)
def test_existing_instances_are_revalidated(model: type[Any]) -> None:
    result = model.model_validate(payload())
    first = model.LABEL_ORDER[0]
    result.labels.extend([first, first])
    with pytest.raises(ValidationError):
        model.model_validate(result)


@pytest.mark.parametrize("model", MODELS)
def test_schema_has_exact_required_fields_and_call_specific_enum(model: type[Any]) -> None:
    schema = model.model_json_schema(mode="validation")
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["labels", "status", "evidence"]
    assert set(schema["properties"]) == {"labels", "status", "evidence"}
    labels_schema = schema["properties"]["labels"]
    assert labels_schema["type"] == "array"
    assert labels_schema["items"]["enum"] == list(model.LABEL_ORDER)
    assert schema["properties"]["status"]["enum"] == ["ok", "empty", "needs_review"]


def test_label_partition_has_2_19_19_disjoint_members() -> None:
    groups = (
        MATERIAL_EQUIPMENT_LABELS,
        PROCESS_OPERATIONS_LABELS,
        DOCUMENT_SUPPORTING_LABELS,
    )
    assert [len(group) for group in groups] == [2, 19, 19]
    labels = [label for group in groups for label in group]
    assert len(set(labels)) == 40
    assert "OTHER_UNCLASSIFIED" not in labels


@pytest.mark.parametrize("model", MODELS)
def test_evidence_matches_labels_exactly(model: type[Any]) -> None:
    first, second = model.LABEL_ORDER[:2]
    mismatched: list[list[dict[str, Any]]] = [
        [],
        list(payload([second])["evidence"]),
        list(payload([first, first])["evidence"]),
    ]
    for evidence in mismatched:
        data = payload([first])
        data["evidence"] = evidence
        with pytest.raises(ValidationError) as error:
            model.model_validate(data)
        assert error.value.errors()[0]["type"] == "evidence_label_mismatch"
    data = payload([first, second])
    cast(list[Any], data["evidence"]).reverse()
    with pytest.raises(ValidationError):
        model.model_validate(data)
    data = payload()
    data["evidence"] = list(payload([first])["evidence"])
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model", MODELS)
def test_evidence_fields_required_no_extras(model: type[Any]) -> None:
    for field in ("label", "quote", "reason", "element_id"):
        data = payload([model.LABEL_ORDER[0]])
        del data["evidence"][0][field]
        with pytest.raises(ValidationError):
            model.model_validate(data)
    data = payload([model.LABEL_ORDER[0]])
    data["evidence"][0]["confidence"] = 0.9
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model", MODELS)
def test_evidence_text_bounds_types_and_blank_values(model: type[Any]) -> None:
    for field, limit in (("quote", 240), ("reason", 240), ("element_id", 256)):
        for value in ("", " \n\t", "x" * (limit + 1), 3, True):
            data = payload([model.LABEL_ORDER[0]])
            data["evidence"][0][field] = value
            with pytest.raises(ValidationError):
                model.model_validate(data)
        data = payload([model.LABEL_ORDER[0]])
        data["evidence"][0][field] = "x" * limit
        assert model.model_validate(data).model_dump() == data
    for field in ("quote", "reason"):
        data = payload([model.LABEL_ORDER[0]])
        data["evidence"][0][field] = None
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize("model", MODELS)
def test_quote_length_one_and_two_forty_accepted_two_forty_one_rejected(
    model: type[Any],
) -> None:
    data = payload([model.LABEL_ORDER[0]])
    data["evidence"][0]["quote"] = "x"
    assert model.model_validate(data).evidence[0].quote == "x"
    data["evidence"][0]["quote"] = "y" * 240
    assert len(model.model_validate(data).evidence[0].quote) == 240
    data["evidence"][0]["quote"] = "z" * 241
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model", MODELS)
def test_evidence_enum_id_and_nested_revalidation(model: type[Any]) -> None:
    other = next(item for item in MODELS if item is not model)
    data = payload([model.LABEL_ORDER[0]])
    data["evidence"][0]["label"] = other.LABEL_ORDER[0]
    with pytest.raises(ValidationError):
        model.model_validate(data)
    for element_id in (None, "materials-table-03"):
        data = payload([model.LABEL_ORDER[0]])
        data["evidence"][0]["element_id"] = element_id
        result = model.model_validate(data)
        assert result.evidence[0].element_id == element_id
        result.evidence[0].quote = " "
        with pytest.raises(ValidationError):
            model.model_validate(result)
    schema = model.model_json_schema()
    ref = schema["properties"]["evidence"]["items"]["$ref"].split("/")[-1]
    item = schema["$defs"][ref]
    assert item["required"] == ["label", "quote", "reason", "element_id"]
    assert item["additionalProperties"] is False
    assert item["properties"]["label"]["enum"] == list(model.LABEL_ORDER)
