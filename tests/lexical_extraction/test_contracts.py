"""Public lexical-extraction contract behavior."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.lexical_extraction.contracts import (
    RECORD_SCHEMA_VERSION,
    VALUE_RULE_ID,
    AmbiguityQualification,
    AmbiguousNumber,
    BlockEvidence,
    BlockRecord,
    CategoricalExpression,
    CharSpan,
    ChebiMaterialCandidate,
    ComparisonValue,
    Component,
    ComponentResult,
    CuedUnitlessValue,
    DictionaryOccurrence,
    EquipmentTypeCandidate,
    EquipmentUnitRecord,
    ExactDecimal,
    ExactEvidence,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FdaEmaMaterialCandidate,
    FinalManifestClaim,
    FuzzyEvidence,
    GenericCueCandidate,
    NormalizedExactEvidence,
    NumberUnitGroup,
    PageRecord,
    ParameterNameCandidate,
    Preset,
    PreValidationFailure,
    PublicationRecord,
    PublicationStatus,
    RangeValue,
    ReviewedHtmlV1Input,
    RunProvenance,
    SafeStructuredError,
    ScalarWithUnit,
    SymmetricTolerance,
    UnitMention,
    UnitOccurrence,
    ValueOccurrence,
    ValueRecognitionEvidence,
    validate_illustrative_result,
    validate_match_against_block,
    validate_resolved_component_coverage,
)

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "lexical_extraction" / "result-example.json"
)
HTML_SHA = "4fc6da769f8ff764fa10b02f657e60c1838f1ed37ec807e49527c0ce4df5e544"


def _span(start: int, end: int, text: str) -> CharSpan:
    return CharSpan(start_char=start, end_char=end, matched_text=text)


def _block(text: str = "water", **overrides: object) -> BlockEvidence:
    data: dict[str, object] = {
        "node_id": "node-1",
        "kind": "line",
        "text": text,
        "page_number": 1,
        "order": 0,
    }
    data.update(overrides)
    return BlockEvidence.model_validate(data)


def _input(**overrides: object) -> ReviewedHtmlV1Input:
    data: dict[str, object] = {
        "html_sha256": HTML_SHA,
        "html_contract_version": 1,
        "job_id": "fixture-lexical-job",
        "review_revision_id": "fixture-revision-0001",
        "review_generation": 1,
        "conversion_status": "SUCCEEDED",
    }
    data.update(overrides)
    return ReviewedHtmlV1Input.model_validate(data)


def _exact() -> ExactEvidence:
    return ExactEvidence()


def _round_trip(model: BaseModel) -> dict[str, object]:
    dumped: dict[str, object] = model.model_dump(mode="json")
    again: dict[str, object] = type(model).model_validate(dumped).model_dump(mode="json")
    assert dumped == again
    return dumped


def test_material_identities_stay_separate_and_generic_cues_have_no_operation_id() -> None:
    source_only = FdaEmaMaterialCandidate(
        matched_term="Purified water",
        source_field="material_name",
        snapshot_id="fixture-snapshot",
        row_id="fda-row-1",
        evidence=_exact(),
    )
    sms_only = FdaEmaMaterialCandidate(
        matched_term="Purified water",
        source_field="alias_name",
        snapshot_id="fixture-snapshot",
        row_id="fda-row-2",
        sms_id="SMS-1",
        alias_type="trade",
        evidence=_exact(),
    )
    chebi = ChebiMaterialCandidate(
        matched_term="water",
        source_field="material_name",
        snapshot_id="fixture-snapshot",
        row_id="chebi-row-1",
        chebi_id="CHEBI:15377",
        evidence=_exact(),
    )
    cue = GenericCueCandidate(
        matched_term="as needed",
        snapshot_id="fixture-snapshot",
        row_id="uo-row-1",
        operation_role="step_cue",
        evidence=_exact(),
    )

    assert source_only.unii is None
    assert source_only.sms_id is None
    assert sms_only.unii is None
    assert sms_only.sms_id == "SMS-1"
    assert source_only.table != chebi.table
    assert "operation_id" not in cue.model_dump()
    with pytest.raises(ValidationError):
        GenericCueCandidate.model_validate({**cue.model_dump(), "operation_id": "UO-1"})
    with pytest.raises(ValidationError):
        FdaEmaMaterialCandidate.model_validate(
            {
                **source_only.model_dump(),
                "evidence": {"method": "fuzzy", "dictionary_term": "water"},
            }
        )


def test_material_alias_text_is_not_language_filtered() -> None:
    """Alias text is accepted as supplied. This check does not detect language or search."""

    greek_alias = "νερό"
    fda = FdaEmaMaterialCandidate(
        matched_term=greek_alias,
        source_field="alias_name",
        snapshot_id="fixture-snapshot",
        row_id="fda-row-el",
        evidence=_exact(),
    )
    chebi = ChebiMaterialCandidate(
        matched_term=greek_alias,
        source_field="alias_name",
        snapshot_id="fixture-snapshot",
        row_id="chebi-row-el",
        evidence=_exact(),
    )

    assert fda.matched_term == greek_alias
    assert chebi.matched_term == greek_alias
    assert fda.source_field == "alias_name"
    assert chebi.source_field == "alias_name"


def test_related_synonym_and_context_required_survive_json_round_trip() -> None:
    candidate = ChebiMaterialCandidate(
        matched_term="oxidane",
        canonical_display_name="water",
        source_field="alias_name",
        snapshot_id="fixture-snapshot",
        row_id="chebi-row-9",
        alias_type="hasRelatedSynonym",
        ambiguity=AmbiguityQualification.CONTEXT_REQUIRED,
        evidence=_exact(),
    )

    dumped = _round_trip(candidate)

    assert dumped["alias_type"] == "hasRelatedSynonym"
    assert dumped["ambiguity"] == "context_required"
    assert dumped["canonical_display_name"] == "water"


def test_parameter_alternatives_do_not_create_an_equipment_association() -> None:
    first = ParameterNameCandidate(
        matched_term="Impeller speed",
        source_field="Operating parameter (EN)",
        snapshot_id="fixture-snapshot",
        row_id="eq-row-1",
        parameter_id="param-1",
        catalogue_equipment_type_id="type-a",
        catalogue_equipment_type_label="Bioreactor",
        evidence=_exact(),
    )
    second = ParameterNameCandidate(
        matched_term="Impeller speed",
        source_field="Operating parameter (EN)",
        snapshot_id="fixture-snapshot",
        row_id="eq-row-2",
        parameter_id="param-2",
        catalogue_equipment_type_id="type-b",
        evidence=_exact(),
    )

    dumped = first.model_dump()
    assert "equipment_mention_id" not in dumped
    assert first.catalogue_equipment_type_id != second.catalogue_equipment_type_id
    assert first.parameter_id != second.parameter_id
    with pytest.raises(ValidationError):
        EquipmentTypeCandidate.model_validate({**dumped, "candidate_kind": "equipment_type"})


def test_parameter_unit_and_value_are_independent_records() -> None:
    parameter = ParameterNameCandidate(
        matched_term="Impeller speed",
        snapshot_id="fixture-snapshot",
        row_id="eq-row-1",
        evidence=_exact(),
    )
    unit = UnitMention(
        literal_text="rpm",
        span=_span(0, 3, "rpm"),
        controlled_spelling="rpm",
        provenance=EquipmentUnitRecord(row_id="eq-unit-1", source_section="Equipment / units"),
        evidence=_exact(),
    )
    value = ScalarWithUnit(
        raw_expression="120 rpm",
        span=_span(0, 7, "120 rpm"),
        number=ExactDecimal(text="120"),
        source_unit_spelling="rpm",
        unit_span=_span(4, 7, "rpm"),
    )
    unitless = CuedUnitlessValue(
        raw_expression="N=2",
        span=_span(0, 3, "N=2"),
        cue="N=",
        number=ExactDecimal(text="2"),
    )

    assert "unit_span" not in parameter.model_dump()
    assert (
        value.model_dump().keys().isdisjoint({"parameter_id", "material_id", "equipment_type_id"})
    )
    assert "parameter_id" not in unit.model_dump()
    assert "unit_span" not in unitless.model_dump()
    with pytest.raises(ValidationError):
        UnitMention.model_validate({**unit.model_dump(), "parameter_id": "param-1"})
    with pytest.raises(ValidationError):
        EquipmentUnitRecord.model_validate(
            {"kind": "equipment_unit_record", "row_id": "eq-unit-1", "parameter_name": "Speed"}
        )
    with pytest.raises(ValidationError):
        UnitMention.model_validate(
            {**unit.model_dump(), "evidence": {"method": "fuzzy", "dictionary_term": "rpm"}}
        )


def test_original_unicode_slices_and_rejected_spans() -> None:
    text = "α\u0301\n\U0001f9ea"
    block = _block(text)
    acute = _span(0, 2, "α\u0301")
    newline = _span(2, 3, "\n")
    alembic = _span(3, 4, "\U0001f9ea")
    overlap = _span(0, 3, "α\u0301\n")

    validate_match_against_block(acute, block)
    validate_match_against_block(newline, block)
    validate_match_against_block(alembic, block)
    validate_match_against_block(overlap, block)
    assert block.text == text

    with pytest.raises(ValidationError):
        _span(-1, 1, "α")
    with pytest.raises(ValidationError):
        _span(2, 2, "x")
    with pytest.raises(ValidationError):
        _span(1, 0, "α")
    outside = _span(4, 5, "z")
    with pytest.raises(ValueError, match="outside"):
        validate_match_against_block(outside, block)
    mismatched = _span(0, 2, "αx")
    with pytest.raises(ValueError, match="does not equal"):
        validate_match_against_block(mismatched, _block("α\u0301"))


def test_empty_blocks_missing_ocr_and_input_absence() -> None:
    empty = _block("", ocr_references=[])
    assert empty.text == ""
    assert empty.ocr_references == ()
    spaced = _block("  a \n ")
    assert spaced.text == "  a \n "

    with pytest.raises(ValidationError):
        _block("a", node_id="")
    with pytest.raises(ValidationError):
        _block("a", page_number=0)
    with pytest.raises(ValidationError):
        _block("a", cell_geometry={"row": 0, "column": 1})

    with pytest.raises(ValidationError):
        _input(job_id=None)
    failure = PreValidationFailure(
        error=SafeStructuredError(
            code="INPUT_NOT_VALIDATED", message="HTML contract was not validated"
        )
    )
    dumped = failure.model_dump()
    assert dumped["validated_input"] is None
    assert "job_id" not in dumped
    assert "review_revision_id" not in dumped
    with pytest.raises(ValidationError):
        PreValidationFailure.model_validate(
            {**dumped, "job_id": "fixture-lexical-job", "review_generation": 1}
        )


def test_decimal_text_is_lossless_and_non_finite_values_are_rejected() -> None:
    number = ExactDecimal(text="1.10")
    ambiguous = AmbiguousNumber(raw_token="1,10")
    assert _round_trip(number)["text"] == "1.10"
    dumped = _round_trip(ambiguous)
    assert dumped["raw_token"] == "1,10"
    assert "text" not in dumped

    for rejected in ("NaN", "Infinity", "inf", "sNaN", "-Infinity"):
        with pytest.raises(ValidationError):
            ExactDecimal(text=rejected)
    with pytest.raises(ValidationError):
        ExactDecimal.model_validate({"kind": "exact_decimal", "text": 1.5})
    with pytest.raises(ValidationError):
        ExactDecimal.model_validate({"kind": "exact_decimal", "text": 10})


def test_completed_zero_partial_and_ambiguity_are_distinct() -> None:
    completed_zero = ComponentResult(
        component=Component.MATERIALS, outcome=ExtractionOutcome.COMPLETED, match_count=0
    )
    not_requested = ComponentResult(
        component=Component.EQUIPMENT, outcome=ExtractionOutcome.NOT_REQUESTED
    )
    failed = ComponentResult(
        component=Component.UNITS,
        outcome=ExtractionOutcome.FAILED,
        error=SafeStructuredError(
            code="COMPONENT_FAILED", message="unit scan failed", component=Component.UNITS
        ),
    )
    kept = ComponentResult(
        component=Component.PARAMETER_NAMES, outcome=ExtractionOutcome.COMPLETED, match_count=1
    )

    assert completed_zero.match_count == 0
    assert completed_zero.error is None
    with pytest.raises(ValidationError):
        ComponentResult(
            component=Component.EQUIPMENT, outcome=ExtractionOutcome.NOT_REQUESTED, match_count=0
        )
    with pytest.raises(ValidationError):
        ExtractionOutcomeRecord(
            overall=ExtractionOutcome.COMPLETED,
            components=(failed,),
        )
    with pytest.raises(ValidationError):
        ExtractionOutcomeRecord(overall=ExtractionOutcome.PARTIAL, components=(failed,))

    partial = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.PARTIAL,
        components=(kept, failed, not_requested, completed_zero),
    )
    assert partial.overall is ExtractionOutcome.PARTIAL
    assert kept.outcome is ExtractionOutcome.COMPLETED

    qualified = ChebiMaterialCandidate(
        matched_term="oxidane",
        source_field="alias_name",
        snapshot_id="fixture-snapshot",
        row_id="chebi-row-9",
        ambiguity=AmbiguityQualification.CONTEXT_REQUIRED,
        evidence=_exact(),
    )
    finished = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=(
            ComponentResult(
                component=Component.MATERIALS, outcome=ExtractionOutcome.COMPLETED, match_count=1
            ),
        ),
    )
    assert qualified.ambiguity is AmbiguityQualification.CONTEXT_REQUIRED
    assert finished.overall is ExtractionOutcome.COMPLETED


def test_partial_publication_is_separate_from_a_failed_manifest_claim() -> None:
    extraction = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.PARTIAL,
        components=(
            ComponentResult(
                component=Component.PARAMETER_NAMES,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=1,
            ),
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(code="COMPONENT_FAILED", message="material scan failed"),
            ),
        ),
    )
    published = PublicationRecord(
        status=PublicationStatus.COMPLETED,
        final_manifest=FinalManifestClaim(manifest_id="fixture-manifest"),
    )
    assert extraction.overall is ExtractionOutcome.PARTIAL
    assert published.status is PublicationStatus.COMPLETED

    with pytest.raises(ValidationError):
        PublicationRecord(
            status=PublicationStatus.FAILED,
            final_manifest=FinalManifestClaim(manifest_id="fixture-manifest"),
        )
    with pytest.raises(ValidationError):
        PublicationRecord.model_validate(
            {
                "status": "interrupted",
                "final_manifest": {
                    "manifest_id": "fixture-manifest",
                    "publication_status": "completed",
                },
            }
        )


def test_unknown_fields_versions_and_coercions_are_rejected() -> None:
    span = _span(0, 5, "water")
    first = span.model_dump(mode="json")
    second = CharSpan.model_validate(first).model_dump(mode="json")
    assert first == second
    assert first["matched_text"] == "water"

    with pytest.raises(ValidationError):
        CharSpan.model_validate({**first, "confidence": 0.9})
    with pytest.raises(ValidationError):
        _input(html_contract_version=2)
    with pytest.raises(ValidationError):
        _input(html_contract_version="1")
    with pytest.raises(ValidationError):
        _block("a", page_number="1")
    with pytest.raises(ValidationError):
        ComponentResult.model_validate(
            {"component": "materials", "outcome": "completed", "match_count": 0.0}
        )
    value_forms = (
        RangeValue(
            raw_expression="10-20 rpm",
            span=_span(0, 9, "10-20 rpm"),
            low=ExactDecimal(text="10"),
            high=ExactDecimal(text="20"),
            source_unit_spelling="rpm",
            unit_span=_span(6, 9, "rpm"),
        ),
        ComparisonValue(
            raw_expression=">10 rpm",
            span=_span(0, 7, ">10 rpm"),
            comparator=">",
            number=ExactDecimal(text="10"),
            source_unit_spelling="rpm",
            unit_span=_span(4, 7, "rpm"),
        ),
        SymmetricTolerance(
            raw_expression="10 ± 1 rpm",
            span=_span(0, 10, "10 ± 1 rpm"),
            center=ExactDecimal(text="10"),
            tolerance=ExactDecimal(text="1"),
            source_unit_spelling="rpm",
            unit_span=_span(7, 10, "rpm"),
        ),
        CategoricalExpression(
            raw_expression="clear solution",
            span=_span(0, 14, "clear solution"),
            category_label="clear solution",
        ),
    )
    for form in value_forms:
        assert _round_trip(form)["raw_expression"] == form.raw_expression


def test_checked_in_example_round_trips_without_changing_evidence() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    run, validated_input, extraction, publication, pages = validate_illustrative_result(payload)

    assert validated_input.html_contract_version == 1
    assert validated_input.external_document_id is None
    assert extraction.overall is ExtractionOutcome.PARTIAL
    assert publication.final_manifest is not None
    assert any(item.outcome is ExtractionOutcome.COMPLETED for item in extraction.components)
    block = pages[0].blocks[0].block
    assert block.text == "Impeller speed: 120 rpm"
    kinds = [occurrence.kind for occurrence in pages[0].blocks[0].occurrences]
    assert kinds == ["dictionary", "unit", "value"]
    value = pages[0].blocks[0].occurrences[2]
    assert isinstance(value, ValueOccurrence)
    assert value.applies_to == (
        Component.QUANTITY_EXPRESSIONS,
        Component.PARAMETER_VALUE_EXPRESSIONS,
    )
    assert value.recognition_rule.rule_id == VALUE_RULE_ID
    assert run.rules_sha256 == "60c79d146bd50add20e3265090ab8789bd5d26f6f7de82106a7769e9b58e0cd2"
    assert run.requested_presets == ()

    rebuilt = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "run": run.model_dump(mode="json"),
        "validated_input": validated_input.model_dump(mode="json"),
        "extraction": extraction.model_dump(mode="json"),
        "publication": publication.model_dump(mode="json"),
        "pages": [page.model_dump(mode="json") for page in pages],
    }
    again = validate_illustrative_result(rebuilt)
    assert again[1].model_dump() == validated_input.model_dump()
    assert again[4][0].blocks[0].block.text == block.text
    assert [item.outcome for item in again[2].components] == [
        item.outcome for item in extraction.components
    ]
    page_only = PageRecord.model_validate(payload["pages"][0])
    assert page_only.blocks[0].block.node_id == block.node_id


def test_overlapping_value_forms_do_not_require_a_parent() -> None:
    text = "Impeller speed: 120 rpm"
    parameter = _span(0, 14, "Impeller speed")
    grouped = ValueOccurrence(
        occurrence_id="value-1",
        block_node_id="node-1",
        expression=ScalarWithUnit(
            raw_expression="120 rpm",
            span=_span(16, 23, "120 rpm"),
            number=AmbiguousNumber(raw_token="120"),
            source_unit_spelling="rpm",
            unit_span=_span(20, 23, "rpm"),
        ),
        applies_to=(Component.QUANTITY_EXPRESSIONS, Component.PARAMETER_VALUE_EXPRESSIONS),
    )
    record = BlockRecord(
        block=_block(text),
        occurrences=(
            DictionaryOccurrence(
                occurrence_id="name-1",
                block_node_id="node-1",
                location=parameter,
                applies_to=(Component.PARAMETER_NAMES,),
                candidates=(
                    ParameterNameCandidate(
                        matched_term="Impeller speed",
                        snapshot_id="fixture-snapshot",
                        row_id="eq-row-1",
                        evidence=_exact(),
                    ),
                ),
            ),
            UnitOccurrence(
                occurrence_id="unit-1",
                block_node_id="node-1",
                mention=UnitMention(
                    literal_text="rpm",
                    span=_span(20, 23, "rpm"),
                    evidence=_exact(),
                ),
            ),
            grouped,
        ),
    )
    assert len(record.occurrences) == 3
    validate_match_against_block(parameter, record.block)
    validate_match_against_block(_span(20, 23, "rpm"), record.block)


RULES_SHA = "60c79d146bd50add20e3265090ab8789bd5d26f6f7de82106a7769e9b58e0cd2"


def _run(**overrides: object) -> RunProvenance:
    data: dict[str, object] = {
        "run_id": "fixture-run",
        "requested_components": ["materials"],
        "resolved_components": ["materials"],
        "input_html_sha256": HTML_SHA,
        "knowledge": {
            "snapshot_id": "fixture-snapshot",
            "database_sha256": "568d324fb0b12f1ef2255b2f45ce051da1a8bd53258e303f5d53edac81944495",
            "manifest_sha256": "35c53b7986dfb2897e7e2e9cdf56c69a49d2c1bcccaea7c310d60b11b59c9397",
        },
        "configuration_sha256": "41ed2a46e9c075dc9c6f98fb4f34c9784178884e77ef065f2d5ea6800d96704e",
        "rules_sha256": RULES_SHA,
        "engine_version": "not-executed",
    }
    data.update(overrides)
    return RunProvenance.model_validate(data)


def _material(term: str = "water") -> FdaEmaMaterialCandidate:
    return FdaEmaMaterialCandidate(
        matched_term=term,
        source_field="material_name",
        snapshot_id="fixture-snapshot",
        row_id="fda-row-1",
        evidence=_exact(),
    )


def test_value_spans_must_agree_and_unitless_values_remain_valid() -> None:
    with pytest.raises(ValidationError):
        ScalarWithUnit(
            raw_expression="999 kg",
            span=_span(0, 7, "120 rpm"),
            number=ExactDecimal(text="120"),
            source_unit_spelling="kg",
            unit_span=_span(4, 7, "rpm"),
        )
    with pytest.raises(ValidationError):
        ScalarWithUnit(
            raw_expression="120",
            span=_span(0, 3, "120"),
            number=ExactDecimal(text="120"),
            source_unit_spelling="rpm",
            unit_span=_span(11, 14, "rpm"),
        )
    with pytest.raises(ValidationError):
        ScalarWithUnit(
            raw_expression="120 rpm",
            span=_span(0, 7, "120 rpm"),
            number=ExactDecimal(text="120"),
            source_unit_spelling="rpm",
            unit_span=_span(4, 7, "rpm"),
            number_unit_group=NumberUnitGroup(
                number_span=_span(0, 3, "120"),
                unit_span=_span(4, 7, "rpm"),
                group_span=_span(0, 3, "120"),
            ),
        )

    text = "α\u0301 rpm"
    nested = ScalarWithUnit(
        raw_expression=text,
        span=_span(0, 6, text),
        number=AmbiguousNumber(raw_token="α\u0301"),
        source_unit_spelling="rpm",
        unit_span=_span(3, 6, "rpm"),
        number_unit_group=NumberUnitGroup(
            number_span=_span(0, 2, "α\u0301"),
            unit_span=_span(3, 6, "rpm"),
            group_span=_span(0, 6, text),
        ),
    )
    assert nested.unit_span is not None
    assert nested.span.matched_text[3:6] == nested.unit_span.matched_text
    unit = UnitMention(literal_text="rpm", span=_span(0, 3, "rpm"), evidence=_exact())
    assert unit.literal_text == unit.span.matched_text
    with pytest.raises(ValidationError):
        UnitMention(literal_text="kg", span=_span(0, 3, "rpm"), evidence=_exact())
    unitless = CuedUnitlessValue(
        raw_expression="N=2",
        span=_span(0, 3, "N=2"),
        cue="N=",
        number=ExactDecimal(text="2"),
    )
    assert unitless.raw_expression == unitless.span.matched_text


def test_dictionary_occurrences_require_source_candidates_and_honest_exact_terms() -> None:
    location = _span(0, 5, "water")
    with pytest.raises(ValidationError):
        DictionaryOccurrence(
            occurrence_id="occ-1",
            block_node_id="node-1",
            location=location,
            applies_to=(Component.MATERIALS,),
            candidates=(),
        )
    with pytest.raises(ValidationError):
        DictionaryOccurrence(
            occurrence_id="occ-1",
            block_node_id="node-1",
            location=location,
            applies_to=(Component.MATERIALS,),
            candidates=(_material("Mixer"),),
        )
    accepted = DictionaryOccurrence(
        occurrence_id="occ-1",
        block_node_id="node-1",
        location=location,
        applies_to=(Component.MATERIALS,),
        candidates=(
            _material("water"),
            ChebiMaterialCandidate(
                matched_term="oxidane",
                source_field="alias_name",
                snapshot_id="fixture-snapshot",
                row_id="chebi-row-1",
                evidence=NormalizedExactEvidence(),
            ),
        ),
    )
    source_only = accepted.candidates[0]
    assert isinstance(source_only, FdaEmaMaterialCandidate)
    assert source_only.unii is None
    cue = DictionaryOccurrence(
        occurrence_id="cue-1",
        block_node_id="node-1",
        location=_span(0, 9, "as needed"),
        applies_to=(Component.UNIT_OPERATIONS,),
        candidates=(
            GenericCueCandidate(
                matched_term="as needed",
                snapshot_id="fixture-snapshot",
                row_id="uo-row-1",
                operation_role="step_cue",
                evidence=_exact(),
            ),
        ),
    )
    assert "operation_id" not in cue.candidates[0].model_dump()


def test_requested_presets_stay_separate_from_resolved_components() -> None:
    combined = _run(
        requested_presets=["materials", "equipment"],
        requested_components=["materials", "equipment"],
        resolved_components=["materials", "equipment", "parameter_names"],
    )
    dumped = _round_trip(combined)
    assert dumped["requested_presets"] == ["materials", "equipment"]
    assert dumped["resolved_components"] == ["materials", "equipment", "parameter_names"]
    assert combined.requested_presets == (Preset.MATERIALS, Preset.EQUIPMENT)

    component_only = _run(
        requested_presets=[],
        requested_components=["units"],
        resolved_components=["units"],
    )
    assert component_only.requested_presets == ()
    assert component_only.requested_components == (Component.UNITS,)


def test_resolved_component_coverage_rejects_missing_and_unexpected_work() -> None:
    materials_done = ComponentResult(
        component=Component.MATERIALS,
        outcome=ExtractionOutcome.COMPLETED,
        match_count=0,
    )
    equipment_done = ComponentResult(
        component=Component.EQUIPMENT,
        outcome=ExtractionOutcome.COMPLETED,
        match_count=1,
    )
    equipment_skipped = ComponentResult(
        component=Component.EQUIPMENT,
        outcome=ExtractionOutcome.NOT_REQUESTED,
    )
    run = _run(resolved_components=["materials", "equipment"])
    completed = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=(materials_done, equipment_done),
    )
    validate_resolved_component_coverage(run, completed)

    with pytest.raises(ValueError, match="exactly one outcome"):
        validate_resolved_component_coverage(
            run,
            ExtractionOutcomeRecord(
                overall=ExtractionOutcome.COMPLETED,
                components=(materials_done,),
            ),
        )
    with pytest.raises(ValueError, match="not_requested"):
        validate_resolved_component_coverage(
            run,
            ExtractionOutcomeRecord(
                overall=ExtractionOutcome.COMPLETED,
                components=(materials_done, equipment_skipped),
            ),
        )
    with pytest.raises(ValueError, match="outside the resolved"):
        validate_resolved_component_coverage(
            _run(resolved_components=["materials"]),
            ExtractionOutcomeRecord(
                overall=ExtractionOutcome.PARTIAL,
                components=(
                    materials_done,
                    ComponentResult(
                        component=Component.EQUIPMENT,
                        outcome=ExtractionOutcome.FAILED,
                        error=SafeStructuredError(code="COMPONENT_FAILED", message="unexpected"),
                    ),
                ),
            ),
        )


def test_value_rule_and_rules_hash_round_trip() -> None:
    occurrence = ValueOccurrence(
        occurrence_id="value-1",
        block_node_id="node-1",
        expression=CuedUnitlessValue(
            raw_expression="N=2",
            span=_span(0, 3, "N=2"),
            cue="N=",
            number=ExactDecimal(text="2"),
        ),
        recognition_rule=ValueRecognitionEvidence(),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    dumped = _round_trip(occurrence)
    assert dumped["recognition_rule"] == {"rule_id": VALUE_RULE_ID}
    provenance = _round_trip(_run())
    assert provenance["rules_sha256"] == RULES_SHA
    assert provenance["rules_version"] == "lexical-internal-rules-v1"
    with pytest.raises(ValidationError):
        _run(rules_sha256="not-a-hash")
    with pytest.raises(ValidationError):
        ValueOccurrence.model_validate(
            {
                **occurrence.model_dump(),
                "recognition_rule": {"rule_id": "custom-parser"},
            }
        )


def test_fuzzy_evidence_is_a_bounded_single_word_claim() -> None:
    valid = FuzzyEvidence(dictionary_term="Impeller", edit_distance=1)
    assert _round_trip(valid)["edit_distance"] == 1
    candidate = ParameterNameCandidate(
        matched_term="Impeller",
        snapshot_id="fixture-snapshot",
        row_id="eq-row-9",
        evidence=valid,
    )
    occurrence = DictionaryOccurrence(
        occurrence_id="fuzzy-1",
        block_node_id="node-1",
        location=_span(0, 7, "Impeler"),
        applies_to=(Component.PARAMETER_NAMES,),
        candidates=(candidate,),
    )
    assert occurrence.candidates[0].matched_term == "Impeller"
    for payload in (
        {"dictionary_term": "Impeller"},
        {"dictionary_term": "Impeller", "edit_distance": 999},
        {"dictionary_term": "Impeller", "edit_distance": "1"},
        {"dictionary_term": "rpm", "edit_distance": 1},
        {"dictionary_term": "Impeller speed", "edit_distance": 1},
    ):
        with pytest.raises(ValidationError):
            FuzzyEvidence.model_validate({"method": "fuzzy", **payload})
    with pytest.raises(ValidationError):
        FdaEmaMaterialCandidate(
            matched_term="Glucose",
            source_field="material_name",
            snapshot_id="fixture-snapshot",
            row_id="fda-row-9",
            evidence=FuzzyEvidence(dictionary_term="Glucose", edit_distance=1),
        )


def test_supporting_row_ids_are_optional_and_exclude_representative() -> None:
    legacy = FdaEmaMaterialCandidate.model_validate(
        {
            "matched_term": "water",
            "source_field": "material_name",
            "snapshot_id": "fixture-snapshot",
            "row_id": "fda-row-1",
            "evidence": {"method": "exact", "rule_id": "lexical-v1-exact"},
        }
    )
    assert legacy.supporting_row_ids == ()
    dumped = _round_trip(legacy)
    assert dumped["supporting_row_ids"] == []

    supported = FdaEmaMaterialCandidate(
        matched_term="water",
        source_field="material_name",
        snapshot_id="fixture-snapshot",
        row_id="fda-row-1",
        supporting_row_ids=("fda-row-2", "fda-row-3"),
        evidence=_exact(),
    )
    assert supported.supporting_row_ids == ("fda-row-2", "fda-row-3")
    with pytest.raises(ValidationError):
        FdaEmaMaterialCandidate(
            matched_term="water",
            source_field="material_name",
            snapshot_id="fixture-snapshot",
            row_id="fda-row-1",
            supporting_row_ids=("fda-row-1",),
            evidence=_exact(),
        )
    with pytest.raises(ValidationError):
        FdaEmaMaterialCandidate(
            matched_term="water",
            source_field="material_name",
            snapshot_id="fixture-snapshot",
            row_id="fda-row-1",
            supporting_row_ids=("fda-row-2", "fda-row-2"),
            evidence=_exact(),
        )

    unit_legacy = EquipmentUnitRecord.model_validate(
        {"kind": "equipment_unit_record", "row_id": "eq-unit-1"}
    )
    assert unit_legacy.supporting_row_ids == ()
    unit_supported = EquipmentUnitRecord(row_id="eq-a", supporting_row_ids=("eq-b", "eq-c"))
    assert unit_supported.supporting_row_ids == ("eq-b", "eq-c")
    with pytest.raises(ValidationError):
        EquipmentUnitRecord(row_id="eq-a", supporting_row_ids=("eq-a",))
    with pytest.raises(ValidationError):
        EquipmentUnitRecord(row_id="eq-a", supporting_row_ids=("eq-b", "eq-b"))
