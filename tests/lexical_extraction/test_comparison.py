"""Fixed V1 comparison normalization, offset projection, and boundary helpers."""

from __future__ import annotations

import unicodedata

import pytest

from app.lexical_extraction.comparison import (
    ComparisonError,
    comparison_profile,
    normalize_block,
    normalize_literal,
    normalize_term,
    project_against_block,
    project_comparison_range,
    respects_boundary,
)
from app.lexical_extraction.contracts import BlockEvidence, Component
from app.lexical_extraction.field_mapping import EligibleSearchTerm


def _term(
    literal: str,
    *,
    term_role: str,
    boundary_hint: str = "default",
    component: Component = Component.EQUIPMENT,
) -> EligibleSearchTerm:
    return EligibleSearchTerm(
        literal=literal,
        component=component,
        term_role=term_role,
        source_table="equipment",
        source_field="Equipment type (EN)",
        row_id="row-1",
        boundary_hint=boundary_hint,
    )


def _block(text: str, *, node_id: str = "n1") -> BlockEvidence:
    return BlockEvidence(
        node_id=node_id,
        kind="paragraph",
        text=text,
        page_number=1,
        order=0,
        element_id="e1",
    )


def _find_comparison_range(surface_text: str, needle: str) -> tuple[int, int]:
    start = surface_text.find(needle)
    assert start >= 0, f"{needle!r} not found in {surface_text!r}"
    return start, start + len(needle)


# --- 1. Case / Unicode composition / whitespace / projection ---


def test_natural_casefold_and_whitespace_run_comparison() -> None:
    term = _term("Mixing  Vessel", term_role="equipment_type")
    block = _block("Start mixing\n\tvessel end")
    term_surface = normalize_term(term)
    block_surface = normalize_block(block, term)

    assert term_surface.comparison_text == "mixing vessel"
    assert "mixing vessel" in block_surface.comparison_text
    assert block.text == "Start mixing\n\tvessel end"

    c_start, c_end = _find_comparison_range(block_surface.comparison_text, "mixing vessel")
    span = project_against_block(block, block_surface, c_start, c_end)
    assert span.matched_text == "mixing\n\tvessel"
    assert block.text[span.start_char : span.end_char] == span.matched_text


def test_combining_mark_projects_to_complete_original_unit() -> None:
    # Source uses decomposed a + combining acute; comparison composes then casefolds.
    original = "buffer a\u0301cid zone"
    term = _term("ÁCID", term_role="parameter_name")
    block = _block(original)
    term_surface = normalize_term(term)
    block_surface = normalize_block(block, term)

    assert term_surface.comparison_text == "ácid"
    c_start, c_end = _find_comparison_range(block_surface.comparison_text, "ácid")
    span = project_comparison_range(block_surface, c_start, c_end)
    assert span.matched_text == "a\u0301cid"
    assert original[span.start_char : span.end_char] == "a\u0301cid"


def test_casefold_expansion_rejects_partial_and_projects_full_unit() -> None:
    original = "pre ß post"
    term = _term("SS", term_role="equipment_type")
    block = _block(original)
    block_surface = normalize_block(block, term)
    term_surface = normalize_term(term)

    assert term_surface.comparison_text == "ss"
    c_start, c_end = _find_comparison_range(block_surface.comparison_text, "ss")
    span = project_comparison_range(block_surface, c_start, c_end)
    assert span.matched_text == "ß"
    assert span.end_char - span.start_char == 1

    with pytest.raises(ComparisonError) as partial:
        project_comparison_range(block_surface, c_start, c_start + 1)
    assert partial.value.code == "PARTIAL_NORMALIZATION_UNIT"

    with pytest.raises(ComparisonError) as off_by_one:
        project_comparison_range(block_surface, c_start + 1, c_end)
    assert off_by_one.value.code == "PARTIAL_NORMALIZATION_UNIT"


def test_supplementary_unicode_and_crlf_whitespace() -> None:
    # Supplementary plane character (emoji) plus CRLF whitespace run.
    giraffe = "\U0001f993"
    original = f"hold{giraffe} temp\r\ncontrol"
    term = _term("TEMP CONTROL", term_role="process_step")
    block = _block(original)
    term_surface = normalize_term(term)
    block_surface = normalize_block(block, term)

    assert term_surface.comparison_text == "temp control"
    c_start, c_end = _find_comparison_range(block_surface.comparison_text, "temp control")
    span = project_comparison_range(block_surface, c_start, c_end)
    assert span.matched_text == "temp\r\ncontrol"
    assert giraffe in block.text
    assert block.text == original


