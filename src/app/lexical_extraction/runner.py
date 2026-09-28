"""Callable L12 lexical extraction runner and evidence-sink boundary.

Composes the accepted L02–L11 pipeline into one bounded run. Streams page/block
evidence through a caller-owned sink suitable for a later L13 publisher. Does
not publish final artifacts, write a final manifest, create a CLI, or build the
review UI.

Failure boundaries
------------------
Shared prerequisites (one HTML validation pass + one L04 snapshot preflight)
affect every requested component. Dictionary components
``unit_operations``, ``process_steps``, ``materials``, and ``equipment`` each
run an independent L05→L07→L08 pass. Selected L10 components
(``parameter_names``, ``units``, ``quantity_expressions``,
``parameter_value_expressions``) share one L10 composition stream so value
expressions are not duplicated when both value components are selected.

Provisional sink writes are not completed coverage. A component is ``completed``
(including match count 0) only after its full stream/replay and sink
``complete_component`` succeed. Independent completed components remain usable
when another component fails (overall ``partial``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from app.lexical_extraction.configuration import (
    COMPONENT_ORDER,
    EffectiveExecutionConfiguration,
    ResourceLimits,
    SelectionOverride,
    effective_configuration_sha256,
    load_execution_configuration,
)
from app.lexical_extraction.contracts import (
    EXACT_RULE_ID,
    FUZZY_MAX_EDIT_DISTANCE,
    FUZZY_MIN_WORD_LENGTH,
    FUZZY_RULE_ID,
    INTERNAL_RULES_VERSION,
    NORMALIZED_EXACT_RULE_ID,
    RECORD_SCHEMA_VERSION,
    UNIT_RULE_ID,
    UNIT_VOCABULARY_ID,
    VALUE_RULE_ID,
    BlockRecord,
    Component,
    ComponentResult,
    DependencyVersion,
    DictionaryOccurrence,
    ElapsedTiming,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    KnowledgeSnapshotIdentity,
    PageCoverage,
    PageEvidence,
    PreValidationFailure,
    ReviewedHtmlV1Input,
    RunProvenance,
    SafeStructuredError,
    UnitOccurrence,
    ValueOccurrence,
    validate_resolved_component_coverage,
)
from app.lexical_extraction.dictionary_aggregation import (
    DictionaryAggregationError,
    iter_aggregated_block_records,
)
from app.lexical_extraction.dictionary_matcher import (
    DictionaryMatchError,
    ReviewedHtmlBlockReplay,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import (
    EligibleSearchTerm,
    FieldMappingError,
    iter_eligible_terms,
)
from app.lexical_extraction.html_reader import (
    ReviewedHtmlReadError,
    open_reviewed_html,
)
from app.lexical_extraction.knowledge_snapshot import (
    KnowledgeSnapshot,
    SnapshotReadError,
    open_knowledge_snapshot,
)
from app.lexical_extraction.monitoring import (
    RunMonitoringAccumulator,
    RunMonitoringSummary,
    measure_peak_process_memory,
)
from app.lexical_extraction.parameter_unit_value import (
    ParameterUnitValueError,
    iter_parameter_unit_value_block_records,
)
from app.lexical_extraction.unit_aggregation import UnitAggregationError
from app.lexical_extraction.unit_value_rules import (
    FIXED_CATEGORICAL_RULES,
    FIXED_CUE_RULES,
    FIXED_QUANTITY_UNITS,
    UNIT_VALUE_RULES_VERSION,
)

logger = logging.getLogger("app.lexical_extraction.runner")

_MAX_ERROR_MESSAGE: Final = 200
_ENGINE_PACKAGE: Final = "batchlens-extract"
_DICTIONARY_COMPONENTS: Final[frozenset[Component]] = frozenset(
    {
        Component.UNIT_OPERATIONS,
        Component.PROCESS_STEPS,
        Component.MATERIALS,
        Component.EQUIPMENT,
    }
)
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


class LexicalRunnerError(Exception):
    """Bounded runner orchestration failure mapped to ``SafeStructuredError``."""

    def __init__(self, code: str, message: str) -> None:
        if not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("runner error message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self, component: Component | None = None) -> SafeStructuredError:
        return SafeStructuredError(
            code=self.code,
            message=self.message,
            component=component,
            retryable=False,
        )


@runtime_checkable
class EvidenceSink(Protocol):
    """Caller-owned bounded evidence destination for one run.

    Lifecycle: ``begin_run`` → zero or more component cycles →
    ``complete_run`` or ``abort_run``. Each component cycle is
    ``begin_component`` → provisional component-scoped ``write_page`` /
    ``write_block`` → ``complete_component`` or ``abort_component``. Writes
    before ``complete_component`` are provisional and must not be treated as
    completed coverage. A failed write is an execution/output failure.

    More than one component may be provisional at the same time when the L10
    shared composition begins each selected component and emits page skeletons
    before the shared block stream. ``write_page`` / ``write_block`` remain
    component-scoped.

    ``abort_component`` must not be called for a component that already
    received ``complete_component``. ``abort_run`` after one or more committed
    components must leave those completed outcomes intact; it is a run-level
    finalization signal, not a demand to retract committed component streams.
    """

    def begin_run(self, run_id: str) -> None:
        """Open the run. May raise to fail the run before search."""

    def begin_component(self, component: Component) -> None:
        """Open one component stream. Writes that follow are provisional."""

    def write_page(self, component: Component, page: PageEvidence) -> None:
        """Emit one page skeleton for ``component`` (may be empty). Provisional."""

    def write_block(self, component: Component, record: BlockRecord) -> None:
        """Emit one block record for ``component``. Provisional until complete."""

    def complete_component(self, component: Component) -> None:
        """Mark the component stream completed after full successful consumption."""

    def abort_component(self, component: Component, error: SafeStructuredError) -> None:
        """Abort an uncommitted component stream; provisional writes are not coverage."""

    def complete_run(self) -> None:
        """Close the run after all requested component cycles finish."""

    def abort_run(self, error: SafeStructuredError) -> None:
        """Signal run-level failure without a completed final-manifest claim."""


@dataclass(frozen=True)
class LexicalRunResult:
    """Typed summary of one L12 callable run.

    ``provenance`` is present only when HTML and snapshot identities are both
    known. ``pre_validation`` is used when HTML validation never completed;
    otherwise ``extraction`` carries per-component outcomes. ``run_error``
    carries an explicit run-level sink/finalization failure while preserving
    committed component outcomes and validated identities when available. L12
    never constructs a completed ``PublicationRecord``.
    """

    run_id: str
    validated_input: ReviewedHtmlV1Input | None
    knowledge: KnowledgeSnapshotIdentity | None
    provenance: RunProvenance | None
    extraction: ExtractionOutcomeRecord | None
    pre_validation: PreValidationFailure | None
    monitoring: RunMonitoringSummary
    run_error: SafeStructuredError | None = None


@dataclass
class _HtmlValidation:
    validated_input: ReviewedHtmlV1Input
    pages_observed: int
    blocks_observed: int


@dataclass
class EligibleTermCounter:
    """Wraps an eligible-term iterable and records accurate term/row counts.

    L05 emits terms row-by-row from a single-table paged scan, so consecutive
    terms share a ``(source_table, row_id)`` until the next eligible row.
    Eligible rows are counted with a single previous-key integer counter — not a
    retained set of row IDs. Source rows that emit no terms are never counted.
    """

    terms: Iterable[EligibleSearchTerm]
    term_count: int = 0
    row_count: int = 0

    def __iter__(self) -> Iterator[EligibleSearchTerm]:
        previous: tuple[str, str] | None = None
        for term in self.terms:
            self.term_count += 1
            key = (term.source_table, term.row_id)
            if key != previous:
                self.row_count += 1
                previous = key
            yield term


def fixed_rules_sha256() -> str:
    """Lower-case SHA-256 of the fixed V1 rules actually used by the engine."""

    material = {
        "rules_version": INTERNAL_RULES_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "exact_rule_id": EXACT_RULE_ID,
        "normalized_exact_rule_id": NORMALIZED_EXACT_RULE_ID,
        "fuzzy_rule_id": FUZZY_RULE_ID,
        "unit_rule_id": UNIT_RULE_ID,
        "value_rule_id": VALUE_RULE_ID,
        "fuzzy_max_edit_distance": FUZZY_MAX_EDIT_DISTANCE,
        "fuzzy_min_word_length": FUZZY_MIN_WORD_LENGTH,
        "unit_vocabulary_id": UNIT_VOCABULARY_ID,
        "unit_value_rules_version": UNIT_VALUE_RULES_VERSION,
        "fixed_quantity_units": [
            {
                "controlled_identity": entry.controlled_identity,
                "controlled_spelling": entry.controlled_spelling,
                "aliases": list(entry.aliases),
            }
            for entry in FIXED_QUANTITY_UNITS
        ],
        "fixed_categorical_rules": [
            {"category_label": rule.category_label, "phrase": rule.phrase}
            for rule in FIXED_CATEGORICAL_RULES
        ],
        "fixed_cue_rules": [{"cue": rule.cue} for rule in FIXED_CUE_RULES],
    }
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_lexical_extraction(
    config: EffectiveExecutionConfiguration,
    sink: EvidenceSink,
) -> LexicalRunResult:
    """Execute exactly the resolved component selection for one configuration.

    Validates reviewed HTML v1 fully, prefights the flat snapshot once, streams
    evidence through ``sink``, and returns honest outcomes plus monitoring.
    """

    run_id = str(uuid.uuid4())
    monitor = RunMonitoringAccumulator()
    monitor.resource_limits = {
        "sqlite_read_batch_rows": config.resources.sqlite_read_batch_rows,
        "sqlite_cache_kib": config.resources.sqlite_cache_kib,
        "max_terms_per_shard": config.resources.max_terms_per_shard,
        "max_term_codepoints_per_shard": config.resources.max_term_codepoints_per_shard,
        "result_buffer_records": config.resources.result_buffer_records,
    }
    resolved = config.resolved_components
    fuzzy_enabled = config.extraction.fuzzy_enabled
    started = time.perf_counter()
    snapshot: KnowledgeSnapshot | None = None
    run_begun = False
    run_finished = False
    validated_input: ReviewedHtmlV1Input | None = None
    knowledge: KnowledgeSnapshotIdentity | None = None
    results: dict[Component, ComponentResult] = {}

    def _finish_peak() -> None:
        peak, method = measure_peak_process_memory()
        monitor.peak_process_memory_bytes = peak
        monitor.peak_memory_method = method

    try:
        sink.begin_run(run_id)
        run_begun = True
        _log(run_id, stage="run", status="started", component=None)

        html_started = time.perf_counter()
        try:
            html = _validate_html(config.input.reviewed_html_path)
        except (ReviewedHtmlReadError, LexicalRunnerError, OSError) as exc:
            error = _map_exception(exc, component=None)
            monitor.record_stage(
                "html_validation",
                _elapsed_ms(html_started),
            )
            _finish_peak()
            monitor.record_stage("total", _elapsed_ms(started))
            _safe_abort_run(sink, error)
            run_finished = True
            _log(
                run_id,
                stage="html_validation",
                status="failed",
                component=None,
                error_code=error.code,
            )
            return LexicalRunResult(
                run_id=run_id,
                validated_input=None,
                knowledge=None,
                provenance=None,
                extraction=None,
                pre_validation=PreValidationFailure(error=error),
                monitoring=monitor.freeze(),
            )
        validated_input = html.validated_input
        monitor.record_stage("html_validation", _elapsed_ms(html_started))
        monitor.pages_observed = html.pages_observed
        monitor.blocks_observed = html.blocks_observed
        _log(
            run_id,
            stage="html_validation",
            status="completed",
            component=None,
            pages=html.pages_observed,
            blocks=html.blocks_observed,
            elapsed_ms=monitor.stage_timings_ms["html_validation"],
        )

        snap_started = time.perf_counter()
        try:
            snapshot = open_knowledge_snapshot(
                config.knowledge.snapshot_directory,
                read_batch_rows=config.resources.sqlite_read_batch_rows,
                cache_kib=config.resources.sqlite_cache_kib,
            )
            knowledge = snapshot.identity
        except SnapshotReadError as exc:
            error = _map_exception(exc, component=None)
            monitor.record_stage("snapshot_preflight", _elapsed_ms(snap_started))
            results = _all_failed_results(resolved, error)
            extraction = ExtractionOutcomeRecord(
                overall=ExtractionOutcome.FAILED,
                components=_full_component_tuple(resolved, results),
            )
            _finish_peak()
            monitor.record_stage("total", _elapsed_ms(started))
            for component in resolved:
                monitor.mark_component_outcome(
                    component,
                    ExtractionOutcome.FAILED,
                    match_count=None,
                )
            _safe_abort_run(sink, error)
            run_finished = True
            _log(
                run_id,
                stage="snapshot_preflight",
                status="failed",
                component=None,
                error_code=error.code,
            )
            return LexicalRunResult(
                run_id=run_id,
                validated_input=validated_input,
                knowledge=None,
                provenance=None,
                extraction=extraction,
                pre_validation=None,
                monitoring=monitor.freeze(),
            )
        monitor.record_stage("snapshot_preflight", _elapsed_ms(snap_started))
        _log(
            run_id,
            stage="snapshot_preflight",
            status="completed",
            component=None,
            elapsed_ms=monitor.stage_timings_ms["snapshot_preflight"],
        )

        try:
            for component in COMPONENT_ORDER:
                if component not in resolved:
                    continue
                if component in _DICTIONARY_COMPONENTS:
                    results[component] = _run_dictionary_component(
                        component=component,
                        html_path=config.input.reviewed_html_path,
                        expected_html_sha256=validated_input.html_sha256,
                        snapshot=snapshot,
                        limits=config.resources,
                        fuzzy_enabled=fuzzy_enabled,
                        sink=sink,
                        monitor=monitor,
                        run_id=run_id,
                    )
            l10_selected = tuple(
                component
                for component in COMPONENT_ORDER
                if component in resolved and component in _L10_COMPONENTS
            )
            if l10_selected:
                l10_results = _run_l10_group(
                    selected=l10_selected,
                    html_path=config.input.reviewed_html_path,
                    expected_html_sha256=validated_input.html_sha256,
                    snapshot=snapshot,
                    limits=config.resources,
                    fuzzy_enabled=fuzzy_enabled,
                    sink=sink,
                    monitor=monitor,
                    run_id=run_id,
                )
                results.update(l10_results)
        finally:
            snapshot.close()
            snapshot = None

        extraction = ExtractionOutcomeRecord(
            overall=_overall_outcome(results, resolved),
            components=_full_component_tuple(resolved, results),
        )
        _finish_peak()
        monitor.record_stage("total", _elapsed_ms(started))
        provenance = _build_provenance(
            run_id=run_id,
            config=config,
            validated_input=validated_input,
            knowledge=knowledge,
            monitor=monitor,
        )
        validate_resolved_component_coverage(provenance, extraction)
        try:
            sink.complete_run()
        except Exception as exc:
            run_error = _map_exception(exc, component=None)
            if run_error.code == "RUNNER_FAILED":
                run_error = SafeStructuredError(
                    code="SINK_COMPLETE_RUN_FAILED",
                    message=_bounded_message(
                        f"evidence sink complete_run failed: {type(exc).__name__}"
                    ),
                    component=None,
                    retryable=False,
                )
            _safe_abort_run(sink, run_error)
            run_finished = True
            _log(
                run_id,
                stage="run",
                status="sink_finalization_failed",
                component=None,
                error_code=run_error.code,
                elapsed_ms=monitor.stage_timings_ms["total"],
            )
            return LexicalRunResult(
                run_id=run_id,
                validated_input=validated_input,
                knowledge=knowledge,
                provenance=provenance,
                extraction=extraction,
                pre_validation=None,
                monitoring=monitor.freeze(),
                run_error=run_error,
            )
        run_finished = True
        _log(
            run_id,
            stage="run",
            status=extraction.overall.value,
            component=None,
            elapsed_ms=monitor.stage_timings_ms["total"],
        )
        return LexicalRunResult(
            run_id=run_id,
            validated_input=validated_input,
            knowledge=knowledge,
            provenance=provenance,
            extraction=extraction,
            pre_validation=None,
            monitoring=monitor.freeze(),
        )
    except Exception as exc:
        error = _map_exception(exc, component=None)
        _finish_peak()
        monitor.record_stage("total", _elapsed_ms(started))
        if run_begun and not run_finished:
            _safe_abort_run(sink, error)
        _log(
            run_id,
            stage="run",
            status="failed",
            component=None,
            error_code=error.code,
        )
        if results:
            for component in resolved:
                if component in results:
                    continue
                results[component] = ComponentResult(
                    component=component,
                    outcome=ExtractionOutcome.FAILED,
                    error=SafeStructuredError(
                        code=error.code,
                        message=error.message,
                        component=component,
                        retryable=False,
                    ),
                )
                monitor.mark_component_outcome(
                    component,
                    ExtractionOutcome.FAILED,
                    match_count=None,
                )
            extraction = ExtractionOutcomeRecord(
                overall=_overall_outcome(results, resolved),
                components=_full_component_tuple(resolved, results),
            )
            provenance = None
            if validated_input is not None and knowledge is not None:
                provenance = _build_provenance(
                    run_id=run_id,
                    config=config,
                    validated_input=validated_input,
                    knowledge=knowledge,
                    monitor=monitor,
                )
            return LexicalRunResult(
                run_id=run_id,
                validated_input=validated_input,
                knowledge=knowledge,
                provenance=provenance,
                extraction=extraction,
                pre_validation=None,
                monitoring=monitor.freeze(),
                run_error=error,
            )
        failed = {
            component: ComponentResult(
                component=component,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(
                    code=error.code,
                    message=error.message,
                    component=component,
                    retryable=False,
                ),
            )
            for component in resolved
        }
        for component in resolved:
            monitor.mark_component_outcome(component, ExtractionOutcome.FAILED, match_count=None)
        return LexicalRunResult(
            run_id=run_id,
            validated_input=validated_input,
            knowledge=knowledge,
            provenance=None,
            extraction=ExtractionOutcomeRecord(
                overall=ExtractionOutcome.FAILED,
                components=_full_component_tuple(resolved, failed),
            ),
            pre_validation=None,
            monitoring=monitor.freeze(),
            run_error=error,
        )
    finally:
        if snapshot is not None:
            snapshot.close()


def run_lexical_extraction_from_config_path(
    config_path: Path,
    sink: EvidenceSink,
    *,
    overrides: SelectionOverride | None = None,
) -> LexicalRunResult:
    """Thin convenience entry: load L02 YAML then run ``run_lexical_extraction``."""

    config = load_execution_configuration(config_path, overrides=overrides)
    return run_lexical_extraction(config, sink)


def _validate_html(path: Path) -> _HtmlValidation:
    try:
        reader = open_reviewed_html(path)
    except ReviewedHtmlReadError:
        raise
    except OSError as exc:
        raise LexicalRunnerError(
            "INPUT_UNREADABLE",
            _bounded_message(f"reviewed HTML could not be opened: {type(exc).__name__}"),
        ) from exc

    pages_observed = 0
    blocks_observed = 0
    try:
        for page in reader.iter_pages():
            pages_observed += 1
            blocks_observed += len(page.blocks)
    except ReviewedHtmlReadError:
        raise

    if not reader.completed:
        raise LexicalRunnerError(
            "HTML_VALIDATION_INCOMPLETE",
            "reviewed HTML validation ended without a finalized identity",
        )
    return _HtmlValidation(
        validated_input=reader.validated_input,
        pages_observed=pages_observed,
        blocks_observed=blocks_observed,
    )


def _run_dictionary_component(
    *,
    component: Component,
    html_path: Path,
    expected_html_sha256: str,
    snapshot: KnowledgeSnapshot,
    limits: ResourceLimits,
    fuzzy_enabled: bool,
    sink: EvidenceSink,
    monitor: RunMonitoringAccumulator,
    run_id: str,
) -> ComponentResult:
    stage = f"component:{component.value}"
    started = time.perf_counter()
    stream = None
    committed = False
    try:
        sink.begin_component(component)
        _emit_component_pages(
            sink,
            component=component,
            html_path=html_path,
            expected_html_sha256=expected_html_sha256,
        )
        terms = EligibleTermCounter(
            iter_eligible_terms(snapshot, (component,), batch_size=limits.sqlite_read_batch_rows)
        )
        blocks = ReviewedHtmlBlockReplay(html_path)
        discoveries = iter_raw_discoveries(
            terms,
            blocks,
            limits,
            fuzzy_enabled=fuzzy_enabled,
        )
        stream = iter_aggregated_block_records(
            discoveries,
            blocks,
            snapshot,
            limits,
            expected_source_identity=expected_html_sha256,
        )
        match_count = 0
        for record in stream:
            match_count += _count_and_record_matches(monitor, component, record)
            try:
                sink.write_block(component, record)
            except Exception as exc:
                raise LexicalRunnerError(
                    "SINK_WRITE_FAILED",
                    _bounded_message(f"evidence sink write failed: {type(exc).__name__}"),
                ) from exc
        coverage = stream.coverage
        if blocks.source_identity != expected_html_sha256:
            raise LexicalRunnerError(
                "REPLAY_IDENTITY_CHANGED",
                "reviewed HTML identity changed during dictionary search",
            )
        _add_term_counts(monitor, terms)
        if monitor.candidates is None:
            monitor.candidates = coverage.candidates
        else:
            monitor.candidates += coverage.candidates
        sink.complete_component(component)
        committed = True
        result = ComponentResult(
            component=component,
            outcome=ExtractionOutcome.COMPLETED,
            match_count=match_count,
            blocks_considered=coverage.blocks_emitted,
        )
        monitor.mark_component_outcome(
            component,
            ExtractionOutcome.COMPLETED,
            match_count=match_count,
        )
        monitor.record_stage(stage, _elapsed_ms(started))
        _log(
            run_id,
            stage=stage,
            status="completed",
            component=component,
            match_count=match_count,
            elapsed_ms=monitor.stage_timings_ms[stage],
        )
        return result
    except Exception as exc:
        error = _map_exception(exc, component=component)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if not committed:
            try:
                sink.abort_component(component, error)
            except Exception:
                pass
            monitor.mark_component_outcome(component, ExtractionOutcome.FAILED, match_count=None)
            monitor.record_stage(stage, _elapsed_ms(started))
            _log(
                run_id,
                stage=stage,
                status="failed",
                component=component,
                error_code=error.code,
                elapsed_ms=monitor.stage_timings_ms[stage],
            )
            return ComponentResult(
                component=component,
                outcome=ExtractionOutcome.FAILED,
                error=error,
            )
        monitor.record_stage(stage, _elapsed_ms(started))
        raise


def _run_l10_group(
    *,
    selected: Sequence[Component],
    html_path: Path,
    expected_html_sha256: str,
    snapshot: KnowledgeSnapshot,
    limits: ResourceLimits,
    fuzzy_enabled: bool,
    sink: EvidenceSink,
    monitor: RunMonitoringAccumulator,
    run_id: str,
) -> dict[Component, ComponentResult]:
    stage = "component_group:l10"
    started = time.perf_counter()
    selected_set = frozenset(selected)
    stream = None
    begun: list[Component] = []
    results: dict[Component, ComponentResult] = {}
    match_counts: dict[Component, int] = {component: 0 for component in selected}
    blocks_considered: int | None = None
    try:
        for component in selected:
            sink.begin_component(component)
            begun.append(component)
            _emit_component_pages(
                sink,
                component=component,
                html_path=html_path,
                expected_html_sha256=expected_html_sha256,
            )

        param_counter: EligibleTermCounter | None = None
        unit_counter: EligibleTermCounter | None = None
        parameter_terms: Iterable[EligibleSearchTerm] = ()
        equipment_unit_terms: Iterable[EligibleSearchTerm] = ()
        if Component.PARAMETER_NAMES in selected_set:
            param_counter = EligibleTermCounter(
                iter_eligible_terms(
                    snapshot,
                    (Component.PARAMETER_NAMES,),
                    batch_size=limits.sqlite_read_batch_rows,
                )
            )
            parameter_terms = param_counter
        if Component.UNITS in selected_set or (selected_set & _VALUE_COMPONENTS):
            unit_counter = EligibleTermCounter(
                iter_eligible_terms(
                    snapshot,
                    (Component.UNITS,),
                    batch_size=limits.sqlite_read_batch_rows,
                )
            )
            equipment_unit_terms = unit_counter

        blocks = ReviewedHtmlBlockReplay(html_path)
        stream = iter_parameter_unit_value_block_records(
            blocks,
            components=selected,
            limits=limits,
            parameter_terms=parameter_terms,
            equipment_unit_terms=equipment_unit_terms,
            snapshot=snapshot,
            expected_source_identity=expected_html_sha256,
            fuzzy_enabled=fuzzy_enabled,
        )
        for record in stream:
            for component in selected:
                added = _count_and_record_matches(monitor, component, record)
                match_counts[component] += added
            for component in selected:
                filtered = _filter_block_for_component(record, component)
                try:
                    sink.write_block(component, filtered)
                except Exception as exc:
                    raise LexicalRunnerError(
                        "SINK_WRITE_FAILED",
                        _bounded_message(f"evidence sink write failed: {type(exc).__name__}"),
                    ) from exc
        coverage = stream.coverage
        blocks_considered = coverage.blocks_emitted
        if param_counter is not None:
            _add_term_counts(monitor, param_counter)
        if unit_counter is not None:
            _add_term_counts(monitor, unit_counter)

        for component in selected:
            sink.complete_component(component)
            count = match_counts[component]
            results[component] = ComponentResult(
                component=component,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=count,
                blocks_considered=blocks_considered,
            )
            monitor.mark_component_outcome(
                component,
                ExtractionOutcome.COMPLETED,
                match_count=count,
            )
            _log(
                run_id,
                stage=f"component:{component.value}",
                status="completed",
                component=component,
                match_count=count,
            )
        monitor.record_stage(stage, _elapsed_ms(started))
        return results
    except Exception as exc:
        error = _map_exception(exc, component=None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        for component in selected:
            if component in results:
                continue
            component_error = SafeStructuredError(
                code=error.code,
                message=error.message,
                component=component,
                retryable=False,
            )
            if component in begun:
                try:
                    sink.abort_component(component, component_error)
                except Exception:
                    pass
            else:
                try:
                    sink.begin_component(component)
                    sink.abort_component(component, component_error)
                except Exception:
                    pass
            results[component] = ComponentResult(
                component=component,
                outcome=ExtractionOutcome.FAILED,
                error=component_error,
            )
            monitor.mark_component_outcome(component, ExtractionOutcome.FAILED, match_count=None)
            _log(
                run_id,
                stage=f"component:{component.value}",
                status="failed",
                component=component,
                error_code=component_error.code,
            )
        monitor.record_stage(stage, _elapsed_ms(started))
        return results


def _emit_component_pages(
    sink: EvidenceSink,
    *,
    component: Component,
    html_path: Path,
    expected_html_sha256: str,
) -> None:
    """Stream page skeletons for one component from a fresh L03 reader.

    Does not retain an all-page list. Empty pages are emitted in document order.
    A changed or incomplete replay fails the component instead of claiming
    completed coverage.
    """

    try:
        reader = open_reviewed_html(html_path)
    except ReviewedHtmlReadError as exc:
        raise LexicalRunnerError(
            "PAGE_REPLAY_FAILED",
            _bounded_message(f"page replay open failed: {exc.code}"),
        ) from exc
    except OSError as exc:
        raise LexicalRunnerError(
            "PAGE_REPLAY_FAILED",
            _bounded_message(f"page replay open failed: {type(exc).__name__}"),
        ) from exc

    try:
        for page in reader.iter_pages():
            try:
                sink.write_page(
                    component,
                    PageEvidence(
                        page_number=page.page.page_number,
                        order=page.page.order,
                        coverage=PageCoverage.COMPLETE,
                    ),
                )
            except Exception as exc:
                raise LexicalRunnerError(
                    "SINK_WRITE_FAILED",
                    _bounded_message(f"evidence sink page write failed: {type(exc).__name__}"),
                ) from exc
    except ReviewedHtmlReadError as exc:
        raise LexicalRunnerError(
            "PAGE_REPLAY_FAILED",
            _bounded_message(f"page replay failed: {exc.code}"),
        ) from exc

    if not reader.completed:
        raise LexicalRunnerError(
            "PAGE_REPLAY_INCOMPLETE",
            "page replay ended without a finalized reviewed HTML identity",
        )
    try:
        digest = reader.validated_input.html_sha256
    except ReviewedHtmlReadError as exc:
        raise LexicalRunnerError(
            "PAGE_REPLAY_INCOMPLETE",
            _bounded_message(f"page replay identity unavailable: {exc.code}"),
        ) from exc
    if digest != expected_html_sha256:
        raise LexicalRunnerError(
            "REPLAY_IDENTITY_CHANGED",
            "reviewed HTML identity changed during component page replay",
        )


def _filter_block_for_component(record: BlockRecord, component: Component) -> BlockRecord:
    kept: list[DictionaryOccurrence | UnitOccurrence | ValueOccurrence] = []
    for occurrence in record.occurrences:
        if isinstance(occurrence, DictionaryOccurrence):
            if component in occurrence.applies_to:
                kept.append(occurrence)
        elif isinstance(occurrence, UnitOccurrence):
            if component is Component.UNITS:
                kept.append(occurrence)
        elif component in occurrence.applies_to:
            kept.append(occurrence)
    if len(kept) == len(record.occurrences):
        return record
    return BlockRecord(block=record.block, occurrences=tuple(kept))


def _count_and_record_matches(
    monitor: RunMonitoringAccumulator,
    component: Component,
    record: BlockRecord,
) -> int:
    stats = monitor.ensure_component(component)
    count = 0
    for occurrence in record.occurrences:
        if isinstance(occurrence, DictionaryOccurrence):
            if component not in occurrence.applies_to:
                continue
            count += 1
            stats.add_method(occurrence.candidates[0].evidence.method, count=1)
        elif isinstance(occurrence, UnitOccurrence):
            if component is not Component.UNITS:
                continue
            count += 1
            stats.add_method("unit", count=1)
        elif component in occurrence.applies_to:
            count += 1
            stats.add_method("value", count=1)
    return count


def _add_term_counts(monitor: RunMonitoringAccumulator, counter: EligibleTermCounter) -> None:
    if monitor.eligible_terms is None:
        monitor.eligible_terms = counter.term_count
    else:
        monitor.eligible_terms += counter.term_count
    if monitor.eligible_rows is None:
        monitor.eligible_rows = counter.row_count
    else:
        monitor.eligible_rows += counter.row_count


def _build_provenance(
    *,
    run_id: str,
    config: EffectiveExecutionConfiguration,
    validated_input: ReviewedHtmlV1Input,
    knowledge: KnowledgeSnapshotIdentity,
    monitor: RunMonitoringAccumulator,
) -> RunProvenance:
    timings = tuple(
        ElapsedTiming(name=name, elapsed_ms=value)
        for name, value in monitor.stage_timings_ms.items()
    )
    measurements = list(monitor.freeze().measurements)
    return RunProvenance(
        run_id=run_id,
        requested_presets=config.extraction.presets,
        requested_components=config.extraction.components,
        resolved_components=config.resolved_components,
        fuzzy_requested=config.extraction.fuzzy_enabled,
        input_html_sha256=validated_input.html_sha256,
        knowledge=knowledge,
        configuration_sha256=effective_configuration_sha256(config),
        rules_sha256=fixed_rules_sha256(),
        engine_version=_engine_version(),
        dependency_versions=_dependency_versions(),
        timings=timings,
        measurements=tuple(measurements),
    )


def _engine_version() -> str:
    try:
        return metadata.version(_ENGINE_PACKAGE)
    except metadata.PackageNotFoundError:
        return "0.1.0"


def _dependency_versions() -> tuple[DependencyVersion, ...]:
    names = ("pyahocorasick", "pydantic", "pyyaml")
    versions: list[DependencyVersion] = []
    for name in names:
        try:
            versions.append(DependencyVersion(name=name, version=metadata.version(name)))
        except metadata.PackageNotFoundError:
            continue
    return tuple(versions)


def _overall_outcome(
    results: dict[Component, ComponentResult],
    resolved: Sequence[Component],
) -> ExtractionOutcome:
    statuses = {results[component].outcome for component in resolved}
    if statuses == {ExtractionOutcome.COMPLETED}:
        return ExtractionOutcome.COMPLETED
    usable = any(
        results[component].outcome in {ExtractionOutcome.COMPLETED, ExtractionOutcome.PARTIAL}
        for component in resolved
    )
    if not usable:
        return ExtractionOutcome.FAILED
    return ExtractionOutcome.PARTIAL


def _all_failed_results(
    resolved: Sequence[Component],
    error: SafeStructuredError,
) -> dict[Component, ComponentResult]:
    return {
        component: ComponentResult(
            component=component,
            outcome=ExtractionOutcome.FAILED,
            error=SafeStructuredError(
                code=error.code,
                message=error.message,
                component=component,
                retryable=False,
            ),
        )
        for component in resolved
    }


def _full_component_tuple(
    resolved: Sequence[Component],
    results: dict[Component, ComponentResult],
) -> tuple[ComponentResult, ...]:
    items: list[ComponentResult] = []
    resolved_set = set(resolved)
    for component in COMPONENT_ORDER:
        if component in resolved_set:
            items.append(results[component])
        else:
            items.append(
                ComponentResult(component=component, outcome=ExtractionOutcome.NOT_REQUESTED)
            )
    return tuple(items)


def _map_exception(exc: BaseException, *, component: Component | None) -> SafeStructuredError:
    mapped: SafeStructuredError | None = None
    if isinstance(exc, LexicalRunnerError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, ReviewedHtmlReadError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, SnapshotReadError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, DictionaryMatchError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, DictionaryAggregationError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, FieldMappingError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, ParameterUnitValueError):
        mapped = exc.to_structured_error()
    elif isinstance(exc, UnitAggregationError):
        mapped = exc.to_structured_error()
    if mapped is not None:
        return SafeStructuredError(
            code=mapped.code,
            message=_bounded_message(mapped.message),
            component=component if component is not None else mapped.component,
            retryable=False,
        )
    return SafeStructuredError(
        code="RUNNER_FAILED",
        message=_bounded_message(f"lexical run failed: {type(exc).__name__}"),
        component=component,
        retryable=False,
    )


def _safe_abort_run(sink: EvidenceSink, error: SafeStructuredError) -> None:
    try:
        sink.abort_run(error)
    except Exception:
        return


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _bounded_message(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE:
        return message
    return message[: _MAX_ERROR_MESSAGE - 3] + "..."


def _log(
    run_id: str,
    *,
    stage: str,
    status: str,
    component: Component | None,
    match_count: int | None = None,
    pages: int | None = None,
    blocks: int | None = None,
    elapsed_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    parts = [
        f"run_id={run_id}",
        f"stage={stage}",
        f"status={status}",
    ]
    if component is not None:
        parts.append(f"component={component.value}")
    if match_count is not None:
        parts.append(f"match_count={match_count}")
    if pages is not None:
        parts.append(f"pages={pages}")
    if blocks is not None:
        parts.append(f"blocks={blocks}")
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms}")
    if error_code is not None:
        parts.append(f"error_code={error_code}")
    logger.info(" ".join(parts))
