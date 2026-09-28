"""Bounded unit-mention aggregation from L07 raw discoveries (L10).

Consumes unit-component ``RawDiscovery`` values from L07, regroups them through a
run-local temporary SQLite spool, and emits validated ``UnitOccurrence`` values
inside ``BlockRecord`` streams. This is deliberately separate from L08 dictionary
aggregation: L08 continues to reject unit discoveries with
``UNEXPECTED_UNIT_DISCOVERY``.

Fixed vocabulary terms use ``FixedUnitVocabulary`` provenance. Equipment ``Unit``
rows use ``EquipmentUnitRecord`` with optional ``supporting_row_ids`` when
denormalized catalogue rows repeat the same spelling at one span.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    BlockEvidence,
    BlockRecord,
    CharSpan,
    Component,
    EquipmentUnitRecord,
    ExactEvidence,
    FixedUnitVocabulary,
    NormalizedExactEvidence,
    SafeStructuredError,
    UnitMention,
    UnitOccurrence,
)
from app.lexical_extraction.dictionary_aggregation import SnapshotLookup
from app.lexical_extraction.dictionary_matcher import (
    BlockReplaySource,
    DictionaryMatchError,
    RawDiscovery,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm, map_source_row
from app.lexical_extraction.knowledge_snapshot import SourceRow
from app.lexical_extraction.unit_value_rules import (
    FIXED_UNIT_VOCABULARY_SOURCE_FIELD,
    FIXED_UNIT_VOCABULARY_SOURCE_TABLE,
    controlled_unit_for_casefolded,
    controlled_unit_for_spelling,
    fixed_unit_row_id,
    fixed_unit_spellings,
)

_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200
_ELLIPSIS: Final = "..."
_METHOD_RANK: Final = {"exact": 0, "normalized_exact": 1}
_DEFAULT_ROW_CACHE: Final = 64


class UnitAggregationError(Exception):
    """Bounded unit-aggregation failure mapped to ``SafeStructuredError``."""

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("unit-aggregation error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class UnitAggregationCoverage:
    """Counts available only after successful complete consumption."""

    blocks_emitted: int
    unit_occurrences: int
    discoveries_consumed: int
    source_identity: str


@dataclass(frozen=True)
class _SpooledHit:
    method: Literal["exact", "normalized_exact"]
    dictionary_term: str
    source_table: str
    source_field: str
    row_id: str
    snapshot_id: str
    start_char: int
    end_char: int
    matched_text: str
    source_section: str | None = None


class UnitBlockStream:
    """Iterator of unit ``BlockRecord`` values with post-completion coverage."""

    def __init__(
        self,
        *,
        discoveries: Iterable[RawDiscovery],
        blocks: BlockReplaySource,
        limits: ResourceLimits,
        expected_source_identity: str,
        snapshot: SnapshotLookup | None,
        row_cache_size: int,
    ) -> None:
        self._discoveries = discoveries
        self._blocks = blocks
        self._limits = limits
        self._expected_source_identity = expected_source_identity
        self._snapshot = snapshot
        self._row_cache_size = row_cache_size
        self._coverage: UnitAggregationCoverage | None = None
        self._started = False
        self._iterator: Iterator[BlockRecord] | None = None

    @property
    def coverage(self) -> UnitAggregationCoverage:
        if self._coverage is None:
            raise UnitAggregationError(
                "AGGREGATION_INCOMPLETE",
                "unit aggregation coverage is available only after complete successful consumption",
            )
        return self._coverage

    def __iter__(self) -> Iterator[BlockRecord]:
        if self._started:
            raise UnitAggregationError(
                "AGGREGATION_REUSED",
                "unit block stream can be consumed only once",
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
                spool_dir = tempfile.TemporaryDirectory(prefix="batchlens-l10-unit-spool-")
                db_path = Path(spool_dir.name) / "unit-discoveries.sqlite"
                connection = _open_spool(db_path)
            except OSError as exc:
                raise UnitAggregationError(
                    "SPOOL_WRITE_FAILED",
                    _bounded_message(f"failed to create unit aggregation spool: {exc}"),
                ) from exc

            try:
                discoveries_consumed = _ingest_discoveries(
                    connection,
                    self._discoveries,
                    self._limits,
                    snapshot=self._snapshot,
                    row_cache_size=self._row_cache_size,
                )
            except BaseException:
                _close_upstream(self._discoveries)
                raise

            pinned = self._blocks.source_identity
            if pinned != self._expected_source_identity:
                raise UnitAggregationError(
                    "REPLAY_IDENTITY_CHANGED",
                    "block source identity does not match the expected unit-aggregation identity",
                )

            blocks_emitted = 0
            unit_occurrences = 0
            cache: dict[tuple[str, str], SourceRow | None] = {}
            try:
                for block in self._blocks.iter_blocks():
                    if self._blocks.source_identity != pinned:
                        raise UnitAggregationError(
                            "REPLAY_IDENTITY_CHANGED",
                            "block source identity changed during unit aggregation replay",
                        )
                    record, count = _build_block_record(
                        connection,
                        block,
                        limits=self._limits,
                        snapshot=self._snapshot,
                        cache=cache,
                        row_cache_size=self._row_cache_size,
                    )
                    if count > self._limits.result_buffer_records:
                        raise UnitAggregationError(
                            "RESOURCE_LIMIT_EXCEEDED",
                            "per-block unit occurrence count exceeds result_buffer_records",
                        )
                    blocks_emitted += 1
                    unit_occurrences += count
                    yield record
                _require_all_hits_consumed(connection)
            except GeneratorExit:
                primary_error = GeneratorExit()
                raise
            except BaseException as exc:
                primary_error = exc
                raise
            else:
                coverage = UnitAggregationCoverage(
                    blocks_emitted=blocks_emitted,
                    unit_occurrences=unit_occurrences,
                    discoveries_consumed=discoveries_consumed,
                    source_identity=pinned,
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


def iter_aggregated_unit_block_records(
    discoveries: Iterable[RawDiscovery],
    blocks: BlockReplaySource,
    limits: ResourceLimits,
    *,
    snapshot: SnapshotLookup | None = None,
    expected_source_identity: str | None = None,
    row_cache_size: int = _DEFAULT_ROW_CACHE,
) -> UnitBlockStream:
    """Aggregate unit raw discoveries into per-block ``UnitOccurrence`` records.

    ``snapshot`` is required only when equipment ``Unit`` discoveries need
    ``source_section`` lookup. Fixed vocabulary discoveries do not query the
    snapshot. Discoveries for non-unit components raise ``UNEXPECTED_COMPONENT``.
    """

    if expected_source_identity is not None:
        identity = expected_source_identity
    else:
        identity = blocks.source_identity
    if not identity:
        raise UnitAggregationError(
            "SOURCE_IDENTITY_REQUIRED",
            "unit aggregation requires a non-empty block source identity",
        )
    return UnitBlockStream(
        discoveries=discoveries,
        blocks=blocks,
        limits=limits,
        expected_source_identity=identity,
        snapshot=snapshot,
        row_cache_size=row_cache_size,
    )


def iter_unit_mentions_from_terms(
    unit_terms: Iterable[EligibleSearchTerm],
    blocks: BlockReplaySource,
    limits: ResourceLimits,
    *,
    snapshot: SnapshotLookup | None = None,
    include_fixed_vocabulary: bool = True,
    expected_source_identity: str | None = None,
) -> UnitBlockStream:
    """Run L07 on unit terms (plus optional fixed vocabulary) and aggregate mentions.

    ``unit_terms`` is streamed into L07 without an intermediate unbounded list.
    Fixed vocabulary terms are a finite tuple chained after the caller stream.
    """

    from itertools import chain

    terms: Iterable[EligibleSearchTerm]
    if include_fixed_vocabulary:
        terms = chain(unit_terms, fixed_vocabulary_unit_terms())
    else:
        terms = unit_terms
    discoveries = iter_raw_discoveries(terms, blocks, limits)
    identity = expected_source_identity
    if identity is None:
        try:
            identity = blocks.source_identity
        except DictionaryMatchError as exc:
            if exc.code != "REPLAY_IDENTITY_UNPINNED":
                raise
            identity = None
    return iter_aggregated_unit_block_records(
        discoveries,
        blocks,
        limits,
        snapshot=snapshot,
        expected_source_identity=identity,
    )


def fixed_vocabulary_unit_terms() -> tuple[EligibleSearchTerm, ...]:
    """Eligible search terms for the fixed quantity-unit vocabulary."""

    terms: list[EligibleSearchTerm] = []
    for spelling in fixed_unit_spellings():
        entry = controlled_unit_for_spelling(spelling)
        if entry is None:
            continue
        terms.append(
            EligibleSearchTerm(
                literal=spelling,
                component=Component.UNITS,
                term_role="unit_spelling",
                source_table=FIXED_UNIT_VOCABULARY_SOURCE_TABLE,
                source_field=FIXED_UNIT_VOCABULARY_SOURCE_FIELD,
                row_id=fixed_unit_row_id(entry.controlled_identity),
                boundary_hint="atomic_unit",
                fuzzy_allowed=False,
                display_name=entry.controlled_spelling,
            )
        )
    return tuple(terms)


def _open_spool(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA temp_store=MEMORY")
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
                source_table TEXT NOT NULL,
                source_field TEXT NOT NULL,
                row_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
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
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def _release_spool(
    connection: sqlite3.Connection | None,
    spool_dir: tempfile.TemporaryDirectory[str] | None,
) -> UnitAggregationError | None:
    """Close the spool connection then delete the temp directory.

    Returns a bounded error when cleanup fails; does not claim deletion
    succeeded when it did not. Coverage must not be set when this returns
    an error after an otherwise successful run.
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
    return UnitAggregationError(
        "SPOOL_CLEANUP_FAILED",
        _bounded_message("; ".join(parts)),
    )