def test_material_preserves_chemical_punctuation_and_casefolds() -> None:
    literal = "α-D-Glucose"
    term = _term(
        literal,
        term_role="material_name",
        component=Component.MATERIALS,
    )
    surface = normalize_term(term)
    profile = comparison_profile(term_role="material_name", boundary_hint="default")

    assert profile["collapse_whitespace"] is False
    assert profile["strip_accents"] is False
    assert "-" in surface.comparison_text
    assert surface.comparison_text == unicodedata.normalize("NFC", literal).casefold()
    # Source alias qualification / stereochemical marks are not stripped.
    assert "α" in surface.comparison_text or "α".casefold() in surface.comparison_text


def test_unii_no_punctuation_stripping() -> None:
    term = _term(
        "059QF0KO0R",
        term_role="unii_code",
        boundary_hint="whole_code",
        component=Component.MATERIALS,
    )
    surface = normalize_term(term)
    assert surface.comparison_text == "059qf0ko0r"
    assert surface.collapse_whitespace is False
    assert (
        comparison_profile(term_role="unii_code", boundary_hint="whole_code")["collapse_whitespace"]
        is False
    )


def test_atomic_unit_preserves_slash_and_superscript() -> None:
    term = _term(
        "min⁻¹",
        term_role="unit_spelling",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
    )
    surface = normalize_term(term)
    assert "⁻" in surface.comparison_text or "¹" in surface.comparison_text
    assert surface.comparison_text == "min⁻¹".casefold()

    slash = normalize_term(
        _term(
            "mL/min",
            term_role="unit_spelling",
            boundary_hint="atomic_unit",
            component=Component.UNITS,
        )
    )
    assert "/" in slash.comparison_text
    assert slash.comparison_text == "ml/min"


# --- 2. Term-role boundaries ---


def test_default_boundary_rejects_embedded_natural_word() -> None:
    original = "premixer vessel"
    assert respects_boundary(original, 3, 9, boundary_hint="default") is False  # "mixer"
    assert original[9:15] == "vessel"
    assert respects_boundary(original, 9, 15, boundary_hint="default") is True


def test_default_boundary_allows_valid_phrase_overlap_prefix() -> None:
    # Boundary helper must not suppress a valid shorter phrase at a word edge.
    original = "cell culture expansion"
    assert respects_boundary(original, 0, 12, boundary_hint="default") is True  # "cell culture"
    assert respects_boundary(original, 0, 22, boundary_hint="default") is True


def test_whole_code_rejects_embedded_unii_forms() -> None:
    code = "059QF0KO0R"
    assert respects_boundary(code, 0, len(code), boundary_hint="whole_code") is True
    assert respects_boundary(f"X{code}", 1, 1 + len(code), boundary_hint="whole_code") is False
    assert respects_boundary(f"{code}-EXTRA", 0, len(code), boundary_hint="whole_code") is False
    assert respects_boundary(f"{code}_1", 0, len(code), boundary_hint="whole_code") is False
    assert respects_boundary(f"({code})", 1, 1 + len(code), boundary_hint="whole_code") is True


def test_material_punctuation_bearing_name_projects_literally() -> None:
    original = "Use (±)-epinephrine now"
    term = _term(
        "(±)-epinephrine",
        term_role="material_alias",
        component=Component.MATERIALS,
    )
    block = _block(original)
    block_surface = normalize_block(block, term)
    needle = normalize_term(term).comparison_text
    c_start, c_end = _find_comparison_range(block_surface.comparison_text, needle)
    span = project_against_block(block, block_surface, c_start, c_end)
    assert span.matched_text == "(±)-epinephrine"
    assert original[span.start_char : span.end_char] == "(±)-epinephrine"
    # Comparison key is casefolded NFC; original matched text stays source spelling.
    assert needle == unicodedata.normalize("NFC", "(±)-epinephrine").casefold()


