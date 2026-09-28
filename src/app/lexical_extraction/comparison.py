"""Fixed V1 comparison normalization, source-offset projection, and boundaries.

Pure helpers for one L05 term or one L03 block. Comparison text is temporary
search material only; original ``EligibleSearchTerm.literal`` and
``BlockEvidence.text`` stay unchanged. This module does not scan documents,
run Aho–Corasick, aggregate candidates, or parse values.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.lexical_extraction.contracts import (
    BlockEvidence,
    CharSpan,
    SafeStructuredError,
    validate_match_against_block,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm

_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200

BoundaryHint = Literal["default", "whole_code", "atomic_unit"]

_NATURAL_ROLES: Final[frozenset[str]] = frozenset(
    {
        "equipment_type",
        "parameter_name",
        "unit_operation",
        "generic_cue",
        "process_step",
    }
)
_MATERIAL_ROLES: Final[frozenset[str]] = frozenset({"material_name", "material_alias"})
_KNOWN_BOUNDARY_HINTS: Final[frozenset[str]] = frozenset({"default", "whole_code", "atomic_unit"})


class ComparisonError(Exception):
    """Bounded comparison/normalization failure.

    ``code`` and ``message`` map to :class:`SafeStructuredError`. Empty keys and
    misaligned prospective ranges fail here instead of disappearing.
    """

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("comparison error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class ComparisonUnit:
    """One source normalization unit and its comparison contribution.

    ``original_start`` / ``original_end`` are half-open Python Unicode code-point
    offsets into the unchanged source string. ``comparison_start`` /
    ``comparison_end`` are half-open offsets into ``comparison_text``. A case-fold
    expansion (for example ``ß`` → ``ss``) keeps one original unit and a longer
    comparison span.
    """

    original_start: int
    original_end: int
    comparison_start: int
    comparison_end: int


@dataclass(frozen=True)
class ComparisonSurface:
    """Immutable comparison text plus provenance for one original string.

    L07 may search ``comparison_text`` and project hits back through ``units``
    without re-normalizing a full document. ``original`` is retained by reference
    equality of content only; callers must not mutate source objects.
    """

    original: str
    comparison_text: str
    units: tuple[ComparisonUnit, ...]
    collapse_whitespace: bool
    boundary_hint: BoundaryHint


def normalize_term(term: EligibleSearchTerm) -> ComparisonSurface:
    """Normalize one eligible search term into a temporary comparison key.

    Uses the term's ``term_role`` and ``boundary_hint``. Does not mutate ``term``.
    Empty or whitespace-only comparison keys raise :class:`ComparisonError`.
    """

    return normalize_literal(
        term.literal,
        term_role=term.term_role,
        boundary_hint=term.boundary_hint,
        strip_edges=True,
    )


def normalize_block(block: BlockEvidence, term: EligibleSearchTerm) -> ComparisonSurface:
    """Normalize one block with the same fixed rules as ``term``.

    Retains a complete comparison→original unit map for later projection.
    Does not mutate ``block`` or ``term``. Block text may be empty; an empty
    comparison surface is allowed for blocks (matching yields nothing later).
    """

    return normalize_literal(
        block.text,
        term_role=term.term_role,
        boundary_hint=term.boundary_hint,
        strip_edges=False,
    )


def normalize_literal(
    text: str,
    *,
    term_role: str,
    boundary_hint: str,
    strip_edges: bool,
) -> ComparisonSurface:
    """Build a :class:`ComparisonSurface` for ``text`` under fixed V1 rules."""

    hint = _resolve_boundary_hint(boundary_hint)
    collapse = _collapse_whitespace_for(term_role=term_role, boundary_hint=hint)
    surface = _build_surface(
        text,
        collapse_whitespace=collapse,
        boundary_hint=hint,
    )
    if strip_edges:
        surface = _strip_comparison_edges(surface)
        if _is_blank_comparison(surface.comparison_text):
            raise ComparisonError(
                "EMPTY_COMPARISON_KEY",
                "comparison key is empty or whitespace-only after fixed V1 normalization",
            )
    return surface


def project_comparison_range(
    surface: ComparisonSurface,
    comparison_start: int,
    comparison_end: int,
    *,
    boundary_hint: str | None = None,
) -> CharSpan:
    """Project a half-open comparison range to an original ``CharSpan``.

    The range must cover complete normalization units. The returned span satisfies
    ``surface.original[start:end] == matched_text``. Boundary checks use the
    original projected sides and ``boundary_hint`` (defaulting to the surface's
    hint). Misaligned, empty, out-of-range, or boundary-rejected ranges raise
    :class:`ComparisonError`.
    """

    hint = _resolve_boundary_hint(surface.boundary_hint if boundary_hint is None else boundary_hint)
    if comparison_start < 0 or comparison_end < 0:
        raise ComparisonError(
            "INVALID_COMPARISON_RANGE",
            "comparison range offsets must be non-negative",
        )
    if comparison_start >= comparison_end:
        raise ComparisonError(
            "INVALID_COMPARISON_RANGE",
            "comparison range must be half-open and non-empty",
        )
    if comparison_end > len(surface.comparison_text):
        raise ComparisonError(
            "INVALID_COMPARISON_RANGE",
            "comparison range ends outside the comparison text",
        )

    original_start, original_end = _original_range_for_comparison(
        surface,
        comparison_start,
        comparison_end,
    )
    matched = surface.original[original_start:original_end]
    if not respects_boundary(
        surface.original,
        original_start,
        original_end,
        boundary_hint=hint,
    ):
        raise ComparisonError(
            "BOUNDARY_REJECTED",
            "projected original range fails the fixed V1 boundary check",
        )
    span = CharSpan(
        start_char=original_start,
        end_char=original_end,
        matched_text=matched,
    )
    # Local coherence only; callers may also validate against BlockEvidence.
    if surface.original[span.start_char : span.end_char] != span.matched_text:
        raise ComparisonError(
            "OFFSET_MISMATCH",
            "projected original slice does not equal matched_text",
        )
    return span


def project_against_block(
    block: BlockEvidence,
    surface: ComparisonSurface,
    comparison_start: int,
    comparison_end: int,
    *,
    boundary_hint: str | None = None,
) -> CharSpan:
    """Project a comparison range and require L01 block slice equality."""

    if surface.original != block.text:
        raise ComparisonError(
            "SURFACE_BLOCK_MISMATCH",
            "comparison surface original text does not equal the block text",
        )
    span = project_comparison_range(
        surface,
        comparison_start,
        comparison_end,
        boundary_hint=boundary_hint,
    )
    try:
        validate_match_against_block(span, block)
    except ValueError as exc:
        raise ComparisonError(
            "BLOCK_SLICE_MISMATCH",
            "projected span failed validate_match_against_block",
        ) from exc
    return span


def respects_boundary(
    original: str,
    start: int,
    end: int,
    *,
    boundary_hint: str,
) -> bool:
    """Return whether ``original[start:end]`` respects the fixed V1 boundary.

    Checks both exterior original code points. Rules are role/hint-aware and are
    not a universal ``\\b`` / ``isalnum()`` test.

    ``default`` treats an adjacent hyphen-minus as word/code continuation so a
    shorter material name is not accepted inside ``glucose-6-phosphate`` or
    ``water-soluble``. ``atomic_unit`` treats slash, middle dot, hyphen,
    superscript signs, and numeric characters (``Nd`` and ``No``) as unit
    continuation, while number-adjacent permission on the left remains ordinary
    decimal digits (``Nd``) only.
    """

    if start < 0 or end < start or end > len(original):
        return False
    if start == end:
        return False
    hint = _resolve_boundary_hint(boundary_hint)
    left = original[start - 1] if start > 0 else None
    right = original[end] if end < len(original) else None

    if hint == "whole_code":
        if left is not None and _is_whole_code_char(left):
            return False
        if right is not None and _is_whole_code_char(right):
            return False
        return True

    if hint == "atomic_unit":
        if left is not None and not _atomic_unit_left_ok(left):
            return False
        if right is not None and not _atomic_unit_right_ok(right):
            return False
        return True

    # default: natural-language and material word/code edges
    if left is not None and _is_default_word_char(left):
        return False
    if right is not None and _is_default_word_char(right):
        return False
    return True


def comparison_profile(
    *,
    term_role: str,
    boundary_hint: str,
) -> Mapping[str, object]:
    """Return the fixed V1 profile decisions for documentation and tests."""

    hint = _resolve_boundary_hint(boundary_hint)
    return {
        "boundary_hint": hint,
        "collapse_whitespace": _collapse_whitespace_for(
            term_role=term_role,
            boundary_hint=hint,
        ),
        # V1 composition is NFC of each starter+combining-mark unit only, not a
        # whole-string NFC pass (adjacent Hangul Jamo are not recomposed).
        "unicode_form": "NFC",
        "composition_scope": "starter_plus_combining_marks",
        "case_handling": "casefold",
        "strip_accents": False,
        "stem": False,
        "compatibility_normalize": False,
    }


def _resolve_boundary_hint(boundary_hint: str) -> BoundaryHint:
    if boundary_hint not in _KNOWN_BOUNDARY_HINTS:
        raise ComparisonError(
            "UNSUPPORTED_BOUNDARY_HINT",
            f"boundary_hint must be one of {sorted(_KNOWN_BOUNDARY_HINTS)}",
        )
    return boundary_hint  # type: ignore[return-value]


def _collapse_whitespace_for(*, term_role: str, boundary_hint: BoundaryHint) -> bool:
    if boundary_hint in {"whole_code", "atomic_unit"}:
        return False
    if term_role in _MATERIAL_ROLES:
        return False
    if term_role in _NATURAL_ROLES:
        return True
    # Unknown roles stay conservative: composition/casefold only, no ws collapse.
    return False


def _build_surface(
    text: str,
    *,
    collapse_whitespace: bool,
    boundary_hint: BoundaryHint,
) -> ComparisonSurface:
    units: list[ComparisonUnit] = []
    parts: list[str] = []
    comp_pos = 0
    i = 0
    n = len(text)

    while i < n:
        if collapse_whitespace and text[i].isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            parts.append(" ")
            units.append(
                ComparisonUnit(
                    original_start=i,
                    original_end=j,
                    comparison_start=comp_pos,
                    comparison_end=comp_pos + 1,
                )
            )
            comp_pos += 1
            i = j
            continue

        j = i + 1
        while j < n and unicodedata.combining(text[j]) != 0:
            j += 1

        original_piece = text[i:j]
        nfc_piece = unicodedata.normalize("NFC", original_piece)
        folded = nfc_piece.casefold()
        # A source unit must remain representable. Empty fold of nonempty source
        # is treated as unrepresentable rather than silently dropped.
        if original_piece and not folded:
            raise ComparisonError(
                "UNREPRESENTABLE_TERM",
                "source unit became empty after fixed V1 case folding",
            )
        clen = len(folded)
        units.append(
            ComparisonUnit(
                original_start=i,
                original_end=j,
                comparison_start=comp_pos,
                comparison_end=comp_pos + clen,
            )
        )
        parts.append(folded)
        comp_pos += clen
        i = j

    return ComparisonSurface(
        original=text,
        comparison_text="".join(parts),
        units=tuple(units),
        collapse_whitespace=collapse_whitespace,
        boundary_hint=boundary_hint,
    )


def _strip_comparison_edges(surface: ComparisonSurface) -> ComparisonSurface:
    text = surface.comparison_text
    if not text:
        return surface
    start = 0
    end = len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == 0 and end == len(text):
        return surface
    if start >= end:
        return ComparisonSurface(
            original=surface.original,
            comparison_text="",
            units=(),
            collapse_whitespace=surface.collapse_whitespace,
            boundary_hint=surface.boundary_hint,
        )

    kept: list[ComparisonUnit] = []
    parts: list[str] = []
    new_pos = 0
    for unit in surface.units:
        if unit.comparison_end <= start or unit.comparison_start >= end:
            continue
        if unit.comparison_start < start or unit.comparison_end > end:
            # Edge strip only removes whole whitespace units at the ends.
            raise ComparisonError(
                "UNREPRESENTABLE_TERM",
                "cannot strip partial normalization units from a comparison key",
            )
        fragment = surface.comparison_text[unit.comparison_start : unit.comparison_end]
        kept.append(
            ComparisonUnit(
                original_start=unit.original_start,
                original_end=unit.original_end,
                comparison_start=new_pos,
                comparison_end=new_pos + len(fragment),
            )
        )
        parts.append(fragment)
        new_pos += len(fragment)

    return ComparisonSurface(
        original=surface.original,
        comparison_text="".join(parts),
        units=tuple(kept),
        collapse_whitespace=surface.collapse_whitespace,
        boundary_hint=surface.boundary_hint,
    )


def _original_range_for_comparison(
    surface: ComparisonSurface,
    comparison_start: int,
    comparison_end: int,
) -> tuple[int, int]:
    if not surface.units:
        raise ComparisonError(
            "INVALID_COMPARISON_RANGE",
            "comparison surface has no normalization units to project",
        )

    start_unit: ComparisonUnit | None = None
    end_unit: ComparisonUnit | None = None
    covering: list[ComparisonUnit] = []
    for unit in surface.units:
        if unit.comparison_start == comparison_start:
            start_unit = unit
        if unit.comparison_end == comparison_end:
            end_unit = unit
        if unit.comparison_end > comparison_start and unit.comparison_start < comparison_end:
            covering.append(unit)

    if start_unit is None or end_unit is None:
        raise ComparisonError(
            "PARTIAL_NORMALIZATION_UNIT",
            "comparison range starts or ends inside a normalization unit",
        )
    if not covering:
        raise ComparisonError(
            "INVALID_COMPARISON_RANGE",
            "comparison range covers no normalization units",
        )
    if covering[0] is not start_unit or covering[-1] is not end_unit:
        raise ComparisonError(
            "PARTIAL_NORMALIZATION_UNIT",
            "comparison range is not aligned to contiguous normalization units",
        )

    expected_start = covering[0].comparison_start
    for index, unit in enumerate(covering):
        if unit.comparison_start != expected_start:
            raise ComparisonError(
                "PARTIAL_NORMALIZATION_UNIT",
                "comparison range skips or splits normalization units",
            )
        expected_start = unit.comparison_end
        if index > 0 and unit.original_start < covering[index - 1].original_end:
            raise ComparisonError(
                "OFFSET_MISMATCH",
                "normalization units overlap in original offsets",
            )

    if covering[-1].comparison_end != comparison_end:
        raise ComparisonError(
            "PARTIAL_NORMALIZATION_UNIT",
            "comparison range does not end on a normalization unit boundary",
        )

    return covering[0].original_start, covering[-1].original_end


def _is_default_word_char(ch: str) -> bool:
    """Letters, marks, decimal digits, connectors, and hyphen-minus.

    Hyphen is treated as word/code continuation so a shorter ``default`` hit is
    rejected inside hyphen-connected chemical/expression forms.
    """

    category = unicodedata.category(ch)
    return category[0] in {"L", "M"} or category == "Nd" or category == "Pc" or ch == "-"


def _is_whole_code_char(ch: str) -> bool:
    """UNII whole-code characters: default word/code chars (already include ``-``)."""

    return _is_default_word_char(ch)


# Superscript plus/minus signs that continue reciprocal or signed unit spellings.
_UNIT_SUPERSCRIPT_SIGNS: Final[frozenset[str]] = frozenset({"⁻", "⁺", "₊", "₋"})


def _is_unit_compound_char(ch: str) -> bool:
    """Characters that continue an atomic unit token or compound spelling.

    Includes letters/marks, connector punctuation, slash, middle dot, hyphen,
    superscript signs, and numeric characters in categories ``Nd`` and ``No``.
    """

    category = unicodedata.category(ch)
    if category[0] in {"L", "M"} or category == "Pc":
        return True
    if category in {"Nd", "No"}:
        return True
    if ch in {"/", "·", "-"} or ch in _UNIT_SUPERSCRIPT_SIGNS:
        return True
    return False


def _atomic_unit_left_ok(left: str) -> bool:
    # Number-adjacent spellings such as 37°C and 120rpm: ordinary decimal digits
    # (Nd) only. Superscript/other numbers (No) continue a compound unit and are
    # not treated as a fresh numeric boundary.
    if unicodedata.category(left) == "Nd":
        return True
    return not _is_unit_compound_char(left)


def _atomic_unit_right_ok(right: str) -> bool:
    return not _is_unit_compound_char(right)


def _is_blank_comparison(text: str) -> bool:
    return text.strip() == ""


__all__ = [
    "BoundaryHint",
    "ComparisonError",
    "ComparisonSurface",
    "ComparisonUnit",
    "comparison_profile",
    "normalize_block",
    "normalize_literal",
    "normalize_term",
    "project_against_block",
    "project_comparison_range",
    "respects_boundary",
]
