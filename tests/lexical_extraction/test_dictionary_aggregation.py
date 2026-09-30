"""Bounded dictionary aggregation (L08) with independent expected results."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    AmbiguityQualification,
    BlockEvidence,
    BlockRecord,
    CharSpan,
    ChebiMaterialCandidate,
    Component,
    DictionaryOccurrence,
    ExactEvidence,
    FdaEmaMaterialCandidate,
    KnowledgeSnapshotIdentity,
    NormalizedExactEvidence,
    ParameterNameCandidate,
    ProcessStepCandidate,
    UnitOperationCandidate,
)
from app.lexical_extraction.dictionary_aggregation import (
    DictionaryAggregationError,
    iter_aggregated_block_records,
)
from app.lexical_extraction.dictionary_matcher import (
    RawDiscovery,
    StaticBlockSource,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import map_source_row
from app.lexical_extraction.knowledge_snapshot import FLAT_SOURCE_TABLES, SourceRow

_HEADERS = dict(FLAT_SOURCE_TABLES)
_SNAPSHOT_ID = "fixture-snapshot-l08"


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


@dataclass
class FakeSnapshot:
    rows: dict[tuple[str, str], SourceRow]
    snapshot_id: str = _SNAPSHOT_ID

    @property
    def identity(self) -> KnowledgeSnapshotIdentity:
        return KnowledgeSnapshotIdentity(
            snapshot_id=self.snapshot_id,
            database_sha256="0" * 64,
            manifest_sha256="1" * 64,
            schema_user_version=1,
            preparation_version="flat-sqlite-1",
        )

    def lookup(self, table_name: str, row_id: str) -> SourceRow | None:
        return self.rows.get((table_name, row_id))


@dataclass
class MutatingIdentitySource:
    blocks: tuple[BlockEvidence, ...]
    identities: list[str]
    _calls: int = field(default=0, init=False)

    @property
    def source_identity(self) -> str:
        index = min(self._calls, len(self.identities) - 1)
        return self.identities[index]

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        self._calls += 1
        yield from self.blocks


def _block(
    text: str,
    *,
    node_id: str = "n1",
    page_number: int = 1,
    order: int = 0,
) -> BlockEvidence:
    return BlockEvidence(
        node_id=node_id,
        kind="paragraph",
        text=text,
        page_number=page_number,
        order=order,
        element_id="e1",
    )


def _limits(*, result_buffer_records: int = 50) -> ResourceLimits:
    return ResourceLimits(result_buffer_records=result_buffer_records)


def _discovery(
    *,
    dictionary_term: str,
    matched_text: str,
    start: int,
    end: int,
    component: Component,
    term_role: str,
    source_table: str,
    source_field: str,
    row_id: str,
    method: str = "exact",
    block_node_id: str = "n1",
    lexical_term_id: str | None = None,
    snapshot_id: str = _SNAPSHOT_ID,
) -> RawDiscovery:
    return RawDiscovery(
        method=method,  # type: ignore[arg-type]
        rule_id="lexical-v1-exact" if method == "exact" else "lexical-v1-normalized-exact",
        dictionary_term=dictionary_term,
        component=component,
        term_role=term_role,
        source_table=source_table,
        source_field=source_field,
        row_id=row_id,
        block_node_id=block_node_id,
        span=CharSpan(start_char=start, end_char=end, matched_text=matched_text),
        lexical_term_id=lexical_term_id,
        snapshot_id=snapshot_id,
    )


def _aggregate(
    discoveries: Sequence[RawDiscovery],
    blocks: Sequence[BlockEvidence],
    snapshot: FakeSnapshot,
    *,
    limits: ResourceLimits | None = None,
    expected_source_identity: str | None = "static-l08",
    identity: str = "static-l08",
) -> list[BlockRecord]:
    stream = iter_aggregated_block_records(
        discoveries,
        StaticBlockSource(blocks=tuple(blocks), identity=identity),
        snapshot,
        limits or _limits(),
        expected_source_identity=expected_source_identity,
    )
    records = list(stream)
    _ = stream.coverage
    return records


def _dictionary_occurrences(record: BlockRecord) -> tuple[DictionaryOccurrence, ...]:
    occurrences: list[DictionaryOccurrence] = []
    for occurrence in record.occurrences:
        assert isinstance(occurrence, DictionaryOccurrence)
        occurrences.append(occurrence)
    return tuple(occurrences)


def test_supporting_refs_group_equivalent_uo_rows_without_process_steps() -> None:
    rows = {
        ("unit_operations", "uo-a"): _row(
            "unit_operations",
            "uo-a",
            **{
                "Search term (EN)": "granulation",
                "Index this row": "TRUE",
                "Match policy": "direct_candidate",
                "record_type": "unit_operation",
                "Operation ID": "UO-001",
                "Canonical unit operation": "Granulation",
                "Unit operation (EN)": "Granulation",
                "Process step (EN)": "Prepare binder",
                "process_step_id": "step-a",
                "lexical_term_id": "lt-gran",
            },
        ),
        ("unit_operations", "uo-b"): _row(
            "unit_operations",
            "uo-b",
            **{
                "Search term (EN)": "granulation",
                "Index this row": "TRUE",
                "Match policy": "direct_candidate",
                "record_type": "unit_operation",
                "Operation ID": "UO-001",
                "Canonical unit operation": "Granulation",
                "Unit operation (EN)": "Granulation",
                "Process step (EN)": "Dry granules",
                "process_step_id": "step-b",
                "lexical_term_id": "lt-gran",
            },
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "granulation"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="granulation",
            matched_text="granulation",
            start=0,
            end=11,
            component=Component.UNIT_OPERATIONS,
            term_role="unit_operation",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-b",
            lexical_term_id="lt-gran",
        ),
        _discovery(
            dictionary_term="granulation",
            matched_text="granulation",
            start=0,
            end=11,
            component=Component.UNIT_OPERATIONS,
            term_role="unit_operation",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-a",
            lexical_term_id="lt-gran",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    assert len(records) == 1
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 1
    assert isinstance(occs[0], DictionaryOccurrence)
    assert len(occs[0].candidates) == 1
    candidate = occs[0].candidates[0]
    assert isinstance(candidate, UnitOperationCandidate)
    assert candidate.row_id == "uo-a"
    assert candidate.supporting_row_ids == ()
    assert candidate.ambiguity is AmbiguityQualification.UNRESOLVED
    assert candidate.operation_id == "UO-001"
    assert occs[0].applies_to == (Component.UNIT_OPERATIONS,)
    assert all(c.candidate_kind != "process_step" for c in occs[0].candidates)


def test_distinct_lexical_ids_and_process_step_stay_separate() -> None:
    rows = {
        ("unit_operations", "uo-1"): _row(
            "unit_operations",
            "uo-1",
            **{
                "Search term (EN)": "mixing",
                "Index this row": "TRUE",
                "Match policy": "direct_candidate",
                "record_type": "unit_operation",
                "Operation ID": "UO-010",
                "Canonical unit operation": "Mixing",
                "Process step (EN)": "Blend powders",
                "process_step_id": "ps-1",
                "lexical_term_id": "lt-mix-1",
            },
        ),
        ("unit_operations", "uo-2"): _row(
            "unit_operations",
            "uo-2",
            **{
                "Search term (EN)": "mixing",
                "Index this row": "TRUE",
                "Match policy": "direct_candidate",
                "record_type": "unit_operation",
                "Operation ID": "UO-010",
                "Canonical unit operation": "Mixing",
                "Process step (EN)": "Blend powders",
                "process_step_id": "ps-1",
                "lexical_term_id": "lt-mix-2",
            },
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "mixing Blend powders"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="mixing",
            matched_text="mixing",
            start=0,
            end=6,
            component=Component.UNIT_OPERATIONS,
            term_role="unit_operation",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-1",
            lexical_term_id="lt-mix-1",
        ),
        _discovery(
            dictionary_term="mixing",
            matched_text="mixing",
            start=0,
            end=6,
            component=Component.UNIT_OPERATIONS,
            term_role="unit_operation",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-2",
            lexical_term_id="lt-mix-2",
        ),
        _discovery(
            dictionary_term="Blend powders",
            matched_text="Blend powders",
            start=7,
            end=20,
            component=Component.PROCESS_STEPS,
            term_role="process_step",
            source_table="unit_operations",
            source_field="Process step (EN)",
            row_id="uo-1",
            lexical_term_id="lt-mix-1",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 2
    mix = next(occ for occ in occs if occ.location.matched_text == "mixing")
    step = next(occ for occ in occs if occ.location.matched_text == "Blend powders")
    assert len(mix.candidates) == 1
    assert mix.candidates[0].supporting_row_ids == ()
    assert mix.candidates[0].ambiguity is AmbiguityQualification.UNRESOLVED
    assert isinstance(mix.candidates[0], UnitOperationCandidate)
    assert mix.candidates[0].lexical_term_id in {"lt-mix-1", "lt-mix-2"}
    assert isinstance(step.candidates[0], ProcessStepCandidate)
    assert step.candidates[0].process_step_id == "ps-1"
    assert step.candidates[0].supporting_row_ids == ()


def test_chebi_related_versus_exact_and_fda_collision_split_across_shards() -> None:
    rows = {
        ("materials_chebi", "c-rel"): _row(
            "materials_chebi",
            "c-rel",
            material_name="water",
            alias_name="oxidane",
            CHEBI_ID="CHEBI:15377",
            alias_type="hasRelatedSynonym",
            lexical_term_id="lt-rel",
        ),
        ("materials_chebi", "c-ex"): _row(
            "materials_chebi",
            "c-ex",
            material_name="water",
            alias_name="oxidane",
            CHEBI_ID="CHEBI:15377",
            alias_type="hasExactSynonym",
            lexical_term_id="lt-ex",
        ),
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            UNII="059QF0KO0R",
            lexical_term_id="lt-fda",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "oxidane water"
    blocks = [_block(text)]
    # Shard-like interleaving: same-span candidates far apart.
    discoveries = [
        _discovery(
            dictionary_term="oxidane",
            matched_text="oxidane",
            start=0,
            end=7,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_chebi",
            source_field="alias_name",
            row_id="c-rel",
            lexical_term_id="lt-rel",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=8,
            end=13,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-fda",
        ),
        _discovery(
            dictionary_term="oxidane",
            matched_text="oxidane",
            start=0,
            end=7,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_chebi",
            source_field="alias_name",
            row_id="c-ex",
            lexical_term_id="lt-ex",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    oxidane = next(occ for occ in occs if occ.location.matched_text == "oxidane")
    water = next(occ for occ in occs if occ.location.matched_text == "water")
    assert len(oxidane.candidates) == 1
    exact = oxidane.candidates[0]
    assert isinstance(exact, ChebiMaterialCandidate)
    assert exact.alias_type == "hasExactSynonym"
    assert exact.ambiguity is AmbiguityQualification.UNRESOLVED
    assert exact.supporting_row_ids == ()
    assert isinstance(water.candidates[0], FdaEmaMaterialCandidate)
    assert water.candidates[0].unii == "059QF0KO0R"
    assert water.candidates[0].supporting_row_ids == ()


def test_exact_precedes_normalized_for_repeated_source_reference() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "water"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            method="normalized_exact",
            lexical_term_id="lt-1",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            method="exact",
            lexical_term_id="lt-1",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    candidate = _dictionary_occurrences(records[0])[0].candidates[0]
    assert isinstance(candidate.evidence, ExactEvidence)


def test_overlapping_spans_and_empty_blocks_preserved() -> None:
    rows = {
        ("materials_fda_ema", "f-g"): _row(
            "materials_fda_ema",
            "f-g",
            material_name="granulation",
            lexical_term_id="lt-g",
        ),
        ("materials_fda_ema", "f-wg"): _row(
            "materials_fda_ema",
            "f-wg",
            material_name="wet granulation",
            lexical_term_id="lt-wg",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "wet granulation"
    blocks = [
        _block("no hits here", node_id="empty", order=0),
        _block(text, node_id="hit", order=1),
    ]
    discoveries = [
        _discovery(
            dictionary_term="wet granulation",
            matched_text="wet granulation",
            start=0,
            end=15,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-wg",
            block_node_id="hit",
            lexical_term_id="lt-wg",
        ),
        _discovery(
            dictionary_term="granulation",
            matched_text="granulation",
            start=4,
            end=15,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-g",
            block_node_id="hit",
            lexical_term_id="lt-g",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    assert records[0].block.node_id == "empty"
    assert records[0].occurrences == ()
    assert records[1].block.node_id == "hit"
    hit_occs = _dictionary_occurrences(records[1])
    assert len(hit_occs) == 2
    spans = {
        (o.location.start_char, o.location.end_char, o.location.matched_text) for o in hit_occs
    }
    assert spans == {(0, 15, "wet granulation"), (4, 15, "granulation")}


def test_equivalent_materials_and_equipment_group_parameters_stay_separate() -> None:
    rows = {
        ("materials_fda_ema", "m-a"): _row(
            "materials_fda_ema",
            "m-a",
            material_name="lactose",
            UNII="3SY5LH9PMK",
            lexical_term_id="lt-m",
        ),
        ("materials_fda_ema", "m-b"): _row(
            "materials_fda_ema",
            "m-b",
            material_name="lactose",
            UNII="3SY5LH9PMK",
            lexical_term_id="lt-m",
        ),
        ("equipment", "e-a"): _row(
            "equipment",
            "e-a",
            **{
                "Equipment type (EN)": "Mixer",
                "equipment_type_id": "EQT-1",
                "Operating parameter (EN)": "Speed",
                "parameter_id": "PAR-1",
            },
        ),
        ("equipment", "e-b"): _row(
            "equipment",
            "e-b",
            **{
                "Equipment type (EN)": "Mixer",
                "equipment_type_id": "EQT-1",
                "Operating parameter (EN)": "Speed",
                "parameter_id": "PAR-2",
            },
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "lactose Mixer Speed"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="lactose",
            matched_text="lactose",
            start=0,
            end=7,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-b",
            lexical_term_id="lt-m",
        ),
        _discovery(
            dictionary_term="lactose",
            matched_text="lactose",
            start=0,
            end=7,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-a",
            lexical_term_id="lt-m",
        ),
        _discovery(
            dictionary_term="Mixer",
            matched_text="Mixer",
            start=8,
            end=13,
            component=Component.EQUIPMENT,
            term_role="equipment_type",
            source_table="equipment",
            source_field="Equipment type (EN)",
            row_id="e-a",
        ),
        _discovery(
            dictionary_term="Mixer",
            matched_text="Mixer",
            start=8,
            end=13,
            component=Component.EQUIPMENT,
            term_role="equipment_type",
            source_table="equipment",
            source_field="Equipment type (EN)",
            row_id="e-b",
        ),
        _discovery(
            dictionary_term="Speed",
            matched_text="Speed",
            start=14,
            end=19,
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="e-a",
        ),
        _discovery(
            dictionary_term="Speed",
            matched_text="Speed",
            start=14,
            end=19,
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="e-b",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    by_text = {o.location.matched_text: o for o in _dictionary_occurrences(records[0])}
    material = by_text["lactose"].candidates[0]
    assert material.row_id == "m-a"
    assert material.supporting_row_ids == ()
    assert material.ambiguity is AmbiguityQualification.UNRESOLVED
    equipment = by_text["Mixer"].candidates[0]
    assert equipment.row_id == "e-a"
    assert equipment.supporting_row_ids == ()
    assert equipment.ambiguity is AmbiguityQualification.UNRESOLVED
    params = by_text["Speed"].candidates
    assert len(params) == 1
    assert params[0].supporting_row_ids == ()
    assert params[0].ambiguity is AmbiguityQualification.UNRESOLVED
    assert isinstance(params[0], ParameterNameCandidate)
    assert params[0].parameter_id in {"PAR-1", "PAR-2"}


def test_stable_order_under_shuffled_discovery_order_and_l07_pipeline() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="glucose",
            lexical_term_id="lt-1",
        ),
        ("materials_chebi", "c-1"): _row(
            "materials_chebi",
            "c-1",
            material_name="glucose",
            CHEBI_ID="CHEBI:17234",
            lexical_term_id="lt-2",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "glucose"
    blocks = [_block(text)]
    terms = [
        *map_source_row(
            rows[("materials_fda_ema", "f-1")],
            components=(Component.MATERIALS,),
            snapshot_id=_SNAPSHOT_ID,
        ),
        *map_source_row(
            rows[("materials_chebi", "c-1")],
            components=(Component.MATERIALS,),
            snapshot_id=_SNAPSHOT_ID,
        ),
    ]
    source = StaticBlockSource(blocks=tuple(blocks), identity="static-l08")
    discoveries = list(iter_raw_discoveries(terms, source, _limits()))
    assert len(discoveries) >= 2

    first = _aggregate(discoveries, blocks, snapshot)
    shuffled = list(reversed(discoveries))
    second = _aggregate(shuffled, blocks, snapshot)
    first_occs = _dictionary_occurrences(first[0])
    second_occs = _dictionary_occurrences(second[0])
    assert first_occs[0].occurrence_id == second_occs[0].occurrence_id
    assert [c.row_id for c in first_occs[0].candidates] == [
        c.row_id for c in second_occs[0].candidates
    ]


def test_absent_native_ids_and_generic_cue_remain_valid() -> None:
    rows = {
        ("materials_fda_ema", "f-blank"): _row(
            "materials_fda_ema",
            "f-blank",
            material_name="excipient",
            UNII="",
            SMS_ID="N/A",
            lexical_term_id="lt-blank",
        ),
        ("unit_operations", "uo-cue"): _row(
            "unit_operations",
            "uo-cue",
            **{
                "Search term (EN)": "as needed",
                "Index this row": "TRUE",
                "Match policy": "step_cue_only",
                "record_type": "generic_step_cue",
                "lexical_term_id": "lt-cue",
            },
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "excipient as needed"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="excipient",
            matched_text="excipient",
            start=0,
            end=9,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-blank",
            lexical_term_id="lt-blank",
        ),
        _discovery(
            dictionary_term="as needed",
            matched_text="as needed",
            start=10,
            end=19,
            component=Component.UNIT_OPERATIONS,
            term_role="generic_cue",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-cue",
            lexical_term_id="lt-cue",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    material = next(o for o in occs if o.location.matched_text == "excipient")
    cue = next(o for o in occs if o.location.matched_text == "as needed")
    assert isinstance(material.candidates[0], FdaEmaMaterialCandidate)
    assert material.candidates[0].unii is None
    assert material.candidates[0].sms_id is None
    assert cue.candidates[0].candidate_kind == "generic_cue"
    assert "operation_id" not in cue.candidates[0].model_dump()


def test_missing_lookup_unit_input_identity_spool_overflow_and_early_close() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    missing = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="missing",
            lexical_term_id="lt-1",
        )
    ]
    with pytest.raises(DictionaryAggregationError) as missing_exc:
        _aggregate(missing, blocks, snapshot)
    assert missing_exc.value.code == "SOURCE_ROW_ABSENT"

    unit_hit = [
        RawDiscovery(
            method="exact",
            rule_id="lexical-v1-exact",
            dictionary_term="rpm",
            component=Component.UNITS,
            term_role="unit_spelling",
            source_table="equipment",
            source_field="Unit",
            row_id="e-1",
            block_node_id="n1",
            span=CharSpan(start_char=0, end_char=3, matched_text="rpm"),
            snapshot_id=_SNAPSHOT_ID,
        )
    ]
    with pytest.raises(DictionaryAggregationError) as unit_exc:
        _aggregate(unit_hit, blocks, snapshot)
    assert unit_exc.value.code == "UNEXPECTED_UNIT_DISCOVERY"

    bad_snapshot = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
            snapshot_id="other-snapshot",
        )
    ]
    with pytest.raises(DictionaryAggregationError) as snap_exc:
        _aggregate(bad_snapshot, blocks, snapshot)
    assert snap_exc.value.code == "SNAPSHOT_IDENTITY_MISMATCH"

    mismatched_field = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]
    with pytest.raises(DictionaryAggregationError) as mismatch_exc:
        _aggregate(mismatched_field, blocks, snapshot)
    assert mismatch_exc.value.code == "SOURCE_TERM_MISMATCH"

    mutating = MutatingIdentitySource(blocks=tuple(blocks), identities=["first", "second"])
    ok = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]
    stream = iter_aggregated_block_records(
        ok,
        mutating,
        snapshot,
        _limits(),
        expected_source_identity="first",
    )
    with pytest.raises(DictionaryAggregationError) as ident_exc:
        list(stream)
    assert ident_exc.value.code == "REPLAY_IDENTITY_CHANGED"

    overflow_hits = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
        for _ in range(3)
    ]
    with pytest.raises(DictionaryAggregationError) as overflow_exc:
        _aggregate(overflow_hits, blocks, snapshot, limits=_limits(result_buffer_records=2))
    assert overflow_exc.value.code == "RESOURCE_LIMIT_EXCEEDED"

    # Spool write failure: force connection execute to fail after open.
    early = iter_aggregated_block_records(
        ok,
        StaticBlockSource(blocks=tuple(blocks), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    iterator = iter(early)
    next(iterator)
    early.close()
    with pytest.raises(DictionaryAggregationError) as incomplete_exc:
        _ = early.coverage
    assert incomplete_exc.value.code == "AGGREGATION_INCOMPLETE"


def test_injected_spool_write_failure_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]

    def boom(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.Error("injected spool write failure")

    monkeypatch.setattr(
        "app.lexical_extraction.dictionary_aggregation.sqlite3.connect",
        boom,
    )
    with pytest.raises(DictionaryAggregationError) as exc:
        _aggregate(discoveries, blocks, snapshot)
    assert exc.value.code == "SPOOL_WRITE_FAILED"


def test_coverage_only_after_complete_consumption() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water"), _block("plain", node_id="n2", order=1)]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]
    stream = iter_aggregated_block_records(
        discoveries,
        StaticBlockSource(blocks=tuple(blocks), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    with pytest.raises(DictionaryAggregationError):
        _ = stream.coverage
    records = list(stream)
    assert len(records) == 2
    coverage = stream.coverage
    assert coverage.blocks_emitted == 2
    assert coverage.dictionary_occurrences == 1
    assert coverage.candidates == 1
    assert coverage.discoveries_consumed == 1
    assert coverage.source_identity == "static-l08"
    first_occ = _dictionary_occurrences(records[0])[0]
    assert isinstance(first_occ.candidates[0].evidence, ExactEvidence | NormalizedExactEvidence)


def test_none_versus_present_lexical_term_id_orders_stably() -> None:
    rows = {
        ("materials_fda_ema", "f-absent"): _row(
            "materials_fda_ema",
            "f-absent",
            material_name="water",
            lexical_term_id="",
        ),
        ("materials_fda_ema", "f-present"): _row(
            "materials_fda_ema",
            "f-present",
            material_name="water",
            lexical_term_id="lt-present",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    forward = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-present",
            lexical_term_id="lt-present",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-absent",
            lexical_term_id=None,
        ),
    ]
    reversed_hits = list(reversed(forward))
    first = _dictionary_occurrences(_aggregate(forward, blocks, snapshot)[0])[0]
    second = _dictionary_occurrences(_aggregate(reversed_hits, blocks, snapshot)[0])[0]
    assert len(first.candidates) == 1
    assert first.candidates[0].row_id == second.candidates[0].row_id
    assert isinstance(first.candidates[0], FdaEmaMaterialCandidate)
    assert first.candidates[0].supporting_row_ids == ()
    assert first.candidates[0].ambiguity is AmbiguityQualification.UNRESOLVED
    assert first.occurrence_id == second.occurrence_id


def test_many_distinct_blocks_stay_within_per_block_bound() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    block_count = 120
    # One block per page keeps the page buffer at one while stressing per-block capacity.
    blocks = [
        _block("water", node_id=f"n-{index}", page_number=index + 1, order=0)
        for index in range(block_count)
    ]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
            block_node_id=f"n-{index}",
        )
        for index in range(block_count)
    ]
    # Per-block limit is 2; 120 distinct pages with one hit each must succeed.
    records = _aggregate(
        discoveries,
        blocks,
        snapshot,
        limits=_limits(result_buffer_records=2),
    )
    assert len(records) == block_count
    assert sum(len(_dictionary_occurrences(record)) for record in records) == block_count
    assert all(len(_dictionary_occurrences(record)) == 1 for record in records)


def test_unmatched_spooled_hits_and_empty_replay_fail_without_coverage() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    discovery = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
            block_node_id="missing-block",
        )
    ]
    stream = iter_aggregated_block_records(
        discovery,
        StaticBlockSource(blocks=(_block("water"),), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    with pytest.raises(DictionaryAggregationError) as absent_exc:
        list(stream)
    assert absent_exc.value.code == "UNMATCHED_SPOOL_HITS"
    with pytest.raises(DictionaryAggregationError) as coverage_exc:
        _ = stream.coverage
    assert coverage_exc.value.code == "AGGREGATION_INCOMPLETE"

    empty_stream = iter_aggregated_block_records(
        discovery,
        StaticBlockSource(blocks=(), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    with pytest.raises(DictionaryAggregationError) as empty_exc:
        list(empty_stream)
    assert empty_exc.value.code == "UNMATCHED_SPOOL_HITS"
    with pytest.raises(DictionaryAggregationError):
        _ = empty_stream.coverage


def test_expected_source_identity_is_required() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    with pytest.raises(DictionaryAggregationError) as exc:
        iter_aggregated_block_records(
            (),
            StaticBlockSource(blocks=(), identity="static-l08"),
            snapshot,
            _limits(),
            expected_source_identity=None,
        )
    assert exc.value.code == "SOURCE_IDENTITY_REQUIRED"


def test_partial_spool_open_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    closed: list[bool] = []

    def connect_then_fail(path: object, *args: object, **kwargs: object) -> object:
        closed_holder: list[bool] = closed

        class Proxy:
            def execute(self, sql: object, parameters: object = ()) -> object:
                raise sqlite3.Error("injected create failure")

            def commit(self) -> None:
                return None

            def close(self) -> None:
                closed_holder.append(True)

        return Proxy()

    monkeypatch.setattr(
        "app.lexical_extraction.dictionary_aggregation.sqlite3.connect",
        connect_then_fail,
    )
    with pytest.raises(DictionaryAggregationError) as exc:
        _aggregate([], [_block("water")], snapshot)
    assert exc.value.code == "SPOOL_WRITE_FAILED"
    assert closed == [True]


def test_failed_cleanup_after_success_blocks_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]
    real_temp = tempfile.TemporaryDirectory
    created: list[tempfile.TemporaryDirectory[str]] = []

    class FailingTempDir:
        def __init__(self, *, prefix: str | None = None) -> None:
            self._inner = real_temp(prefix=prefix)
            created.append(self._inner)
            self.name = self._inner.name

        def cleanup(self) -> None:
            raise OSError("injected cleanup failure")

    monkeypatch.setattr(
        "app.lexical_extraction.dictionary_aggregation.tempfile.TemporaryDirectory",
        FailingTempDir,
    )
    stream = iter_aggregated_block_records(
        discoveries,
        StaticBlockSource(blocks=(_block("water"),), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    try:
        with pytest.raises(DictionaryAggregationError) as exc:
            list(stream)
        assert exc.value.code == "SPOOL_CLEANUP_FAILED"
        with pytest.raises(DictionaryAggregationError) as coverage_exc:
            _ = stream.coverage
        assert coverage_exc.value.code == "AGGREGATION_INCOMPLETE"
    finally:
        for directory in created:
            directory.cleanup()


def test_early_ingest_failure_closes_upstream_iterator() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    closed: list[bool] = []

    def discoveries() -> Iterator[RawDiscovery]:
        try:
            yield _discovery(
                dictionary_term="water",
                matched_text="water",
                start=0,
                end=5,
                component=Component.MATERIALS,
                term_role="material_name",
                source_table="materials_fda_ema",
                source_field="material_name",
                row_id="f-1",
                lexical_term_id="lt-1",
            )
            yield RawDiscovery(
                method="exact",
                rule_id="lexical-v1-exact",
                dictionary_term="rpm",
                component=Component.UNITS,
                term_role="unit_spelling",
                source_table="equipment",
                source_field="Unit",
                row_id="e-1",
                block_node_id="n1",
                span=CharSpan(start_char=0, end_char=3, matched_text="rpm"),
                snapshot_id=_SNAPSHOT_ID,
            )
        finally:
            closed.append(True)

    generator = discoveries()
    stream = iter_aggregated_block_records(
        generator,
        StaticBlockSource(blocks=(_block("water"),), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    with pytest.raises(DictionaryAggregationError) as exc:
        list(stream)
    assert exc.value.code == "UNEXPECTED_UNIT_DISCOVERY"
    assert closed == [True]
    with pytest.raises(DictionaryAggregationError):
        _ = stream.coverage


def test_commit_failure_after_valid_discoveries_is_spool_write_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
    ]
    real_connect = sqlite3.connect

    class CommitFailingConnection:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self._fail_next_commit = False

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
            if "INSERT INTO discoveries" in sql:
                self._fail_next_commit = True
            return self._inner.execute(sql, parameters)

        def commit(self) -> None:
            if self._fail_next_commit:
                raise sqlite3.Error("injected commit failure")
            self._inner.commit()

        def rollback(self) -> None:
            self._inner.rollback()

        def close(self) -> None:
            self._inner.close()

    def connect_failing_commit(*args: Any, **kwargs: Any) -> CommitFailingConnection:
        return CommitFailingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(
        "app.lexical_extraction.dictionary_aggregation.sqlite3.connect",
        connect_failing_commit,
    )
    stream = iter_aggregated_block_records(
        discoveries,
        StaticBlockSource(blocks=(_block("water"),), identity="static-l08"),
        snapshot,
        _limits(),
        expected_source_identity="static-l08",
    )
    with pytest.raises(DictionaryAggregationError) as exc:
        list(stream)
    assert exc.value.code == "SPOOL_WRITE_FAILED"
    assert "commit" in exc.value.message.lower()
    with pytest.raises(DictionaryAggregationError) as coverage_exc:
        _ = stream.coverage
    assert coverage_exc.value.code == "AGGREGATION_INCOMPLETE"


def test_block_counter_threshold_without_discoveries_count_star(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    at_limit = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        )
        for _ in range(2)
    ]
    over_limit = [
        *at_limit,
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
        ),
    ]

    real_connect = sqlite3.connect
    recorded_sql: list[str] = []

    class LoggingConnection:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
            recorded_sql.append(" ".join(sql.split()))
            return self._inner.execute(sql, parameters)

        def commit(self) -> None:
            self._inner.commit()

        def rollback(self) -> None:
            self._inner.rollback()

        def close(self) -> None:
            self._inner.close()

    def connect_logging(*args: Any, **kwargs: Any) -> LoggingConnection:
        return LoggingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(
        "app.lexical_extraction.dictionary_aggregation.sqlite3.connect",
        connect_logging,
    )

    records = _aggregate(
        at_limit,
        blocks,
        snapshot,
        limits=_limits(result_buffer_records=2),
    )
    assert len(_dictionary_occurrences(records[0])) == 1
    assert not any(
        "COUNT(*)" in sql.upper()
        and "from discoveries" in sql.lower()
        and "block_node_id" in sql.lower()
        for sql in recorded_sql
    )
    assert any("FROM block_hit_counts" in sql for sql in recorded_sql)

    recorded_sql.clear()
    with pytest.raises(DictionaryAggregationError) as overflow_exc:
        _aggregate(
            over_limit,
            blocks,
            snapshot,
            limits=_limits(result_buffer_records=2),
        )
    assert overflow_exc.value.code == "RESOURCE_LIMIT_EXCEEDED"
    assert not any(
        "COUNT(*)" in sql.upper()
        and "from discoveries" in sql.lower()
        and "block_node_id" in sql.lower()
        for sql in recorded_sql
    )


def test_same_material_span_emits_one_candidate_without_supporting_rows() -> None:
    rows = {
        ("materials_fda_ema", "m-a"): _row(
            "materials_fda_ema",
            "m-a",
            material_name="water",
            lexical_term_id="lt-a",
        ),
        ("materials_fda_ema", "m-b"): _row(
            "materials_fda_ema",
            "m-b",
            material_name="water",
            lexical_term_id="lt-b",
        ),
        ("materials_chebi", "c-1"): _row(
            "materials_chebi",
            "c-1",
            material_name="water",
            CHEBI_ID="CHEBI:15377",
            lexical_term_id="lt-c",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-b",
            lexical_term_id="lt-b",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_chebi",
            source_field="material_name",
            row_id="c-1",
            lexical_term_id="lt-c",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-a",
            lexical_term_id="lt-a",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 1
    occ = occs[0]
    assert occ.applies_to == (Component.MATERIALS,)
    assert len(occ.candidates) == 1
    candidate = occ.candidates[0]
    assert candidate.supporting_row_ids == ()
    assert candidate.ambiguity is AmbiguityQualification.UNRESOLVED
    assert candidate.row_id in {"m-a", "m-b", "c-1"}
    assert occ.location.matched_text == "water"
    assert occ.block_node_id == blocks[0].node_id
    assert isinstance(candidate.evidence, ExactEvidence)


def test_same_span_two_components_remain_independent() -> None:
    rows = {
        ("materials_fda_ema", "m-1"): _row(
            "materials_fda_ema",
            "m-1",
            material_name="Mixer",
            lexical_term_id="lt-m",
        ),
        ("equipment", "e-1"): _row(
            "equipment",
            "e-1",
            **{"Equipment type (EN)": "Mixer", "equipment_type_id": "EQ-1"},
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("Mixer")]
    discoveries = [
        _discovery(
            dictionary_term="Mixer",
            matched_text="Mixer",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-1",
            lexical_term_id="lt-m",
        ),
        _discovery(
            dictionary_term="Mixer",
            matched_text="Mixer",
            start=0,
            end=5,
            component=Component.EQUIPMENT,
            term_role="equipment_type",
            source_table="equipment",
            source_field="Equipment type (EN)",
            row_id="e-1",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 2
    by_component = {occ.applies_to[0]: occ for occ in occs}
    assert set(by_component) == {Component.MATERIALS, Component.EQUIPMENT}
    for occ in occs:
        assert len(occ.candidates) == 1
        assert occ.candidates[0].supporting_row_ids == ()
        assert occ.location.matched_text == "Mixer"
        assert occ.block_node_id == blocks[0].node_id


def test_related_synonym_alias_is_searchable_and_short_context_still_excluded() -> None:
    rows = {
        ("materials_chebi", "c-rel"): _row(
            "materials_chebi",
            "c-rel",
            material_name="solvent",
            alias_name="related spelling",
            CHEBI_ID="CHEBI:1",
            alias_type="hasRelatedSynonym",
            lexical_term_id="lt-rel",
        ),
        ("unit_operations", "uo-ctx"): _row(
            "unit_operations",
            "uo-ctx",
            **{
                "Search term (EN)": "sieving",
                "Index this row": "TRUE",
                "Match policy": "context_required",
                "record_type": "unit_operation",
                "Operation ID": "UO-1",
                "lexical_term_id": "lt-ctx",
            },
        ),
        ("materials_fda_ema", "m-short"): _row(
            "materials_fda_ema",
            "m-short",
            material_name="to",
            lexical_term_id="lt-short",
        ),
        ("materials_fda_ema", "m-ok"): _row(
            "materials_fda_ema",
            "m-ok",
            material_name="lactose",
            lexical_term_id="lt-ok",
        ),
    }
    related_terms = map_source_row(
        rows[("materials_chebi", "c-rel")], components=(Component.MATERIALS,)
    )
    related_alias = next(term for term in related_terms if term.source_field == "alias_name")
    assert related_alias.literal == "related spelling"
    assert related_alias.alias_type == "hasRelatedSynonym"
    assert (
        map_source_row(rows[("unit_operations", "uo-ctx")], components=(Component.UNIT_OPERATIONS,))
        == ()
    )
    assert (
        map_source_row(rows[("materials_fda_ema", "m-short")], components=(Component.MATERIALS,))
        == ()
    )

    snapshot = FakeSnapshot(rows=rows)
    text = "related spelling sieving to lactose"
    blocks = [_block(text)]
    discoveries = [
        _discovery(
            dictionary_term="related spelling",
            matched_text="related spelling",
            start=0,
            end=16,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_chebi",
            source_field="alias_name",
            row_id="c-rel",
            lexical_term_id="lt-rel",
        ),
        _discovery(
            dictionary_term="sieving",
            matched_text="sieving",
            start=17,
            end=24,
            component=Component.UNIT_OPERATIONS,
            term_role="unit_operation",
            source_table="unit_operations",
            source_field="Search term (EN)",
            row_id="uo-ctx",
            lexical_term_id="lt-ctx",
        ),
        _discovery(
            dictionary_term="to",
            matched_text="to",
            start=25,
            end=27,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-short",
            lexical_term_id="lt-short",
        ),
        _discovery(
            dictionary_term="lactose",
            matched_text="lactose",
            start=28,
            end=35,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-ok",
            lexical_term_id="lt-ok",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 2
    by_text = {occ.location.matched_text: occ for occ in occs}
    assert set(by_text) == {"related spelling", "lactose"}
    related_occ = by_text["related spelling"]
    assert related_occ.applies_to == (Component.MATERIALS,)
    assert len(related_occ.candidates) == 1
    assert related_occ.candidates[0].row_id == "c-rel"
    assert related_occ.candidates[0].supporting_row_ids == ()
    assert related_occ.candidates[0].ambiguity is AmbiguityQualification.CONTEXT_REQUIRED
    assert isinstance(related_occ.candidates[0], ChebiMaterialCandidate)
    assert related_occ.candidates[0].alias_type == "hasRelatedSynonym"
    lactose = by_text["lactose"]
    assert lactose.candidates[0].row_id == "m-ok"
    assert lactose.candidates[0].supporting_row_ids == ()
    assert lactose.candidates[0].ambiguity is AmbiguityQualification.NONE
    assert isinstance(lactose.candidates[0].evidence, ExactEvidence)


def test_canonical_name_wins_over_alias_on_same_span() -> None:
    rows = {
        ("materials_fda_ema", "m-name"): _row(
            "materials_fda_ema",
            "m-name",
            material_name="water",
            lexical_term_id="lt-name",
        ),
        ("materials_fda_ema", "m-alias"): _row(
            "materials_fda_ema",
            "m-alias",
            material_name="dihydrogen oxide",
            alias_name="water",
            alias_type="hasExactSynonym",
            lexical_term_id="lt-alias",
        ),
        ("materials_fda_ema", "m-alias-2"): _row(
            "materials_fda_ema",
            "m-alias-2",
            material_name="oxidane label",
            alias_name="water",
            alias_type="hasRelatedSynonym",
            lexical_term_id="lt-alias-2",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="m-alias",
            lexical_term_id="lt-alias",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="m-alias-2",
            lexical_term_id="lt-alias-2",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-name",
            lexical_term_id="lt-name",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 1
    candidate = occs[0].candidates[0]
    assert len(occs[0].candidates) == 1
    assert candidate.supporting_row_ids == ()
    assert isinstance(candidate, FdaEmaMaterialCandidate)
    assert candidate.source_field == "material_name"
    assert candidate.row_id == "m-name"


def test_alias_only_span_emits_one_deterministic_candidate() -> None:
    rows = {
        ("materials_fda_ema", "m-b"): _row(
            "materials_fda_ema",
            "m-b",
            material_name="display b",
            alias_name="water",
            alias_type="hasExactSynonym",
            lexical_term_id="lt-b",
        ),
        ("materials_fda_ema", "m-a"): _row(
            "materials_fda_ema",
            "m-a",
            material_name="display a",
            alias_name="water",
            alias_type="hasRelatedSynonym",
            lexical_term_id="lt-a",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [_block("water")]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="m-b",
            lexical_term_id="lt-b",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="m-a",
            lexical_term_id="lt-a",
        ),
    ]
    forward = _aggregate(discoveries, blocks, snapshot)
    reversed_hits = _aggregate(list(reversed(discoveries)), blocks, snapshot)
    forward_occ = _dictionary_occurrences(forward[0])[0]
    reversed_occ = _dictionary_occurrences(reversed_hits[0])[0]
    assert len(forward_occ.candidates) == 1
    assert len(reversed_occ.candidates) == 1
    assert forward_occ.candidates[0].supporting_row_ids == ()
    assert reversed_occ.candidates[0].supporting_row_ids == ()
    assert forward_occ.candidates[0].row_id == reversed_occ.candidates[0].row_id
    assert forward_occ.occurrence_id == reversed_occ.occurrence_id
    assert isinstance(forward_occ.candidates[0], FdaEmaMaterialCandidate)
    assert forward_occ.candidates[0].source_field == "alias_name"


def test_page_dedup_keeps_one_occurrence_per_component_text() -> None:
    rows = {
        ("materials_fda_ema", "m-alias"): _row(
            "materials_fda_ema",
            "m-alias",
            material_name="dihydrogen oxide",
            alias_name="water",
            alias_type="hasExactSynonym",
            lexical_term_id="lt-alias",
        ),
        ("materials_fda_ema", "m-name"): _row(
            "materials_fda_ema",
            "m-name",
            material_name="water",
            lexical_term_id="lt-name",
        ),
        ("materials_fda_ema", "m-other"): _row(
            "materials_fda_ema",
            "m-other",
            material_name="lactose",
            lexical_term_id="lt-other",
        ),
        ("equipment", "e-1"): _row(
            "equipment",
            "e-1",
            **{"Equipment type (EN)": "water", "equipment_type_id": "EQ-1"},
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [
        _block("water", node_id="b1", page_number=1, order=0),
        _block("water again", node_id="b2", page_number=1, order=1),
        _block("lactose", node_id="b4", page_number=1, order=2),
        _block("water", node_id="b3", page_number=2, order=0),
    ]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_alias",
            source_table="materials_fda_ema",
            source_field="alias_name",
            row_id="m-alias",
            block_node_id="b1",
            lexical_term_id="lt-alias",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.EQUIPMENT,
            term_role="equipment_type",
            source_table="equipment",
            source_field="Equipment type (EN)",
            row_id="e-1",
            block_node_id="b1",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-name",
            block_node_id="b2",
            lexical_term_id="lt-name",
        ),
        _discovery(
            dictionary_term="lactose",
            matched_text="lactose",
            start=0,
            end=7,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-other",
            block_node_id="b4",
            lexical_term_id="lt-other",
        ),
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="m-name",
            block_node_id="b3",
            lexical_term_id="lt-name",
        ),
    ]
    records = _aggregate(discoveries, blocks, snapshot)
    by_node = {record.block.node_id: record for record in records}
    assert _dictionary_occurrences(by_node["b1"])  # equipment kept; material alias suppressed
    b1_occs = _dictionary_occurrences(by_node["b1"])
    assert len(b1_occs) == 1
    assert b1_occs[0].applies_to == (Component.EQUIPMENT,)
    b2_occs = _dictionary_occurrences(by_node["b2"])
    assert len(b2_occs) == 1
    assert b2_occs[0].applies_to == (Component.MATERIALS,)
    assert isinstance(b2_occs[0].candidates[0], FdaEmaMaterialCandidate)
    assert b2_occs[0].candidates[0].source_field == "material_name"
    assert b2_occs[0].candidates[0].supporting_row_ids == ()
    b3_occs = _dictionary_occurrences(by_node["b3"])
    assert len(b3_occs) == 1
    assert b3_occs[0].location.matched_text == "water"
    b4_occs = _dictionary_occurrences(by_node["b4"])
    assert len(b4_occs) == 1
    assert b4_occs[0].location.matched_text == "lactose"


def test_page_buffer_exceeding_result_buffer_records_fails() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [
        _block("water", node_id="n-0", page_number=1, order=0),
        _block("water", node_id="n-1", page_number=1, order=1),
        _block("water", node_id="n-2", page_number=1, order=2),
    ]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
            block_node_id=f"n-{index}",
        )
        for index in range(3)
    ]
    with pytest.raises(DictionaryAggregationError) as overflow_exc:
        _aggregate(
            discoveries,
            blocks,
            snapshot,
            limits=_limits(result_buffer_records=2),
        )
    assert overflow_exc.value.code == "RESOURCE_LIMIT_EXCEEDED"
    assert overflow_exc.value.message == "per-page block count exceeds result_buffer_records"
    structured = overflow_exc.value.to_structured_error()
    assert structured.code == "RESOURCE_LIMIT_EXCEEDED"
    assert structured.message == "per-page block count exceeds result_buffer_records"
    assert structured.retryable is False


def test_page_buffer_count_resets_across_pages() -> None:
    rows = {
        ("materials_fda_ema", "f-1"): _row(
            "materials_fda_ema",
            "f-1",
            material_name="water",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    blocks = [
        _block("water", node_id="p1-a", page_number=1, order=0),
        _block("water", node_id="p1-b", page_number=1, order=1),
        _block("water", node_id="p2-a", page_number=2, order=0),
        _block("water", node_id="p2-b", page_number=2, order=1),
    ]
    discoveries = [
        _discovery(
            dictionary_term="water",
            matched_text="water",
            start=0,
            end=5,
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="f-1",
            lexical_term_id="lt-1",
            block_node_id=node_id,
        )
        for node_id in ("p1-a", "p1-b", "p2-a", "p2-b")
    ]
    records = _aggregate(
        discoveries,
        blocks,
        snapshot,
        limits=_limits(result_buffer_records=2),
    )
    assert len(records) == 4
    by_node = {record.block.node_id: record for record in records}
    assert len(_dictionary_occurrences(by_node["p1-a"])) == 1
    assert by_node["p1-b"].occurrences == ()
    assert len(_dictionary_occurrences(by_node["p2-a"])) == 1
    assert by_node["p2-b"].occurrences == ()


def test_meaningful_exact_term_keeps_source_backed_span_evidence() -> None:
    rows = {
        ("materials_fda_ema", "m-1"): _row(
            "materials_fda_ema",
            "m-1",
            material_name="glucose",
            UNII="5SL0G7R0OK",
            lexical_term_id="lt-1",
        ),
    }
    snapshot = FakeSnapshot(rows=rows)
    text = "charge glucose now"
    blocks = [_block(text)]
    terms = map_source_row(
        rows[("materials_fda_ema", "m-1")],
        components=(Component.MATERIALS,),
        snapshot_id=_SNAPSHOT_ID,
    )
    assert any(term.literal == "glucose" for term in terms)
    source = StaticBlockSource(blocks=tuple(blocks), identity="static-l08")
    discoveries = list(iter_raw_discoveries(terms, source, _limits()))
    records = _aggregate(discoveries, blocks, snapshot)
    occs = _dictionary_occurrences(records[0])
    assert len(occs) == 1
    occ = occs[0]
    assert occ.applies_to == (Component.MATERIALS,)
    assert len(occ.candidates) == 1
    candidate = occ.candidates[0]
    assert isinstance(candidate, FdaEmaMaterialCandidate)
    assert candidate.row_id == "m-1"
    assert candidate.supporting_row_ids == ()
    assert candidate.ambiguity is AmbiguityQualification.NONE
    assert occ.location.matched_text == "glucose"
    assert occ.location.start_char == text.index("glucose")
    assert occ.location.end_char == text.index("glucose") + len("glucose")
    assert occ.block_node_id == blocks[0].node_id
    assert isinstance(candidate.evidence, ExactEvidence)