def test_atomic_unit_rpm_versus_slash_compound_and_number_adjacent() -> None:
    assert respects_boundary("120rpm", 3, 6, boundary_hint="atomic_unit") is True
    assert respects_boundary("37°C", 2, 4, boundary_hint="atomic_unit") is True
    assert respects_boundary("rpm/min", 0, 3, boundary_hint="atomic_unit") is False
    assert respects_boundary("rpms", 0, 3, boundary_hint="atomic_unit") is False
    assert respects_boundary("xrpm", 1, 4, boundary_hint="atomic_unit") is False
    assert respects_boundary(" rpm ", 1, 4, boundary_hint="atomic_unit") is True


def test_unit_projection_preserves_original_matched_text() -> None:
    original = "Set 120rpm and 37°C."
    term = _term(
        "RPM",
        term_role="unit_spelling",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
    )
    block = _block(original)
    block_surface = normalize_block(block, term)
    c_start, c_end = _find_comparison_range(block_surface.comparison_text, "rpm")
    span = project_against_block(block, block_surface, c_start, c_end)
    assert span.matched_text == "rpm"

    celsius = _term(
        "°C",
        term_role="unit_spelling",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
    )
    block_surface_c = normalize_block(block, celsius)
    c_start, c_end = _find_comparison_range(block_surface_c.comparison_text, "°c")
    span_c = project_against_block(block, block_surface_c, c_start, c_end)
    assert span_c.matched_text == "°C"


# --- 3. Explicit errors and purity ---


def test_empty_and_whitespace_only_terms_fail_explicitly() -> None:
    with pytest.raises(ComparisonError) as blank:
        normalize_term(_term("   ", term_role="equipment_type"))
    assert blank.value.code == "EMPTY_COMPARISON_KEY"

    with pytest.raises(ComparisonError) as empty:
        normalize_literal(
            "",
            term_role="equipment_type",
            boundary_hint="default",
            strip_edges=True,
        )
    assert empty.value.code == "EMPTY_COMPARISON_KEY"

    err = blank.value.to_structured_error()
    assert err.code == "EMPTY_COMPARISON_KEY"
    assert 1 <= len(err.message) <= 200


def test_malformed_prospective_ranges_fail_explicitly() -> None:
    term = _term("vessel", term_role="equipment_type")
    block = _block("vessel")
    surface = normalize_block(block, term)

    with pytest.raises(ComparisonError) as inverted:
        project_comparison_range(surface, 3, 1)
    assert inverted.value.code == "INVALID_COMPARISON_RANGE"

    with pytest.raises(ComparisonError) as outside:
        project_comparison_range(surface, 0, len(surface.comparison_text) + 1)
    assert outside.value.code == "INVALID_COMPARISON_RANGE"

    with pytest.raises(ComparisonError) as rejected:
        project_comparison_range(
            normalize_block(_block("premixer"), term),
            *_find_comparison_range(
                normalize_block(_block("premixer"), term).comparison_text,
                "mixer",
            ),
        )
    assert rejected.value.code == "BOUNDARY_REJECTED"


def test_helpers_are_pure_and_do_not_mutate_sources() -> None:
    term = _term("Vessel", term_role="equipment_type")
    block = _block("Vessel")
    literal_before = term.literal
    text_before = block.text

    surfaces = [normalize_term(term) for _ in range(3)]
    blocks = [normalize_block(block, term) for _ in range(3)]

    assert term.literal == literal_before
    assert block.text == text_before
    assert {s.comparison_text for s in surfaces} == {"vessel"}
    assert {s.comparison_text for s in blocks} == {"vessel"}
    # No document/dictionary accumulation: each call returns a fresh surface.
    assert all(s.original == "Vessel" for s in blocks)


def test_unsupported_boundary_hint_fails() -> None:
    with pytest.raises(ComparisonError) as exc:
        normalize_literal(
            "x",
            term_role="equipment_type",
            boundary_hint="weird",
            strip_edges=True,
        )
    assert exc.value.code == "UNSUPPORTED_BOUNDARY_HINT"


# --- 4. Boundary correction: compound units and hyphen-connected materials ---


def _unit_term(literal: str) -> EligibleSearchTerm:
    return _term(
        literal,
        term_role="unit_spelling",
        boundary_hint="atomic_unit",
        component=Component.UNITS,
    )


def _material_term(literal: str) -> EligibleSearchTerm:
    return _term(
        literal,
        term_role="material_name",
        boundary_hint="default",
        component=Component.MATERIALS,
    )


def _project_term_in_block(literal_term: EligibleSearchTerm, block_text: str):
    block = _block(block_text)
    surface = normalize_block(block, literal_term)
    needle = normalize_term(literal_term).comparison_text
    c_start, c_end = _find_comparison_range(surface.comparison_text, needle)
    return project_against_block(block, surface, c_start, c_end)


