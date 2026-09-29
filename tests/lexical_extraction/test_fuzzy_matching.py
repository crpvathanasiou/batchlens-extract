"""Optional restricted fuzzy dictionary matching (L11)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import pytest

from app.lexical_extraction.comparison import (
    ComparisonError,
    normalize_literal,
    normalize_term,
    project_against_block,
)
from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    FUZZY_RULE_ID,
    BlockEvidence,
    CharSpan,
    Component,
    DictionaryOccurrence,
    ExactEvidence,
    FuzzyEvidence,
    KnowledgeSnapshotIdentity,
    NormalizedExactEvidence,
    ParameterNameCandidate,
    UnitOccurrence,
)
from app.lexical_extraction.dictionary_aggregation import (
    DictionaryAggregationError,
    iter_aggregated_block_records,
)
from app.lexical_extraction.dictionary_matcher import (
    DictionaryMatchError,
    RawDiscovery,
    StaticBlockSource,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm, map_source_row
from app.lexical_extraction.fuzzy_matching import (
    FuzzyCandidateIndex,
    add_fuzzy_term,
    candidate_keys_for_observed,
    deletion_signatures,
    fuzzy_signature_storage_codepoints,
    ordinary_levenshtein,
)
from app.lexical_extraction.knowledge_snapshot import FLAT_SOURCE_TABLES, SourceRow
from app.lexical_extraction.parameter_unit_value import iter_parameter_unit_value_block_records

_HEADERS = dict(FLAT_SOURCE_TABLES)
_SNAPSHOT_ID = "fixture-snapshot-l11"


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
class _FlipIdentitySource:
    blocks: tuple[BlockEvidence, ...]
    _identity: str = "id-initial"
    _passes: int = 0

    @property
    def source_identity(self) -> str:
        return self._identity

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        self._passes += 1
        if self._passes > 1:
            self._identity = "id-changed"
        yield from self.blocks


def _block(text: str, *, node_id: str = "n1") -> BlockEvidence:
    return BlockEvidence(
        node_id=node_id,
        kind="paragraph",
        text=text,
        page_number=1,
        order=0,
        element_id="e1",
    )


def _limits(
    *,
    max_terms_per_shard: int = 100,
    max_term_codepoints_per_shard: int = 100_000,
    result_buffer_records: int = 50,
) -> ResourceLimits:
    return ResourceLimits(
        max_terms_per_shard=max_terms_per_shard,
        max_term_codepoints_per_shard=max_term_codepoints_per_shard,
        result_buffer_records=result_buffer_records,
    )


def _term(
    literal: str,
    *,
    term_role: str = "parameter_name",
    component: Component = Component.PARAMETER_NAMES,
    source_table: str = "equipment",
    source_field: str = "Operating parameter (EN)",
    row_id: str = "eq-1",
    fuzzy_allowed: bool = True,
    match_policy: str | None = None,
    snapshot_id: str | None = _SNAPSHOT_ID,
    lexical_term_id: str | None = None,
    boundary_hint: str = "default",
) -> EligibleSearchTerm:
    return EligibleSearchTerm(
        literal=literal,
        component=component,
        term_role=term_role,
        source_table=source_table,
        source_field=source_field,
        row_id=row_id,
        snapshot_id=snapshot_id,
        lexical_term_id=lexical_term_id,
        boundary_hint=boundary_hint,
        fuzzy_allowed=fuzzy_allowed,
        match_policy=match_policy,
        display_name=literal,
    )


def _discovery_key(discovery: RawDiscovery) -> tuple[object, ...]:
    return (
        discovery.method,
        discovery.rule_id,
        discovery.dictionary_term,
        discovery.component,
        discovery.term_role,
        discovery.source_table,
        discovery.source_field,
        discovery.row_id,
        discovery.lexical_term_id,
        discovery.snapshot_id,
        discovery.block_node_id,
        discovery.span.start_char,
        discovery.span.end_char,
        discovery.span.matched_text,
        discovery.boundary_hint,
        discovery.edit_distance,
    )


def _multiset(discoveries: Iterable[RawDiscovery]) -> dict[tuple[object, ...], int]:
    counts: dict[tuple[object, ...], int] = {}
    for item in discoveries:
        key = _discovery_key(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _independent_fuzzy_oracle(
    terms: Sequence[EligibleSearchTerm],
    blocks: Sequence[BlockEvidence],
) -> list[RawDiscovery]:
    """Tiny exhaustive Levenshtein oracle for synthetic vocabularies only."""

    out: list[RawDiscovery] = []
    for term in terms:
        if not term.fuzzy_allowed:
            continue
        if term.term_role not in {
            "equipment_type",
            "parameter_name",
            "unit_operation",
            "process_step",
        }:
            continue
        if term.match_policy in {
            "context_required",
            "step_cue_only",
            "support_only",
            "inspection_only",
        }:
            continue
        term_surface = normalize_term(term)
        key = term_surface.comparison_text
        if any(ch.isspace() for ch in key) or not key.isalpha() or len(key) < 6:
            continue
        for block in blocks:
            if not block.text:
                continue
            block_surface = normalize_literal(
                block.text,
                term_role=term.term_role,
                boundary_hint=term.boundary_hint,
                strip_edges=False,
            )
            text = block_surface.comparison_text
            index = 0
            while index < len(text):
                if not text[index].isalpha():
                    index += 1
                    continue
                start = index
                index += 1
                while index < len(text) and text[index].isalpha():
                    index += 1
                observed = text[start:index]
                if len(observed) < 5:
                    continue
                distance = ordinary_levenshtein(observed, key, limit=1)
                if distance != 1:
                    continue
                try:
                    span = project_against_block(
                        block,
                        block_surface,
                        start,
                        index,
                        boundary_hint=term.boundary_hint,
                    )
                except ComparisonError as exc:
                    if exc.code in {"BOUNDARY_REJECTED", "PARTIAL_NORMALIZATION_UNIT"}:
                        continue
                    raise
                out.append(
                    RawDiscovery(
                        method="fuzzy",
                        rule_id=FUZZY_RULE_ID,
                        dictionary_term=term.literal,
                        component=term.component,
                        term_role=term.term_role,
                        source_table=term.source_table,
                        source_field=term.source_field,
                        row_id=term.row_id,
                        block_node_id=block.node_id,
                        span=span,
                        lexical_term_id=term.lexical_term_id,
                        snapshot_id=term.snapshot_id,
                        boundary_hint=term.boundary_hint,
                        edit_distance=1,
                        match_policy=term.match_policy,
                        fuzzy_allowed=term.fuzzy_allowed,
                    )
                )
    return out


def test_fuzzy_off_preserves_exact_and_builds_no_fuzzy_hits() -> None:
    terms = [_term("Filter", fuzzy_allowed=True)]
    blocks = [_block("Filter and Falter nearby")]
    source = StaticBlockSource(tuple(blocks), identity="off")
    off = list(iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=False))
    on = list(iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=True))
    assert all(item.method != "fuzzy" for item in off)
    assert any(item.method == "exact" and item.span.matched_text == "Filter" for item in off)
    off_exact = _multiset(item for item in off if item.method != "fuzzy")
    on_exact = _multiset(item for item in on if item.method != "fuzzy")
    assert off_exact == on_exact
    assert any(item.method == "fuzzy" and item.span.matched_text == "Falter" for item in on)


def test_one_edit_operations_and_transposition_negative() -> None:
    terms = [_term("Filter", fuzzy_allowed=True)]
    cases = {
        "insertion": ("Filters", True),
        "deletion": ("Filtr", True),
        "substitution": ("Falter", True),
        "adjacent_transposition": ("Filtre", False),
        "two_edits": ("Falsar", False),
    }

    for label, (text, expect_hit) in cases.items():
        discoveries = list(
            iter_raw_discoveries(
                terms,
                StaticBlockSource((_block(text),), identity=label),
                _limits(),
                fuzzy_enabled=True,
            )
        )
        fuzzy = [item for item in discoveries if item.method == "fuzzy"]
        if expect_hit:
            assert len(fuzzy) == 1, label
            assert fuzzy[0].edit_distance == 1
            assert fuzzy[0].rule_id == FUZZY_RULE_ID
            assert fuzzy[0].dictionary_term == "Filter"
            assert fuzzy[0].span.matched_text == text
            assert text[fuzzy[0].span.start_char : fuzzy[0].span.end_char] == text
        else:
            assert fuzzy == [], label


def test_five_char_observed_word_against_six_char_term() -> None:
    terms = [_term("Filter", fuzzy_allowed=True)]
    discoveries = list(
        iter_raw_discoveries(
            terms,
            StaticBlockSource((_block("Filtr"),), identity="five"),
            _limits(),
            fuzzy_enabled=True,
        )
    )
    fuzzy = [item for item in discoveries if item.method == "fuzzy"]
    assert len(fuzzy) == 1
    assert fuzzy[0].span.matched_text == "Filtr"


def test_casefold_unicode_projection_original_slice() -> None:
    terms = [_term("Filter", fuzzy_allowed=True)]
    text = "FILTERX"
    discoveries = list(
        iter_raw_discoveries(
            terms,
            StaticBlockSource((_block(text),), identity="case"),
            _limits(),
            fuzzy_enabled=True,
        )
    )
    fuzzy = [item for item in discoveries if item.method == "fuzzy"]
    assert len(fuzzy) == 1
    span = fuzzy[0].span
    assert text[span.start_char : span.end_char] == span.matched_text == "FILTERX"


def test_hyphen_identifier_and_forbidden_categories_are_non_fuzzy() -> None:
    equipment = _row(
        "equipment",
        "eq-1",
        **{
            "Equipment type (EN)": "Blender",
            "Operating parameter (EN)": "Pressure",
            "Unit": "rpm",
        },
    )
    material = _row(
        "materials_fda_ema",
        "mat-1",
        material_name="Glucose",
        UNII="ABCDEFGHIJ",
        lexical_term_id="lt-1",
    )
    chebi = _row(
        "materials_chebi",
        "ch-1",
        material_name="Oxidane",
        alias_name="Waterx",
        lexical_term_id="lt-2",
        chebi_id="CHEBI:1",
    )
    uo = _row(
        "unit_operations",
        "uo-1",
        **{
            "Index this row": "TRUE",
            "Match policy": "context_required",
            "record_type": "unit_operation",
            "Search term (EN)": "Mixing",
            "Process step (EN)": "Heating",
            "Canonical unit operation": "mixing",
        },
    )
    terms = [
        *map_source_row(
            equipment,
            components=(Component.EQUIPMENT, Component.PARAMETER_NAMES, Component.UNITS),
            snapshot_id=_SNAPSHOT_ID,
        ),
        *map_source_row(material, components=(Component.MATERIALS,), snapshot_id=_SNAPSHOT_ID),
        *map_source_row(chebi, components=(Component.MATERIALS,), snapshot_id=_SNAPSHOT_ID),
        *map_source_row(
            uo,
            components=(Component.UNIT_OPERATIONS, Component.PROCESS_STEPS),
            snapshot_id=_SNAPSHOT_ID,
        ),
        _term(
            "Blender",
            term_role="equipment_type",
            component=Component.EQUIPMENT,
            source_field="Equipment type (EN)",
            fuzzy_allowed=True,
        ),
    ]
    # Hyphen continuation and identifier-like tokens must not fuzzy-match.
    text = "Blendr glucose-6-phosphate ABCDEFGHIJ Waterx Mixin Heatin rpm"
    discoveries = list(
        iter_raw_discoveries(
            terms,
            StaticBlockSource((_block(text),), identity="forbidden"),
            _limits(),
            fuzzy_enabled=True,
        )
    )
    fuzzy = [item for item in discoveries if item.method == "fuzzy"]
    assert all(
        item.term_role in {"equipment_type", "parameter_name", "unit_operation", "process_step"}
        for item in fuzzy
    )
    assert all(item.component != Component.MATERIALS for item in fuzzy)
    assert all(item.term_role != "unit_spelling" for item in fuzzy)
    assert all(item.term_role != "generic_cue" for item in fuzzy)
    # context_required process/UO cues are non-fuzzy even when alphabetic.
    assert all(item.dictionary_term not in {"Mixing", "Heating"} for item in fuzzy)
    assert any(
        item.dictionary_term == "Blender" and item.span.matched_text == "Blendr" for item in fuzzy
    )
    # Hyphenated continuation rejects partial projection for Blendr inside a hyphen form.
    hyphen_discoveries = list(
        iter_raw_discoveries(
            [
                _term(
                    "Blender",
                    term_role="equipment_type",
                    component=Component.EQUIPMENT,
                    source_field="Equipment type (EN)",
                )
            ],
            StaticBlockSource((_block("Blendr-unit"),), identity="hyphen"),
            _limits(),
            fuzzy_enabled=True,
        )
    )
    assert [item for item in hyphen_discoveries if item.method == "fuzzy"] == []


def test_parameter_names_without_equipment_and_multi_interpretation() -> None:
    rows = {
        ("equipment", "eq-a"): _row(
            "equipment",
            "eq-a",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-a"},
        ),
        ("equipment", "eq-b"): _row(
            "equipment",
            "eq-b",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-b"},
        ),
        ("equipment", "eq-c"): _row(
            "equipment",
            "eq-c",
            **{"Equipment type (EN)": "Blender", "equipment_type_id": "et-1"},
        ),
        ("equipment", "eq-d"): _row(
            "equipment",
            "eq-d",
            **{"Equipment type (EN)": "Blender", "equipment_type_id": "et-1"},
        ),
    }
    terms = [
        term
        for row_id in ("eq-a", "eq-b")
        for term in map_source_row(
            rows[("equipment", row_id)],
            components=(Component.PARAMETER_NAMES,),
            snapshot_id=_SNAPSHOT_ID,
        )
    ]
    assert all(term.fuzzy_allowed for term in terms)
    source = StaticBlockSource((_block("Presure"),), identity="params")
    discoveries = list(iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=True))
    fuzzy = [item for item in discoveries if item.method == "fuzzy"]
    assert len(fuzzy) == 2
    assert {item.row_id for item in fuzzy} == {"eq-a", "eq-b"}
    stream = iter_aggregated_block_records(
        discoveries,
        source,
        FakeSnapshot(rows),
        _limits(),
        expected_source_identity="params",
    )
    records = list(stream)
    occurrence = records[0].occurrences[0]
    assert isinstance(occurrence, DictionaryOccurrence)
    candidates = occurrence.candidates
    assert len(candidates) == 1
    assert isinstance(candidates[0], ParameterNameCandidate)
    assert isinstance(candidates[0].evidence, FuzzyEvidence)
    assert candidates[0].evidence.edit_distance == 1
    assert candidates[0].row_id in {"eq-a", "eq-b"}
    assert candidates[0].supporting_row_ids == ()
    assert candidates[0].ambiguity.value == "unresolved"

    equipment_terms = [
        term
        for row_id in ("eq-c", "eq-d")
        for term in map_source_row(
            rows[("equipment", row_id)],
            components=(Component.EQUIPMENT,),
            snapshot_id=_SNAPSHOT_ID,
        )
    ]
    eq_source = StaticBlockSource((_block("Blendr"),), identity="equip")
    eq_discoveries = list(
        iter_raw_discoveries(equipment_terms, eq_source, _limits(), fuzzy_enabled=True)
    )
    eq_stream = iter_aggregated_block_records(
        eq_discoveries,
        eq_source,
        FakeSnapshot(rows),
        _limits(),
        expected_source_identity="equip",
    )
    eq_occurrence = list(eq_stream)[0].occurrences[0]
    assert isinstance(eq_occurrence, DictionaryOccurrence)
    eq_candidate = eq_occurrence.candidates[0]
    assert isinstance(eq_candidate.evidence, FuzzyEvidence)
    assert eq_candidate.row_id == "eq-c"
    assert eq_candidate.supporting_row_ids == ()
    assert eq_candidate.ambiguity.value == "unresolved"


def test_same_reference_method_precedence_and_exact_elsewhere() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-1"},
        ),
    }
    terms = map_source_row(
        rows[("equipment", "eq-1")],
        components=(Component.PARAMETER_NAMES,),
        snapshot_id=_SNAPSHOT_ID,
    )
    text = "Pressure and Presure"
    source = StaticBlockSource((_block(text),), identity="prec")
    discoveries = list(iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=True))
    assert any(
        item.method == "exact" and item.span.matched_text == "Pressure" for item in discoveries
    )
    assert any(
        item.method == "fuzzy" and item.span.matched_text == "Presure" for item in discoveries
    )

    # Injected same-span exact+fuzzy: exact wins for one reference.
    span = CharSpan(start_char=0, end_char=8, matched_text="Pressure")
    injected = [
        RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=CharSpan(start_char=0, end_char=7, matched_text="Presure"),
            snapshot_id=_SNAPSHOT_ID,
            edit_distance=1,
            fuzzy_allowed=True,
        ),
        RawDiscovery(
            method="exact",
            rule_id="lexical-v1-exact",
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=span,
            snapshot_id=_SNAPSHOT_ID,
        ),
        RawDiscovery(
            method="normalized_exact",
            rule_id="lexical-v1-normalized-exact",
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=span,
            snapshot_id=_SNAPSHOT_ID,
        ),
    ]
    # Use only the exact+normalized pair on the exact span for precedence.
    stream = iter_aggregated_block_records(
        injected[1:],
        StaticBlockSource((_block("Pressure"),), identity="prec2"),
        FakeSnapshot(rows),
        _limits(),
        expected_source_identity="prec2",
    )
    occurrence = list(stream)[0].occurrences[0]
    assert isinstance(occurrence, DictionaryOccurrence)
    candidate = occurrence.candidates[0]
    assert isinstance(candidate.evidence, ExactEvidence)


def test_repeated_overlapping_and_component_only_selection() -> None:
    terms = [
        _term("Filter", row_id="eq-1", fuzzy_allowed=True),
        _term("Filters", row_id="eq-2", fuzzy_allowed=True),
    ]
    text = "Filters Filters"
    discoveries = list(
        iter_raw_discoveries(
            terms,
            StaticBlockSource((_block(text),), identity="rep"),
            _limits(),
            fuzzy_enabled=True,
        )
    )
    # Exact "Filters" plus fuzzy "Filter"→"Filters" (insertion) retained; repeats kept.
    exact = [item for item in discoveries if item.method == "exact"]
    fuzzy = [item for item in discoveries if item.method == "fuzzy"]
    assert len(exact) == 2
    assert len(fuzzy) >= 2
    assert all(item.dictionary_term == "Filter" for item in fuzzy)


def test_l10_parameter_seam_fuzzy_on_leaves_unit_value_unchanged() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{
                "Operating parameter (EN)": "Pressure",
                "parameter_id": "p-1",
                "Unit": "rpm",
            },
        ),
    }
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
    blocks = [_block("Presure 120 rpm")]
    source = StaticBlockSource(tuple(blocks), identity="l10-seam")

    def _run(*, fuzzy_enabled: bool):
        stream = iter_parameter_unit_value_block_records(
            source,
            components=(
                Component.PARAMETER_NAMES,
                Component.UNITS,
                Component.QUANTITY_EXPRESSIONS,
            ),
            limits=_limits(),
            parameter_terms=parameter_terms,
            equipment_unit_terms=unit_terms,
            snapshot=FakeSnapshot(rows),
            fuzzy_enabled=fuzzy_enabled,
        )
        return list(stream)

    off_records = _run(fuzzy_enabled=False)
    on_records = _run(fuzzy_enabled=True)
    off_units = [occ for occ in off_records[0].occurrences if isinstance(occ, UnitOccurrence)]
    on_units = [occ for occ in on_records[0].occurrences if isinstance(occ, UnitOccurrence)]
    off_values = [
        occ for occ in off_records[0].occurrences if getattr(occ, "kind", None) == "value"
    ]
    on_values = [occ for occ in on_records[0].occurrences if getattr(occ, "kind", None) == "value"]
    assert len(off_units) == len(on_units) == 1
    assert off_units[0].mention.span.matched_text == on_units[0].mention.span.matched_text
    assert len(off_values) == len(on_values) == 1
    off_dict = [occ for occ in off_records[0].occurrences if isinstance(occ, DictionaryOccurrence)]
    on_dict = [occ for occ in on_records[0].occurrences if isinstance(occ, DictionaryOccurrence)]
    assert off_dict == []
    assert len(on_dict) == 1
    assert isinstance(on_dict[0].candidates[0].evidence, FuzzyEvidence)


def test_deletion_signature_index_matches_brute_force_oracle() -> None:
    vocab = [
        _term("Filter", row_id="1"),
        _term(
            "Blender",
            row_id="2",
            term_role="equipment_type",
            component=Component.EQUIPMENT,
            source_field="Equipment type (EN)",
        ),
        _term(
            "Heating",
            row_id="3",
            term_role="process_step",
            component=Component.PROCESS_STEPS,
            source_table="unit_operations",
            source_field="Process step (EN)",
        ),
        _term("Mixer", row_id="4", fuzzy_allowed=False),  # too short / disabled
        _term(
            "ABCDEF",
            row_id="5",
            fuzzy_allowed=False,
            term_role="material_name",
            component=Component.MATERIALS,
            source_table="materials_fda_ema",
            source_field="material_name",
        ),
    ]
    # Keep eligible fuzzy terms only for oracle comparison.
    eligible = [term for term in vocab if term.fuzzy_allowed and len(term.literal) >= 6]
    blocks = [
        _block("Filtr Blendr Heatin Mixer ABCDEG", node_id="n1"),
        _block("Filters", node_id="n2"),
    ]
    source = StaticBlockSource(tuple(blocks), identity="oracle")
    actual = [
        item
        for item in iter_raw_discoveries(eligible, source, _limits(), fuzzy_enabled=True)
        if item.method == "fuzzy"
    ]
    expected = _independent_fuzzy_oracle(eligible, blocks)
    assert _multiset(actual) == _multiset(expected)

    # Adversarial signature collision still requires distance verification.
    index = FuzzyCandidateIndex()
    add_fuzzy_term(index, comparison_key="abcdef", reference="a")
    add_fuzzy_term(index, comparison_key="abcxef", reference="b")
    keys = candidate_keys_for_observed(index, "abcgef")
    assert "abcdef" in keys and "abcxef" in keys
    assert ordinary_levenshtein("abcgef", "abcdef") == 1
    assert ordinary_levenshtein("abcgef", "abcxef") == 1
    assert ordinary_levenshtein("abcfed", "abcdef", limit=2) == 2  # transposition


def test_shard_multiset_invariance_and_finite_index_failure() -> None:
    terms = [
        _term("Filter", row_id="1"),
        _term(
            "Blender",
            row_id="2",
            term_role="equipment_type",
            component=Component.EQUIPMENT,
            source_field="Equipment type (EN)",
        ),
    ]
    blocks = [_block("Filtr Blendr")]
    source = StaticBlockSource(tuple(blocks), identity="shard")
    wide = _multiset(
        iter_raw_discoveries(terms, source, _limits(max_terms_per_shard=100), fuzzy_enabled=True)
    )
    narrow = _multiset(
        iter_raw_discoveries(terms, source, _limits(max_terms_per_shard=1), fuzzy_enabled=True)
    )
    assert wide == narrow

    # Limit sits above exact-only reference cost but below reference + fuzzy signatures.
    # Cost formula mirrors L07 ``_reference_codepoints`` + signature storage.
    pressure = _term("Pressure", fuzzy_allowed=True)
    comparison_key = normalize_term(pressure).comparison_text
    base_cost = (
        len(pressure.literal)
        + len(comparison_key)
        + len(pressure.source_table)
        + len(pressure.source_field)
        + len(pressure.row_id)
        + len(pressure.term_role)
        + len(pressure.boundary_hint)
        + len(pressure.component.value)
    )
    if pressure.lexical_term_id is not None:
        base_cost += len(pressure.lexical_term_id)
    if pressure.snapshot_id is not None:
        base_cost += len(pressure.snapshot_id)
    if pressure.match_policy is not None:
        base_cost += len(pressure.match_policy)
    signature_cost = fuzzy_signature_storage_codepoints(comparison_key)
    assert signature_cost > 0
    limit = base_cost + 1
    assert base_cost < limit < base_cost + signature_cost

    off = list(
        iter_raw_discoveries(
            [pressure],
            source,
            _limits(max_term_codepoints_per_shard=limit),
            fuzzy_enabled=False,
        )
    )
    assert all(item.method != "fuzzy" for item in off)

    with pytest.raises(DictionaryMatchError) as excinfo:
        list(
            iter_raw_discoveries(
                [pressure],
                source,
                _limits(max_term_codepoints_per_shard=limit),
                fuzzy_enabled=True,
            )
        )
    assert excinfo.value.code == "OVERSIZED_TERM"


def test_late_error_early_close_replay_and_no_coverage_on_failure() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-1"},
        ),
    }
    terms = map_source_row(
        rows[("equipment", "eq-1")],
        components=(Component.PARAMETER_NAMES,),
        snapshot_id=_SNAPSHOT_ID,
    )
    blocks = (_block("Presure"),)
    source = StaticBlockSource(blocks, identity="ok")
    discoveries = iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=True)
    first = next(discoveries)
    assert first.method == "fuzzy"
    discoveries.close()

    bad = _FlipIdentitySource(blocks)
    with pytest.raises(DictionaryMatchError) as match_exc:
        list(
            iter_raw_discoveries(
                [
                    *terms,
                    _term(
                        "Blender",
                        row_id="eq-2",
                        term_role="equipment_type",
                        component=Component.EQUIPMENT,
                        source_field="Equipment type (EN)",
                    ),
                ],
                bad,
                _limits(max_terms_per_shard=1),
                fuzzy_enabled=True,
            )
        )
    assert match_exc.value.code == "REPLAY_IDENTITY_CHANGED"

    # Injected ineligible fuzzy must not become evidence or completed coverage.
    injected = [
        RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term="Glucose",
            component=Component.MATERIALS,
            term_role="material_name",
            source_table="materials_fda_ema",
            source_field="material_name",
            row_id="mat-1",
            block_node_id="n1",
            span=CharSpan(start_char=0, end_char=6, matched_text="Glucos"),
            snapshot_id=_SNAPSHOT_ID,
            lexical_term_id="lt-1",
            edit_distance=1,
        )
    ]
    material_rows = {
        ("materials_fda_ema", "mat-1"): _row(
            "materials_fda_ema",
            "mat-1",
            material_name="Glucose",
            lexical_term_id="lt-1",
        ),
    }
    agg = iter_aggregated_block_records(
        injected,
        StaticBlockSource((_block("Glucos"),), identity="inj"),
        FakeSnapshot(material_rows),
        _limits(),
        expected_source_identity="inj",
    )
    with pytest.raises(DictionaryAggregationError) as agg_exc:
        list(agg)
    assert agg_exc.value.code == "FUZZY_NOT_ELIGIBLE"
    with pytest.raises(DictionaryAggregationError):
        _ = agg.coverage


def test_fake_fuzzy_distance_is_revalidated() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-1"},
        ),
    }
    injected = [
        RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=CharSpan(start_char=0, end_char=8, matched_text="Pressure"),
            snapshot_id=_SNAPSHOT_ID,
            edit_distance=1,
            fuzzy_allowed=True,
        )
    ]
    stream = iter_aggregated_block_records(
        injected,
        StaticBlockSource((_block("Pressure"),), identity="dist"),
        FakeSnapshot(rows),
        _limits(),
        expected_source_identity="dist",
    )
    with pytest.raises(DictionaryAggregationError) as excinfo:
        list(stream)
    assert excinfo.value.code == "FUZZY_DISTANCE_MISMATCH"
    with pytest.raises(DictionaryAggregationError):
        _ = stream.coverage


def test_malformed_and_boundary_invalid_fuzzy_discoveries_rejected() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Filter", "parameter_id": "p-filter"},
        ),
        ("equipment", "eq-2"): _row(
            "equipment",
            "eq-2",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-pressure"},
        ),
    }
    snapshot = FakeSnapshot(rows)

    def _inject(
        *,
        dictionary_term: str,
        matched_text: str,
        start: int,
        end: int,
        row_id: str,
        block_text: str,
        identity: str,
        edit_distance: object = 1,
    ) -> None:
        discovery = RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term=dictionary_term,
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id=row_id,
            block_node_id="n1",
            span=CharSpan(start_char=start, end_char=end, matched_text=matched_text),
            snapshot_id=_SNAPSHOT_ID,
            edit_distance=edit_distance,  # type: ignore[arg-type]
            fuzzy_allowed=True,
        )
        stream = iter_aggregated_block_records(
            [discovery],
            StaticBlockSource((_block(block_text),), identity=identity),
            snapshot,
            _limits(),
            expected_source_identity=identity,
        )
        with pytest.raises(DictionaryAggregationError) as excinfo:
            list(stream)
        assert excinfo.value.code in {
            "FUZZY_OBSERVED_NOT_WORD",
            "FUZZY_BOUNDARY_REJECTED",
            "INVALID_FUZZY_DISCOVERY",
        }
        with pytest.raises(DictionaryAggregationError):
            _ = stream.coverage

    # Distance-1 punctuation / whitespace are not one alphabetic observed word.
    _inject(
        dictionary_term="Filter",
        matched_text="Fil ter",
        start=0,
        end=7,
        row_id="eq-1",
        block_text="Fil ter",
        identity="ws",
    )
    _inject(
        dictionary_term="Filter",
        matched_text="Filter!",
        start=0,
        end=7,
        row_id="eq-1",
        block_text="Filter!",
        identity="punct",
    )
    # Forged interior span fails the default word boundary on replay.
    _inject(
        dictionary_term="Pressure",
        matched_text="Presure",
        start=1,
        end=8,
        row_id="eq-2",
        block_text="xPresure",
        identity="bound",
    )
    # Boolean True must not pass as integer edit_distance 1.
    _inject(
        dictionary_term="Pressure",
        matched_text="Presure",
        start=0,
        end=7,
        row_id="eq-2",
        block_text="Presure",
        identity="bool",
        edit_distance=True,
    )

    # Genuine one-word fuzzy hit still aggregates with FuzzyEvidence and offsets.
    genuine = RawDiscovery(
        method="fuzzy",
        rule_id=FUZZY_RULE_ID,
        dictionary_term="Pressure",
        component=Component.PARAMETER_NAMES,
        term_role="parameter_name",
        source_table="equipment",
        source_field="Operating parameter (EN)",
        row_id="eq-2",
        block_node_id="n1",
        span=CharSpan(start_char=0, end_char=7, matched_text="Presure"),
        snapshot_id=_SNAPSHOT_ID,
        edit_distance=1,
        fuzzy_allowed=True,
    )
    ok_stream = iter_aggregated_block_records(
        [genuine],
        StaticBlockSource((_block("Presure"),), identity="ok-fuzzy"),
        snapshot,
        _limits(),
        expected_source_identity="ok-fuzzy",
    )
    records = list(ok_stream)
    coverage = ok_stream.coverage
    assert coverage.dictionary_occurrences == 1
    occurrence = records[0].occurrences[0]
    assert isinstance(occurrence, DictionaryOccurrence)
    assert occurrence.location.start_char == 0
    assert occurrence.location.end_char == 7
    assert occurrence.location.matched_text == "Presure"
    assert "Presure"[occurrence.location.start_char : occurrence.location.end_char] == "Presure"
    evidence = occurrence.candidates[0].evidence
    assert isinstance(evidence, FuzzyEvidence)
    assert evidence.edit_distance == 1
    assert evidence.dictionary_term == "Pressure"

    # Ordinary matcher fuzzy output still aggregates normally.
    terms = map_source_row(
        rows[("equipment", "eq-2")],
        components=(Component.PARAMETER_NAMES,),
        snapshot_id=_SNAPSHOT_ID,
    )
    source = StaticBlockSource((_block("Presure"),), identity="matcher-agg")
    discoveries = list(iter_raw_discoveries(terms, source, _limits(), fuzzy_enabled=True))
    assert any(item.method == "fuzzy" for item in discoveries)
    matched_stream = iter_aggregated_block_records(
        discoveries,
        source,
        snapshot,
        _limits(),
        expected_source_identity="matcher-agg",
    )
    matched_records = list(matched_stream)
    matched_occ = matched_records[0].occurrences[0]
    assert isinstance(matched_occ, DictionaryOccurrence)
    assert isinstance(matched_occ.candidates[0].evidence, FuzzyEvidence)
    _ = matched_stream.coverage


def test_fuzzy_rejects_edge_whitespace_inside_claimed_span() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-1"},
        ),
    }
    snapshot = FakeSnapshot(rows)

    def _reject(*, matched_text: str, block_text: str, identity: str) -> None:
        discovery = RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=CharSpan(
                start_char=0,
                end_char=len(matched_text),
                matched_text=matched_text,
            ),
            snapshot_id=_SNAPSHOT_ID,
            edit_distance=1,
            fuzzy_allowed=True,
        )
        stream = iter_aggregated_block_records(
            [discovery],
            StaticBlockSource((_block(block_text),), identity=identity),
            snapshot,
            _limits(),
            expected_source_identity=identity,
        )
        with pytest.raises(DictionaryAggregationError) as excinfo:
            list(stream)
        assert excinfo.value.code == "FUZZY_OBSERVED_NOT_WORD"
        with pytest.raises(DictionaryAggregationError):
            _ = stream.coverage

    _reject(matched_text=" Presure", block_text=" Presure", identity="lead-ws")
    _reject(matched_text="Presure ", block_text="Presure ", identity="trail-ws")

    # Outer whitespace in the block is fine when the claimed span is the inner word.
    inner = RawDiscovery(
        method="fuzzy",
        rule_id=FUZZY_RULE_ID,
        dictionary_term="Pressure",
        component=Component.PARAMETER_NAMES,
        term_role="parameter_name",
        source_table="equipment",
        source_field="Operating parameter (EN)",
        row_id="eq-1",
        block_node_id="n1",
        span=CharSpan(start_char=1, end_char=8, matched_text="Presure"),
        snapshot_id=_SNAPSHOT_ID,
        edit_distance=1,
        fuzzy_allowed=True,
    )
    block_text = " Presure "
    assert block_text[1:8] == "Presure"
    ok_stream = iter_aggregated_block_records(
        [inner],
        StaticBlockSource((_block(block_text),), identity="inner-word"),
        snapshot,
        _limits(),
        expected_source_identity="inner-word",
    )
    records = list(ok_stream)
    _ = ok_stream.coverage
    occurrence = records[0].occurrences[0]
    assert isinstance(occurrence, DictionaryOccurrence)
    assert occurrence.location.start_char == 1
    assert occurrence.location.end_char == 8
    assert occurrence.location.matched_text == "Presure"
    assert block_text[occurrence.location.start_char : occurrence.location.end_char] == "Presure"
    evidence = occurrence.candidates[0].evidence
    assert isinstance(evidence, FuzzyEvidence)
    assert evidence.edit_distance == 1
    assert evidence.dictionary_term == "Pressure"


def test_normalized_exact_outranks_fuzzy_for_same_reference() -> None:
    rows = {
        ("equipment", "eq-1"): _row(
            "equipment",
            "eq-1",
            **{"Operating parameter (EN)": "Pressure", "parameter_id": "p-1"},
        ),
    }
    span = CharSpan(start_char=0, end_char=7, matched_text="presure")
    discoveries = [
        RawDiscovery(
            method="fuzzy",
            rule_id=FUZZY_RULE_ID,
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=span,
            snapshot_id=_SNAPSHOT_ID,
            edit_distance=1,
            fuzzy_allowed=True,
        ),
        RawDiscovery(
            method="normalized_exact",
            rule_id="lexical-v1-normalized-exact",
            dictionary_term="Pressure",
            component=Component.PARAMETER_NAMES,
            term_role="parameter_name",
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="eq-1",
            block_node_id="n1",
            span=span,
            snapshot_id=_SNAPSHOT_ID,
        ),
    ]
    stream = iter_aggregated_block_records(
        discoveries,
        StaticBlockSource((_block("presure"),), identity="rank"),
        FakeSnapshot(rows),
        _limits(),
        expected_source_identity="rank",
    )
    occurrence = list(stream)[0].occurrences[0]
    assert isinstance(occurrence, DictionaryOccurrence)
    evidence = occurrence.candidates[0].evidence
    assert isinstance(evidence, NormalizedExactEvidence)


def test_deletion_signatures_cover_distance_one_neighborhood() -> None:
    key = "filter"
    observed_variants = {
        "filterx",  # insertion
        "filtr",  # deletion
        "falter",  # substitution
    }
    key_sigs = set(deletion_signatures(key))
    for observed in observed_variants:
        assert key_sigs & set(deletion_signatures(observed))
        assert ordinary_levenshtein(observed, key) == 1
    assert ordinary_levenshtein("filtre", key, limit=2) == 2
