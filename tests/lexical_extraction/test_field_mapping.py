"""Fixed V1 source-field mapping from flat SourceRow values to eligible terms."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.lexical_extraction.contracts import Component
from app.lexical_extraction.field_mapping import (
    EligibleSearchTerm,
    FieldMappingError,
    fuzzy_shape_eligible,
    index_this_row_authorizes,
    is_eligible_equipment_unit_spelling,
    is_unavailable_identity_marker,
    iter_eligible_terms,
    map_source_row,
    tables_for_components,
)
from app.lexical_extraction.knowledge_snapshot import (
    FLAT_SOURCE_TABLES,
    SourceBatch,
    SourceRow,
)

_HEADERS = dict(FLAT_SOURCE_TABLES)


def _row(table: str, row_id: str, **overrides: str) -> SourceRow:
    headers = _HEADERS[table]
    values = dict.fromkeys(headers, "")
    values["row_id"] = row_id
    values.update(overrides)
    return SourceRow(
        table_name=table,
        scan_cursor=1,
        row_id=row_id,
        values=tuple((header, values[header]) for header in headers),
    )


def _fields(terms: tuple[EligibleSearchTerm, ...]) -> list[tuple[str, str, str]]:
    return [(term.component.value, term.source_field, term.literal) for term in terms]


def test_fda_ema_permitted_and_excluded_fields() -> None:
    row = _row(
        "materials_fda_ema",
        "fda-1",
        material_name="Water",
        alias_name="aqua",
        UNII="059QF0KO0R",
        SMS_ID="100000",
        CAS_NUMBER="7732-18-5",
        alias_type="sys",
        source="FDA",
        lexical_term_id="term-1",
        Language="en",
        Is_Preferred_Name="True",
        match_status="matched",
    )
    terms = map_source_row(row, components=(Component.MATERIALS,))
    assert _fields(terms) == [
        ("materials", "material_name", "Water"),
        ("materials", "alias_name", "aqua"),
        ("materials", "UNII", "059QF0KO0R"),
    ]
    assert all(term.term_role != "sms_id" for term in terms)
    assert all(term.source_field != "CAS_NUMBER" for term in terms)
    assert all(term.source_field != "SMS_ID" for term in terms)
    unii = terms[2]
    assert unii.term_role == "unii_code"
    assert unii.boundary_hint == "whole_code"
    assert unii.fuzzy_allowed is False
    assert unii.unii == "059QF0KO0R"
    assert unii.sms_id == "100000"
    assert unii.display_name == "Water"
    assert map_source_row(row, components=(Component.EQUIPMENT,)) == ()


def test_chebi_alias_qualification_and_no_id_search() -> None:
    related = _row(
        "materials_chebi",
        "chebi-related",
        material_name="medicarpin",
        alias_name="related spelling",
        CHEBI_ID="CHEBI:100",
        alias_type="hasRelatedSynonym",
        CAS_NUMBER="32383-76-9",
        source="ChEBI",
        source_version="v1",
        source_record="rec-1",
        lexical_term_id="lt-1",
    )
    exact = _row(
        "materials_chebi",
        "chebi-exact",
        material_name="medicarpin",
        alias_name="exact spelling",
        CHEBI_ID="CHEBI:100",
        alias_type="hasExactSynonym",
        lexical_term_id="lt-2",
    )
    blank_alias = _row(
        "materials_chebi",
        "chebi-blank",
        material_name="usable name",
        alias_name="",
        CHEBI_ID="",
        lexical_term_id="lt-3",
    )
    related_terms = map_source_row(related, components=(Component.MATERIALS,))
    exact_terms = map_source_row(exact, components=(Component.MATERIALS,))
    blank_terms = map_source_row(blank_alias, components=(Component.MATERIALS,))
    assert _fields(related_terms) == [
        ("materials", "material_name", "medicarpin"),
        ("materials", "alias_name", "related spelling"),
    ]
    related_alias = next(term for term in related_terms if term.source_field == "alias_name")
    assert related_alias.alias_type == "hasRelatedSynonym"
    assert related_alias.term_role == "material_alias"
    assert exact_terms[1].alias_type == "hasExactSynonym"
    assert all(term.source_field != "CAS_NUMBER" for term in related_terms)
    assert all(term.source_field != "CHEBI_ID" for term in related_terms)
    assert related_terms[0].chebi_id == "CHEBI:100"
    assert _fields(blank_terms) == [("materials", "material_name", "usable name")]
    assert blank_terms[0].chebi_id is None
    assert blank_terms[0].display_name == "usable name"


def test_no_cross_catalogue_merge_for_same_spelling() -> None:
    fda = _row(
        "materials_fda_ema",
        "fda-water",
        material_name="Water",
        UNII="059QF0KO0R",
    )
    chebi = _row(
        "materials_chebi",
        "chebi-water",
        material_name="Water",
        CHEBI_ID="CHEBI:15377",
    )
    fda_terms = map_source_row(fda, components=(Component.MATERIALS,))
    chebi_terms = map_source_row(chebi, components=(Component.MATERIALS,))
    assert fda_terms[0].source_table == "materials_fda_ema"
    assert chebi_terms[0].source_table == "materials_chebi"
    assert fda_terms[0].unii == "059QF0KO0R"
    assert fda_terms[0].chebi_id is None
    assert chebi_terms[0].chebi_id == "CHEBI:15377"
    assert chebi_terms[0].unii is None


def test_equipment_role_independence_and_exclusions() -> None:
    row = _row(
        "equipment",
        "eq-1",
        **{
            "Equipment type (EN)": "Pump",
            "Τύπος εξοπλισμού (GR)": "αντλία",
            "Brand / Manufacturer": "Acme",
            "Model": "X-100",
            "Operating parameter (EN)": "Speed",
            "Παράμετρος λειτουργίας (GR)": "ταχύτητα",
            "Unit": "rpm",
            "Published range": "10–100",
            "Source / section": "sec-1",
            "equipment_type_id": "EQT-1",
            "manufacturer_id": "MFR-1",
            "model_id": "MOD-1",
            "parameter_id": "PAR-1",
        },
    )
    all_terms = map_source_row(
        row,
        components=(
            Component.EQUIPMENT,
            Component.PARAMETER_NAMES,
            Component.UNITS,
        ),
    )
    assert _fields(all_terms) == [
        ("equipment", "Equipment type (EN)", "Pump"),
        ("parameter_names", "Operating parameter (EN)", "Speed"),
        ("units", "Unit", "rpm"),
    ]
    assert all_terms[1].parameter_id == "PAR-1"
    assert all_terms[1].catalogue_equipment_type_id == "EQT-1"
    assert all_terms[1].catalogue_equipment_type_label == "Pump"
    assert all_terms[1].equipment_type_id is None
    assert all_terms[2].boundary_hint == "atomic_unit"
    assert all_terms[2].fuzzy_allowed is False
    assert all_terms[2].parameter_id is None
    assert all_terms[2].equipment_type_id is None

    equipment_only = map_source_row(row, components=(Component.EQUIPMENT,))
    assert _fields(equipment_only) == [("equipment", "Equipment type (EN)", "Pump")]
    parameter_only = map_source_row(row, components=(Component.PARAMETER_NAMES,))
    assert _fields(parameter_only) == [("parameter_names", "Operating parameter (EN)", "Speed")]
    units_only = map_source_row(row, components=(Component.UNITS,))
    assert _fields(units_only) == [("units", "Unit", "rpm")]

    excluded_literals = {
        "αντλία",
        "Acme",
        "X-100",
        "ταχύτητα",
        "10–100",
        "MFR-1",
        "MOD-1",
    }
    assert all(term.literal not in excluded_literals for term in all_terms)


def test_shared_parameter_label_keeps_scoped_candidates() -> None:
    first = _row(
        "equipment",
        "eq-a",
        **{
            "Equipment type (EN)": "Blender",
            "Operating parameter (EN)": "Mixing speed",
            "equipment_type_id": "EQT-A",
            "parameter_id": "PAR-A",
        },
    )
    second = _row(
        "equipment",
        "eq-b",
        **{
            "Equipment type (EN)": "Mixer",
            "Operating parameter (EN)": "Mixing speed",
            "equipment_type_id": "EQT-B",
            "parameter_id": "PAR-B",
        },
    )
    terms = (
        *map_source_row(first, components=(Component.PARAMETER_NAMES,)),
        *map_source_row(second, components=(Component.PARAMETER_NAMES,)),
    )
    assert len(terms) == 2
    assert terms[0].literal == terms[1].literal == "Mixing speed"
    assert terms[0].parameter_id == "PAR-A"
    assert terms[1].parameter_id == "PAR-B"
    assert terms[0].catalogue_equipment_type_id == "EQT-A"
    assert terms[1].catalogue_equipment_type_id == "EQT-B"
    assert terms[0].row_id != terms[1].row_id


@pytest.mark.parametrize(
    ("cell", "eligible"),
    [
        ("rpm", True),
        ("°C", True),
        ("mL/min", True),
        ("N·m", True),
        ("min⁻¹", True),
        ("", False),
        ("   ", False),
        ("Unknown", False),
        ("Source unit unknown", False),
        ("Not applicable — categorical", False),
        ("g or mg¹", False),
        ("psi / bar", False),
        ("pieces/bottle; target-setting unit unverified", False),
        ("°C*", False),
        ("rpm¹", False),
        ("10–100", False),
        ("m/min — indicative recording unit", False),
    ],
)
def test_equipment_unit_eligibility_rule(cell: str, eligible: bool) -> None:
    assert is_eligible_equipment_unit_spelling(cell) is eligible
    row = _row("equipment", "eq-unit", **{"Unit": cell})
    terms = map_source_row(row, components=(Component.UNITS,))
    if eligible:
        assert _fields(terms) == [("units", "Unit", cell)]
    else:
        assert terms == ()


def test_unit_operations_index_flag_and_policies() -> None:
    active = _row(
        "unit_operations",
        "uo-active",
        **{
            "Search term (EN)": "sieving",
            "Process step (EN)": "Removal of fines",
            "Index this row": "TRUE",
            "Match policy": "direct_candidate",
            "record_type": "unit_operation",
            "Operation ID": "UO-003",
            "process_step_id": "PS-1",
            "Canonical unit operation": "Sieving",
            "Unit operation (EN)": "Sieving / particle separation",
            "Term relation": "industry_expression",
            "Operation role": "product_process",
            "Provenance / source": "prov",
            "Source / supporting evidence": "evidence",
            "lexical_term_id": "lt-uo",
        },
    )
    inactive = _row(
        "unit_operations",
        "uo-inactive",
        **{
            "Search term (EN)": "support wording",
            "Process step (EN)": "Still eligible step",
            "Index this row": "FALSE",
            "Match policy": "support_only",
            "record_type": "unit_operation",
            "Operation ID": "UO-010",
            "process_step_id": "PS-2",
        },
    )
    unknown_flag = _row(
        "unit_operations",
        "uo-unknown-flag",
        **{
            "Search term (EN)": "mystery",
            "Process step (EN)": "Step remains",
            "Index this row": "YES",
            "Match policy": "direct_candidate",
            "record_type": "unit_operation",
            "Operation ID": "UO-011",
            "process_step_id": "PS-3",
        },
    )
    context = _row(
        "unit_operations",
        "uo-context",
        **{
            "Search term (EN)": "context term",
            "Index this row": "TRUE",
            "Match policy": "context_required",
            "record_type": "unit_operation",
            "Operation ID": "UO-012",
        },
    )
    inspection = _row(
        "unit_operations",
        "uo-inspect",
        **{
            "Search term (EN)": "inspect term",
            "Index this row": "TRUE",
            "Match policy": "inspection_only",
            "record_type": "unit_operation",
            "Operation ID": "UO-013",
        },
    )
    generic = _row(
        "unit_operations",
        "uo-generic",
        **{
            "Search term (EN)": "step cue",
            "Index this row": "TRUE",
            "Match policy": "step_cue_only",
            "record_type": "generic_step_cue",
            "Operation ID": "",
            "Operation role": "step_cue",
        },
    )

    both = map_source_row(
        active,
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert _fields(both) == [
        ("unit_operations", "Search term (EN)", "sieving"),
        ("process_steps", "Process step (EN)", "Removal of fines"),
    ]
    assert both[0].term_role == "unit_operation"
    assert both[0].operation_id == "UO-003"
    assert both[0].canonical_unit_operation == "Sieving"
    assert both[0].unit_operation_en == "Sieving / particle separation"
    assert both[0].match_policy == "direct_candidate"
    assert both[1].process_step_id == "PS-1"
    assert both[1].supporting_evidence == "evidence"
    assert both[1].index_this_row == "TRUE"

    inactive_terms = map_source_row(
        inactive,
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert _fields(inactive_terms) == [
        ("process_steps", "Process step (EN)", "Still eligible step")
    ]
    assert inactive_terms[0].index_this_row == "FALSE"

    unknown_terms = map_source_row(
        unknown_flag,
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert index_this_row_authorizes("YES") is False
    assert _fields(unknown_terms) == [("process_steps", "Process step (EN)", "Step remains")]

    assert map_source_row(context, components=(Component.UNIT_OPERATIONS,)) == ()
    inspection_term = map_source_row(inspection, components=(Component.UNIT_OPERATIONS,))[0]
    assert inspection_term.term_role == "generic_cue"
    assert inspection_term.operation_id is None
    assert inspection_term.match_policy == "inspection_only"

    generic_term = map_source_row(generic, components=(Component.UNIT_OPERATIONS,))[0]
    assert generic_term.term_role == "generic_cue"
    assert generic_term.operation_id is None


def test_missing_ids_preserve_usable_labels_and_repeat_rows() -> None:
    missing = _row(
        "unit_operations",
        "uo-missing",
        **{
            "Search term (EN)": "generic cue text",
            "Process step (EN)": "cue step",
            "Index this row": "TRUE",
            "Match policy": "step_cue_only",
            "record_type": "generic_step_cue",
            "Operation ID": "",
            "process_step_id": "",
        },
    )
    terms = map_source_row(
        missing,
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert terms[0].operation_id is None
    assert terms[1].process_step_id is None
    assert terms[0].literal == "generic cue text"
    assert terms[1].literal == "cue step"

    first = _row(
        "unit_operations",
        "uo-repeat-1",
        **{
            "Search term (EN)": "sieving",
            "Index this row": "TRUE",
            "Match policy": "direct_candidate",
            "record_type": "unit_operation",
            "Operation ID": "UO-003",
        },
    )
    second = _row(
        "unit_operations",
        "uo-repeat-2",
        **{
            "Search term (EN)": "sieving",
            "Index this row": "TRUE",
            "Match policy": "direct_candidate",
            "record_type": "unit_operation",
            "Operation ID": "UO-003",
        },
    )
    repeated = (
        *map_source_row(first, components=(Component.UNIT_OPERATIONS,)),
        *map_source_row(second, components=(Component.UNIT_OPERATIONS,)),
    )
    assert len(repeated) == 2
    assert repeated[0].row_id != repeated[1].row_id
    assert repeated[0].literal == repeated[1].literal == "sieving"


def test_unicode_whitespace_and_literal_preservation() -> None:
    fda = _row(
        "materials_fda_ema",
        "fda-unicode",
        material_name="α-γλυκόζη",
        alias_name="  spaced  ",
        UNII="N/A",
        SMS_ID="",
        Is_Preferred_Name="FALSE",
    )
    terms = map_source_row(fda, components=(Component.MATERIALS,))
    assert _fields(terms) == [
        ("materials", "material_name", "α-γλυκόζη"),
        ("materials", "alias_name", "  spaced  "),
    ]
    assert terms[0].unii is None
    assert terms[0].sms_id is None
    assert terms[0].fuzzy_allowed is False

    blank_name = _row(
        "materials_fda_ema",
        "fda-blank-name",
        material_name="   ",
        alias_name="",
        UNII="",
    )
    assert map_source_row(blank_name, components=(Component.MATERIALS,)) == ()


def test_component_table_selection_and_row_stream() -> None:
    assert tables_for_components((Component.MATERIALS,)) == (
        "materials_fda_ema",
        "materials_chebi",
    )
    assert tables_for_components((Component.EQUIPMENT,)) == ("equipment",)
    assert tables_for_components(
        (Component.EQUIPMENT, Component.PARAMETER_NAMES, Component.UNITS)
    ) == ("equipment",)
    assert tables_for_components((Component.UNIT_OPERATIONS, Component.PROCESS_STEPS)) == (
        "unit_operations",
    )
    assert tables_for_components((Component.QUANTITY_EXPRESSIONS,)) == ()
    assert tables_for_components((Component.PARAMETER_VALUE_EXPRESSIONS,)) == ()

    class _FakeSnapshot:
        identity = type("Identity", (), {"snapshot_id": "flat-v1-test"})()

        def iter_batches(
            self, table_name: str, batch_size: int | None = None
        ) -> Iterator[SourceBatch]:
            del batch_size
            if table_name != "equipment":
                raise AssertionError(f"unexpected table scan: {table_name}")
            yield SourceBatch(
                table_name="equipment",
                after_rowid=0,
                rows=(
                    _row(
                        "equipment",
                        "eq-stream",
                        **{
                            "Equipment type (EN)": "Pump",
                            "Operating parameter (EN)": "Speed",
                            "Unit": "rpm",
                            "equipment_type_id": "EQT-1",
                            "parameter_id": "PAR-1",
                        },
                    ),
                ),
            )

    streamed = tuple(
        iter_eligible_terms(
            _FakeSnapshot(),  # type: ignore[arg-type]
            (Component.PARAMETER_NAMES,),
        )
    )
    assert _fields(streamed) == [("parameter_names", "Operating parameter (EN)", "Speed")]
    assert streamed[0].snapshot_id == "flat-v1-test"
    assert not isinstance(streamed, list)


def test_map_source_row_does_not_fabricate_l01_candidates() -> None:
    row = _row(
        "materials_fda_ema",
        "fda-no-candidate",
        material_name="Water",
        UNII="059QF0KO0R",
    )
    terms = map_source_row(row, components=(Component.MATERIALS,))
    assert all(isinstance(term, EligibleSearchTerm) for term in terms)
    assert all(not hasattr(term, "evidence") for term in terms)
    assert all(not hasattr(term, "candidate_kind") for term in terms)


def test_production_snapshot_bounded_mapping_smoke() -> None:
    snapshot_dir = Path(
        r"C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items"
        r"\Prepared\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed"
    )
    if not (snapshot_dir / "knowledge.sqlite").is_file():
        pytest.skip("local production flat snapshot unavailable")

    from app.lexical_extraction.knowledge_snapshot import open_knowledge_snapshot

    with open_knowledge_snapshot(snapshot_dir, read_batch_rows=5000, cache_kib=65536) as snapshot:
        fda = snapshot.read_batch("materials_fda_ema", after_rowid=0, batch_size=1).rows[0]
        chebi = snapshot.read_batch("materials_chebi", after_rowid=0, batch_size=1).rows[0]
        equipment = snapshot.read_batch("equipment", after_rowid=0, batch_size=1).rows[0]
        unit_ops = snapshot.read_batch("unit_operations", after_rowid=0, batch_size=1).rows[0]

        fda_terms = map_source_row(
            fda,
            components=(Component.MATERIALS,),
            snapshot_id=snapshot.identity.snapshot_id,
        )
        chebi_terms = map_source_row(
            chebi,
            components=(Component.MATERIALS,),
            snapshot_id=snapshot.identity.snapshot_id,
        )
        equipment_terms = map_source_row(
            equipment,
            components=(
                Component.EQUIPMENT,
                Component.PARAMETER_NAMES,
                Component.UNITS,
            ),
            snapshot_id=snapshot.identity.snapshot_id,
        )
        uo_terms = map_source_row(
            unit_ops,
            components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
            snapshot_id=snapshot.identity.snapshot_id,
        )

        assert fda_terms
        assert fda_terms[0].source_field == "material_name"
        assert any(term.source_field == "UNII" for term in fda_terms)
        assert chebi_terms
        assert chebi_terms[0].chebi_id is not None
        assert equipment_terms
        assert equipment_terms[0].term_role == "equipment_type"
        assert uo_terms
        assert {term.component for term in uo_terms} <= {
            Component.UNIT_OPERATIONS,
            Component.PROCESS_STEPS,
        }


@pytest.mark.parametrize(
    "marker",
    ["N/A", "n/a", "NA", "unknown", "None", " none "],
)
def test_unavailable_unii_markers_excluded_from_code_search(marker: str) -> None:
    assert is_unavailable_identity_marker(marker) is True
    row = _row(
        "materials_fda_ema",
        "fda-unavailable",
        material_name="Water",
        alias_name="N/A",
        UNII=marker,
        SMS_ID="NA",
    )
    terms = map_source_row(row, components=(Component.MATERIALS,))
    assert _fields(terms) == [
        ("materials", "material_name", "Water"),
        ("materials", "alias_name", "N/A"),
    ]
    assert all(term.source_field != "UNII" for term in terms)
    assert terms[0].unii is None
    assert terms[0].sms_id is None
    assert terms[0].row_id == "fda-unavailable"


def test_real_unii_remains_whole_code_search_term() -> None:
    row = _row(
        "materials_fda_ema",
        "fda-real-unii",
        material_name="Water",
        UNII="059QF0KO0R",
        SMS_ID="100000",
    )
    terms = map_source_row(row, components=(Component.MATERIALS,))
    unii = next(term for term in terms if term.source_field == "UNII")
    assert unii.literal == "059QF0KO0R"
    assert unii.boundary_hint == "whole_code"
    assert unii.fuzzy_allowed is False
    assert unii.unii == "059QF0KO0R"
    assert unii.sms_id == "100000"


def test_unknown_uo_policy_and_record_type_fail_closed() -> None:
    unknown_policy = _row(
        "unit_operations",
        "uo-novel-policy",
        **{
            "Search term (EN)": "mystery wording",
            "Process step (EN)": "Independent step",
            "Index this row": "TRUE",
            "Match policy": "novel_policy",
            "record_type": "unit_operation",
            "Operation ID": "UO-999",
        },
    )
    with pytest.raises(FieldMappingError) as policy_exc:
        map_source_row(unknown_policy, components=(Component.UNIT_OPERATIONS,))
    assert policy_exc.value.code == "UNKNOWN_MATCH_POLICY"
    structured = policy_exc.value.to_structured_error()
    assert structured.code == "UNKNOWN_MATCH_POLICY"
    assert structured.retryable is False
    assert "uo-novel-policy" in structured.message
    assert len(structured.message) <= 200

    # Process-step-only selection does not classify the UO search term.
    step_only = map_source_row(unknown_policy, components=(Component.PROCESS_STEPS,))
    assert _fields(step_only) == [("process_steps", "Process step (EN)", "Independent step")]

    unknown_record = _row(
        "unit_operations",
        "uo-novel-record",
        **{
            "Search term (EN)": "another mystery",
            "Index this row": "TRUE",
            "Match policy": "direct_candidate",
            "record_type": "novel_record",
            "Operation ID": "UO-998",
        },
    )
    with pytest.raises(FieldMappingError) as record_exc:
        map_source_row(unknown_record, components=(Component.UNIT_OPERATIONS,))
    assert record_exc.value.code == "UNKNOWN_RECORD_TYPE"
    assert "uo-novel-record" in record_exc.value.message
    assert len(record_exc.value.message) <= 200

    inactive = _row(
        "unit_operations",
        "uo-false-step",
        **{
            "Search term (EN)": "ignored search",
            "Process step (EN)": "Still mapped step",
            "Index this row": "FALSE",
            "Match policy": "novel_policy",
            "record_type": "unit_operation",
            "Operation ID": "UO-997",
            "process_step_id": "PS-false",
        },
    )
    # Index FALSE suppresses UO search, so unknown policy is not classified.
    inactive_terms = map_source_row(
        inactive,
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert _fields(inactive_terms) == [("process_steps", "Process step (EN)", "Still mapped step")]
    assert inactive_terms[0].index_this_row == "FALSE"


def test_known_uo_policies_remain_distinct() -> None:
    cases = (
        ("direct_candidate", "unit_operation", "unit_operation", True),
        ("step_cue_only", "generic_step_cue", "generic_cue", False),
        ("support_only", "unit_operation", "generic_cue", False),
        ("inspection_only", "unit_operation", "generic_cue", False),
    )
    for policy, record_type, expected_role, keeps_operation_id in cases:
        row = _row(
            "unit_operations",
            f"uo-{policy}",
            **{
                "Search term (EN)": "sieving",
                "Index this row": "TRUE",
                "Match policy": policy,
                "record_type": record_type,
                "Operation ID": "UO-KEEP",
            },
        )
        term = map_source_row(row, components=(Component.UNIT_OPERATIONS,))[0]
        assert term.term_role == expected_role
        assert term.match_policy == policy
        if keeps_operation_id:
            assert term.operation_id == "UO-KEEP"
        else:
            assert term.operation_id is None

    context_terms = map_source_row(
        _row(
            "unit_operations",
            "uo-context_required",
            **{
                "Search term (EN)": "sieving",
                "Index this row": "TRUE",
                "Match policy": "context_required",
                "record_type": "unit_operation",
                "Operation ID": "UO-KEEP",
            },
        ),
        components=(Component.UNIT_OPERATIONS,),
    )
    assert context_terms == ()


def test_fuzzy_allowed_shape_and_scope() -> None:
    assert fuzzy_shape_eligible("Blender") is True
    assert fuzzy_shape_eligible("Pump") is False
    assert fuzzy_shape_eligible("Impeller speed") is False
    assert fuzzy_shape_eligible("rpm") is False

    eligible_equipment = _row(
        "equipment",
        "eq-fuzzy-yes",
        **{
            "Equipment type (EN)": "Blender",
            "Operating parameter (EN)": "Temperature",
            "Unit": "rpm",
        },
    )
    ineligible_equipment = _row(
        "equipment",
        "eq-fuzzy-no",
        **{
            "Equipment type (EN)": "Pump",
            "Operating parameter (EN)": "Impeller speed",
            "Unit": "rpm",
        },
    )
    yes_terms = map_source_row(
        eligible_equipment,
        components=(
            Component.EQUIPMENT,
            Component.PARAMETER_NAMES,
            Component.UNITS,
        ),
    )
    no_terms = map_source_row(
        ineligible_equipment,
        components=(
            Component.EQUIPMENT,
            Component.PARAMETER_NAMES,
            Component.UNITS,
        ),
    )
    assert yes_terms[0].fuzzy_allowed is True
    assert yes_terms[1].fuzzy_allowed is True
    assert yes_terms[2].fuzzy_allowed is False
    assert no_terms[0].fuzzy_allowed is False
    assert no_terms[1].fuzzy_allowed is False

    uo_direct = map_source_row(
        _row(
            "unit_operations",
            "uo-fuzzy-direct",
            **{
                "Search term (EN)": "sieving",
                "Process step (EN)": "Removal of undesired fines",
                "Index this row": "TRUE",
                "Match policy": "direct_candidate",
                "record_type": "unit_operation",
                "Operation ID": "UO-003",
            },
        ),
        components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
    )
    assert uo_direct[0].fuzzy_allowed is True
    assert uo_direct[1].fuzzy_allowed is False

    uo_context = map_source_row(
        _row(
            "unit_operations",
            "uo-fuzzy-context",
            **{
                "Search term (EN)": "sieving",
                "Index this row": "TRUE",
                "Match policy": "context_required",
                "record_type": "unit_operation",
                "Operation ID": "UO-012",
            },
        ),
        components=(Component.UNIT_OPERATIONS,),
    )
    assert uo_context == ()

    material = map_source_row(
        _row(
            "materials_fda_ema",
            "fda-fuzzy",
            material_name="Glucose",
            UNII="059QF0KO0R",
        ),
        components=(Component.MATERIALS,),
    )
    assert all(term.fuzzy_allowed is False for term in material)
    assert not any(hasattr(term, "evidence") for term in (*yes_terms, *material))


def test_long_row_id_keeps_bounded_field_mapping_errors() -> None:
    long_row_id = "UOR-" + ("x" * 200)
    assert len(long_row_id) > 200

    unknown_policy = _row(
        "unit_operations",
        long_row_id,
        **{
            "Search term (EN)": "mystery wording",
            "Index this row": "TRUE",
            "Match policy": "novel_policy",
            "record_type": "unit_operation",
            "Operation ID": "UO-999",
        },
    )
    with pytest.raises(FieldMappingError) as policy_exc:
        map_source_row(unknown_policy, components=(Component.UNIT_OPERATIONS,))
    assert policy_exc.value.code == "UNKNOWN_MATCH_POLICY"
    assert isinstance(policy_exc.value, FieldMappingError)
    policy_message = policy_exc.value.message
    assert 1 <= len(policy_message) <= 200
    assert policy_message.startswith("unrecognized Match policy on unit_operations row ")
    assert policy_message.endswith("...")
    assert "UOR-" in policy_message
    assert long_row_id not in policy_message
    structured = policy_exc.value.to_structured_error()
    assert structured.code == "UNKNOWN_MATCH_POLICY"
    assert structured.message == policy_message
    assert len(structured.message) <= 200

    unknown_record = _row(
        "unit_operations",
        long_row_id,
        **{
            "Search term (EN)": "another mystery",
            "Index this row": "TRUE",
            "Match policy": "direct_candidate",
            "record_type": "novel_record",
            "Operation ID": "UO-998",
        },
    )
    with pytest.raises(FieldMappingError) as record_exc:
        map_source_row(unknown_record, components=(Component.UNIT_OPERATIONS,))
    assert record_exc.value.code == "UNKNOWN_RECORD_TYPE"
    assert 1 <= len(record_exc.value.message) <= 200
    assert record_exc.value.message.endswith("...")
    assert long_row_id not in record_exc.value.message

    ambiguous = _row(
        "unit_operations",
        long_row_id,
        **{
            "Search term (EN)": "unclassified",
            "Index this row": "TRUE",
            "Match policy": "",
            "record_type": "",
            "Operation ID": "UO-997",
        },
    )
    with pytest.raises(FieldMappingError) as ambiguous_exc:
        map_source_row(ambiguous, components=(Component.UNIT_OPERATIONS,))
    assert ambiguous_exc.value.code == "AMBIGUOUS_UO_CLASSIFICATION"
    assert 1 <= len(ambiguous_exc.value.message) <= 200
    assert ambiguous_exc.value.message.startswith(
        "UO search term lacks classifiable policy/record_type on row "
    )
    assert ambiguous_exc.value.message.endswith("...")
    assert long_row_id not in ambiguous_exc.value.message
    # Source row_id on the L04 row is unchanged; only the diagnostic is clipped.
    assert ambiguous.row_id == long_row_id