def test_atomic_unit_rejects_shorter_unit_inside_reciprocal_and_compounds() -> None:
    with pytest.raises(ComparisonError) as min_in_reciprocal:
        _project_term_in_block(_unit_term("min"), "min⁻¹")
    assert min_in_reciprocal.value.code == "BOUNDARY_REJECTED"

    with pytest.raises(ComparisonError) as ml_in_dot_compound:
        _project_term_in_block(_unit_term("mL"), "mL·min⁻¹")
    assert ml_in_dot_compound.value.code == "BOUNDARY_REJECTED"

    with pytest.raises(ComparisonError) as kg_in_squared:
        _project_term_in_block(_unit_term("kg"), "kg²")
    assert kg_in_squared.value.code == "BOUNDARY_REJECTED"

    with pytest.raises(ComparisonError) as rpm_in_slash:
        _project_term_in_block(_unit_term("rpm"), "rpm/min")
    assert rpm_in_slash.value.code == "BOUNDARY_REJECTED"


def test_atomic_unit_accepts_complete_compound_and_number_adjacent() -> None:
    span_reciprocal = _project_term_in_block(_unit_term("min⁻¹"), "min⁻¹")
    assert span_reciprocal.matched_text == "min⁻¹"
    assert span_reciprocal.start_char == 0
    assert span_reciprocal.end_char == len("min⁻¹")

    span_slash = _project_term_in_block(_unit_term("mL/min"), "flow  mL/min ok")
    assert span_slash.matched_text == "mL/min"
    block = _block("flow  mL/min ok")
    assert block.text[span_slash.start_char : span_slash.end_char] == "mL/min"

    span_rpm = _project_term_in_block(_unit_term("rpm"), "Set 120rpm now")
    assert span_rpm.matched_text == "rpm"
    assert _block("Set 120rpm now").text[span_rpm.start_char : span_rpm.end_char] == "rpm"

    span_c = _project_term_in_block(_unit_term("°C"), "Hold 37°C steady")
    assert span_c.matched_text == "°C"
    assert _block("Hold 37°C steady").text[span_c.start_char : span_c.end_char] == "°C"


def test_default_rejects_material_inside_hyphen_connected_expression() -> None:
    with pytest.raises(ComparisonError) as glucose:
        _project_term_in_block(_material_term("glucose"), "glucose-6-phosphate")
    assert glucose.value.code == "BOUNDARY_REJECTED"

    with pytest.raises(ComparisonError) as water:
        _project_term_in_block(_material_term("water"), "water-soluble")
    assert water.value.code == "BOUNDARY_REJECTED"


def test_default_accepts_full_hyphenated_chemical_and_space_phrase_overlap() -> None:
    full = "glucose-6-phosphate"
    span_full = _project_term_in_block(_material_term(full), f"add {full} now")
    assert span_full.matched_text == full
    assert _block(f"add {full} now").text[span_full.start_char : span_full.end_char] == full

    # Valid overlaps across real word separators (space), not hyphen continuation.
    block_text = "wet granulation step"
    granulation = _term("granulation", term_role="unit_operation")
    wet_granulation = _term("wet granulation", term_role="unit_operation")

    span_short = _project_term_in_block(granulation, block_text)
    assert span_short.matched_text == "granulation"
    assert block_text[span_short.start_char : span_short.end_char] == "granulation"

    span_phrase = _project_term_in_block(wet_granulation, block_text)
    assert span_phrase.matched_text == "wet granulation"
    assert block_text[span_phrase.start_char : span_phrase.end_char] == "wet granulation"


def test_composition_scope_is_starter_plus_combining_marks_not_whole_string() -> None:
    profile = comparison_profile(term_role="equipment_type", boundary_hint="default")
    assert profile["unicode_form"] == "NFC"
    assert profile["composition_scope"] == "starter_plus_combining_marks"
    # Adjacent Hangul Jamo remain uncomposed under V1 unit walking.
    jamo = "\u1100\u1161"  # 가
    surface = normalize_literal(
        jamo,
        term_role="equipment_type",
        boundary_hint="default",
        strip_edges=True,
    )
    assert surface.comparison_text == jamo.casefold()
    assert surface.comparison_text != unicodedata.normalize("NFC", jamo).casefold()
