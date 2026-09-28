"""Bounded Aho–Corasick raw discoveries (L07) with independent tiny reference."""

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
from app.lexical_extraction.contracts import BlockEvidence, Component
from app.lexical_extraction.dictionary_matcher import (
    DictionaryMatchError,
    RawDiscovery,
    StaticBlockSource,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm


def _term(
    literal: str,
    *,
    term_role: str,
    boundary_hint: str = "default",
    component: Component = Component.MATERIALS,
    source_table: str = "materials_fda_ema",
    source_field: str = "material_name",
    row_id: str = "row-1",
    lexical_term_id: str | None = None,
    snapshot_id: str | None = None,
) -> EligibleSearchTerm:
    return EligibleSearchTerm(
        literal=literal,
        component=component,
        term_role=term_role,
        source_table=source_table,
        source_field=source_field,
        row_id=row_id,
        lexical_term_id=lexical_term_id,
        snapshot_id=snapshot_id,
        boundary_hint=boundary_hint,
    )


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


def _discovery_key(d: RawDiscovery) -> tuple[object, ...]:
    return (
        d.method,
        d.rule_id,
        d.dictionary_term,
        d.component,
        d.term_role,
        d.source_table,
        d.source_field,
        d.row_id,
        d.lexical_term_id,
        d.snapshot_id,
        d.block_node_id,
        d.span.start_char,
        d.span.end_char,
        d.span.matched_text,
        d.boundary_hint,
    )


def _multiset(discoveries: Iterable[RawDiscovery]) -> dict[tuple[object, ...], int]:
    counts: dict[tuple[object, ...], int] = {}
    for item in discoveries:
        key = _discovery_key(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _independent_reference(
    terms: Sequence[EligibleSearchTerm],
    blocks: Sequence[BlockEvidence],
) -> list[RawDiscovery]:
    """Exhaustive per-term substring search for tiny fixtures only."""

    out: list[RawDiscovery] = []
    for term in terms:
        term_surface = normalize_term(term)
        key = term_surface.comparison_text
        for block in blocks:
            if not block.text:
                continue
            block_surface = normalize_literal(
                block.text,
                term_role=term.term_role,
                boundary_hint=term.boundary_hint,
                strip_edges=False,
            )
            hay = block_surface.comparison_text
            start = 0
            while True:
                idx = hay.find(key, start)
                if idx < 0:
                    break
                end = idx + len(key)
                try:
                    span = project_against_block(
                        block,
                        block_surface,
                        idx,
                        end,
                        boundary_hint=term.boundary_hint,
                    )
                except ComparisonError as exc:
                    if exc.code in {"BOUNDARY_REJECTED", "PARTIAL_NORMALIZATION_UNIT"}:
                        start = idx + 1
                        continue
                    raise
                method = "exact" if span.matched_text == term.literal else "normalized_exact"
                rule_id = "lexical-v1-exact" if method == "exact" else "lexical-v1-normalized-exact"
                out.append(
                    RawDiscovery(
                        method=method,
                        rule_id=rule_id,
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
                    )
                )
                start = idx + 1
    return out


# --- exact / normalized-exact / isolation ---


def test_exact_versus_normalized_exact_and_unicode_whitespace() -> None:
    terms = [
        _term("Glucose", term_role="material_name", row_id="m1"),
        _term(
            "ÁCID",
            term_role="parameter_name",
            component=Component.PARAMETER_NAMES,
            source_table="equipment",
            source_field="Operating parameter (EN)",
            row_id="p1",
        ),
        _term(
            "Mixing Vessel",
            term_role="equipment_type",
            component=Component.EQUIPMENT,
            source_table="equipment",
            source_field="Equipment type (EN)",
            row_id="e1",
        ),
    ]
    blocks = [
        _block("add Glucose slowly", node_id="b-exact"),
        _block("buffer a\u0301cid zone", node_id="b-accent"),
        _block("Start mixing\n\tvessel end", node_id="b-ws"),
        _block("", node_id="b-empty"),
        _block("Glucose again", node_id="b-page2", page_number=2, order=0),
    ]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:exact-norm")
    got = list(iter_raw_discoveries(terms, source, _limits()))
    expected = _independent_reference(terms, blocks)
    assert _multiset(got) == _multiset(expected)

    by_node = {d.block_node_id: d for d in got if d.dictionary_term == "Glucose"}
    assert by_node["b-exact"].method == "exact"
    assert by_node["b-exact"].span.matched_text == "Glucose"
    assert by_node["b-page2"].method == "exact"

    accent = next(d for d in got if d.dictionary_term == "ÁCID")
    assert accent.method == "normalized_exact"
    assert accent.span.matched_text == "a\u0301cid"
    assert accent.rule_id == "lexical-v1-normalized-exact"

    vessel = next(d for d in got if d.dictionary_term == "Mixing Vessel")
    assert vessel.method == "normalized_exact"
    assert vessel.span.matched_text == "mixing\n\tvessel"
    assert not any(d.block_node_id == "b-empty" for d in got)


def test_repeated_hits_overlaps_and_shared_normalized_keys() -> None:
    lactose_fda = _term(
        "lactose",
        term_role="material_name",
        source_table="materials_fda_ema",
        source_field="material_name",
        row_id="fda-1",
        snapshot_id="snap-1",
    )
    lactose_ema_alias = _term(
        "Lactose",
        term_role="material_alias",
        source_table="materials_fda_ema",
        source_field="alias_name",
        row_id="fda-2",
        snapshot_id="snap-1",
    )
    lactose_chebi = _term(
        "lactose",
        term_role="material_name",
        source_table="materials_chebi",
        source_field="material_name",
        row_id="chebi-1",
        snapshot_id="snap-1",
    )
    granulation = _term(
        "granulation",
        term_role="unit_operation",
        component=Component.UNIT_OPERATIONS,
        source_table="unit_operations",
        source_field="Search term (EN)",
        row_id="uo-1",
        lexical_term_id="lt-gran",
    )
    wet_granulation = _term(
        "wet granulation",
        term_role="unit_operation",
        component=Component.UNIT_OPERATIONS,
        source_table="unit_operations",
        source_field="Search term (EN)",
        row_id="uo-2",
        lexical_term_id="lt-wet",
    )
    # Same source row, distinct permitted fields.
    same_row_name = _term(
        "mixing",
        term_role="equipment_type",
        component=Component.EQUIPMENT,
        source_table="equipment",
        source_field="Equipment type (EN)",
        row_id="eq-9",
    )
    same_row_param = _term(
        "mixing",
        term_role="parameter_name",
        component=Component.PARAMETER_NAMES,
        source_table="equipment",
        source_field="Operating parameter (EN)",
        row_id="eq-9",
    )
    terms = [
        lactose_fda,
        lactose_ema_alias,
        lactose_chebi,
        granulation,
        wet_granulation,
        same_row_name,
        same_row_param,
    ]
    blocks = [
        _block("lactose lactose", node_id="b-lac"),
        _block("wet granulation step", node_id="b-gran"),
        _block("mixing vessel", node_id="b-mix"),
    ]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:overlap")
    got = list(iter_raw_discoveries(terms, source, _limits()))
    expected = _independent_reference(terms, blocks)
    assert _multiset(got) == _multiset(expected)

    lac_hits = [d for d in got if d.block_node_id == "b-lac"]
    assert len(lac_hits) == 6  # 2 occurrences × 3 catalogue identities
    row_ids = {d.row_id for d in lac_hits}
    assert row_ids == {"fda-1", "fda-2", "chebi-1"}

    gran_hits = [d for d in got if d.block_node_id == "b-gran"]
    assert {d.dictionary_term for d in gran_hits} == {"granulation", "wet granulation"}

    mix_hits = [d for d in got if d.block_node_id == "b-mix"]
    assert {(d.source_field, d.term_role) for d in mix_hits} == {
        ("Equipment type (EN)", "equipment_type"),
        ("Operating parameter (EN)", "parameter_name"),
    }


def test_whole_code_units_and_hyphen_boundaries() -> None:
    unii = _term(
        "AB12C",
        term_role="unii",
        boundary_hint="whole_code",
        source_field="UNII",
        row_id="u1",
    )
    rpm = _term(
        "rpm",
        term_role="unit",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
        source_table="equipment",
        source_field="Unit",
        row_id="unit-1",
    )
    min_inv = _term(
        "min⁻¹",
        term_role="unit",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
        source_table="equipment",
        source_field="Unit",
        row_id="unit-2",
    )
    ml_min = _term(
        "mL/min",
        term_role="unit",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
        source_table="equipment",
        source_field="Unit",
        row_id="unit-3",
    )
    glucose = _term("glucose", term_role="material_name", row_id="g1")
    water = _term("water", term_role="material_name", row_id="w1")
    terms = [unii, rpm, min_inv, ml_min, glucose, water]
    blocks = [
        _block("code AB12C ok", node_id="b-unii-ok"),
        _block("code AB12C-EXTRA", node_id="b-unii-reject"),
        _block("speed 120rpm then", node_id="b-rpm"),
        _block("rate min⁻¹ and mL/min flow", node_id="b-units"),
        _block("inside rpm/min compound", node_id="b-rpm-compound"),
        _block("glucose-6-phosphate and water-soluble", node_id="b-hyphen"),
        _block("glucose water", node_id="b-plain"),
    ]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:boundaries")
    got = list(iter_raw_discoveries(terms, source, _limits()))
    expected = _independent_reference(terms, blocks)
    assert _multiset(got) == _multiset(expected)

    assert any(d.block_node_id == "b-unii-ok" and d.dictionary_term == "AB12C" for d in got)
    assert not any(d.block_node_id == "b-unii-reject" for d in got)
    assert any(d.block_node_id == "b-rpm" and d.span.matched_text == "rpm" for d in got)
    assert any(d.dictionary_term == "min⁻¹" for d in got)
    assert any(d.dictionary_term == "mL/min" for d in got)
    assert not any(d.block_node_id == "b-rpm-compound" and d.dictionary_term == "rpm" for d in got)
    assert not any(d.block_node_id == "b-hyphen" for d in got)
    assert {d.dictionary_term for d in got if d.block_node_id == "b-plain"} == {
        "glucose",
        "water",
    }


def test_shard_limits_split_same_key_but_preserve_multiset() -> None:
    shared_key_terms = [
        _term(
            "lactose",
            term_role="material_name",
            row_id=f"r{i}",
            source_table="materials_fda_ema",
        )
        for i in range(4)
    ]
    terms = shared_key_terms
    blocks = [_block("lactose present", node_id="b1")]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:shards")

    large = list(iter_raw_discoveries(terms, source, _limits(max_terms_per_shard=100)))
    tiny = list(iter_raw_discoveries(terms, source, _limits(max_terms_per_shard=1)))
    # One lactose reference is ~75 code points; 100 forces a new shard per term.
    by_codepoints = list(
        iter_raw_discoveries(
            terms,
            source,
            _limits(max_terms_per_shard=100, max_term_codepoints_per_shard=100),
        )
    )
    reference = _independent_reference(terms, blocks)

    assert _multiset(large) == _multiset(reference)
    assert _multiset(tiny) == _multiset(reference)
    assert _multiset(by_codepoints) == _multiset(reference)
    assert len(tiny) == 4


@dataclass
class _FlipIdentitySource:
    """Changes identity starting at the second complete block pass."""

    blocks: tuple[BlockEvidence, ...]
    _identity: str = "id-1"
    _passes: int = 0

    @property
    def source_identity(self) -> str:
        return self._identity

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        self._passes += 1
        if self._passes > 1:
            self._identity = "id-changed"
        yield from self.blocks


def test_oversized_term_block_replay_identity_and_cleanup() -> None:
    huge = _term("x" * 50, term_role="material_name", row_id="huge")
    source = StaticBlockSource((_block("x" * 50),), identity="synthetic:oversize")
    with pytest.raises(DictionaryMatchError) as exc:
        list(
            iter_raw_discoveries(
                [huge],
                source,
                _limits(max_term_codepoints_per_shard=20),
            )
        )
    assert exc.value.code == "OVERSIZED_TERM"

    terms = [
        _term("alpha", term_role="material_name", row_id="a"),
        _term("beta", term_role="material_name", row_id="b"),
    ]
    blocks = [_block("alpha and beta", node_id="n")]
    flipping = _FlipIdentitySource(tuple(blocks))
    with pytest.raises(DictionaryMatchError) as changed:
        list(iter_raw_discoveries(terms, flipping, _limits(max_terms_per_shard=1)))
    assert changed.value.code == "REPLAY_IDENTITY_CHANGED"

    # Early stop must not raise during cleanup.
    steady = StaticBlockSource(tuple(blocks), identity="synthetic:early")
    stream = iter_raw_discoveries(terms, steady, _limits(max_terms_per_shard=1))
    assert next(stream).dictionary_term in {"alpha", "beta"}
    stream.close()


def test_matcher_does_not_retain_all_vocabulary_or_blocks() -> None:
    produced: list[str] = []

    def term_stream() -> Iterator[EligibleSearchTerm]:
        for i in range(3):
            produced.append(f"t{i}")
            yield _term(f"term{i}", term_role="material_name", row_id=f"r{i}")

    blocks = [_block("term0 term1 term2", node_id="n")]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:stream")
    got = list(iter_raw_discoveries(term_stream(), source, _limits(max_terms_per_shard=1)))
    assert len(got) == 3
    assert produced == ["t0", "t1", "t2"]
    # An already-exhausted term iterator yields nothing — no retained vocabulary.
    exhausted = term_stream()
    list(exhausted)
    assert list(iter_raw_discoveries(exhausted, source, _limits())) == []


def test_spelling_retention_across_normalized_collision() -> None:
    terms = [
        _term("NaCl", term_role="material_name", row_id="s1"),
        _term("nacl", term_role="material_name", row_id="s2"),
        _term("NACL", term_role="material_name", row_id="s3"),
    ]
    blocks = [_block("dissolve nacl carefully", node_id="b1")]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:spell")
    got = list(iter_raw_discoveries(terms, source, _limits()))
    spellings = {d.dictionary_term for d in got}
    assert spellings == {"NaCl", "nacl", "NACL"}
    exact = [d for d in got if d.method == "exact"]
    assert len(exact) == 1
    assert exact[0].dictionary_term == "nacl"
    assert all(d.method == "normalized_exact" for d in got if d.dictionary_term != "nacl")


def test_sharp_s_partial_unit_skipped_while_ss_projects() -> None:
    """``s`` inside ``ß``→``ss`` is a non-hit; whole ``ss`` remains normalized-exact."""

    short = _term("s", term_role="material_alias", source_field="alias_name", row_id="alias-s")
    whole = _term("ss", term_role="material_alias", source_field="alias_name", row_id="alias-ss")
    terms = [short, whole]
    blocks = [_block("ß", node_id="b-eszett")]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:eszett")

    got = list(iter_raw_discoveries(terms, source, _limits()))
    tiny = list(iter_raw_discoveries(terms, source, _limits(max_terms_per_shard=1)))
    expected = _independent_reference(terms, blocks)

    assert _multiset(got) == _multiset(expected)
    assert _multiset(tiny) == _multiset(expected)
    assert len(got) == 1
    hit = got[0]
    assert hit.dictionary_term == "ss"
    assert hit.method == "normalized_exact"
    assert hit.span.start_char == 0
    assert hit.span.end_char == 1
    assert hit.span.matched_text == "ß"
    assert not any(d.dictionary_term == "s" for d in got)


def test_projection_coherence_failure_is_projection_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lexical_extraction import dictionary_matcher as matcher
    from app.lexical_extraction.comparison import ComparisonError

    released: list[int] = []
    original_release = matcher._release_automata  # pyright: ignore[reportPrivateUsage]

    def tracking_release(automata: object) -> None:
        released.append(1)
        original_release(automata)  # type: ignore[arg-type]

    def boom_project(*_args: object, **_kwargs: object) -> object:
        raise ComparisonError(
            "OFFSET_MISMATCH",
            "projected original slice does not equal matched_text",
        )

    monkeypatch.setattr(matcher, "project_against_block", boom_project)
    monkeypatch.setattr(matcher, "_release_automata", tracking_release)

    terms = [_term("glucose", term_role="material_name", row_id="g1")]
    source = StaticBlockSource((_block("glucose"),), identity="synthetic:proj-fail")
    with pytest.raises(DictionaryMatchError) as exc:
        list(iter_raw_discoveries(terms, source, _limits()))
    assert exc.value.code == "PROJECTION_FAILED"
    assert released  # shard state released on failure


def test_ac_iterator_failure_during_consumption_is_match_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lexical_extraction import dictionary_matcher as matcher

    released: list[int] = []
    original_release = matcher._release_automata  # pyright: ignore[reportPrivateUsage]

    def tracking_release(automata: object) -> None:
        released.append(1)
        original_release(automata)  # type: ignore[arg-type]

    def boom_iter(_automaton: object, _text: str) -> Iterator[tuple[int, str]]:
        # Iterator object is created; failure happens while consuming it.
        if False:  # pragma: no cover
            yield (0, "")
        raise RuntimeError("ac iterator boom")

    monkeypatch.setattr(matcher, "automaton_iter", boom_iter)
    monkeypatch.setattr(matcher, "_release_automata", tracking_release)

    terms = [_term("glucose", term_role="material_name", row_id="g1")]
    source = StaticBlockSource((_block("glucose"),), identity="synthetic:ac-fail")
    with pytest.raises(DictionaryMatchError) as exc:
        list(iter_raw_discoveries(terms, source, _limits()))
    assert exc.value.code == "MATCH_FAILED"
    assert "RuntimeError" in exc.value.message
    assert released


def test_ordinary_boundary_rejection_remains_skipped_hit() -> None:
    terms = [_term("glucose", term_role="material_name", row_id="g1")]
    blocks = [_block("glucose-6-phosphate", node_id="b-hyphen")]
    source = StaticBlockSource(tuple(blocks), identity="synthetic:boundary-skip")
    got = list(iter_raw_discoveries(terms, source, _limits()))
    assert got == []
    assert _independent_reference(terms, blocks) == []
