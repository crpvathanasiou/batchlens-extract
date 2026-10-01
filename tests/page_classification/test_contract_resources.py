"""Integrated prompt/schema resource synchronization checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from app.page_classification.page_classification_schemas import (
    DOCUMENT_SUPPORTING_LABELS,
    MATERIAL_EQUIPMENT_LABELS,
    PROCESS_OPERATIONS_LABELS,
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "app" / "page_classification"
PROMPTS = PACKAGE_ROOT / "prompts"
SCHEMAS = PACKAGE_ROOT / "json_schemas"

PROMPT_FILES = (
    ("01-materials-equipment.txt", MaterialEquipmentResponse, MATERIAL_EQUIPMENT_LABELS),
    (
        "02-process-operations-controls.txt",
        ProcessOperationsResponse,
        PROCESS_OPERATIONS_LABELS,
    ),
    (
        "03-document-supporting-records.txt",
        DocumentSupportingResponse,
        DOCUMENT_SUPPORTING_LABELS,
    ),
)

SCHEMA_FILES = (
    ("01-materials-equipment.schema.json", MaterialEquipmentResponse),
    ("02-process-operations-controls.schema.json", ProcessOperationsResponse),
    ("03-document-supporting-records.schema.json", DocumentSupportingResponse),
)

ROLE_INTRO = "You are a pharmaceutical batch-record page classifier with expertise in"


def test_generated_json_schemas_equal_model_validation_schemas() -> None:
    for filename, model in SCHEMA_FILES:
        on_disk = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
        generated = model.model_json_schema(mode="validation")
        assert on_disk == generated


@pytest.mark.parametrize(("filename", "model", "labels"), PROMPT_FILES)
def test_prompt_label_lists_match_models(
    filename: str,
    model: type[object],
    labels: tuple[str, ...],
) -> None:
    text = (PROMPTS / filename).read_text(encoding="utf-8")
    assert text.startswith(ROLE_INTRO)
    for label in labels:
        assert label in text
    listed: list[str] = []
    if "Allowed labels:\n" in text:
        block = text.split("Allowed labels:\n", 1)[1]
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                break
            if stripped in labels:
                listed.append(stripped)
            elif listed:
                break
    else:
        block = text.split("ALLOWED LABELS AND DEFINITIONS\n", 1)[1]
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split(":", 1)[0].strip()
            if name in labels:
                listed.append(name)
            elif listed and name.isupper() and name not in labels:
                break
            elif listed and not name.isupper():
                # Continue scanning definitions; stop once a non-label section starts.
                if stripped.startswith("SHORT EXAMPLES") or stripped.startswith("EVIDENCE RULES"):
                    break
    assert listed == list(labels)
    assert list(model.LABEL_ORDER) == list(labels)  # type: ignore[attr-defined]


@pytest.mark.parametrize(("filename", "model", "labels"), PROMPT_FILES)
def test_prompts_do_not_require_label_or_evidence_order(
    filename: str,
    model: type[object],
    labels: tuple[str, ...],
) -> None:
    del model, labels
    text = (PROMPTS / filename).read_text(encoding="utf-8")
    assert "in output order" not in text
    assert "output in this order" not in text
    assert "in the same order as labels" not in text
    assert "in definition order" not in text
    assert "in the listed order" not in text
    assert "in any order" in text


_IDENTIFIER_CONTRACT_MARKERS = (
    "id, data-node-id, data-element-id, or data-table-id",
    "smallest identifiable element containing the complete quote",
    "nearest identifiable ancestor",
    "Use null when no suitable identifier exists",
    "Never invent, repair, or convert",
)


@pytest.mark.parametrize(("filename", "model", "labels"), PROMPT_FILES)
def test_prompts_express_supported_identifier_contract(
    filename: str,
    model: type[object],
    labels: tuple[str, ...],
) -> None:
    del model, labels
    text = (PROMPTS / filename).read_text(encoding="utf-8")
    for marker in _IDENTIFIER_CONTRACT_MARKERS:
        assert marker in text
    assert "not substitutes for id" not in text


@pytest.mark.parametrize(("filename", "model"), SCHEMA_FILES)
def test_schema_element_id_description_matches_supported_identifiers(
    filename: str,
    model: type[object],
) -> None:
    schema = cast(dict[str, Any], model.model_json_schema(mode="validation"))  # type: ignore[attr-defined]
    items = cast(dict[str, Any], schema["properties"]["evidence"]["items"])
    ref = cast(str, items["$ref"]).split("/")[-1]
    defs = cast(dict[str, Any], schema["$defs"])
    description = cast(str, defs[ref]["properties"]["element_id"]["description"])
    assert "id, data-node-id, data-element-id, or data-table-id" in description
    assert "smallest identifiable element" in description
    assert "Never invent, repair, or convert" in description
    on_disk = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    assert on_disk == schema


@pytest.mark.parametrize(("filename", "model", "labels"), PROMPT_FILES)
def test_prompts_specify_corrected_quote_bound(
    filename: str,
    model: type[object],
    labels: tuple[str, ...],
) -> None:
    del model, labels
    text = (PROMPTS / filename).read_text(encoding="utf-8")
    assert "1-240 characters" in text
    assert re.search(r"quote:.*1-240 characters", text) is not None
    assert "1-600 characters" not in text
    assert "600 characters" not in text


def test_no_integrated_contract_resource_keeps_superseded_quote_maximum() -> None:
    for path in list(PROMPTS.glob("*.txt")) + list(SCHEMAS.glob("*.schema.json")):
        text = path.read_text(encoding="utf-8")
        assert 'maxLength": 600' not in text
        assert "max_length=600" not in text
        assert "1-600" not in text


@pytest.mark.parametrize(("filename", "model"), SCHEMA_FILES)
def test_schema_quote_max_length_is_240(filename: str, model: type[object]) -> None:
    del filename
    schema = cast(dict[str, Any], model.model_json_schema(mode="validation"))  # type: ignore[attr-defined]
    items = cast(dict[str, Any], schema["properties"]["evidence"]["items"])
    ref = cast(str, items["$ref"]).split("/")[-1]
    defs = cast(dict[str, Any], schema["$defs"])
    quote = cast(dict[str, Any], defs[ref]["properties"]["quote"])
    assert quote["maxLength"] == 240
    assert quote["minLength"] == 1


def test_prompt_json_examples_validate() -> None:
    example_re = re.compile(
        r'\{\s*"labels"\s*:\s*\[.*?\]\s*,\s*"status"\s*:\s*"[^"]+"\s*,\s*"evidence"\s*:\s*\[.*?\]\s*\}'
    )
    for filename, model, _labels in PROMPT_FILES:
        text = (PROMPTS / filename).read_text(encoding="utf-8")
        examples = example_re.findall(text)
        assert examples, filename
        for raw in examples:
            model.model_validate_json(raw)  # type: ignore[attr-defined]
