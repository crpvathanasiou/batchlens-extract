"""Fixed V1 optional fuzzy dictionary helpers (L11).

Deletion-signature candidate retrieval and ordinary Levenshtein distance-1
verification over L06 comparison strings. Not a selectable algorithm, not
value/unit fuzzy matching, and not a runner.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from app.lexical_extraction.comparison import (
    ComparisonError,
    ComparisonSurface,
    normalize_literal,
    project_against_block,
)
from app.lexical_extraction.contracts import (
    FUZZY_MAX_EDIT_DISTANCE,
    FUZZY_MIN_WORD_LENGTH,
    BlockEvidence,
    CharSpan,
)
from app.lexical_extraction.field_mapping import fuzzy_shape_eligible

_FUZZY_ROLES: Final[frozenset[str]] = frozenset(
    {
        "equipment_type",
        "parameter_name",
        "unit_operation",
        "process_step",
    }
)
_FUZZY_FORBIDDEN_POLICIES: Final[frozenset[str]] = frozenset(
    {
        "context_required",
        "step_cue_only",
        "support_only",
        "inspection_only",
    }
)


def ordinary_levenshtein(a: str, b: str, *, limit: int = FUZZY_MAX_EDIT_DISTANCE) -> int | None:
    """Return ordinary Levenshtein distance when it is at most ``limit``.

    One insertion, deletion, or substitution costs one. Adjacent transposition
    alone costs two. Returns ``None`` when the distance exceeds ``limit``.
    """

    if a == b:
        return 0
    if limit < 0:
        return None
    len_a = len(a)
    len_b = len(b)
    if abs(len_a - len_b) > limit:
        return None
    if len_a < len_b:
        a, b = b, a
        len_a, len_b = len_b, len_a
    # a is the longer-or-equal string.
    previous = list(range(len_b + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i] + [0] * len_b
        row_min = current[0]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
            if current[j] < row_min:
                row_min = current[j]
        if row_min > limit:
            return None
        previous = current
    distance = previous[len_b]
    if distance > limit:
        return None
    return distance


def deletion_signatures(text: str) -> tuple[str, ...]:
    """Return ``text`` and every single-character deletion of ``text``."""

    if not text:
        return (text,)
    signatures = [text]
    for index in range(len(text)):
        signatures.append(text[:index] + text[index + 1 :])
    return tuple(signatures)


def fuzzy_signature_storage_codepoints(comparison_key: str) -> int:
    """Code points retained for one term's deletion-signature entries."""

    length = len(comparison_key)
    if length == 0:
        return 0
    # Full key once, plus each length-(n-1) deletion.
    return length + length * (length - 1)


def fuzzy_role_policy_eligible(
    *,
    term_role: str,
    match_policy: str | None = None,
) -> bool:
    """Fixed V1 role/policy gate used together with ``fuzzy_allowed``."""

    if term_role not in _FUZZY_ROLES:
        return False
    if match_policy is not None and match_policy in _FUZZY_FORBIDDEN_POLICIES:
        return False
    return True


def is_fuzzy_index_eligible(
    *,
    fuzzy_allowed: bool,
    term_role: str,
    comparison_key: str,
    match_policy: str | None = None,
) -> bool:
    """Return whether a prepared term may enter the optional fuzzy index."""

    if not fuzzy_allowed:
        return False
    if not fuzzy_role_policy_eligible(term_role=term_role, match_policy=match_policy):
        return False
    return fuzzy_shape_eligible(comparison_key)


@dataclass
class FuzzyCandidateIndex:
    """Bounded deletion-signature index over one shard's fuzzy-eligible keys."""

    signatures: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    key_to_refs: dict[str, list[object]] = field(default_factory=dict[str, list[object]])
    max_key_length: int = 0
    min_key_length: int = 0
    signature_codepoints: int = 0

    def release(self) -> None:
        self.signatures.clear()
        self.key_to_refs.clear()
        self.max_key_length = 0
        self.min_key_length = 0
        self.signature_codepoints = 0


def add_fuzzy_term(
    index: FuzzyCandidateIndex,
    *,
    comparison_key: str,
    reference: object,
) -> int:
    """Index one eligible comparison key. Returns added signature code points."""

    added = 0
    if comparison_key not in index.key_to_refs:
        for signature in deletion_signatures(comparison_key):
            bucket = index.signatures.get(signature)
            if bucket is None:
                index.signatures[signature] = {comparison_key}
                added += len(signature)
            else:
                bucket.add(comparison_key)
        index.key_to_refs[comparison_key] = [reference]
        length = len(comparison_key)
        if index.max_key_length == 0 and index.min_key_length == 0:
            index.max_key_length = length
            index.min_key_length = length
        else:
            index.max_key_length = max(index.max_key_length, length)
            index.min_key_length = min(index.min_key_length, length)
    else:
        index.key_to_refs[comparison_key].append(reference)
    index.signature_codepoints += added
    return added


