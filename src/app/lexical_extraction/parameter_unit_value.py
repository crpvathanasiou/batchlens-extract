"""Independent parameter-name, unit, and value-expression capability (L10).

Reusable by the later L12 runner. Parameter names stay on the accepted
L05→L07→L08 dictionary path without selecting or detecting equipment. Units use
L07 raw discovery plus L10 unit aggregation (not L08). Value expressions use the
shared L10 parser. Optional L11 ``fuzzy_enabled`` is honored only on the
parameter-name dictionary seam; units and values remain non-fuzzy. Component
selection suppresses unrequested output. This is not a CLI, publisher,
side-by-side review UI, or LLM workflow.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import chain
from typing import Final

from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import (
    BlockEvidence,
    BlockRecord,
    Component,
    DictionaryOccurrence,
    LexicalOccurrence,
    SafeStructuredError,
    UnitOccurrence,
    ValueOccurrence,
)
from app.lexical_extraction.dictionary_aggregation import (
    AggregatedBlockStream,
    DictionaryAggregationError,
    SnapshotLookup,
    iter_aggregated_block_records,
)
from app.lexical_extraction.dictionary_matcher import (
    BlockReplaySource,
    DictionaryMatchError,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm
from app.lexical_extraction.unit_aggregation import (
    UnitAggregationError,
    UnitBlockStream,
    fixed_vocabulary_unit_terms,
    iter_aggregated_unit_block_records,
)
from app.lexical_extraction.unit_value_rules import controlled_unit_for_casefolded
from app.lexical_extraction.value_expressions import (
    RecognizedUnitSpelling,
    recognize_value_expressions,
)

_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200
# Equipment catalogue is hundreds of rows in the published snapshot. A finite
# bound far above that size fails closed instead of silently dropping terms.
_MAX_EQUIPMENT_UNIT_TERMS: Final = 10_000

_L10_COMPONENTS: Final[frozenset[Component]] = frozenset(
    {
        Component.PARAMETER_NAMES,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
        Component.PARAMETER_VALUE_EXPRESSIONS,
    }
)
_VALUE_COMPONENTS: Final[frozenset[Component]] = frozenset(
    {
        Component.QUANTITY_EXPRESSIONS,
        Component.PARAMETER_VALUE_EXPRESSIONS,
    }
)


class ParameterUnitValueError(Exception):
    """Bounded L10 orchestration failure mapped to ``SafeStructuredError``."""

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("parameter-unit-value error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class ParameterUnitValueCoverage:
    """Counts available only after successful complete consumption and cleanup."""

    blocks_emitted: int
    dictionary_occurrences: int
    unit_occurrences: int
    value_occurrences: int
    source_identity: str


@dataclass
class ParameterUnitValueStream:
    """Bounded block-stream of independent parameter / unit / value evidence.

    Composes ordered L08 dictionary blocks, L10 unit blocks, and per-block value
    recognition incrementally. Does not retain whole-document discovery or
    occurrence containers.
    """

    _blocks: BlockReplaySource
    _selected: frozenset[Component]
    _limits: ResourceLimits
    _parameter_terms: Iterable[EligibleSearchTerm]
    _equipment_unit_terms: Iterable[EligibleSearchTerm]
    _snapshot: SnapshotLookup | None
    _expected_source_identity: str | None = None
    _fuzzy_enabled: bool = False
    _coverage: ParameterUnitValueCoverage | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _iterator: Iterator[BlockRecord] | None = field(default=None, init=False, repr=False)
    _owned_closeables: list[object] = field(default_factory=lambda: [], init=False, repr=False)

    @property
    def coverage(self) -> ParameterUnitValueCoverage:
        if self._coverage is None:
            raise ParameterUnitValueError(
                "STREAM_INCOMPLETE",
                "coverage is available only after complete successful consumption",
            )
        return self._coverage

    def __iter__(self) -> Iterator[BlockRecord]:
        if self._started:
            raise ParameterUnitValueError(
                "STREAM_REUSED",
                "parameter/unit/value stream can be consumed only once",
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
        self._close_owned()

    def _close_owned(self) -> None:
        while self._owned_closeables:
            owned = self._owned_closeables.pop()
            close = getattr(owned, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    continue

    def _run(self) -> Iterator[BlockRecord]:
        primary_error: BaseException | None = None
        param_stream: AggregatedBlockStream | None = None
        unit_stream: UnitBlockStream | None = None
        try:
            equipment_terms = _bounded_equipment_terms(self._equipment_unit_terms)
            unit_spellings = self._recognition_units(equipment_terms)
            value_components = tuple(
                component for component in _VALUE_COMPONENTS if component in self._selected
            )
            identity = self._resolve_source_identity()

            if Component.PARAMETER_NAMES in self._selected:
                param_stream = self._open_parameter_stream(identity)
            if Component.UNITS in self._selected:
                unit_stream = self._open_unit_stream(equipment_terms, identity)

            blocks_emitted = 0
            dictionary_occurrences = 0
            unit_occurrences = 0
            value_occurrences = 0

            for block, dict_occs, unit_occs in _iter_merged_blocks(
                self._blocks,
                param_stream,
                unit_stream,
                pinned_identity=identity,
            ):
                occurrences: list[LexicalOccurrence] = []
                occurrences.extend(dict_occs)
                occurrences.extend(unit_occs)
                if value_components:
                    occurrences.extend(
                        recognize_value_expressions(
                            block,
                            applies_to=value_components,
                            unit_spellings=unit_spellings,
                        )
                    )
                if len(occurrences) > self._limits.result_buffer_records:
                    raise ParameterUnitValueError(
                        "RESOURCE_LIMIT_EXCEEDED",
                        "per-block occurrence count exceeds result_buffer_records",
                    )
                occurrences.sort(
                    key=lambda occ: (
                        _occurrence_start(occ),
                        _occurrence_end(occ),
                        occ.occurrence_id,
                    )
                )
                dictionary_occurrences += sum(
                    1 for item in occurrences if isinstance(item, DictionaryOccurrence)
                )
                unit_occurrences += sum(
                    1 for item in occurrences if isinstance(item, UnitOccurrence)
                )
                value_occurrences += sum(
                    1 for item in occurrences if isinstance(item, ValueOccurrence)
                )
                blocks_emitted += 1
                yield BlockRecord(block=block, occurrences=tuple(occurrences))

            # Child streams expose coverage only after their own successful cleanup.
            if param_stream is not None:
                _ = param_stream.coverage
            if unit_stream is not None:
                _ = unit_stream.coverage
            self._coverage = ParameterUnitValueCoverage(
                blocks_emitted=blocks_emitted,
                dictionary_occurrences=dictionary_occurrences,
                unit_occurrences=unit_occurrences,
                value_occurrences=value_occurrences,
                source_identity=identity,
            )
        except GeneratorExit:
            primary_error = GeneratorExit()
            raise
        except (DictionaryAggregationError, UnitAggregationError, DictionaryMatchError) as exc:
            primary_error = exc
            raise ParameterUnitValueError(exc.code, exc.message) from exc
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            del primary_error
            self._close_owned()

    def _resolve_source_identity(self) -> str:
        if self._expected_source_identity:
            return self._expected_source_identity
        try:
            identity = self._blocks.source_identity
        except DictionaryMatchError as exc:
            raise ParameterUnitValueError(exc.code, exc.message) from exc
        if not identity:
            raise ParameterUnitValueError(
                "SOURCE_IDENTITY_REQUIRED",
                "parameter/unit/value stream requires a non-empty block source identity",
            )
        return identity

    def _open_parameter_stream(self, identity: str) -> AggregatedBlockStream:
        if self._snapshot is None:
            raise ParameterUnitValueError(
                "SNAPSHOT_REQUIRED",
                "parameter_names selection requires an open knowledge snapshot for L08 aggregation",
            )
        discoveries = iter_raw_discoveries(
            self._parameter_terms,
            self._blocks,
            self._limits,
            fuzzy_enabled=self._fuzzy_enabled,
        )
        self._owned_closeables.append(discoveries)
        stream = iter_aggregated_block_records(
            discoveries,
            self._blocks,
            self._snapshot,
            self._limits,
            expected_source_identity=identity,
        )
        self._owned_closeables.append(stream)
        return stream

    def _open_unit_stream(
        self,
        equipment_terms: tuple[EligibleSearchTerm, ...],
        identity: str,
    ) -> UnitBlockStream:
        terms = chain(equipment_terms, fixed_vocabulary_unit_terms())
        discoveries = iter_raw_discoveries(
            terms,
            self._blocks,
            self._limits,
            fuzzy_enabled=False,
        )
        self._owned_closeables.append(discoveries)
        stream = iter_aggregated_unit_block_records(
            discoveries,
            self._blocks,
            self._limits,
            snapshot=self._snapshot,
            expected_source_identity=identity,
        )
        self._owned_closeables.append(stream)
        return stream

    def _recognition_units(
        self,
        equipment_terms: Sequence[EligibleSearchTerm],
    ) -> tuple[RecognizedUnitSpelling, ...]:
        if not (self._selected & _VALUE_COMPONENTS):
            return ()
        seen: set[str] = set()
        units: list[RecognizedUnitSpelling] = []
        for term in equipment_terms:
            key = term.literal.casefold()
            if key in seen:
                continue
            seen.add(key)
            fixed = controlled_unit_for_casefolded(term.literal)
            units.append(
                RecognizedUnitSpelling(
                    spelling=term.literal,
                    controlled_spelling=None if fixed is None else fixed.controlled_spelling,
                    controlled_identity=None if fixed is None else fixed.controlled_identity,
                )
            )
        return tuple(units)


def iter_parameter_unit_value_block_records(
    blocks: BlockReplaySource,
    *,
    components: Sequence[Component],
    limits: ResourceLimits,
    parameter_terms: Iterable[EligibleSearchTerm] = (),
    equipment_unit_terms: Iterable[EligibleSearchTerm] = (),
    snapshot: SnapshotLookup | None = None,
    expected_source_identity: str | None = None,
    fuzzy_enabled: bool = False,
) -> ParameterUnitValueStream:
    """Stream per-block parameter-name, unit, and/or value evidence.

    Only ``parameter_names``, ``units``, ``quantity_expressions``, and
    ``parameter_value_expressions`` are accepted. Equipment detection is never
    performed. Term iterables are consumed by L07 without a whole-document
    discovery materialization. Equipment unit terms used for dual unit/value
    recognition are retained only under the explicit finite bound
    ``_MAX_EQUIPMENT_UNIT_TERMS`` (fail closed; no silent loss).

    ``fuzzy_enabled`` is honored only for the parameter-name dictionary path.
    Units and value expressions remain non-fuzzy.

    ``result_buffer_records`` bounds one block's buffered occurrences, not the
    cumulative document total. Coverage is available only after complete
    successful consumption and child-stream cleanup.
    """

    selected = frozenset(components)
    if not selected:
        raise ParameterUnitValueError(
            "SELECTION_REQUIRED",
            "at least one of parameter_names, units, or value expression components is required",
        )
    unknown = selected - _L10_COMPONENTS
    if unknown:
        raise ParameterUnitValueError(
            "UNSUPPORTED_COMPONENT",
            "L10 accepts parameter_names, units, and the two value components only",
        )
    identity = expected_source_identity
    if identity is None:
        try:
            identity = blocks.source_identity
        except DictionaryMatchError as exc:
            if exc.code != "REPLAY_IDENTITY_UNPINNED":
                raise ParameterUnitValueError(exc.code, exc.message) from exc
            identity = None
    if identity == "":
        raise ParameterUnitValueError(
            "SOURCE_IDENTITY_REQUIRED",
            "parameter/unit/value stream requires a non-empty block source identity",
        )

    return ParameterUnitValueStream(
        _blocks=blocks,
        _selected=selected,
        _limits=limits,
        _parameter_terms=parameter_terms,
        _equipment_unit_terms=equipment_unit_terms,
        _snapshot=snapshot,
        _expected_source_identity=identity,
        _fuzzy_enabled=fuzzy_enabled,
    )


def recognize_block_values(
    block: BlockEvidence,
    *,
    components: Sequence[Component],
    equipment_unit_terms: Sequence[EligibleSearchTerm] = (),
) -> tuple[ValueOccurrence, ...]:
    """Per-block value API for callers that do not need the full stream."""

    selected = tuple(
        component
        for component in (
            Component.QUANTITY_EXPRESSIONS,
            Component.PARAMETER_VALUE_EXPRESSIONS,
        )
        if component in components
    )
    if not selected:
        return ()
    spellings: list[RecognizedUnitSpelling] = []
    for term in equipment_unit_terms:
        fixed = controlled_unit_for_casefolded(term.literal)
        spellings.append(
            RecognizedUnitSpelling(
                spelling=term.literal,
                controlled_spelling=None if fixed is None else fixed.controlled_spelling,
                controlled_identity=None if fixed is None else fixed.controlled_identity,
            )
        )
    return recognize_value_expressions(block, applies_to=selected, unit_spellings=spellings)


def _bounded_equipment_terms(
    terms: Iterable[EligibleSearchTerm],
) -> tuple[EligibleSearchTerm, ...]:
    taken: list[EligibleSearchTerm] = []
    for term in terms:
        if len(taken) >= _MAX_EQUIPMENT_UNIT_TERMS:
            raise ParameterUnitValueError(
                "RESOURCE_LIMIT_EXCEEDED",
                "equipment unit term count exceeds the finite equipment-term bound",
            )
        taken.append(term)
    return tuple(taken)


def _iter_merged_blocks(
    blocks: BlockReplaySource,
    param_stream: AggregatedBlockStream | None,
    unit_stream: UnitBlockStream | None,
    *,
    pinned_identity: str,
) -> Iterator[tuple[BlockEvidence, tuple[DictionaryOccurrence, ...], tuple[UnitOccurrence, ...]]]:
    """Yield document-ordered blocks with aligned dictionary and unit occurrences."""

    if param_stream is None and unit_stream is None:
        yield from _iter_value_only_blocks(blocks, pinned_identity=pinned_identity)
        return

    param_it = iter(param_stream) if param_stream is not None else None
    unit_it = iter(unit_stream) if unit_stream is not None else None

    if param_it is not None and unit_it is not None:
        for param_rec, unit_rec in zip(param_it, unit_it, strict=True):
            if param_rec.block.node_id != unit_rec.block.node_id:
                raise ParameterUnitValueError(
                    "BLOCK_IDENTITY_MISMATCH",
                    "parameter and unit block streams diverged in document order",
                )
            if param_rec.block.text != unit_rec.block.text:
                raise ParameterUnitValueError(
                    "BLOCK_IDENTITY_MISMATCH",
                    "parameter and unit block streams disagree on block text",
                )
            yield (
                param_rec.block,
                tuple(
                    occ for occ in param_rec.occurrences if isinstance(occ, DictionaryOccurrence)
                ),
                tuple(occ for occ in unit_rec.occurrences if isinstance(occ, UnitOccurrence)),
            )
        return

    if param_it is not None:
        for param_rec in param_it:
            yield (
                param_rec.block,
                tuple(
                    occ for occ in param_rec.occurrences if isinstance(occ, DictionaryOccurrence)
                ),
                (),
            )
        return

    assert unit_it is not None
    for unit_rec in unit_it:
        yield (
            unit_rec.block,
            (),
            tuple(occ for occ in unit_rec.occurrences if isinstance(occ, UnitOccurrence)),
        )


def _iter_value_only_blocks(
    blocks: BlockReplaySource,
    *,
    pinned_identity: str,
) -> Iterator[tuple[BlockEvidence, tuple[DictionaryOccurrence, ...], tuple[UnitOccurrence, ...]]]:
    """Stream value-only blocks; verify HTML replay identity after a full pass.

    A fresh ``ReviewedHtmlBlockReplay`` stays unpinned until one complete
    ``iter_blocks`` pass finishes. When the caller supplied an expected full-file
    identity, allow that unpinned first pass without buffering the document, then
    require the finalized digest to match before the orchestrator publishes
    coverage. Already-pinned sources keep immediate identity checks.
    """

    already_pinned = False
    try:
        current = blocks.source_identity
        already_pinned = True
        if current != pinned_identity:
            raise ParameterUnitValueError(
                "REPLAY_IDENTITY_CHANGED",
                "block source identity does not match the expected parameter/unit/value identity",
            )
    except DictionaryMatchError as exc:
        if exc.code != "REPLAY_IDENTITY_UNPINNED":
            raise ParameterUnitValueError(exc.code, exc.message) from exc

    for block in blocks.iter_blocks():
        if already_pinned and blocks.source_identity != pinned_identity:
            raise ParameterUnitValueError(
                "REPLAY_IDENTITY_CHANGED",
                "block source identity changed during parameter/unit/value replay",
            )
        yield block, (), ()

    try:
        finalized = blocks.source_identity
    except DictionaryMatchError as exc:
        raise ParameterUnitValueError(exc.code, exc.message) from exc
    if finalized != pinned_identity:
        raise ParameterUnitValueError(
            "REPLAY_IDENTITY_CHANGED",
            "block source identity does not match the expected parameter/unit/value identity",
        )


def _occurrence_start(occurrence: LexicalOccurrence) -> int:
    if isinstance(occurrence, DictionaryOccurrence):
        return occurrence.location.start_char
    if isinstance(occurrence, UnitOccurrence):
        return occurrence.mention.span.start_char
    return occurrence.expression.span.start_char


def _occurrence_end(occurrence: LexicalOccurrence) -> int:
    if isinstance(occurrence, DictionaryOccurrence):
        return occurrence.location.end_char
    if isinstance(occurrence, UnitOccurrence):
        return occurrence.mention.span.end_char
    return occurrence.expression.span.end_char


__all__ = [
    "ParameterUnitValueCoverage",
    "ParameterUnitValueError",
    "ParameterUnitValueStream",
    "iter_parameter_unit_value_block_records",
    "recognize_block_values",
]
