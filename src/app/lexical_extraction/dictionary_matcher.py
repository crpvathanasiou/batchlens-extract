"""Bounded exact and normalized-exact Aho–Corasick dictionary matching (L07).

Consumes L05 eligible terms and a replayable L03 block source, builds finite
Aho–Corasick shards under L02 resource limits, and streams source-backed raw
discoveries with original document spans. This is not occurrence aggregation,
candidate resolution, fuzzy matching, value parsing, or a runner/CLI.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Generator, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Protocol, runtime_checkable

import ahocorasick  # type: ignore[import-untyped]

from app.lexical_extraction.comparison import (
    ComparisonError,
    ComparisonSurface,
    normalize_literal,
    normalize_term,
    project_against_block,
)
from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    EXACT_RULE_ID,
    NORMALIZED_EXACT_RULE_ID,
    BlockEvidence,
    CharSpan,
    Component,
    SafeStructuredError,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm
from app.lexical_extraction.html_reader import ReviewedHtmlReadError, open_reviewed_html

_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200
_ELLIPSIS: Final = "..."

MatchMethod = Literal["exact", "normalized_exact"]


class DictionaryMatchError(Exception):
    """Bounded dictionary-matching failure.

    ``code`` and ``message`` map to :class:`SafeStructuredError`. Shard
    construction failures, oversized references, block-read failures, and
    changed or incomplete replay identities fail here instead of reporting
    successful complete coverage.
    """

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("dictionary-match error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class RawDiscovery:
    """One intermediate exact or normalized-exact hit with original span.

    Not an L01 ``DictionaryOccurrence``, candidate, entity association, or
    execution claim. Repeated occurrences, overlaps, and distinct source
    references that share a comparison key are all retained as separate records.
    """

    method: MatchMethod
    rule_id: Literal["lexical-v1-exact", "lexical-v1-normalized-exact"]
    dictionary_term: str
    component: Component
    term_role: str
    source_table: str
    source_field: str
    row_id: str
    block_node_id: str
    span: CharSpan
    lexical_term_id: str | None = None
    snapshot_id: str | None = None
    boundary_hint: str = "default"


@runtime_checkable
class BlockReplaySource(Protocol):
    """Replayable bounded source of L03 blocks for every shard pass.

    Each call to :meth:`iter_blocks` must yield every eligible block again.
    Implementations must not silently exhaust a one-shot reader. A stable
    ``source_identity`` is required so the matcher can pin and compare document
    bytes across complete passes. Synthetic tests may supply an explicit identity;
    reviewed-HTML replay should use the finalized L03 SHA-256 after a complete
    successful pass.
    """

    @property
    def source_identity(self) -> str:
        """Stable identity for the pinned document bytes or synthetic fixture."""
        ...

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        """Yield every eligible block for one complete pass."""
        ...


@dataclass(frozen=True)
class StaticBlockSource:
    """Small explicitly bounded, repeatable block source for tests and probes.

    Holds a finite tuple of blocks in memory. Suitable only for synthetic or
    small fixtures — not a substitute for streaming reviewed HTML.
    """

    blocks: tuple[BlockEvidence, ...]
    identity: str

    @property
    def source_identity(self) -> str:
        return self.identity

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        yield from self.blocks


class ReviewedHtmlBlockReplay:
    """Reopen reviewed HTML v1 for each shard and pin the finalized SHA-256.

    Lifecycle: each :meth:`iter_blocks` opens a fresh L03 reader, streams pages
    without retaining the whole document, and requires a completed read before
    the pass finishes. The first successful complete pass pins ``html_sha256``;
    a later pass with a different digest or an incomplete read raises
    :class:`DictionaryMatchError`. Callers do not need to close this object;
    readers are scoped to each pass.
    """

    def __init__(self, path: Path | str, *, chunk_size: int = 64 * 1024) -> None:
        self._path = Path(path)
        self._chunk_size = chunk_size
        self._pinned_sha256: str | None = None

    @property
    def source_identity(self) -> str:
        if self._pinned_sha256 is None:
            raise DictionaryMatchError(
                "REPLAY_IDENTITY_UNPINNED",
                "reviewed HTML identity is available only after a complete block pass",
            )
        return self._pinned_sha256

    def iter_blocks(self) -> Iterator[BlockEvidence]:
        try:
            reader = open_reviewed_html(self._path, chunk_size=self._chunk_size)
        except ReviewedHtmlReadError as exc:
            raise DictionaryMatchError(
                "BLOCK_READ_FAILED",
                _bounded_message(f"failed to open reviewed HTML: {exc.code}"),
            ) from exc

        try:
            for page in reader.iter_pages():
                for record in page.blocks:
                    yield record.block
        except ReviewedHtmlReadError as exc:
            raise DictionaryMatchError(
                "BLOCK_READ_FAILED",
                _bounded_message(f"reviewed HTML read failed: {exc.code}"),
            ) from exc

        if not reader.completed:
            raise DictionaryMatchError(
                "REPLAY_INCOMPLETE",
                "reviewed HTML pass ended without a finalized validated input digest",
            )
        try:
            digest = reader.validated_input.html_sha256
        except ReviewedHtmlReadError as exc:
            raise DictionaryMatchError(
                "REPLAY_INCOMPLETE",
                _bounded_message(f"validated HTML identity unavailable: {exc.code}"),
            ) from exc
        if self._pinned_sha256 is None:
            self._pinned_sha256 = digest
        elif self._pinned_sha256 != digest:
            raise DictionaryMatchError(
                "REPLAY_IDENTITY_CHANGED",
                "reviewed HTML SHA-256 changed between shard passes",
            )


@dataclass(frozen=True)
class _PreparedReference:
    """Compact shard-local source reference sharing one comparison key."""

    literal: str
    comparison_key: str
    collapse_whitespace: bool
    component: Component
    term_role: str
    source_table: str
    source_field: str
    row_id: str
    lexical_term_id: str | None
    snapshot_id: str | None
    boundary_hint: str


@dataclass
class _ShardAutomaton:
    """One collapse-profile automaton and its key→references map."""

    collapse_whitespace: bool
    automaton: Any
    key_references: dict[str, list[_PreparedReference]]

    def release(self) -> None:
        self.key_references.clear()
        self.automaton = _new_automaton()


def _new_automaton() -> Any:
    """Construct an untyped ``ahocorasick.Automaton``."""

    return ahocorasick.Automaton()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


class _TermCursor:
    """One-shot term stream with single-term pushback for shard boundaries."""

    def __init__(self, terms: Iterable[EligibleSearchTerm]) -> None:
        self._iter = iter(terms)
        self._pending: EligibleSearchTerm | None = None

    def next_term(self) -> EligibleSearchTerm | None:
        if self._pending is not None:
            term = self._pending
            self._pending = None
            return term
        try:
            return next(self._iter)
        except StopIteration:
            return None

    def push_back(self, term: EligibleSearchTerm) -> None:
        if self._pending is not None:
            raise DictionaryMatchError(
                "SHARD_CONSTRUCTION_FAILED",
                "internal term cursor pushback overflow",
            )
        self._pending = term


def iter_raw_discoveries(
    terms: Iterable[EligibleSearchTerm],
    blocks: BlockReplaySource,
    limits: ResourceLimits,
) -> Generator[RawDiscovery, None, None]:
    """Stream exact/normalized-exact raw discoveries under finite shard limits.

    Terms are consumed once and partitioned into shards by
    ``max_terms_per_shard`` (source references) and
    ``max_term_codepoints_per_shard`` (literal + comparison key + retained
    reference strings). Each shard builds Aho–Corasick automata, rescans every
    block from ``blocks``, emits discoveries through a bounded result buffer,
    then releases shard-local state before the next shard. Fuzzy matching is
    never applied; L02 ``fuzzy_enabled`` is ignored here.

    The discovery multiset for identical pinned inputs is independent of shard
    limits; emission order may follow shard order. Early close or failure
    releases the current automata. This iterator does not retain an
    all-vocabulary or all-block collection across shards.
    """

    if limits.max_terms_per_shard < 1 or limits.max_term_codepoints_per_shard < 1:
        raise DictionaryMatchError(
            "INVALID_SHARD_LIMIT",
            "shard resource limits must be at least 1",
        )

    cursor = _TermCursor(terms)
    active: list[_ShardAutomaton] = []
    pinned_identity: str | None = None
    try:
        while True:
            shard_refs = _fill_shard(cursor, limits)
            if not shard_refs:
                break
            active = _build_shard_automata(shard_refs)
            try:
                yield from _stream_shard(active, blocks, limits.result_buffer_records)
                pass_identity = _require_identity(blocks)
                if pinned_identity is None:
                    pinned_identity = pass_identity
                elif pinned_identity != pass_identity:
                    raise DictionaryMatchError(
                        "REPLAY_IDENTITY_CHANGED",
                        "block source identity changed between shard passes",
                    )
            finally:
                _release_automata(active)
                active = []
                del shard_refs
    except GeneratorExit:
        _release_automata(active)
        raise
    finally:
        _release_automata(active)


def _fill_shard(cursor: _TermCursor, limits: ResourceLimits) -> list[_PreparedReference]:
    refs: list[_PreparedReference] = []
    codepoints = 0
    while True:
        term = cursor.next_term()
        if term is None:
            return refs
        prepared = _prepare_reference(term)
        cost = _reference_codepoints(prepared)
        if cost > limits.max_term_codepoints_per_shard:
            raise DictionaryMatchError(
                "OVERSIZED_TERM",
                "single source term/reference exceeds max_term_codepoints_per_shard",
            )
        if refs and (
            len(refs) >= limits.max_terms_per_shard
            or codepoints + cost > limits.max_term_codepoints_per_shard
        ):
            cursor.push_back(term)
            return refs
        refs.append(prepared)
        codepoints += cost
        if len(refs) >= limits.max_terms_per_shard:
            return refs


def _prepare_reference(term: EligibleSearchTerm) -> _PreparedReference:
    try:
        surface = normalize_term(term)
    except ComparisonError as exc:
        raise DictionaryMatchError(
            "TERM_NORMALIZATION_FAILED",
            _bounded_message(f"eligible term normalization failed: {exc.code}"),
        ) from exc
    return _PreparedReference(
        literal=term.literal,
        comparison_key=surface.comparison_text,
        collapse_whitespace=surface.collapse_whitespace,
        component=term.component,
        term_role=term.term_role,
        source_table=term.source_table,
        source_field=term.source_field,
        row_id=term.row_id,
        lexical_term_id=term.lexical_term_id,
        snapshot_id=term.snapshot_id,
        boundary_hint=term.boundary_hint,
    )


def _reference_codepoints(ref: _PreparedReference) -> int:
    total = len(ref.literal) + len(ref.comparison_key)
    total += len(ref.source_table) + len(ref.source_field) + len(ref.row_id)
    total += len(ref.term_role) + len(ref.boundary_hint) + len(ref.component.value)
    if ref.lexical_term_id is not None:
        total += len(ref.lexical_term_id)
    if ref.snapshot_id is not None:
        total += len(ref.snapshot_id)
    return total


def _build_shard_automata(refs: Sequence[_PreparedReference]) -> list[_ShardAutomaton]:
    by_collapse: dict[bool, dict[str, list[_PreparedReference]]] = {False: {}, True: {}}
    for ref in refs:
        bucket = by_collapse[ref.collapse_whitespace]
        bucket.setdefault(ref.comparison_key, []).append(ref)

    built: list[_ShardAutomaton] = []
    try:
        for collapse, key_map in by_collapse.items():
            if not key_map:
                continue
            automaton = _new_automaton()
            for key in key_map:
                automaton.add_word(key, key)
            automaton.make_automaton()
            built.append(
                _ShardAutomaton(
                    collapse_whitespace=collapse,
                    automaton=automaton,
                    key_references=key_map,
                )
            )
    except Exception as exc:
        _release_automata(built)
        raise DictionaryMatchError(
            "SHARD_CONSTRUCTION_FAILED",
            _bounded_message(f"Aho-Corasick shard construction failed: {type(exc).__name__}"),
        ) from exc
    return built


def _stream_shard(
    automata: Sequence[_ShardAutomaton],
    blocks: BlockReplaySource,
    result_buffer_records: int,
) -> Iterator[RawDiscovery]:
    """Stream discoveries for one shard, buffering at most ``result_buffer_records``."""

    buffer: deque[RawDiscovery] = deque()
    try:
        for block in blocks.iter_blocks():
            for discovery in _match_block(block, automata):
                buffer.append(discovery)
                if len(buffer) >= result_buffer_records:
                    while buffer:
                        yield buffer.popleft()
        while buffer:
            yield buffer.popleft()
    except DictionaryMatchError:
        buffer.clear()
        raise
    except Exception as exc:
        buffer.clear()
        raise DictionaryMatchError(
            "BLOCK_READ_FAILED",
            _bounded_message(f"block replay failed: {type(exc).__name__}"),
        ) from exc


def _require_identity(blocks: BlockReplaySource) -> str:
    try:
        return blocks.source_identity
    except DictionaryMatchError:
        raise
    except Exception as exc:
        raise DictionaryMatchError(
            "REPLAY_INCOMPLETE",
            _bounded_message(f"block source identity unavailable: {type(exc).__name__}"),
        ) from exc


def _match_block(
    block: BlockEvidence,
    automata: Sequence[_ShardAutomaton],
) -> Iterator[RawDiscovery]:
    if not block.text:
        return
    surfaces: dict[bool, ComparisonSurface] = {}
    for shard in automata:
        if shard.collapse_whitespace not in surfaces:
            surfaces[shard.collapse_whitespace] = _normalize_block_for_profile(
                block,
                collapse_whitespace=shard.collapse_whitespace,
            )
        surface = surfaces[shard.collapse_whitespace]
        if not surface.comparison_text:
            continue
        try:
            hits: Iterator[tuple[int, str]] = automaton_iter(
                shard.automaton,
                surface.comparison_text,
            )
            for end_index, key in hits:
                start_index = end_index - len(key) + 1
                for ref in shard.key_references.get(key, ()):
                    discovery = _project_discovery(
                        block,
                        surface,
                        start_index,
                        end_index + 1,
                        ref,
                    )
                    if discovery is not None:
                        yield discovery
        except DictionaryMatchError:
            raise
        except Exception as exc:
            # Covers failures creating or consuming the AC iterator. GeneratorExit
            # is a BaseException and is not caught here. Block-source failures
            # remain classified in ``_stream_shard``.
            raise DictionaryMatchError(
                "MATCH_FAILED",
                _bounded_message(f"Aho-Corasick search failed: {type(exc).__name__}"),
            ) from exc


def automaton_iter(automaton: Any, text: str) -> Iterator[tuple[int, str]]:
    """Typed wrapper around ``ahocorasick.Automaton.iter``."""

    for end_index, key in automaton.iter(text):
        yield int(end_index), str(key)


def _normalize_block_for_profile(
    block: BlockEvidence,
    *,
    collapse_whitespace: bool,
) -> ComparisonSurface:
    # Representative role/hint pairs that produce the same fixed V1 collapse
    # decision as the indexed keys for this profile.
    if collapse_whitespace:
        term_role = "equipment_type"
        boundary_hint = "default"
    else:
        term_role = "material_name"
        boundary_hint = "default"
    try:
        return normalize_literal(
            block.text,
            term_role=term_role,
            boundary_hint=boundary_hint,
            strip_edges=False,
        )
    except ComparisonError as exc:
        raise DictionaryMatchError(
            "BLOCK_NORMALIZATION_FAILED",
            _bounded_message(f"block normalization failed: {exc.code}"),
        ) from exc


def _project_discovery(
    block: BlockEvidence,
    surface: ComparisonSurface,
    comparison_start: int,
    comparison_end: int,
    ref: _PreparedReference,
) -> RawDiscovery | None:
    try:
        span = project_against_block(
            block,
            surface,
            comparison_start,
            comparison_end,
            boundary_hint=ref.boundary_hint,
        )
    except ComparisonError as exc:
        # Normal non-hits: failed word/code/unit boundary, or a valid AC
        # substring that lies inside one L06 normalization unit (for example
        # ``s`` inside the ``ß`` → ``ss`` expansion). Other projection errors
        # indicate an invalid AC range or broken surface/block coherence and
        # must fail closed rather than look like successful coverage.
        if exc.code in {"BOUNDARY_REJECTED", "PARTIAL_NORMALIZATION_UNIT"}:
            return None
        raise DictionaryMatchError(
            "PROJECTION_FAILED",
            _bounded_message(f"comparison projection failed: {exc.code}"),
        ) from exc

    if span.matched_text == ref.literal:
        method: MatchMethod = "exact"
        rule_id: Literal["lexical-v1-exact", "lexical-v1-normalized-exact"] = EXACT_RULE_ID
    else:
        method = "normalized_exact"
        rule_id = NORMALIZED_EXACT_RULE_ID

    return RawDiscovery(
        method=method,
        rule_id=rule_id,
        dictionary_term=ref.literal,
        component=ref.component,
        term_role=ref.term_role,
        source_table=ref.source_table,
        source_field=ref.source_field,
        row_id=ref.row_id,
        block_node_id=block.node_id,
        span=span,
        lexical_term_id=ref.lexical_term_id,
        snapshot_id=ref.snapshot_id,
        boundary_hint=ref.boundary_hint,
    )


def _release_automata(automata: Sequence[_ShardAutomaton]) -> None:
    for shard in automata:
        shard.release()


def _bounded_message(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE:
        return message
    keep = _MAX_ERROR_MESSAGE - len(_ELLIPSIS)
    return message[:keep] + _ELLIPSIS


__all__ = [
    "BlockReplaySource",
    "DictionaryMatchError",
    "RawDiscovery",
    "ReviewedHtmlBlockReplay",
    "StaticBlockSource",
    "iter_raw_discoveries",
]