def iter_comparison_alphabetic_words(
    comparison_text: str,
) -> Iterator[tuple[int, int, str]]:
    """Yield half-open alphabetic runs from an L06 comparison string."""

    index = 0
    length = len(comparison_text)
    min_observed = FUZZY_MIN_WORD_LENGTH - FUZZY_MAX_EDIT_DISTANCE
    while index < length:
        char = comparison_text[index]
        if not char.isalpha():
            index += 1
            continue
        start = index
        index += 1
        while index < length and comparison_text[index].isalpha():
            index += 1
        word = comparison_text[start:index]
        if len(word) >= min_observed:
            yield start, index, word


def candidate_keys_for_observed(index: FuzzyCandidateIndex, observed: str) -> set[str]:
    """Return comparison keys sharing a deletion signature with ``observed``."""

    if not index.signatures:
        return set()
    if index.min_key_length and len(observed) < index.min_key_length - FUZZY_MAX_EDIT_DISTANCE:
        return set()
    if index.max_key_length and len(observed) > index.max_key_length + FUZZY_MAX_EDIT_DISTANCE:
        return set()
    keys: set[str] = set()
    for signature in deletion_signatures(observed):
        bucket = index.signatures.get(signature)
        if bucket is not None:
            keys.update(bucket)
    return keys


@dataclass(frozen=True)
class VerifiedFuzzyHit:
    """One distance-1 fuzzy hit on the comparison surface before projection."""

    comparison_start: int
    comparison_end: int
    observed_comparison: str
    source_comparison_key: str
    edit_distance: int
    reference: object


def iter_verified_fuzzy_hits(
    index: FuzzyCandidateIndex,
    surface: ComparisonSurface,
) -> Iterator[VerifiedFuzzyHit]:
    """Sound candidate retrieval with exact distance-1 verification."""

    if not index.key_to_refs or not surface.comparison_text:
        return
    for start, end, observed in iter_comparison_alphabetic_words(surface.comparison_text):
        for key in candidate_keys_for_observed(index, observed):
            distance = ordinary_levenshtein(observed, key, limit=FUZZY_MAX_EDIT_DISTANCE)
            if distance != FUZZY_MAX_EDIT_DISTANCE:
                continue
            for reference in index.key_to_refs.get(key, ()):
                yield VerifiedFuzzyHit(
                    comparison_start=start,
                    comparison_end=end,
                    observed_comparison=observed,
                    source_comparison_key=key,
                    edit_distance=distance,
                    reference=reference,
                )


def project_fuzzy_span(
    block: BlockEvidence,
    surface: ComparisonSurface,
    comparison_start: int,
    comparison_end: int,
    *,
    boundary_hint: str = "default",
) -> CharSpan | None:
    """Project a fuzzy comparison word to an original span, or skip non-hits."""

    try:
        return project_against_block(
            block,
            surface,
            comparison_start,
            comparison_end,
            boundary_hint=boundary_hint,
        )
    except ComparisonError as exc:
        if exc.code in {"BOUNDARY_REJECTED", "PARTIAL_NORMALIZATION_UNIT"}:
            return None
        raise


def recompute_fuzzy_distance(
    *,
    dictionary_term: str,
    matched_text: str,
    term_role: str,
    boundary_hint: str = "default",
) -> int | None:
    """Recompute ordinary distance on L06 comparison keys for L08 validation.

    Returns ``1`` only when the entire observed span normalizes to one alphabetic
    word (edges are not stripped) within the allowed one-edit length of the
    source key and the ordinary Levenshtein distance is exactly one. Leading or
    trailing whitespace, punctuation, and other non-word comparison text return
    ``None``. Source terms still use edge-stripped normalization.
    """

    try:
        source_surface = normalize_literal(
            dictionary_term,
            term_role=term_role,
            boundary_hint=boundary_hint,
            strip_edges=True,
        )
        observed_surface = normalize_literal(
            matched_text,
            term_role=term_role,
            boundary_hint=boundary_hint,
            strip_edges=False,
        )
    except ComparisonError:
        return None
    source_key = source_surface.comparison_text
    observed_key = observed_surface.comparison_text
    if not observed_key or observed_key[0].isspace() or observed_key[-1].isspace():
        return None
    if not observed_key.isalpha():
        return None
    if abs(len(observed_key) - len(source_key)) > FUZZY_MAX_EDIT_DISTANCE:
        return None
    min_observed = FUZZY_MIN_WORD_LENGTH - FUZZY_MAX_EDIT_DISTANCE
    if len(observed_key) < min_observed:
        return None
    return ordinary_levenshtein(
        observed_key,
        source_key,
        limit=FUZZY_MAX_EDIT_DISTANCE,
    )


__all__ = [
    "FuzzyCandidateIndex",
    "VerifiedFuzzyHit",
    "add_fuzzy_term",
    "candidate_keys_for_observed",
    "deletion_signatures",
    "fuzzy_role_policy_eligible",
    "fuzzy_signature_storage_codepoints",
    "is_fuzzy_index_eligible",
    "iter_comparison_alphabetic_words",
    "iter_verified_fuzzy_hits",
    "ordinary_levenshtein",
    "project_fuzzy_span",
    "recompute_fuzzy_distance",
]
