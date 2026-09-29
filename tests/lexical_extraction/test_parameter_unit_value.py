"""L10 independent parameter names, units, and value expressions."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    AmbiguousNumber,
    BlockEvidence,
    CategoricalExpression,
    ComparisonValue,
    Component,
    CuedUnitlessValue,
    DictionaryOccurrence,
    EquipmentUnitRecord,
    ExactDecimal,
    FixedUnitVocabulary,
    KnowledgeSnapshotIdentity,
    ParameterNameCandidate,
    RangeValue,
    ScalarWithUnit,
    SymmetricTolerance,
    UnitOccurrence,
    ValueOccurrence,
)
from app.lexical_extraction.dictionary_matcher import (
    DictionaryMatchError,
    ReviewedHtmlBlockReplay,
    StaticBlockSource,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm, map_source_row
from app.lexical_extraction.knowledge_snapshot import FLAT_SOURCE_TABLES, SourceRow
from app.lexical_extraction.parameter_unit_value import (
    ParameterUnitValueError,
    iter_parameter_unit_value_block_records,
    recognize_block_values,
)
from app.lexical_extraction.unit_aggregation import (
    UnitAggregationError,
    fixed_vocabulary_unit_terms,
    iter_unit_mentions_from_terms,
)
from app.lexical_extraction.value_expressions import recognize_value_expressions

_HEADERS = dict(FLAT_SOURCE_TABLES)
_SNAPSHOT_ID = "fixture-snapshot-l10"


def _limits(**overrides: int) -> ResourceLimits:
    data = {
        "sqlite_read_batch_rows": 100,
        "sqlite_cache_kib": 1024,
        "max_terms_per_shard": 1000,
        "max_term_codepoints_per_shard": 100000,
        "result_buffer_records": 1000,
    }
    data.update(overrides)
    return ResourceLimits.model_validate(data)


def _block(
    text: str,
    *,
    node_id: str = "n1",
    page_number: int = 1,
    order: int = 1,
) -> BlockEvidence:
    return BlockEvidence(
        node_id=node_id,
        kind="paragraph",
        text=text,
        page_number=page_number,
        order=order,
        element_id="e1",
        ocr_references=(),
    )


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


def _parameter_term(literal: str = "Impeller speed", *, row_id: str = "eq-1") -> EligibleSearchTerm:
    return EligibleSearchTerm(
        literal=literal,
        component=Component.PARAMETER_NAMES,
        term_role="parameter_name",
        source_table="equipment",
        source_field="Operating parameter (EN)",
        row_id=row_id,
        snapshot_id=_SNAPSHOT_ID,
        boundary_hint="default",
        fuzzy_allowed=False,
        display_name=literal,
        parameter_id=f"param-{row_id}",
    )


def _equipment_unit_term(literal: str = "rpm", *, row_id: str = "eq-u1") -> EligibleSearchTerm:
    return EligibleSearchTerm(
        literal=literal,
        component=Component.UNITS,
        term_role="unit_spelling",
        source_table="equipment",
        source_field="Unit",
        row_id=row_id,
        snapshot_id=_SNAPSHOT_ID,
        boundary_hint="atomic_unit",
        fuzzy_allowed=False,
        source_section="Equipment / units",
    )


def _run(
    blocks: Sequence[BlockEvidence],
    *,
    components: Sequence[Component],
    parameter_terms: Sequence[EligibleSearchTerm] = (),
    equipment_unit_terms: Sequence[EligibleSearchTerm] = (),
    snapshot: FakeSnapshot | None = None,
    limits: ResourceLimits | None = None,
):
    source = StaticBlockSource(tuple(blocks), identity="synthetic:l10")
    stream = iter_parameter_unit_value_block_records(
        source,
        components=components,
        limits=limits or _limits(),
        parameter_terms=parameter_terms,
        equipment_unit_terms=equipment_unit_terms,
        snapshot=snapshot,
    )
    records = list(stream)
    return records, stream.coverage


def test_independent_four_example_behavior() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{
                "Operating parameter (EN)": "Impeller speed",
                "parameter_id": "param-eq-1",
                "Unit": "rpm",
                "Source / section": "Mixing",
            },
        ),
    }
    snapshot = FakeSnapshot(rows)
    parameter_terms = map_source_row(
        rows[("equipment", "eq-1")],
        components=(Component.PARAMETER_NAMES,),
        snapshot_id=_SNAPSHOT_ID,
    )
    unit_terms = map_source_row(
        rows[("equipment", "eq-1")],
        components=(Component.UNITS,),
        snapshot_id=_SNAPSHOT_ID,
    )

    name_only, _ = _run(
        [_block("Impeller speed", node_id="b-name")],
        components=(Component.PARAMETER_NAMES,),
        parameter_terms=parameter_terms,
        snapshot=snapshot,
    )
    assert len(name_only) == 1
    assert len(name_only[0].occurrences) == 1
    assert isinstance(name_only[0].occurrences[0], DictionaryOccurrence)
    assert name_only[0].occurrences[0].location.matched_text == "Impeller speed"
    assert not any(
        isinstance(o, UnitOccurrence | ValueOccurrence) for o in name_only[0].occurrences
    )

    unit_only, _ = _run(
        [_block("rpm", node_id="b-unit")],
        components=(Component.UNITS,),
        equipment_unit_terms=unit_terms,
        snapshot=snapshot,
    )
    assert len(unit_only[0].occurrences) == 1
    unit_occ = unit_only[0].occurrences[0]
    assert isinstance(unit_occ, UnitOccurrence)
    assert unit_occ.mention.literal_text == "rpm"
    assert unit_occ.mention.provenance is not None
    assert unit_occ.mention.provenance.kind == "equipment_unit_record"

    for text, node in (("120 rpm", "b-space"), ("120rpm", "b-tight")):
        values, _ = _run(
            [_block(text, node_id=node)],
            components=(Component.QUANTITY_EXPRESSIONS,),
        )
        assert len(values[0].occurrences) == 1
        value = values[0].occurrences[0]
        assert isinstance(value, ValueOccurrence)
        assert isinstance(value.expression, ScalarWithUnit)
        assert value.expression.raw_expression == text
        assert value.expression.source_unit_spelling == "rpm"
        assert value.expression.number == ExactDecimal(text="120")
        assert not any(isinstance(o, UnitOccurrence) for o in values[0].occurrences)

    combined, _ = _run(
        [_block("Impeller speed: 120 rpm", node_id="b-combo")],
        components=(
            Component.PARAMETER_NAMES,
            Component.UNITS,
            Component.QUANTITY_EXPRESSIONS,
            Component.PARAMETER_VALUE_EXPRESSIONS,
        ),
        parameter_terms=parameter_terms,
        equipment_unit_terms=unit_terms,
        snapshot=snapshot,
    )
    kinds = {type(o).__name__ for o in combined[0].occurrences}
    assert kinds == {"DictionaryOccurrence", "UnitOccurrence", "ValueOccurrence"}
    dict_occ = next(o for o in combined[0].occurrences if isinstance(o, DictionaryOccurrence))
    assert dict_occ.location.matched_text == "Impeller speed"
    value_occ = next(o for o in combined[0].occurrences if isinstance(o, ValueOccurrence))
    assert value_occ.applies_to == (
        Component.QUANTITY_EXPRESSIONS,
        Component.PARAMETER_VALUE_EXPRESSIONS,
    )
    assert "parameter_id" not in value_occ.expression.model_dump()


def test_supported_value_forms_and_offsets() -> None:
    text = "dose 2.5 kg at 20–25 °C with < 2.0% and 100 ± 5 g; keep 1.10 kg"
    block = _block(text)
    values = recognize_value_expressions(
        block,
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    by_raw = {value.expression.raw_expression: value.expression for value in values}
    assert isinstance(by_raw["2.5 kg"], ScalarWithUnit)
    assert by_raw["2.5 kg"].number == ExactDecimal(text="2.5")
    assert by_raw["2.5 kg"].source_unit_spelling == "kg"
    assert isinstance(by_raw["20–25 °C"], RangeValue)
    assert isinstance(by_raw["< 2.0%"], ComparisonValue)
    assert by_raw["< 2.0%"].comparator == "<"
    assert isinstance(by_raw["100 ± 5 g"], SymmetricTolerance)
    assert isinstance(by_raw["1.10 kg"], ScalarWithUnit)
    assert by_raw["1.10 kg"].number == ExactDecimal(text="1.10")
    for value in values:
        start = value.expression.span.start_char
        end = value.expression.span.end_char
        assert text[start:end] == value.expression.raw_expression


def test_tight_units_atomic_false_positives_and_categoricals() -> None:
    tight = recognize_value_expressions(
        _block("hold at 37°C then 120rpm"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert {v.expression.raw_expression for v in tight} == {"37°C", "120rpm"}

    compound = recognize_value_expressions(
        _block("inside rpm/min and min⁻¹ and mL·min⁻¹ and kg²"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert compound == ()

    units_only, _ = _run(
        [_block("inside rpm/min compound", node_id="b-false")],
        components=(Component.UNITS,),
        equipment_unit_terms=(_equipment_unit_term("rpm"),),
        snapshot=FakeSnapshot(
            {
                ("equipment", "eq-u1"): _row(
                    "equipment",
                    "eq-u1",
                    Unit="rpm",
                    **{"Source / section": "Mixing"},
                )
            }
        ),
    )
    assert units_only[0].occurrences == ()

    categorical = recognize_value_expressions(
        _block("set OFF and keep under vacuum"),
        applies_to=(Component.PARAMETER_VALUE_EXPRESSIONS,),
    )
    assert {v.expression.raw_expression for v in categorical} == {"OFF", "under vacuum"}
    assert all(isinstance(v.expression, CategoricalExpression) for v in categorical)

    cued = recognize_value_expressions(
        _block("Speed: 120"),
        applies_to=(Component.PARAMETER_VALUE_EXPRESSIONS,),
    )
    assert len(cued) == 1
    assert isinstance(cued[0].expression, CuedUnitlessValue)
    assert cued[0].expression.cue == "Speed:"
    assert cued[0].expression.number == ExactDecimal(text="120")


def test_both_value_components_once_and_units_suppressed() -> None:
    both = recognize_block_values(
        _block("2.5 kg"),
        components=(Component.QUANTITY_EXPRESSIONS, Component.PARAMETER_VALUE_EXPRESSIONS),
    )
    assert len(both) == 1
    assert both[0].applies_to == (
        Component.QUANTITY_EXPRESSIONS,
        Component.PARAMETER_VALUE_EXPRESSIONS,
    )

    quantity_only, coverage = _run(
        [_block("2.5 kg and rpm", node_id="b-q")],
        components=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert coverage.unit_occurrences == 0
    assert coverage.value_occurrences == 1
    assert all(isinstance(o, ValueOccurrence) for o in quantity_only[0].occurrences)
    assert not any(isinstance(o, UnitOccurrence) for o in quantity_only[0].occurrences)


def test_duplicate_equipment_unit_rows_retain_supporting_references() -> None:
    rows = {
        ("equipment", "eq-a"): _row(
            "equipment",
            "eq-a",
            Unit="rpm",
            **{"Source / section": "Mix A"},
        ),
        ("equipment", "eq-b"): _row(
            "equipment",
            "eq-b",
            Unit="rpm",
            **{"Source / section": "Mix B"},
        ),
    }
    for term_order in (
        ["eq-a", "eq-b"],
        ["eq-b", "eq-a"],
    ):
        terms = [
            term
            for row_id in term_order
            for term in map_source_row(
                rows[("equipment", row_id)],
                components=(Component.UNITS,),
                snapshot_id=_SNAPSHOT_ID,
            )
        ]
        records, _ = _run(
            [_block("rpm", node_id="b-dup")],
            components=(Component.UNITS,),
            equipment_unit_terms=terms,
            snapshot=FakeSnapshot(rows),
        )
        assert len(records[0].occurrences) == 1
        unit_occ = records[0].occurrences[0]
        assert isinstance(unit_occ, UnitOccurrence)
        mention = unit_occ.mention
        assert isinstance(mention.provenance, EquipmentUnitRecord)
        provenance = mention.provenance
        assert provenance.row_id == "eq-a"
        assert provenance.supporting_row_ids == ("eq-b",)
        assert provenance.source_section == "Mix A"
        assert mention.controlled_identity == "rpm"
        assert mention.controlled_spelling == "rpm"


def test_fixed_quantity_unit_absent_from_equipment() -> None:
    records, _ = _run(
        [_block("add 2.5 kg", node_id="b-kg")],
        components=(Component.UNITS, Component.QUANTITY_EXPRESSIONS),
    )
    unit_occs = [o for o in records[0].occurrences if isinstance(o, UnitOccurrence)]
    value_occs = [o for o in records[0].occurrences if isinstance(o, ValueOccurrence)]
    assert any(o.mention.literal_text == "kg" for o in unit_occs)
    fixed = next(o for o in unit_occs if o.mention.literal_text == "kg")
    assert isinstance(fixed.mention.provenance, FixedUnitVocabulary)
    assert fixed.mention.controlled_identity == "kg"
    assert value_occs[0].expression.raw_expression == "2.5 kg"


def test_multiple_parameter_candidates_without_equipment_inference() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{
                "Operating parameter (EN)": "Impeller speed",
                "parameter_id": "p1",
                "Equipment type (EN)": "Mixer",
                "equipment_type_id": "et-1",
            },
        ),
        ("equipment", "eq-2"): _row(
            "equipment",
            "eq-2",
            **{
                "Operating parameter (EN)": "Impeller speed",
                "parameter_id": "p2",
                "Equipment type (EN)": "Agitator",
                "equipment_type_id": "et-2",
            },
        ),
    }
    terms = [
        term
        for row in rows.values()
        for term in map_source_row(
            row, components=(Component.PARAMETER_NAMES,), snapshot_id=_SNAPSHOT_ID
        )
    ]
    records, _ = _run(
        [_block("Impeller speed", node_id="b-params")],
        components=(Component.PARAMETER_NAMES,),
        parameter_terms=terms,
        snapshot=FakeSnapshot(rows),
    )
    occ = records[0].occurrences[0]
    assert isinstance(occ, DictionaryOccurrence)
    assert len(occ.candidates) == 1
    assert {c.candidate_kind for c in occ.candidates} == {"parameter_name"}
    assert isinstance(occ.candidates[0], ParameterNameCandidate)
    assert occ.candidates[0].parameter_id in {"p1", "p2"}
    assert occ.candidates[0].supporting_row_ids == ()
    assert occ.candidates[0].ambiguity.value == "unresolved"


def test_casefolded_unit_value_and_controlled_identity() -> None:
    equipment = _equipment_unit_term("rpm", row_id="eq-u1")
    block = _block("hold 120 RPM")
    stream_values = recognize_block_values(
        block,
        components=(Component.QUANTITY_EXPRESSIONS,),
        equipment_unit_terms=(equipment,),
    )
    direct = recognize_value_expressions(
        block,
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
        unit_spellings=(),
    )
    assert len(stream_values) == 1
    assert len(direct) == 1
    stream_expr = stream_values[0].expression
    direct_expr = direct[0].expression
    assert isinstance(stream_expr, ScalarWithUnit)
    assert isinstance(direct_expr, ScalarWithUnit)
    assert stream_expr.source_unit_spelling == "RPM"
    assert stream_expr.controlled_unit_identity == "rpm"
    assert direct_expr.controlled_unit_identity == "rpm"
    assert stream_expr.controlled_unit_identity == direct_expr.controlled_unit_identity

    compound = recognize_value_expressions(
        _block("inside rpm/min and min⁻¹ and mL·min⁻¹ and kg²"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert compound == ()


def test_identifier_prefix_and_embedded_cue_negatives() -> None:
    assert (
        recognize_value_expressions(
            _block("batchID20–25 °C"),
            applies_to=(Component.QUANTITY_EXPRESSIONS,),
        )
        == ()
    )
    assert (
        recognize_value_expressions(
            _block("tagX100 ± 5 g"),
            applies_to=(Component.QUANTITY_EXPRESSIONS,),
        )
        == ()
    )
    assert (
        recognize_value_expressions(
            _block("MaxSpeed: 120"),
            applies_to=(Component.PARAMETER_VALUE_EXPRESSIONS,),
        )
        == ()
    )


def test_multi_block_buffer_is_per_block_not_cumulative() -> None:
    blocks = [
        _block("2.5 kg", node_id="b1", order=1),
        _block("3.0 kg", node_id="b2", order=2),
        _block("4.0 kg", node_id="b3", order=3),
    ]
    records, coverage = _run(
        blocks,
        components=(Component.QUANTITY_EXPRESSIONS,),
        limits=_limits(result_buffer_records=1),
    )
    assert len(records) == 3
    assert coverage.value_occurrences == 3
    assert all(len(record.occurrences) == 1 for record in records)


def _synthetic_reviewed_html(text_block: str) -> str:
    return (
        "<!doctype html>"
        '<html data-review-html-version="1" data-job-id="job-1" '
        'data-review-revision-id="rev-l10" data-review-generation="1" '
        'data-conversion-status="SUCCEEDED">'
        '<head><meta charset="utf-8"><title>L10 value-only</title></head>'
        "<body>"
        '<header class="summary" data-generated="true"><h1>Reviewed</h1></header>'
        '<main><section class="page" id="source-page-1" data-page="1">'
        '<h2 data-generated="true">Page 1</h2>'
        '<article class="element" data-element-id="el-1" data-kind="text">'
        f'<p data-node-id="node-1">{text_block}</p>'
        "</article>"
        "</section></main></body></html>"
    )


def test_value_only_fresh_html_replay_expected_digest(tmp_path: Path) -> None:
    html = _synthetic_reviewed_html("charge 2.5 kg")
    path = tmp_path / "value-only.html"
    path.write_bytes(html.encode("utf-8"))
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()

    fresh = ReviewedHtmlBlockReplay(path)
    with pytest.raises(DictionaryMatchError) as unpinned:
        _ = fresh.source_identity
    assert unpinned.value.code == "REPLAY_IDENTITY_UNPINNED"

    stream = iter_parameter_unit_value_block_records(
        fresh,
        components=(Component.QUANTITY_EXPRESSIONS,),
        limits=_limits(),
        expected_source_identity=digest,
    )
    records = list(stream)
    coverage = stream.coverage
    assert coverage.blocks_emitted == 1
    assert coverage.value_occurrences == 1
    assert coverage.source_identity == digest
    assert len(records) == 1
    value = records[0].occurrences[0]
    assert isinstance(value, ValueOccurrence)
    assert value.expression.raw_expression == "2.5 kg"
    assert isinstance(value.expression, ScalarWithUnit)

    wrong = ReviewedHtmlBlockReplay(path)
    bad_stream = iter_parameter_unit_value_block_records(
        wrong,
        components=(Component.QUANTITY_EXPRESSIONS,),
        limits=_limits(),
        expected_source_identity="0" * 64,
    )
    with pytest.raises(ParameterUnitValueError) as exc:
        list(bad_stream)
    assert exc.value.code == "REPLAY_IDENTITY_CHANGED"
    with pytest.raises(ParameterUnitValueError) as incomplete:
        _ = bad_stream.coverage
    assert incomplete.value.code == "STREAM_INCOMPLETE"


def test_equipment_unit_requires_snapshot() -> None:
    source = StaticBlockSource((_block("rpm"),), identity="synthetic:no-snap")
    stream = iter_unit_mentions_from_terms(
        (_equipment_unit_term("rpm"),),
        source,
        _limits(),
        snapshot=None,
        include_fixed_vocabulary=False,
    )
    with pytest.raises(UnitAggregationError) as exc:
        list(stream)
    assert exc.value.code == "SNAPSHOT_REQUIRED"


def test_exact_fixed_and_normalized_equipment_coexist() -> None:
    rows = {
        ("equipment", "eq-u1"): _row(
            "equipment",
            "eq-u1",
            Unit="RPM",
            **{"Source / section": "Mix"},
        ),
    }
    terms = map_source_row(
        rows[("equipment", "eq-u1")],
        components=(Component.UNITS,),
        snapshot_id=_SNAPSHOT_ID,
    )
    records, _ = _run(
        [_block("rpm", node_id="b-mixed")],
        components=(Component.UNITS,),
        equipment_unit_terms=terms,
        snapshot=FakeSnapshot(rows),
    )
    assert len(records[0].occurrences) == 1
    unit_occ = records[0].occurrences[0]
    assert isinstance(unit_occ, UnitOccurrence)
    mention = unit_occ.mention
    assert mention.literal_text == "rpm"
    assert mention.evidence.method == "exact"
    assert mention.controlled_identity == "rpm"
    assert isinstance(mention.provenance, EquipmentUnitRecord)
    assert mention.provenance.row_id == "eq-u1"


def test_ambiguous_separator_and_negatives() -> None:
    ambiguous = recognize_value_expressions(
        _block("charge 1,000 kg"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert len(ambiguous) == 1
    expression = ambiguous[0].expression
    assert isinstance(expression, ScalarWithUnit)
    assert isinstance(expression.number, AmbiguousNumber)
    assert expression.number.raw_token == "1,000"

    negatives = recognize_value_expressions(
        _block("Page 12 Step 3 ID AB-12 dated 2024-01-15"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert negatives == ()

    bare = recognize_value_expressions(
        _block("exactly 120 alone"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert bare == ()


def test_overlapping_repeated_expressions_preserved() -> None:
    values = recognize_value_expressions(
        _block("2.5 kg then again 2.5 kg"),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert len(values) == 2
    assert values[0].expression.span.start_char != values[1].expression.span.start_char


def test_component_only_selection_and_early_close_cleanup() -> None:
    snapshot = FakeSnapshot(
        {
            ("equipment", "eq-1"): _row(
                "equipment",
                "eq-1",
                **{"Operating parameter (EN)": "Impeller speed", "parameter_id": "p1"},
            )
        }
    )
    source = StaticBlockSource(
        (
            _block("Impeller speed", node_id="b1", order=1),
            _block("still open", node_id="b2", order=2),
        ),
        identity="synthetic:close",
    )
    stream = iter_parameter_unit_value_block_records(
        source,
        components=(Component.PARAMETER_NAMES,),
        limits=_limits(),
        parameter_terms=(_parameter_term(),),
        snapshot=snapshot,
    )
    iterator = iter(stream)
    first = next(iterator)
    assert isinstance(first.occurrences[0], DictionaryOccurrence)
    stream.close()
    with pytest.raises(ParameterUnitValueError) as exc:
        _ = stream.coverage
    assert exc.value.code == "STREAM_INCOMPLETE"


def test_unit_stream_early_close_and_fixed_vocab_terms() -> None:
    assert any(term.literal == "kg" for term in fixed_vocabulary_unit_terms())
    source = StaticBlockSource(
        (_block("kg", node_id="b1"), _block("again", node_id="b2")),
        identity="synthetic:unit-close",
    )
    stream = iter_unit_mentions_from_terms((), source, _limits(), include_fixed_vocabulary=True)
    iterator = iter(stream)
    record = next(iterator)
    assert any(isinstance(o, UnitOccurrence) for o in record.occurrences)
    stream.close()
    with pytest.raises(UnitAggregationError) as exc:
        _ = stream.coverage
    assert exc.value.code == "AGGREGATION_INCOMPLETE"


def test_unicode_whitespace_literal_slices() -> None:
    text = "mass 2.5\u00a0kg"
    values = recognize_value_expressions(
        _block(text),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    assert len(values) == 1
    span = values[0].expression.span
    assert text[span.start_char : span.end_char] == values[0].expression.raw_expression
