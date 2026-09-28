"""Controlled V1 value-expression recognition for one block (L10).

Recognizes scalar-with-unit, range, comparison, symmetric-tolerance, categorical,
and cued-unitless forms against a finite unit spelling set and fixed cue/category
rules. Grouping is syntactic only. No unit conversion, parent entity binding,
catalogue Published-range substitution, or plausibility correction.

Standalone ``UnitOccurrence`` emission is owned by unit aggregation; this module
may recognize a unit span inside a value expression without selecting the
``units`` component.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.lexical_extraction.comparison import respects_boundary
from app.lexical_extraction.contracts import (
    AmbiguousNumber,
    BlockEvidence,
    CategoricalExpression,
    CharSpan,
    ComparisonValue,
    Component,
    CuedUnitlessValue,
    ExactDecimal,
    NumberToken,
    NumberUnitGroup,
    RangeValue,
    ScalarWithUnit,
    SymmetricTolerance,
    ValueExpression,
    ValueOccurrence,
)
from app.lexical_extraction.unit_value_rules import (
    FIXED_CATEGORICAL_RULES,
    FIXED_CUE_RULES,
    controlled_unit_for_casefolded,
    controlled_unit_for_spelling,
    fixed_unit_spellings,
)

_VALUE_COMPONENTS = frozenset(
    {Component.QUANTITY_EXPRESSIONS, Component.PARAMETER_VALUE_EXPRESSIONS}
)
_COMPONENT_ORDER = (
    Component.QUANTITY_EXPRESSIONS,
    Component.PARAMETER_VALUE_EXPRESSIONS,
)

# Number token: digits with optional single decimal point; comma form is ambiguous.
_NUMBER = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\d*\.\d+)"
_COMPARATORS = ("<=", ">=", "<", ">", "=")
_RANGE_SEPARATORS = ("–", "-", "—")  # en-dash, hyphen-minus, em-dash
_TOLERANCE = "±"

_DATE_PATTERN = re.compile(
    r"^(?:(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]" r"(?:19|20)\d{2})$"
)
_PAGE_PATTERN = re.compile(r"^(?:page|p\.)\s*\d+$", re.IGNORECASE)
_STEP_PATTERN = re.compile(r"^(?:step|stage)\s*\d+[a-z]?$", re.IGNORECASE)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Z]{2,}[-_]?\d{2,}[A-Z0-9_-]*$")
_BARE_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_PAGE_PREFIX = re.compile(r"(?i)(?:\bpage|\bp\.)\s*$")
_STEP_PREFIX = re.compile(r"(?i)(?:\bstep|\bstage)\s*$")


@dataclass(frozen=True)
class RecognizedUnitSpelling:
    """One unit spelling available for value recognition (not an occurrence)."""

    spelling: str
    controlled_spelling: str | None = None
    controlled_identity: str | None = None


def recognize_value_expressions(
    block: BlockEvidence,
    *,
    applies_to: Sequence[Component],
    unit_spellings: Sequence[RecognizedUnitSpelling] = (),
) -> tuple[ValueOccurrence, ...]:
    """Return value occurrences for ``block`` under the selected value components.

    When both quantity and parameter-value components are selected and one
    expression is eligible for both, it is emitted once with both ``applies_to``
    values. Overlapping spans that describe different evidence are preserved;
    duplicate identical expressions from competing grammar rules are not.
    """

    selected = tuple(component for component in _COMPONENT_ORDER if component in applies_to)
    if not selected:
        return ()
    unknown = {component for component in applies_to if component not in _VALUE_COMPONENTS}
    if unknown:
        raise ValueError("value recognition applies only to quantity or parameter-value components")

    unit_index = _unit_index(unit_spellings)
    expressions = _scan_expressions(block.text, unit_index)
    occurrences: list[ValueOccurrence] = []
    for index, expression in enumerate(expressions):
        occurrence_id = _occurrence_id(block.node_id, expression, selected, index)
        occurrences.append(
            ValueOccurrence(
                occurrence_id=occurrence_id,
                block_node_id=block.node_id,
                expression=expression,
                applies_to=selected,
            )
        )
    return tuple(occurrences)


def _unit_index(
    unit_spellings: Sequence[RecognizedUnitSpelling],
) -> dict[str, RecognizedUnitSpelling]:
    """Index by casefold key; longer spellings win; first-seen wins ties."""

    index: dict[str, RecognizedUnitSpelling] = {}

    def _register(item: RecognizedUnitSpelling) -> None:
        key = item.spelling.casefold()
        current = index.get(key)
        if current is None or len(item.spelling) > len(current.spelling):
            fixed = controlled_unit_for_casefolded(item.spelling)
            index[key] = RecognizedUnitSpelling(
                spelling=item.spelling,
                controlled_spelling=(
                    item.controlled_spelling
                    if item.controlled_spelling is not None
                    else (None if fixed is None else fixed.controlled_spelling)
                ),
                controlled_identity=(
                    item.controlled_identity
                    if item.controlled_identity is not None
                    else (None if fixed is None else fixed.controlled_identity)
                ),
            )

    for item in sorted(unit_spellings, key=lambda entry: (-len(entry.spelling), entry.spelling)):
        _register(item)
    for spelling in sorted(fixed_unit_spellings(), key=lambda value: (-len(value), value)):
        if spelling.casefold() not in index:
            fixed = controlled_unit_for_spelling(spelling)
            _register(
                RecognizedUnitSpelling(
                    spelling=spelling,
                    controlled_spelling=None if fixed is None else fixed.controlled_spelling,
                    controlled_identity=None if fixed is None else fixed.controlled_identity,
                )
            )
    return index


def _scan_expressions(
    text: str,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> tuple[ValueExpression, ...]:
    claimed: list[tuple[int, int]] = []
    found: list[ValueExpression] = []

    def _accept(expression: ValueExpression) -> None:
        span = expression.span
        if _overlaps(claimed, span.start_char, span.end_char):
            return
        claimed.append((span.start_char, span.end_char))
        found.append(expression)

    # Longer / more specific forms first to avoid duplicate competing grammars.
    for _start, expression in _find_tolerances(text, unit_index):
        _accept(expression)
    for _start, expression in _find_ranges(text, unit_index):
        _accept(expression)
    for _start, expression in _find_comparisons(text, unit_index):
        _accept(expression)
    for _start, expression in _find_scalars(text, unit_index):
        _accept(expression)
    for _start, expression in _find_categoricals(text):
        _accept(expression)
    for _start, expression in _find_cued_unitless(text):
        _accept(expression)

    found.sort(key=lambda item: (item.span.start_char, item.span.end_char, item.raw_expression))
    return tuple(found)


def _overlaps(claimed: Sequence[tuple[int, int]], start: int, end: int) -> bool:
    return any(not (end <= left or start >= right) for left, right in claimed)


def _find_tolerances(
    text: str,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> list[tuple[int, ValueExpression]]:
    pattern = re.compile(
        rf"(?P<center>{_NUMBER})\s*{re.escape(_TOLERANCE)}\s*(?P<tol>{_NUMBER})"
        rf"(?P<gap>\s*)(?P<unit>\S+)"
    )
    results: list[tuple[int, ValueExpression]] = []
    for match in pattern.finditer(text):
        if not _left_number_ok(text, match.start("center")):
            continue
        unit_match = _match_unit_at(text, match.start("unit"), unit_index)
        if unit_match is None:
            continue
        unit_spelling, unit_end, unit_meta = unit_match
        center = _number_token(match.group("center"))
        tol = _number_token(match.group("tol"))
        if center is None or tol is None:
            continue
        if _rejected_free_standing_context(text, match.start(), unit_end):
            continue
        expr_start = match.start()
        expr_end = unit_end
        raw = text[expr_start:expr_end]
        unit_span = CharSpan(
            start_char=match.start("unit"),
            end_char=unit_end,
            matched_text=unit_spelling,
        )
        center_start = match.start("center")
        center_end = match.end("center")
        group = NumberUnitGroup(
            number_span=CharSpan(
                start_char=center_start,
                end_char=center_end,
                matched_text=text[center_start:center_end],
            ),
            unit_span=unit_span,
            group_span=CharSpan(
                start_char=expr_start,
                end_char=expr_end,
                matched_text=raw,
            ),
        )
        results.append(
            (
                expr_start,
                SymmetricTolerance(
                    raw_expression=raw,
                    span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
                    center=center,
                    tolerance=tol,
                    source_unit_spelling=unit_spelling,
                    unit_span=unit_span,
                    controlled_unit_spelling=unit_meta.controlled_spelling,
                    controlled_unit_identity=unit_meta.controlled_identity,
                    number_unit_group=group,
                ),
            )
        )
    return results


def _find_ranges(
    text: str,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> list[tuple[int, ValueExpression]]:
    results: list[tuple[int, ValueExpression]] = []
    for separator in _RANGE_SEPARATORS:
        pattern = re.compile(
            rf"(?P<low>{_NUMBER})\s*{re.escape(separator)}\s*(?P<high>{_NUMBER})"
            rf"(?P<gap>\s*)(?P<unit>\S+)"
        )
        for match in pattern.finditer(text):
            if not _left_number_ok(text, match.start("low")):
                continue
            unit_match = _match_unit_at(text, match.start("unit"), unit_index)
            if unit_match is None:
                continue
            unit_spelling, unit_end, unit_meta = unit_match
            low = _number_token(match.group("low"))
            high = _number_token(match.group("high"))
            if low is None or high is None:
                continue
            if _looks_like_date_fragment(text, match.start(), unit_end):
                continue
            if _rejected_free_standing_context(text, match.start(), unit_end):
                continue
            expr_start = match.start()
            expr_end = unit_end
            raw = text[expr_start:expr_end]
            unit_span = CharSpan(
                start_char=match.start("unit"),
                end_char=unit_end,
                matched_text=unit_spelling,
            )
            results.append(
                (
                    expr_start,
                    RangeValue(
                        raw_expression=raw,
                        span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
                        low=low,
                        high=high,
                        source_unit_spelling=unit_spelling,
                        unit_span=unit_span,
                        controlled_unit_spelling=unit_meta.controlled_spelling,
                        controlled_unit_identity=unit_meta.controlled_identity,
                    ),
                )
            )
    return results


def _find_comparisons(
    text: str,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> list[tuple[int, ValueExpression]]:
    results: list[tuple[int, ValueExpression]] = []
    for comparator in _COMPARATORS:
        pattern = re.compile(
            rf"(?<![<>==]){re.escape(comparator)}\s*(?P<number>{_NUMBER})"
            rf"(?P<gap>\s*)(?P<unit>\S+)"
        )
        for match in pattern.finditer(text):
            unit_match = _match_unit_at(text, match.start("unit"), unit_index)
            if unit_match is None:
                continue
            unit_spelling, unit_end, unit_meta = unit_match
            number = _number_token(match.group("number"))
            if number is None:
                continue
            if _rejected_free_standing_context(text, match.start(), unit_end):
                continue
            expr_start = match.start()
            expr_end = unit_end
            raw = text[expr_start:expr_end]
            unit_span = CharSpan(
                start_char=match.start("unit"),
                end_char=unit_end,
                matched_text=unit_spelling,
            )
            results.append(
                (
                    expr_start,
                    ComparisonValue(
                        raw_expression=raw,
                        span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
                        comparator=comparator,  # type: ignore[arg-type]
                        number=number,
                        source_unit_spelling=unit_spelling,
                        unit_span=unit_span,
                        controlled_unit_spelling=unit_meta.controlled_spelling,
                        controlled_unit_identity=unit_meta.controlled_identity,
                    ),
                )
            )
    return results


def _find_scalars(
    text: str,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> list[tuple[int, ValueExpression]]:
    results: list[tuple[int, ValueExpression]] = []
    pattern = re.compile(rf"(?P<number>{_NUMBER})(?P<gap>\s*)(?P<unit>\S+)")
    for match in pattern.finditer(text):
        unit_match = _match_unit_at(text, match.start("unit"), unit_index)
        if unit_match is None:
            continue
        unit_spelling, unit_end, unit_meta = unit_match
        unit_start = match.start("unit")
        number_text = match.group("number")
        number = _number_token(number_text)
        if number is None:
            continue
        expr_start = match.start("number")
        expr_end = unit_end
        if not _left_number_ok(text, expr_start):
            continue
        if _is_range_high_fragment(text, expr_start):
            continue
        if _is_tolerance_tail_fragment(text, expr_start):
            continue
        if _rejected_free_standing_context(text, expr_start, expr_end):
            continue
        if _looks_like_date_fragment(text, expr_start, expr_end):
            continue
        raw = text[expr_start:expr_end]
        number_span = CharSpan(
            start_char=expr_start,
            end_char=match.end("number"),
            matched_text=number_text,
        )
        unit_span = CharSpan(start_char=unit_start, end_char=unit_end, matched_text=unit_spelling)
        group = NumberUnitGroup(
            number_span=number_span,
            unit_span=unit_span,
            group_span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
        )
        results.append(
            (
                expr_start,
                ScalarWithUnit(
                    raw_expression=raw,
                    span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
                    number=number,
                    source_unit_spelling=unit_spelling,
                    unit_span=unit_span,
                    controlled_unit_spelling=unit_meta.controlled_spelling,
                    controlled_unit_identity=unit_meta.controlled_identity,
                    number_unit_group=group,
                ),
            )
        )
    return results


def _find_categoricals(text: str) -> list[tuple[int, ValueExpression]]:
    results: list[tuple[int, ValueExpression]] = []
    for rule in FIXED_CATEGORICAL_RULES:
        phrase = rule.phrase
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            end = index + len(phrase)
            if _phrase_boundary_ok(text, index, end):
                results.append(
                    (
                        index,
                        CategoricalExpression(
                            raw_expression=phrase,
                            span=CharSpan(start_char=index, end_char=end, matched_text=phrase),
                            category_label=rule.category_label,
                        ),
                    )
                )
            start = index + 1
    return results


def _find_cued_unitless(text: str) -> list[tuple[int, ValueExpression]]:
    results: list[tuple[int, ValueExpression]] = []
    for rule in FIXED_CUE_RULES:
        cue = rule.cue
        # Require a non-word character (or start) before the cue so embedded
        # forms such as ``MaxSpeed:`` are not treated as the fixed cue.
        pattern = re.compile(rf"(?<!\w){re.escape(cue)}\s*(?P<number>{_NUMBER})")
        for match in pattern.finditer(text):
            number = _number_token(match.group("number"))
            if number is None:
                continue
            expr_start = match.start()
            expr_end = match.end()
            if _rejected_free_standing_context(text, expr_start, expr_end):
                continue
            raw = text[expr_start:expr_end]
            results.append(
                (
                    expr_start,
                    CuedUnitlessValue(
                        raw_expression=raw,
                        span=CharSpan(start_char=expr_start, end_char=expr_end, matched_text=raw),
                        cue=cue,
                        number=number,
                    ),
                )
            )
    return results


def _match_unit_at(
    text: str,
    start: int,
    unit_index: dict[str, RecognizedUnitSpelling],
) -> tuple[str, int, RecognizedUnitSpelling] | None:
    """Match the longest known unit spelling at ``start`` under atomic_unit boundaries.

    Comparison is case-insensitive (Unicode casefold), matching L06/L07 unit
    normalization. The returned spelling is the exact original substring.
    """

    remaining = text[start:]
    if not remaining:
        return None
    best: tuple[str, int, RecognizedUnitSpelling] | None = None
    for meta in sorted(unit_index.values(), key=lambda item: (-len(item.spelling), item.spelling)):
        length = len(meta.spelling)
        if length > len(remaining):
            continue
        candidate = remaining[:length]
        if candidate.casefold() != meta.spelling.casefold():
            continue
        end = start + length
        if not _unit_boundary_ok(text, start, end):
            continue
        fixed = controlled_unit_for_casefolded(candidate)
        resolved = RecognizedUnitSpelling(
            spelling=meta.spelling,
            controlled_spelling=(
                meta.controlled_spelling
                if meta.controlled_spelling is not None
                else (None if fixed is None else fixed.controlled_spelling)
            ),
            controlled_identity=(
                meta.controlled_identity
                if meta.controlled_identity is not None
                else (None if fixed is None else fixed.controlled_identity)
            ),
        )
        if best is None or length > (best[1] - start):
            best = (candidate, end, resolved)
    return best


def _unit_boundary_ok(text: str, start: int, end: int) -> bool:
    return respects_boundary(text, start, end, boundary_hint="atomic_unit")


def _left_number_ok(text: str, start: int) -> bool:
    if start > 0 and _is_identifier_char(text[start - 1]):
        return False
    return True


def _is_range_high_fragment(text: str, number_start: int) -> bool:
    """Return whether ``number_start`` is the high side of a number–separator–number form.

    Used so an identifier-prefixed range such as ``ID20–25 °C`` does not emit the
    trailing ``25 °C`` as a free-standing scalar after the range is rejected.
    """

    index = number_start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    for separator in _RANGE_SEPARATORS:
        width = len(separator)
        if index >= width and text[index - width : index] == separator:
            before = index - width
            while before > 0 and text[before - 1].isspace():
                before -= 1
            end = before
            start = end
            while start > 0 and (text[start - 1].isdigit() or text[start - 1] in {",", "."}):
                start -= 1
            if start < end and re.fullmatch(_NUMBER, text[start:end]) is not None:
                return True
    return False


def _is_tolerance_tail_fragment(text: str, number_start: int) -> bool:
    """Return whether ``number_start`` is the tolerance side of ``N ± M``.

    Prevents ``tagX100 ± 5 g`` from emitting trailing ``5 g`` after the
    identifier-prefixed tolerance form is rejected.
    """

    index = number_start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    width = len(_TOLERANCE)
    if index < width or text[index - width : index] != _TOLERANCE:
        return False
    before = index - width
    while before > 0 and text[before - 1].isspace():
        before -= 1
    end = before
    start = end
    while start > 0 and (text[start - 1].isdigit() or text[start - 1] in {",", "."}):
        start -= 1
    return start < end and re.fullmatch(_NUMBER, text[start:end]) is not None


def _phrase_boundary_ok(text: str, start: int, end: int) -> bool:
    left = text[start - 1] if start > 0 else None
    right = text[end] if end < len(text) else None
    if left is not None and (left.isalnum() or left == "_"):
        return False
    if right is not None and (right.isalnum() or right == "_"):
        return False
    return True


def _number_token(raw: str) -> NumberToken | None:
    if "," in raw:
        # Never silently choose thousands versus decimal.
        return AmbiguousNumber(raw_token=raw)
    if not raw or raw in {".", "-"}:
        return None
    try:
        ExactDecimal(text=raw)
    except Exception:
        return None
    return ExactDecimal(text=raw)


def _rejected_free_standing_context(text: str, start: int, end: int) -> bool:
    window = text[start:end].strip()
    if _PAGE_PATTERN.fullmatch(window) or _STEP_PATTERN.fullmatch(window):
        return True
    if _DATE_PATTERN.fullmatch(window) or _IDENTIFIER_PATTERN.fullmatch(window):
        return True
    # Expand slightly left for "Page 12" / "Step 3" prefixes when the match is numeric.
    prefix_start = max(0, start - 8)
    prefix = text[prefix_start:start]
    if _PAGE_PREFIX.search(prefix) or _STEP_PREFIX.search(prefix):
        return True
    return False


def _looks_like_date_fragment(text: str, start: int, end: int) -> bool:
    fragment = text[start:end]
    if _DATE_PATTERN.fullmatch(fragment):
        return True
    # Hyphen ranges that are pure year-like without a unit were already excluded
    # by requiring a unit; still reject bare years as number tokens in identifiers.
    number_only = re.fullmatch(_NUMBER, fragment)
    return bool(number_only and _BARE_YEAR.fullmatch(fragment))


def _is_identifier_char(ch: str) -> bool:
    return ch.isalnum() or ch in {"_", "-"}


def _occurrence_id(
    block_node_id: str,
    expression: ValueExpression,
    applies_to: Sequence[Component],
    index: int,
) -> str:
    material = "|".join(
        (
            block_node_id,
            str(expression.span.start_char),
            str(expression.span.end_char),
            expression.raw_expression,
            ",".join(component.value for component in applies_to),
            str(index),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"value:{digest}"