def _close_upstream(discoveries: Iterable[RawDiscovery]) -> None:
    close = getattr(discoveries, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return


def _ingest_discoveries(
    connection: sqlite3.Connection,
    discoveries: Iterable[RawDiscovery],
    limits: ResourceLimits,
    *,
    snapshot: SnapshotLookup | None,
    row_cache_size: int,
) -> int:
    consumed = 0
    try:
        for discovery in discoveries:
            consumed += 1
            if discovery.component is not Component.UNITS:
                raise UnitAggregationError(
                    "UNEXPECTED_COMPONENT",
                    "unit aggregation accepts only units-component raw discoveries",
                )
            _require_block_capacity(connection, discovery.block_node_id, limits)
            if discovery.source_table == FIXED_UNIT_VOCABULARY_SOURCE_TABLE:
                entry = controlled_unit_for_spelling(discovery.dictionary_term)
                expected_row = (
                    None if entry is None else fixed_unit_row_id(entry.controlled_identity)
                )
                if entry is None or discovery.row_id != expected_row:
                    raise UnitAggregationError(
                        "FIXED_VOCABULARY_MISMATCH",
                        "fixed unit discovery does not match the versioned vocabulary entry",
                    )
            elif discovery.source_table == "equipment" and discovery.source_field == "Unit":
                if snapshot is None:
                    raise UnitAggregationError(
                        "SNAPSHOT_REQUIRED",
                        "equipment unit discoveries require an open knowledge snapshot",
                    )
                _require_equipment_unit_term(discovery, snapshot, row_cache_size=row_cache_size)
            else:
                raise UnitAggregationError(
                    "UNEXPECTED_UNIT_SOURCE",
                    "unit discovery source must be fixed vocabulary or equipment.Unit",
                )
            try:
                connection.execute(
                    """
                    INSERT INTO discoveries (
                        block_node_id, start_char, end_char, matched_text, method,
                        dictionary_term, source_table, source_field, row_id, snapshot_id, consumed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        discovery.block_node_id,
                        discovery.span.start_char,
                        discovery.span.end_char,
                        discovery.span.matched_text,
                        discovery.method,
                        discovery.dictionary_term,
                        discovery.source_table,
                        discovery.source_field,
                        discovery.row_id,
                        discovery.snapshot_id or "",
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
                _rollback(connection)
                raise UnitAggregationError(
                    "SPOOL_WRITE_FAILED",
                    _bounded_message(f"failed to write unit discovery to spool: {exc}"),
                ) from exc
        try:
            connection.commit()
        except sqlite3.Error as exc:
            _rollback(connection)
            raise UnitAggregationError(
                "SPOOL_WRITE_FAILED",
                _bounded_message(f"failed to commit unit aggregation spool: {exc}"),
            ) from exc
    except UnitAggregationError:
        raise
    except DictionaryMatchError as exc:
        raise UnitAggregationError(exc.code, exc.message) from exc
    return consumed


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        return


def _require_block_capacity(
    connection: sqlite3.Connection,
    block_node_id: str,
    limits: ResourceLimits,
) -> None:
    row = connection.execute(
        "SELECT hit_count FROM block_hit_counts WHERE block_node_id = ?",
        (block_node_id,),
    ).fetchone()
    current = int(row[0]) if row is not None else 0
    if current >= limits.result_buffer_records:
        raise UnitAggregationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "per-block unit discovery count exceeds result_buffer_records",
        )


def _require_equipment_unit_term(
    discovery: RawDiscovery,
    snapshot: SnapshotLookup,
    *,
    row_cache_size: int,
) -> None:
    del row_cache_size  # reserved for caller-level caches; lookup is direct here
    if discovery.snapshot_id is None or discovery.snapshot_id != snapshot.identity.snapshot_id:
        raise UnitAggregationError(
            "SNAPSHOT_IDENTITY_MISMATCH",
            "equipment unit discovery snapshot identity does not match the open snapshot",
        )
    row = snapshot.lookup(discovery.source_table, discovery.row_id)
    if row is None:
        raise UnitAggregationError(
            "SOURCE_ROW_ABSENT",
            "equipment unit discovery row_id is absent from the open snapshot",
        )
    terms = map_source_row(
        row,
        components=(Component.UNITS,),
        snapshot_id=snapshot.identity.snapshot_id,
    )
    matched = [
        term
        for term in terms
        if term.source_field == discovery.source_field
        and term.row_id == discovery.row_id
        and term.literal == discovery.dictionary_term
    ]
    if not matched:
        raise UnitAggregationError(
            "SOURCE_TERM_MISMATCH",
            "equipment unit discovery does not match the mapped source Unit cell",
        )


def _build_block_record(
    connection: sqlite3.Connection,
    block: BlockEvidence,
    *,
    limits: ResourceLimits,
    snapshot: SnapshotLookup | None,
    cache: dict[tuple[str, str], SourceRow | None],
    row_cache_size: int,
) -> tuple[BlockRecord, int]:
    hits = _load_block_hits(connection, block, limits=limits)
    if not hits:
        return BlockRecord(block=block, occurrences=()), 0

    grouped: dict[tuple[int, int, str], list[_SpooledHit]] = {}
    for hit in hits:
        key = (hit.start_char, hit.end_char, hit.matched_text)
        grouped.setdefault(key, []).append(hit)

    occurrences: list[UnitOccurrence] = []
    for (start, end, matched_text), span_hits in sorted(grouped.items()):
        location = CharSpan(start_char=start, end_char=end, matched_text=matched_text)
        mention = _build_mention(
            location,
            span_hits,
            snapshot=snapshot,
            cache=cache,
            row_cache_size=row_cache_size,
        )
        occurrence_id = _occurrence_id(block.node_id, location, mention)
        occurrences.append(
            UnitOccurrence(
                occurrence_id=occurrence_id,
                block_node_id=block.node_id,
                mention=mention,
            )
        )
    return BlockRecord(block=block, occurrences=tuple(occurrences)), len(occurrences)


def _load_block_hits(
    connection: sqlite3.Connection,
    block: BlockEvidence,
    *,
    limits: ResourceLimits,
) -> list[_SpooledHit]:
    try:
        rows = connection.execute(
            """
            SELECT
                method, dictionary_term, source_table, source_field, row_id, snapshot_id,
                start_char, end_char, matched_text, id
            FROM discoveries
            WHERE block_node_id = ? AND consumed = 0
            ORDER BY start_char, end_char, id
            LIMIT ?
            """,
            (block.node_id, limits.result_buffer_records + 1),
        ).fetchall()
    except sqlite3.Error as exc:
        raise UnitAggregationError(
            "SPOOL_READ_FAILED",
            _bounded_message(f"failed to read unit discoveries from spool: {exc}"),
        ) from exc
    if len(rows) > limits.result_buffer_records:
        raise UnitAggregationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "per-block unit discovery count exceeds result_buffer_records",
        )
    hits: list[_SpooledHit] = []
    ids: list[int] = []
    for row in rows:
        ids.append(int(row[9]))
        hits.append(
            _SpooledHit(
                method=row[0],
                dictionary_term=row[1],
                source_table=row[2],
                source_field=row[3],
                row_id=row[4],
                snapshot_id=row[5],
                start_char=int(row[6]),
                end_char=int(row[7]),
                matched_text=row[8],
            )
        )
    if ids:
        try:
            connection.executemany(
                "UPDATE discoveries SET consumed = 1 WHERE id = ?",
                [(item,) for item in ids],
            )
            connection.commit()
        except sqlite3.Error as exc:
            _rollback(connection)
            raise UnitAggregationError(
                "SPOOL_WRITE_FAILED",
                _bounded_message(f"failed to mark unit discoveries consumed: {exc}"),
            ) from exc
    return hits


def _require_all_hits_consumed(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute("SELECT COUNT(*) FROM discoveries WHERE consumed = 0").fetchone()
    except sqlite3.Error as exc:
        raise UnitAggregationError(
            "SPOOL_READ_FAILED",
            _bounded_message(f"failed to verify unit spool consumption: {exc}"),
        ) from exc
    remaining = int(row[0]) if row is not None else 0
    if remaining > 0:
        raise UnitAggregationError(
            "UNMATCHED_SPOOL_HITS",
            "spooled unit discoveries remain for blocks that were not emitted during replay",
        )


def _build_mention(
    location: CharSpan,
    hits: Sequence[_SpooledHit],
    *,
    snapshot: SnapshotLookup | None,
    cache: dict[tuple[str, str], SourceRow | None],
    row_cache_size: int,
) -> UnitMention:
    best_by_ref: dict[tuple[str, str, str], _SpooledHit] = {}
    for hit in hits:
        ref_key = (hit.source_table, hit.source_field, hit.row_id)
        current = best_by_ref.get(ref_key)
        if current is None or _METHOD_RANK[hit.method] < _METHOD_RANK[current.method]:
            best_by_ref[ref_key] = hit

    methods = {hit.method for hit in best_by_ref.values()}
    method: Literal["exact", "normalized_exact"] = (
        "exact" if "exact" in methods else "normalized_exact"
    )
    evidence = ExactEvidence() if method == "exact" else NormalizedExactEvidence()
    # Exact evidence is validated only against exact hits. A co-located
    # normalized-exact alternative (for example case-folded equipment spelling)
    # must not invalidate an otherwise exact fixed-vocabulary hit.
    if method == "exact":
        exact_hits = [hit for hit in best_by_ref.values() if hit.method == "exact"]
        if any(hit.dictionary_term != location.matched_text for hit in exact_hits):
            raise UnitAggregationError(
                "EXACT_EVIDENCE_MISMATCH",
                "exact unit evidence requires the dictionary term to equal the span text",
            )

    fixed_hits = [
        hit
        for hit in best_by_ref.values()
        if hit.source_table == FIXED_UNIT_VOCABULARY_SOURCE_TABLE
    ]
    equipment_hits = [
        hit
        for hit in best_by_ref.values()
        if hit.source_table == "equipment" and hit.source_field == "Unit"
    ]
    if len(fixed_hits) + len(equipment_hits) != len(best_by_ref):
        raise UnitAggregationError(
            "UNEXPECTED_UNIT_SOURCE",
            "unit mention references an unsupported source table or field",
        )

    controlled_spelling: str | None = None
    controlled_identity: str | None = None
    provenance: FixedUnitVocabulary | EquipmentUnitRecord | None = None

    if fixed_hits:
        entry = controlled_unit_for_spelling(fixed_hits[0].dictionary_term)
        if entry is None:
            raise UnitAggregationError(
                "FIXED_VOCABULARY_MISMATCH",
                "fixed unit mention does not match the versioned vocabulary entry",
            )
        controlled_spelling = entry.controlled_spelling
        controlled_identity = entry.controlled_identity

    if equipment_hits:
        ordered_ids = tuple(sorted({hit.row_id for hit in equipment_hits}))
        representative = ordered_ids[0]
        supporting = ordered_ids[1:]
        representative_hit = next(hit for hit in equipment_hits if hit.row_id == representative)
        source_section = _source_section_for(
            representative_hit,
            snapshot=snapshot,
            cache=cache,
            row_cache_size=row_cache_size,
        )
        provenance = EquipmentUnitRecord(
            row_id=representative,
            supporting_row_ids=supporting,
            source_section=source_section,
        )
        if controlled_identity is None:
            # Equipment-only hit may still share a fixed vocabulary identity.
            fixed = controlled_unit_for_casefolded(location.matched_text)
            if fixed is not None:
                controlled_spelling = fixed.controlled_spelling
                controlled_identity = fixed.controlled_identity
    elif fixed_hits:
        provenance = FixedUnitVocabulary()

    return UnitMention(
        literal_text=location.matched_text,
        span=location,
        controlled_spelling=controlled_spelling,
        controlled_identity=controlled_identity,
        provenance=provenance,
        evidence=evidence,
    )


def _source_section_for(
    hit: _SpooledHit,
    *,
    snapshot: SnapshotLookup | None,
    cache: dict[tuple[str, str], SourceRow | None],
    row_cache_size: int,
) -> str | None:
    if snapshot is None:
        return None
    key = (hit.source_table, hit.row_id)
    if key in cache:
        row = cache[key]
    else:
        if len(cache) >= row_cache_size:
            cache.clear()
        row = snapshot.lookup(hit.source_table, hit.row_id)
        cache[key] = row
    if row is None:
        return None
    values = dict(row.values)
    section = values.get("Source / section", "")
    return section if section != "" else None


def _occurrence_id(block_node_id: str, location: CharSpan, mention: UnitMention) -> str:
    provenance_kind = "none" if mention.provenance is None else mention.provenance.kind
    material = "|".join(
        (
            block_node_id,
            str(location.start_char),
            str(location.end_char),
            location.matched_text,
            provenance_kind,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"unit:{digest}"


def _bounded_message(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE:
        return message
    keep = _MAX_ERROR_MESSAGE - len(_ELLIPSIS)
    return message[:keep] + _ELLIPSIS


__all__ = [
    "UnitAggregationCoverage",
    "UnitAggregationError",
    "UnitBlockStream",
    "fixed_vocabulary_unit_terms",
    "iter_aggregated_unit_block_records",
    "iter_unit_mentions_from_terms",
]
