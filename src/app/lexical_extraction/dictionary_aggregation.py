"""Bounded dictionary aggregation from L07 raw discoveries into L01 block records (L08).

Consumes an L07 raw-discovery iterator, a replayable L03 block source, and an open
L04 knowledge snapshot. Discoveries are regrouped through a run-local temporary
SQLite spool, rehydrated via single-table lookup plus L05 mapping, and emitted as
validated L01 ``BlockRecord`` values in document order. Optional L11 fuzzy hits are
accepted only after source eligibility and distance revalidation. This is not value
parsing, unit aggregation, a runner/CLI, or a published result.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, runtime_checkable

from app.lexical_extraction.comparison import (
    ComparisonError,
    normalize_literal,
    respects_boundary,
)
from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    EXACT_RULE_ID,
    FUZZY_MAX_EDIT_DISTANCE,
    FUZZY_MIN_WORD_LENGTH,
    FUZZY_RULE_ID,
    NORMALIZED_EXACT_RULE_ID,
    AmbiguityQualification,
    BlockEvidence,
    BlockRecord,
    CharSpan,
    ChebiMaterialCandidate,
    Component,
    DictionaryOccurrence,
    EquipmentTypeCandidate,
    ExactEvidence,
    FdaEmaMaterialCandidate,
    FuzzyEvidence,
    GenericCueCandidate,
    KnowledgeSnapshotIdentity,
    LexicalCandidate,
    NormalizedExactEvidence,
    ParameterNameCandidate,
    ProcessStepCandidate,
    SafeStructuredError,
    UnitOperationCandidate,
    validate_match_against_block,
)
from app.lexical_extraction.dictionary_matcher import (
    BlockReplaySource,
    DictionaryMatchError,
    RawDiscovery,
)
from app.lexical_extraction.field_mapping import (
    EligibleSearchTerm,
    FieldMappingError,
    map_source_row,
)
from app.lexical_extraction.fuzzy_matching import (
    fuzzy_role_policy_eligible,
    is_fuzzy_index_eligible,
    ordinary_levenshtein,
)
from app.lexical_extraction.knowledge_snapshot import SnapshotReadError, SourceRow

_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200
_ELLIPSIS: Final = "..."
_DICTIONARY_COMPONENTS: Final[frozenset[Component]] = frozenset(
    {
        Component.UNIT_OPERATIONS,
        Component.PROCESS_STEPS,
        Component.MATERIALS,
        Component.EQUIPMENT,
        Component.PARAMETER_NAMES,
    }
)
_METHOD_RANK: Final[Mapping[str, int]] = {
    "exact": 0,
    "normalized_exact": 1,
    "fuzzy": 2,
}
_COMPONENT_ORDER: Final[tuple[Component, ...]] = (
    Component.UNIT_OPERATIONS,
    Component.PROCESS_STEPS,
    Component.MATERIALS,
    Component.EQUIPMENT,
    Component.PARAMETER_NAMES,
)
_DEFAULT_ROW_CACHE: Final = 64
MatchMethodName = Literal["exact", "normalized_exact", "fuzzy"]


class DictionaryAggregationError(Exception):
    """Bounded dictionary-aggregation failure.

    ``code`` and ``message`` map to :class:`SafeStructuredError`. Resource
    overflow, lookup mismatch, unexpected unit input, spool failures, and replay
    identity changes fail here instead of reporting completed coverage.
    """

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("dictionary-aggregation error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@runtime_checkable
class SnapshotLookup(Protocol):
    """Minimal open L04 surface required by aggregation."""

    @property
    def identity(self) -> KnowledgeSnapshotIdentity:
        """Pinned snapshot identity from a successful preflight."""
        ...

    def lookup(self, table_name: str, row_id: str) -> SourceRow | None:
        """Return one source row by primary key, or ``None`` when absent."""
        ...


@dataclass(frozen=True)
class AggregationCoverage:
    """Counts available only after the aggregator finishes successfully."""

    blocks_emitted: int
    dictionary_occurrences: int
    candidates: int
    discoveries_consumed: int
    source_identity: str


@dataclass(frozen=True)
class _SpooledHit:
    method: MatchMethodName
    dictionary_term: str
    component: Component
    term_role: str
    source_table: str
    source_field: str
    row_id: str
    lexical_term_id: str | None
    snapshot_id: str
    start_char: int
    end_char: int
    matched_text: str
    edit_distance: int | None = None


@dataclass
class _GroupState:
    method: MatchMethodName
    term: EligibleSearchTerm
    row_ids: set[str]
    edit_distance: int | None = None


class AggregatedBlockStream:
    """Iterator of aggregated ``BlockRecord`` values with post-completion coverage.

    Yielded records before a late failure are provisional. ``coverage`` is available
    only after successful complete consumption of discoveries and the final block
    replay, and only when spool cleanup also succeeds. Closing the iterator early
    releases the temporary spool.
    """

    def __init__(
        self,
        *,
        discoveries: Iterable[RawDiscovery],
        blocks: BlockReplaySource,
        snapshot: SnapshotLookup,
        limits: ResourceLimits,
        expected_source_identity: str,
        row_cache_size: int,
    ) -> None:
        self._discoveries = discoveries
        self._blocks = blocks
        self._snapshot = snapshot
        self._limits = limits
        self._expected_source_identity = expected_source_identity
        self._row_cache_size = row_cache_size
        self._coverage: AggregationCoverage | None = None
        self._started = False
        self._iterator: Iterator[BlockRecord] | None = None

    @property
    def coverage(self) -> AggregationCoverage:
        if self._coverage is None:
            raise DictionaryAggregationError(
                "AGGREGATION_INCOMPLETE",
                "aggregation coverage is available only after complete successful consumption",
            )
        return self._coverage

    def __iter__(self) -> Iterator[BlockRecord]:
        if self._started:
            raise DictionaryAggregationError(
                "AGGREGATION_REUSED",
                "aggregated block stream can be consumed only once",
            )
        self._started = True
        self._iterator = self._run()
        return self._iterator

    def close(self) -> None:
        iterator = self._iterator
        self._iterator = None
        if iterator is not None:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    def _run(self) -> Iterator[BlockRecord]:
        spool_dir: tempfile.TemporaryDirectory[str] | None = None
        connection: sqlite3.Connection | None = None
        primary_error: BaseException | None = None
        try:
            try:
                spool_dir = tempfile.TemporaryDirectory(prefix="batchlens-l08-spool-")
                db_path = Path(spool_dir.name) / "discoveries.sqlite"
                connection = _open_spool(db_path)
            except OSError as exc:
                raise DictionaryAggregationError(
                    "SPOOL_WRITE_FAILED",
                    _bounded_message(f"failed to create aggregation spool: {exc}"),
                ) from exc

            try:
                discoveries_consumed = _ingest_discoveries(
                    connection,
                    self._discoveries,
                    self._snapshot,
                    self._limits,
                    row_cache_size=self._row_cache_size,
                )
            except BaseException:
                _close_upstream(self._discoveries)
                raise

            blocks_emitted = 0
            occurrence_count = 0
            candidate_count = 0
            try:
                for block in self._blocks.iter_blocks():
                    record, occ_n, cand_n = _build_block_record(
                        connection,
                        block,
                        self._snapshot,
                        self._limits,
                        row_cache_size=self._row_cache_size,
                    )
                    blocks_emitted += 1
                    occurrence_count += occ_n
                    candidate_count += cand_n
                    yield record
            except DictionaryMatchError as exc:
                raise DictionaryAggregationError(exc.code, exc.message) from exc
            except DictionaryAggregationError:
                raise
            except OSError as exc:
                raise DictionaryAggregationError(
                    "BLOCK_READ_FAILED",
                    _bounded_message(f"block replay failed: {exc}"),
                ) from exc

            _require_all_hits_consumed(connection)

            try:
                source_identity = self._blocks.source_identity
            except DictionaryMatchError as exc:
                raise DictionaryAggregationError(exc.code, exc.message) from exc
            if source_identity != self._expected_source_identity:
                raise DictionaryAggregationError(
                    "REPLAY_IDENTITY_CHANGED",
                    "block replay identity does not match the expected L07 document identity",
                )

            coverage = AggregationCoverage(
                blocks_emitted=blocks_emitted,
                dictionary_occurrences=occurrence_count,
                candidates=candidate_count,
                discoveries_consumed=discoveries_consumed,
                source_identity=source_identity,
            )
            cleanup_error = _release_spool(connection, spool_dir)
            connection = None
            spool_dir = None
            if cleanup_error is not None:
                raise cleanup_error
            self._coverage = coverage
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            leftover = _release_spool(connection, spool_dir)
            if leftover is not None:
                self._coverage = None
                if primary_error is None:
                    raise leftover
                # Preserve the original failure; cleanup failure is not claimed as success.


def iter_aggregated_block_records(
    discoveries: Iterable[RawDiscovery],
    blocks: BlockReplaySource,
    snapshot: SnapshotLookup,
    limits: ResourceLimits,
    *,
    expected_source_identity: str | None = None,
    row_cache_size: int = _DEFAULT_ROW_CACHE,
) -> AggregatedBlockStream:
    """Aggregate dictionary raw discoveries into document-ordered block records.

    Only dictionary components are accepted. Unit discoveries must not be passed
    here. ``expected_source_identity`` is required and must equal the pinned L07
    document identity after replay. The returned stream yields provisional
    ``BlockRecord`` values; call ``coverage`` only after the iterator is fully
    consumed without error. Temporary spool files are deleted on normal
    completion, early close, or failure; coverage is not set when cleanup fails.
    """

    if row_cache_size < 1:
        raise DictionaryAggregationError(
            "INVALID_LIMIT",
            "row_cache_size must be a positive integer",
        )
    if expected_source_identity is None or expected_source_identity == "":
        raise DictionaryAggregationError(
            "SOURCE_IDENTITY_REQUIRED",
            "aggregation requires an explicit pinned L07 source identity",
        )
    try:
        _ = snapshot.identity
    except SnapshotReadError as exc:
        raise DictionaryAggregationError(exc.code, _bounded_message(exc.message)) from exc
    return AggregatedBlockStream(
        discoveries=discoveries,
        blocks=blocks,
        snapshot=snapshot,
        limits=limits,
        expected_source_identity=expected_source_identity,
        row_cache_size=row_cache_size,
    )


def _open_spool(path: Path) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        # Keep SQLite temp/spill on disk so large sorts do not escape process bounds
        # via an in-memory temp store.
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(
            """
            CREATE TABLE discoveries (
                id INTEGER PRIMARY KEY,
                block_node_id TEXT NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                matched_text TEXT NOT NULL,
                method TEXT NOT NULL,
                dictionary_term TEXT NOT NULL,
                component TEXT NOT NULL,
                term_role TEXT NOT NULL,
                source_table TEXT NOT NULL,
                source_field TEXT NOT NULL,
                row_id TEXT NOT NULL,
                lexical_term_id TEXT,
                snapshot_id TEXT NOT NULL,
                edit_distance INTEGER,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX discoveries_block_span
            ON discoveries (block_node_id, start_char, end_char, matched_text)
            """
        )
        connection.execute(
            """
            CREATE TABLE block_hit_counts (
                block_node_id TEXT PRIMARY KEY,
                hit_count INTEGER NOT NULL
            )
            """
        )
        connection.commit()
    except sqlite3.Error as exc:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        raise DictionaryAggregationError(
            "SPOOL_WRITE_FAILED",
            _bounded_message(f"failed to initialize aggregation spool: {exc}"),
        ) from exc
    return connection


def _release_spool(
    connection: sqlite3.Connection | None,
    spool_dir: tempfile.TemporaryDirectory[str] | None,
) -> DictionaryAggregationError | None:
    """Close the spool connection then delete the temp directory.

    Connection close precedes directory cleanup so Windows file locks do not
    leave the directory behind. Returns a bounded error when cleanup fails;
    does not claim deletion succeeded when it did not.
    """

    close_error: Exception | None = None
    cleanup_error: Exception | None = None
    if connection is not None:
        try:
            connection.close()
        except Exception as exc:  # noqa: BLE001 - report any close failure honestly
            close_error = exc
    if spool_dir is not None:
        try:
            spool_dir.cleanup()
        except Exception as exc:  # noqa: BLE001 - report any cleanup failure honestly
            cleanup_error = exc
    if close_error is None and cleanup_error is None:
        return None
    parts: list[str] = []
    if close_error is not None:
        parts.append(f"connection close failed: {close_error}")
    if cleanup_error is not None:
        parts.append(f"temporary spool deletion failed: {cleanup_error}")
    return DictionaryAggregationError(
        "SPOOL_CLEANUP_FAILED",
        _bounded_message("; ".join(parts)),
    )


def _close_upstream(discoveries: Iterable[RawDiscovery]) -> None:
    """Release a closable upstream discovery iterator without masking callers."""

    close = getattr(discoveries, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return


def _ingest_discoveries(
    connection: sqlite3.Connection,
    discoveries: Iterable[RawDiscovery],
    snapshot: SnapshotLookup,
    limits: ResourceLimits,
    *,
    row_cache_size: int,
) -> int:
    cache: dict[tuple[str, str], SourceRow | None] = {}
    consumed = 0
    snapshot_id = snapshot.identity.snapshot_id
    try:
        for discovery in discoveries:
            consumed += 1
            if discovery.component not in _DICTIONARY_COMPONENTS:
                raise DictionaryAggregationError(
                    "UNEXPECTED_UNIT_DISCOVERY",
                    "dictionary aggregation rejects unit or non-dictionary raw discoveries",
                )
            if discovery.snapshot_id is None or discovery.snapshot_id != snapshot_id:
                raise DictionaryAggregationError(
                    "SNAPSHOT_IDENTITY_MISMATCH",
                    "raw discovery snapshot identity does not match the open knowledge snapshot",
                )
            _require_block_capacity(connection, discovery.block_node_id, limits)
            term = _require_matching_term(discovery, snapshot, cache, row_cache_size=row_cache_size)
            edit_distance = _validated_edit_distance(discovery, term)
            try:
                connection.execute(
                    """
                    INSERT INTO discoveries (
                        block_node_id, start_char, end_char, matched_text, method,
                        dictionary_term, component, term_role, source_table, source_field,
                        row_id, lexical_term_id, snapshot_id, edit_distance, consumed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        discovery.block_node_id,
                        discovery.span.start_char,
                        discovery.span.end_char,
                        discovery.span.matched_text,
                        discovery.method,
                        discovery.dictionary_term,
                        discovery.component.value,
                        discovery.term_role,
                        discovery.source_table,
                        discovery.source_field,
                        discovery.row_id,
                        discovery.lexical_term_id,
                        discovery.snapshot_id,
                        edit_distance,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO block_hit_counts (block_node_id, hit_count)
                    VALUES (?, 1)
                    ON CONFLICT(block_node_id) DO UPDATE SET
                        hit_count = hit_count + 1
                    """,
                    (discovery.block_node_id,),
                )
            except sqlite3.Error as exc:
                _rollback_spool(connection)
                raise DictionaryAggregationError(
                    "SPOOL_WRITE_FAILED",
                    _bounded_message(f"failed to write discovery to spool: {exc}"),
                ) from exc
        try:
            connection.commit()
        except sqlite3.Error as exc:
            _rollback_spool(connection)
            raise DictionaryAggregationError(
                "SPOOL_WRITE_FAILED",
                _bounded_message(f"failed to commit aggregation spool: {exc}"),
            ) from exc
    except DictionaryAggregationError:
        _rollback_spool(connection)
        raise
    except SnapshotReadError as exc:
        _rollback_spool(connection)
        raise DictionaryAggregationError(exc.code, _bounded_message(exc.message)) from exc
    except FieldMappingError as exc:
        _rollback_spool(connection)
        raise DictionaryAggregationError(exc.code, exc.message) from exc
    except OSError as exc:
        _rollback_spool(connection)
        raise DictionaryAggregationError(
            "SPOOL_WRITE_FAILED",
            _bounded_message(f"spool write failed: {exc}"),
        ) from exc
    return consumed


def _rollback_spool(connection: sqlite3.Connection) -> None:
    """Best-effort rollback so discovery rows and block counters stay aligned."""

    try:
        connection.rollback()
    except sqlite3.Error:
        return


def _require_block_capacity(
    connection: sqlite3.Connection,
    block_node_id: str,
    limits: ResourceLimits,
) -> None:
    """Enforce per-block capacity via the disk-backed counter table.

    Looks up one primary-key counter row. Does not repeatedly ``COUNT(*)`` the
    discoveries table. ``_load_block_hits`` keeps ``LIMIT result_buffer_records + 1``
    as a defensive read guard.
    """

    try:
        row = connection.execute(
            "SELECT hit_count FROM block_hit_counts WHERE block_node_id = ?",
            (block_node_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise DictionaryAggregationError(
            "SPOOL_READ_FAILED",
            _bounded_message(f"failed to read block discovery counter: {exc}"),
        ) from exc
    count = int(row[0]) if row is not None else 0
    if count >= limits.result_buffer_records:
        raise DictionaryAggregationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "per-block discovery count exceeds result_buffer_records",
        )


def _build_block_record(
    connection: sqlite3.Connection,
    block: BlockEvidence,
    snapshot: SnapshotLookup,
    limits: ResourceLimits,
    *,
    row_cache_size: int,
) -> tuple[BlockRecord, int, int]:
    hits = _load_block_hits(connection, block.node_id, limits)
    if not hits:
        return BlockRecord(block=block, occurrences=()), 0, 0

    by_span: dict[tuple[int, int, str], list[_SpooledHit]] = {}
    for hit in hits:
        key = (hit.start_char, hit.end_char, hit.matched_text)
        by_span.setdefault(key, []).append(hit)

    occurrences: list[DictionaryOccurrence] = []
    candidate_total = 0
    cache: dict[tuple[str, str], SourceRow | None] = {}
    for start, end, matched_text in sorted(by_span, key=lambda item: (item[0], item[1], item[2])):
        span_hits = by_span[(start, end, matched_text)]
        occurrence, cand_n = _build_occurrence(
            block=block,
            location=CharSpan(start_char=start, end_char=end, matched_text=matched_text),
            hits=span_hits,
            snapshot=snapshot,
            limits=limits,
            cache=cache,
            row_cache_size=row_cache_size,
        )
        occurrences.append(occurrence)
        candidate_total += cand_n
    record = BlockRecord(block=block, occurrences=tuple(occurrences))
    return record, len(occurrences), candidate_total


def _load_block_hits(
    connection: sqlite3.Connection,
    block_node_id: str,
    limits: ResourceLimits,
) -> list[_SpooledHit]:
    fetch_limit = limits.result_buffer_records + 1
    try:
        rows = connection.execute(
            """
            SELECT method, dictionary_term, component, term_role, source_table, source_field,
                   row_id, lexical_term_id, snapshot_id, start_char, end_char, matched_text,
                   edit_distance
            FROM discoveries
            WHERE block_node_id = ?
            ORDER BY start_char, end_char, matched_text, source_table, source_field, row_id, method
            LIMIT ?
            """,
            (block_node_id, fetch_limit),
        ).fetchall()
    except sqlite3.Error as exc:
        raise DictionaryAggregationError(
            "SPOOL_READ_FAILED",
            _bounded_message(f"failed to read aggregation spool: {exc}"),
        ) from exc
    if len(rows) > limits.result_buffer_records:
        raise DictionaryAggregationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "per-block discovery count exceeds result_buffer_records",
        )
    hits: list[_SpooledHit] = []
    for row in rows:
        method = row[0]
        if method not in _METHOD_RANK:
            raise DictionaryAggregationError(
                "INVALID_SPOOL_RECORD",
                "aggregation spool contains an unsupported match method",
            )
        edit_distance = row[12]
        hits.append(
            _SpooledHit(
                method=method,  # type: ignore[arg-type]
                dictionary_term=row[1],
                component=Component(row[2]),
                term_role=row[3],
                source_table=row[4],
                source_field=row[5],
                row_id=row[6],
                lexical_term_id=row[7],
                snapshot_id=row[8],
                start_char=int(row[9]),
                end_char=int(row[10]),
                matched_text=row[11],
                edit_distance=None if edit_distance is None else int(edit_distance),
            )
        )
    if hits:
        try:
            connection.execute(
                "UPDATE discoveries SET consumed = 1 WHERE block_node_id = ?",
                (block_node_id,),
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise DictionaryAggregationError(
                "SPOOL_WRITE_FAILED",
                _bounded_message(f"failed to mark spool hits consumed: {exc}"),
            ) from exc
    return hits


def _require_all_hits_consumed(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute("SELECT COUNT(*) FROM discoveries WHERE consumed = 0").fetchone()
    except sqlite3.Error as exc:
        raise DictionaryAggregationError(
            "SPOOL_READ_FAILED",
            _bounded_message(f"failed to verify spool consumption: {exc}"),
        ) from exc
    remaining = int(row[0]) if row is not None else 0
    if remaining > 0:
        raise DictionaryAggregationError(
            "UNMATCHED_SPOOL_HITS",
            "spooled discoveries remain for blocks that were not emitted during replay",
        )


def _build_occurrence(
    *,
    block: BlockEvidence,
    location: CharSpan,
    hits: Sequence[_SpooledHit],
    snapshot: SnapshotLookup,
    limits: ResourceLimits,
    cache: dict[tuple[str, str], SourceRow | None],
    row_cache_size: int,
) -> tuple[DictionaryOccurrence, int]:
    # Deduplicate repeated source references at this span; exact wins.
    best_by_ref: dict[tuple[str, str, str, str, str, str | None], _SpooledHit] = {}
    for hit in hits:
        ref_key = (
            hit.source_table,
            hit.source_field,
            hit.row_id,
            hit.component.value,
            hit.term_role,
            hit.lexical_term_id,
        )
        current = best_by_ref.get(ref_key)
        if current is None or _METHOD_RANK[hit.method] < _METHOD_RANK[current.method]:
            best_by_ref[ref_key] = hit

    groups: dict[tuple[object, ...], _GroupState] = {}
    for hit in best_by_ref.values():
        term = _require_matching_term_from_hit(hit, snapshot, cache, row_cache_size=row_cache_size)
        if hit.method == "fuzzy":
            _require_fuzzy_span_against_block(block=block, location=location, term=term)
        key = _interpretation_key(term, hit.dictionary_term)
        group = groups.get(key)
        if group is None:
            groups[key] = _GroupState(
                method=hit.method,
                term=term,
                row_ids={hit.row_id},
                edit_distance=hit.edit_distance,
            )
        else:
            group.row_ids.add(hit.row_id)
            if _METHOD_RANK[hit.method] < _METHOD_RANK[group.method]:
                group.method = hit.method
                group.term = term
                group.edit_distance = hit.edit_distance

    if len(groups) > limits.result_buffer_records:
        raise DictionaryAggregationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "per-span candidate group count exceeds result_buffer_records",
        )

    candidates: list[LexicalCandidate] = []
    applies: set[Component] = set()
    for key in sorted(groups, key=_candidate_sort_key):
        group = groups[key]
        ordered_ids = tuple(sorted(group.row_ids))
        representative = ordered_ids[0]
        supporting = ordered_ids[1:]
        evidence = _evidence_for(
            group.method,
            dictionary_term=group.term.literal,
            edit_distance=group.edit_distance,
        )
        if group.method == "exact" and group.term.literal != location.matched_text:
            raise DictionaryAggregationError(
                "EXACT_EVIDENCE_MISMATCH",
                "exact evidence requires the dictionary term to equal the span text",
            )
        candidate = _build_candidate(
            group.term,
            matched_term=group.term.literal,
            row_id=representative,
            supporting_row_ids=supporting,
            evidence=evidence,
        )
        candidates.append(candidate)
        applies.add(group.term.component)

    applies_to = tuple(component for component in _COMPONENT_ORDER if component in applies)
    occurrence_id = _occurrence_id(block.node_id, location, applies_to, candidates)
    occurrence = DictionaryOccurrence(
        occurrence_id=occurrence_id,
        block_node_id=block.node_id,
        location=location,
        applies_to=applies_to,
        candidates=tuple(candidates),
    )
    return occurrence, len(candidates)


def _require_matching_term(
    discovery: RawDiscovery,
    snapshot: SnapshotLookup,
    cache: dict[tuple[str, str], SourceRow | None],
    *,
    row_cache_size: int,
) -> EligibleSearchTerm:
    hit = _SpooledHit(
        method=discovery.method,
        dictionary_term=discovery.dictionary_term,
        component=discovery.component,
        term_role=discovery.term_role,
        source_table=discovery.source_table,
        source_field=discovery.source_field,
        row_id=discovery.row_id,
        lexical_term_id=discovery.lexical_term_id,
        snapshot_id=discovery.snapshot_id or "",
        start_char=discovery.span.start_char,
        end_char=discovery.span.end_char,
        matched_text=discovery.span.matched_text,
        edit_distance=discovery.edit_distance,
    )
    return _require_matching_term_from_hit(hit, snapshot, cache, row_cache_size=row_cache_size)


def _validated_edit_distance(
    discovery: RawDiscovery,
    term: EligibleSearchTerm,
) -> int | None:
    """Validate fuzzy claims; return stored distance or ``None`` for non-fuzzy."""

    if discovery.method != "fuzzy":
        if discovery.edit_distance is not None:
            raise DictionaryAggregationError(
                "INVALID_FUZZY_DISCOVERY",
                "non-fuzzy raw discoveries must not carry edit_distance",
            )
        return None
    # Booleans are subclasses of int; require an exact integer 1.
    if (
        type(discovery.edit_distance) is not int
        or discovery.edit_distance != FUZZY_MAX_EDIT_DISTANCE
    ):
        raise DictionaryAggregationError(
            "INVALID_FUZZY_DISCOVERY",
            "fuzzy raw discoveries require edit_distance equal to the integer 1",
        )
    if discovery.rule_id != FUZZY_RULE_ID:
        raise DictionaryAggregationError(
            "INVALID_FUZZY_DISCOVERY",
            "fuzzy raw discoveries require the fixed lexical-v1-fuzzy rule id",
        )
    if not term.fuzzy_allowed or not fuzzy_role_policy_eligible(
        term_role=term.term_role,
        match_policy=term.match_policy,
    ):
        raise DictionaryAggregationError(
            "FUZZY_NOT_ELIGIBLE",
            "fuzzy claim rejected because the source term is not fuzzy-eligible",
        )
    if not is_fuzzy_index_eligible(
        fuzzy_allowed=True,
        term_role=term.term_role,
        comparison_key=discovery.dictionary_term,
        match_policy=term.match_policy,
    ):
        # Dictionary term must still satisfy the fixed single-word alphabetic shape.
        raise DictionaryAggregationError(
            "FUZZY_NOT_ELIGIBLE",
            "fuzzy claim rejected because the dictionary term fails the V1 shape gate",
        )
    try:
        source_surface = normalize_literal(
            discovery.dictionary_term,
            term_role=term.term_role,
            boundary_hint=term.boundary_hint,
            strip_edges=True,
        )
        # Do not strip edges of the claimed span: leading/trailing whitespace inside
        # matched_text must keep the observed comparison from being one alphabetic word.
        observed_surface = normalize_literal(
            discovery.span.matched_text,
            term_role=term.term_role,
            boundary_hint=term.boundary_hint,
            strip_edges=False,
        )
    except ComparisonError as exc:
        raise DictionaryAggregationError(
            "FUZZY_OBSERVED_NOT_WORD",
            "fuzzy claim failed L06 normalization of the observed span or source term",
        ) from exc
    source_key = source_surface.comparison_text
    observed_key = observed_surface.comparison_text
    if not observed_key or observed_key[0].isspace() or observed_key[-1].isspace():
        raise DictionaryAggregationError(
            "FUZZY_OBSERVED_NOT_WORD",
            "fuzzy claim rejects leading or trailing whitespace inside the observed span",
        )
    min_observed = FUZZY_MIN_WORD_LENGTH - FUZZY_MAX_EDIT_DISTANCE
    if (
        not observed_key.isalpha()
        or abs(len(observed_key) - len(source_key)) > FUZZY_MAX_EDIT_DISTANCE
        or len(observed_key) < min_observed
    ):
        raise DictionaryAggregationError(
            "FUZZY_OBSERVED_NOT_WORD",
            "fuzzy claim requires one alphabetic observed word within one-edit length",
        )
    distance = ordinary_levenshtein(
        observed_key,
        source_key,
        limit=FUZZY_MAX_EDIT_DISTANCE,
    )
    if distance != FUZZY_MAX_EDIT_DISTANCE:
        raise DictionaryAggregationError(
            "FUZZY_DISTANCE_MISMATCH",
            "fuzzy claim failed recomputed ordinary Levenshtein distance-1 verification",
        )
    return FUZZY_MAX_EDIT_DISTANCE


def _require_fuzzy_span_against_block(
    *,
    block: BlockEvidence,
    location: CharSpan,
    term: EligibleSearchTerm,
) -> None:
    """Reject fuzzy spans that fail literal slice equality or L06 boundaries."""

    try:
        validate_match_against_block(location, block)
    except ValueError as exc:
        raise DictionaryAggregationError(
            "FUZZY_SPAN_MISMATCH",
            "fuzzy span failed literal block slice equality during aggregation replay",
        ) from exc
    if not respects_boundary(
        block.text,
        location.start_char,
        location.end_char,
        boundary_hint=term.boundary_hint,
    ):
        raise DictionaryAggregationError(
            "FUZZY_BOUNDARY_REJECTED",
            "fuzzy span fails the source term's fixed L06 boundary against the block",
        )


def _require_matching_term_from_hit(
    hit: _SpooledHit,
    snapshot: SnapshotLookup,
    cache: dict[tuple[str, str], SourceRow | None],
    *,
    row_cache_size: int,
) -> EligibleSearchTerm:
    row = _cached_lookup(
        snapshot, hit.source_table, hit.row_id, cache, row_cache_size=row_cache_size
    )
    if row is None:
        raise DictionaryAggregationError(
            "SOURCE_ROW_ABSENT",
            "knowledge snapshot lookup returned no row for a raw discovery reference",
        )
    try:
        terms = map_source_row(
            row,
            components=(hit.component,),
            snapshot_id=snapshot.identity.snapshot_id,
        )
    except FieldMappingError as exc:
        raise DictionaryAggregationError(exc.code, exc.message) from exc
    matches = [
        term
        for term in terms
        if term.source_table == hit.source_table
        and term.source_field == hit.source_field
        and term.row_id == hit.row_id
        and term.component == hit.component
        and term.term_role == hit.term_role
        and term.literal == hit.dictionary_term
        and term.lexical_term_id == hit.lexical_term_id
        and term.snapshot_id == hit.snapshot_id
    ]
    if len(matches) != 1:
        raise DictionaryAggregationError(
            "SOURCE_TERM_MISMATCH",
            "mapped source row does not reproduce the raw discovery term reference",
        )
    return matches[0]


def _cached_lookup(
    snapshot: SnapshotLookup,
    table_name: str,
    row_id: str,
    cache: dict[tuple[str, str], SourceRow | None],
    *,
    row_cache_size: int,
) -> SourceRow | None:
    key = (table_name, row_id)
    if key in cache:
        return cache[key]
    try:
        row = snapshot.lookup(table_name, row_id)
    except SnapshotReadError as exc:
        raise DictionaryAggregationError(exc.code, _bounded_message(exc.message)) from exc
    if len(cache) >= row_cache_size:
        # Finite cache: drop an arbitrary oldest entry without growing unbounded.
        cache.pop(next(iter(cache)))
    cache[key] = row
    return row


def _interpretation_key(term: EligibleSearchTerm, matched_term: str) -> tuple[object, ...]:
    ambiguity = _ambiguity_for(term)
    return (
        term.source_table,
        term.source_field,
        term.component.value,
        term.term_role,
        matched_term,
        term.lexical_term_id,
        term.display_name,
        term.unii,
        term.sms_id,
        term.chebi_id,
        term.alias_type,
        term.source,
        term.source_version,
        term.source_record,
        term.equipment_type_id,
        term.parameter_id,
        term.catalogue_equipment_type_id,
        term.catalogue_equipment_type_label,
        term.source_section,
        term.operation_id,
        term.canonical_unit_operation,
        term.unit_operation_en,
        term.process_step_id,
        term.index_this_row,
        term.match_policy,
        term.record_type,
        term.term_relation,
        term.operation_role,
        term.provenance_source,
        term.supporting_evidence,
        ambiguity.value,
        term.snapshot_id,
    )


def _comparable_sort_item(value: object) -> tuple[int, str]:
    """Deterministic comparable form for optional interpretation-key fields.

    ``None`` sorts before any string. Grouping equality still uses the raw key
    (``None`` versus a string remain distinct groups).
    """

    if value is None:
        return (0, "")
    if isinstance(value, str):
        return (1, value)
    return (2, repr(value))


def _candidate_sort_key(key: tuple[object, ...]) -> tuple[tuple[int, str], ...]:
    return tuple(_comparable_sort_item(item) for item in key)


def _ambiguity_for(term: EligibleSearchTerm) -> AmbiguityQualification:
    if term.alias_type == "hasRelatedSynonym":
        return AmbiguityQualification.CONTEXT_REQUIRED
    if term.match_policy == "context_required":
        return AmbiguityQualification.CONTEXT_REQUIRED
    return AmbiguityQualification.NONE


def _evidence_for(
    method: MatchMethodName,
    *,
    dictionary_term: str,
    edit_distance: int | None,
) -> ExactEvidence | NormalizedExactEvidence | FuzzyEvidence:
    if method == "exact":
        return ExactEvidence(method="exact", rule_id=EXACT_RULE_ID)
    if method == "normalized_exact":
        return NormalizedExactEvidence(
            method="normalized_exact",
            rule_id=NORMALIZED_EXACT_RULE_ID,
        )
    if edit_distance != FUZZY_MAX_EDIT_DISTANCE:
        raise DictionaryAggregationError(
            "INVALID_FUZZY_DISCOVERY",
            "fuzzy evidence requires verified edit_distance equal to one",
        )
    return FuzzyEvidence(
        method="fuzzy",
        rule_id=FUZZY_RULE_ID,
        dictionary_term=dictionary_term,
        edit_distance=edit_distance,
    )


def _build_candidate(
    term: EligibleSearchTerm,
    *,
    matched_term: str,
    row_id: str,
    supporting_row_ids: tuple[str, ...],
    evidence: ExactEvidence | NormalizedExactEvidence | FuzzyEvidence,
) -> LexicalCandidate:
    if term.snapshot_id is None:
        raise DictionaryAggregationError(
            "SNAPSHOT_IDENTITY_MISMATCH",
            "eligible term is missing the required snapshot identity",
        )
    ambiguity = _ambiguity_for(term)
    snapshot_id = term.snapshot_id
    display_name = term.display_name
    if term.source_table == "materials_fda_ema":
        if term.source_field not in {"material_name", "alias_name", "UNII"}:
            raise DictionaryAggregationError(
                "SOURCE_TERM_MISMATCH",
                "FDA/EMA discovery source field is not a permitted material search field",
            )
        source_field: Literal["material_name", "alias_name", "UNII"] = term.source_field  # type: ignore[assignment]
        return FdaEmaMaterialCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            source_field=source_field,
            unii=term.unii,
            sms_id=term.sms_id,
            alias_type=term.alias_type,
            lexical_term_id=term.lexical_term_id,
            source=term.source,
        )
    if term.source_table == "materials_chebi":
        if term.source_field not in {"material_name", "alias_name"}:
            raise DictionaryAggregationError(
                "SOURCE_TERM_MISMATCH",
                "ChEBI discovery source field is not a permitted material search field",
            )
        chebi_field: Literal["material_name", "alias_name"] = term.source_field  # type: ignore[assignment]
        return ChebiMaterialCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            source_field=chebi_field,
            chebi_id=term.chebi_id,
            alias_type=term.alias_type,
            lexical_term_id=term.lexical_term_id,
            source=term.source,
            source_version=term.source_version,
            source_record=term.source_record,
        )
    if term.term_role == "equipment_type":
        return EquipmentTypeCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            equipment_type_id=term.equipment_type_id,
            source_section=term.source_section,
        )
    if term.term_role == "parameter_name":
        return ParameterNameCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            parameter_id=term.parameter_id,
            catalogue_equipment_type_id=term.catalogue_equipment_type_id,
            catalogue_equipment_type_label=term.catalogue_equipment_type_label,
            source_section=term.source_section,
        )
    if term.term_role == "unit_operation":
        return UnitOperationCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            operation_id=term.operation_id,
            canonical_unit_operation=term.canonical_unit_operation,
            unit_operation_en=term.unit_operation_en,
            index_this_row=term.index_this_row,
            match_policy=term.match_policy,
            record_type=term.record_type,
            term_relation=term.term_relation,
            operation_role=term.operation_role,
            lexical_term_id=term.lexical_term_id,
            provenance_source=term.provenance_source,
        )
    if term.term_role == "generic_cue":
        return GenericCueCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            operation_role=term.operation_role,
            match_policy=term.match_policy,
            record_type=term.record_type,
            term_relation=term.term_relation,
            lexical_term_id=term.lexical_term_id,
            provenance_source=term.provenance_source,
        )
    if term.term_role == "process_step":
        return ProcessStepCandidate(
            matched_term=matched_term,
            canonical_display_name=display_name,
            ambiguity=ambiguity,
            snapshot_id=snapshot_id,
            row_id=row_id,
            supporting_row_ids=supporting_row_ids,
            evidence=evidence,
            process_step_id=term.process_step_id,
            lexical_term_id=term.lexical_term_id,
            provenance_source=term.provenance_source,
            supporting_evidence=term.supporting_evidence,
            match_policy=term.match_policy,
            record_type=term.record_type,
            term_relation=term.term_relation,
            operation_role=term.operation_role,
        )
    raise DictionaryAggregationError(
        "SOURCE_TERM_MISMATCH",
        "raw discovery term role cannot be projected to an L01 dictionary candidate",
    )


def _occurrence_id(
    block_node_id: str,
    location: CharSpan,
    applies_to: Sequence[Component],
    candidates: Sequence[LexicalCandidate],
) -> str:
    material = {
        "block_node_id": block_node_id,
        "start_char": location.start_char,
        "end_char": location.end_char,
        "matched_text": location.matched_text,
        "applies_to": [component.value for component in applies_to],
        "candidates": [
            candidate.model_dump(mode="json", exclude={"evidence"}) for candidate in candidates
        ],
    }
    encoded = repr(material).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:32]
    return f"dict-{digest}"


def _bounded_message(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE:
        return message
    keep = _MAX_ERROR_MESSAGE - len(_ELLIPSIS)
    return message[:keep] + _ELLIPSIS
