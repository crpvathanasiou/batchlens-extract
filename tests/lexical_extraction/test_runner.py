"""L12 callable extraction runner and sink lifecycle."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.lexical_extraction.configuration import (
    EffectiveExecutionConfiguration,
    ExtractionRequest,
    InputPaths,
    KnowledgePaths,
    OutputPaths,
    ResourceLimits,
    effective_configuration_sha256,
    resolve_components,
)
from app.lexical_extraction.contracts import (
    BlockRecord,
    Component,
    DictionaryOccurrence,
    ExtractionOutcome,
    PageEvidence,
    Preset,
    SafeStructuredError,
    UnitOccurrence,
    ValueOccurrence,
    validate_match_against_block,
)
from app.lexical_extraction.field_mapping import EligibleSearchTerm
from app.lexical_extraction.knowledge_snapshot import (
    FLAT_SOURCE_TABLES,
    derive_snapshot_id,
)
from app.lexical_extraction.runner import (
    EligibleTermCounter,
    EvidenceSink,
    LexicalRunResult,
    fixed_rules_sha256,
    run_lexical_extraction,
    run_lexical_extraction_from_config_path,
)

REVISION_ID = "00000000-0000-4000-8000-000000000001"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _root(
    *,
    version: str = "1",
    job_id: str = "job-l12",
    revision_id: str = REVISION_ID,
    generation: str = "1",
    status: str = "SUCCEEDED",
) -> str:
    return (
        "<!doctype html>"
        f'<html data-review-html-version="{version}" data-job-id="{job_id}" '
        f'data-review-revision-id="{revision_id}" data-review-generation="{generation}" '
        f'data-conversion-status="{status}">'
    )


def _wrap(body: str, **root_kwargs: str) -> str:
    return (
        f"{_root(**root_kwargs)}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body>'
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _write(path: Path, html: str) -> Path:
    path.write_bytes(html.encode("utf-8"))
    return path


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row(headers: tuple[str, ...], row_id: str, **overrides: str) -> tuple[str, ...]:
    values = dict.fromkeys(headers, "")
    values["row_id"] = row_id
    values.update(overrides)
    return tuple(values[header] for header in headers)


def _fixture_rows() -> dict[str, list[tuple[str, ...]]]:
    headers = dict(FLAT_SOURCE_TABLES)
    fda = headers["materials_fda_ema"]
    chebi = headers["materials_chebi"]
    equipment = headers["equipment"]
    unit = headers["unit_operations"]
    return {
        "materials_fda_ema": [
            _row(fda, "fda-water", material_name="Water", UNII="N/A"),
            _row(fda, "fda-nacl", material_name="Sodium Chloride", alias_name="NaCl"),
        ],
        "materials_chebi": [_row(chebi, "chebi-1", material_name="aqua")],
        "equipment": [
            _row(
                equipment,
                "eq-1",
                **{
                    "Equipment type (EN)": "Reactor",
                    "Operating parameter (EN)": "Pressure",
                    "Unit": "rpm",
                    "parameter_id": "p-1",
                    "manufacturer_id": "M1",
                    "model_id": "MOD1",
                },
            )
        ],
        "unit_operations": [
            _row(
                unit,
                "uo-1",
                **{
                    "Search term (EN)": "Mixing",
                    "Index this row": "TRUE",
                    "Match policy": "direct_candidate",
                    "record_type": "unit_operation",
                    "Process step (EN)": "Blend materials",
                    "Unit operation (EN)": "Mixing",
                    "Canonical unit operation": "Mixing",
                },
            )
        ],
    }


def _create_database(path: Path, rows: dict[str, list[tuple[str, ...]]]) -> None:
    connection = sqlite3.connect(path)
    try:
        for table_name, headers in FLAT_SOURCE_TABLES:
            columns = [
                f'{_quote(header)} TEXT NOT NULL{" PRIMARY KEY" if header == "row_id" else ""}'
                for header in headers
            ]
            connection.execute(f"CREATE TABLE {_quote(table_name)} ({', '.join(columns)})")
            table_rows = rows.get(table_name, [])
            if table_rows:
                placeholders = ", ".join("?" for _ in headers)
                names = ", ".join(_quote(header) for header in headers)
                connection.executemany(
                    f"INSERT INTO {_quote(table_name)} ({names}) VALUES ({placeholders})",
                    table_rows,
                )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()


def _dump(path: Path, payload: object) -> None:
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def _publish_snapshot(
    directory: Path,
    rows: dict[str, list[tuple[str, ...]]] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    chosen = _fixture_rows() if rows is None else rows
    _create_database(directory / "knowledge.sqlite", chosen)
    database = directory / "knowledge.sqlite"
    database_bytes = database.read_bytes()
    identity_sources: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for table_name, headers in FLAT_SOURCE_TABLES:
        source_sha = hashlib.sha256(table_name.encode("utf-8")).hexdigest()
        row_count = len(chosen.get(table_name, []))
        identity_sources.append({"logical_name": table_name, "sha256": source_sha})
        sources.append(
            {
                "logical_name": table_name,
                "relative_path": f"missing/{table_name}.csv",
                "sha256": source_sha,
                "size_bytes": 0,
                "headers": list(headers),
                "row_count": row_count,
                "blank_records_skipped": 0,
            }
        )
        tables.append(
            {
                "table": table_name,
                "columns": list(headers),
                "column_count": len(headers),
                "imported_rows": row_count,
            }
        )
    manifest: dict[str, Any] = {
        "flat_schema_version": 1,
        "preparation_version": "flat-sqlite-1",
        "snapshot_id": derive_snapshot_id(
            {
                "flat_schema_version": 1,
                "preparation_version": "flat-sqlite-1",
                "sources": identity_sources,
            }
        ),
        "snapshot_identity": {
            "flat_schema_version": 1,
            "preparation_version": "flat-sqlite-1",
            "sources": identity_sources,
        },
        "code_identity_sha256": "0" * 64,
        "completed_at": "2026-09-28T00:00:00+00:00",
        "completion_status": "complete",
        "sources": sources,
        "database": {
            "file_name": "knowledge.sqlite",
            "sha256": _sha256(database_bytes),
            "size_bytes": len(database_bytes),
            "user_version": 1,
        },
        "settings": {"journal_mode": "DELETE"},
    }
    report: dict[str, Any] = {
        "integrity_check": "ok",
        "content_digests_match": True,
        "source_files_unchanged": True,
        "wal_sidecar_absent": True,
        "elapsed_seconds": 0.1,
        "tables": tables,
        "blank_record_rule": "synthetic fixture",
    }
    _dump(directory / "manifest.json", manifest)
    _dump(directory / "validation_report.json", report)
    (directory / "FLAT_SQLITE_CONTRACT.md").write_text(
        "synthetic flat contract\n",
        encoding="utf-8",
    )
    return directory


def _sample_html() -> str:
    return _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<h2 data-generated="true">Page 1</h2>'
        '<article class="element" data-kind="text" data-element-id="b1">'
        '<p data-node-id="b1">Mixing Water at 10 rpm and Pressure set to 1 bar</p>'
        "</article>"
        '<article class="element" data-kind="text" data-element-id="b-empty">'
        '<p data-node-id="b-empty"></p></article></section>'
        '<section class="page" id="source-page-2" data-page="2">'
        '<h2 data-generated="true">Page 2</h2></section>'
        '<section class="page" id="source-page-3" data-page="3">'
        '<article class="element" data-kind="text" data-element-id="b3">'
        '<p data-node-id="b3">Blend materials with NaCl</p></article></section>'
    )


def _limits() -> ResourceLimits:
    return ResourceLimits(
        sqlite_read_batch_rows=100,
        sqlite_cache_kib=1024,
        max_terms_per_shard=1000,
        max_term_codepoints_per_shard=100_000,
        result_buffer_records=1000,
    )


def _config(
    tmp_path: Path,
    *,
    presets: tuple[Preset, ...] = (),
    components: tuple[Component, ...] = (Component.MATERIALS,),
    fuzzy_enabled: bool = False,
    html_name: str = "reviewed.html",
    html_text: str | None = None,
) -> EffectiveExecutionConfiguration:
    tmp_path.mkdir(parents=True, exist_ok=True)
    html_path = _write(tmp_path / html_name, html_text if html_text is not None else _sample_html())
    snapshot = _publish_snapshot(tmp_path / "snapshot")
    output = tmp_path / "out"
    output.mkdir(exist_ok=True)
    request = ExtractionRequest(
        presets=presets,
        components=components,
        fuzzy_enabled=fuzzy_enabled,
    )
    return EffectiveExecutionConfiguration(
        input=InputPaths(reviewed_html_path=html_path.resolve()),
        knowledge=KnowledgePaths(snapshot_directory=snapshot.resolve()),
        output=OutputPaths(directory=output.resolve()),
        extraction=request,
        resolved_components=resolve_components(presets, components),
        resources=_limits(),
    )


def _empty_component_list() -> list[Component]:
    return []


def _empty_abort_list() -> list[tuple[Component, SafeStructuredError]]:
    return []


def _empty_page_list() -> list[tuple[Component, PageEvidence]]:
    return []


def _empty_block_list() -> list[tuple[Component, BlockRecord]]:
    return []


@dataclass
class RecordingSink:
    """Small in-memory sink retaining a synthetic fixture for tests only.

    Committed components remain listed after ``abort_run``; ``abort_component``
    is recorded separately and must not be used to retract a completed component.
    """

    fail_on_component_write: Component | None = None
    fail_on_nth_block_write: int | None = None
    fail_complete_component: Component | None = None
    fail_complete_run: bool = False
    run_id: str | None = None
    begun_components: list[Component] = field(default_factory=_empty_component_list)
    completed_components: list[Component] = field(default_factory=_empty_component_list)
    aborted_components: list[tuple[Component, SafeStructuredError]] = field(
        default_factory=_empty_abort_list
    )
    pages: list[tuple[Component, PageEvidence]] = field(default_factory=_empty_page_list)
    blocks: list[tuple[Component, BlockRecord]] = field(default_factory=_empty_block_list)
    run_completed: bool = False
    run_aborted: SafeStructuredError | None = None
    _block_writes: int = 0

    def begin_run(self, run_id: str) -> None:
        self.run_id = run_id

    def begin_component(self, component: Component) -> None:
        self.begun_components.append(component)

    def write_page(self, component: Component, page: PageEvidence) -> None:
        self.pages.append((component, page))

    def write_block(self, component: Component, record: BlockRecord) -> None:
        self._block_writes += 1
        if self.fail_on_component_write is component:
            raise RuntimeError("injected sink component failure")
        if (
            self.fail_on_nth_block_write is not None
            and self._block_writes >= self.fail_on_nth_block_write
        ):
            raise RuntimeError("injected sink block failure")
        self.blocks.append((component, record))

    def complete_component(self, component: Component) -> None:
        if self.fail_complete_component is component:
            raise RuntimeError("injected complete failure")
        self.completed_components.append(component)

    def abort_component(self, component: Component, error: SafeStructuredError) -> None:
        if component in self.completed_components:
            raise AssertionError("abort_component called for a committed component")
        self.aborted_components.append((component, error))

    def complete_run(self) -> None:
        if self.fail_complete_run:
            raise RuntimeError("injected complete_run failure")
        self.run_completed = True

    def abort_run(self, error: SafeStructuredError) -> None:
        self.run_aborted = error

    def completed_blocks(self, component: Component) -> list[BlockRecord]:
        if component not in self.completed_components:
            return []
        return [record for item, record in self.blocks if item is component]

    def pages_for(self, component: Component) -> list[PageEvidence]:
        return [page for item, page in self.pages if item is component]


def _outcome_for(result: LexicalRunResult, component: Component):
    assert result.extraction is not None
    for item in result.extraction.components:
        if item.component is component:
            return item
    raise AssertionError(f"missing outcome for {component}")


def test_materials_component_and_empty_page_zero_hits(tmp_path: Path) -> None:
    config = _config(tmp_path, components=(Component.MATERIALS,))
    sink = RecordingSink()
    result = run_lexical_extraction(config, sink)

    assert result.pre_validation is None
    assert result.validated_input is not None
    assert result.knowledge is not None
    assert result.provenance is not None
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED
    materials = _outcome_for(result, Component.MATERIALS)
    assert materials.outcome is ExtractionOutcome.COMPLETED
    assert materials.match_count is not None and materials.match_count >= 1
    assert Component.MATERIALS in sink.completed_components
    assert sink.run_completed is True

    page_numbers = {page.page_number for page in sink.pages_for(Component.MATERIALS)}
    assert 2 in page_numbers  # empty page emitted
    assert [page.page_number for page in sink.pages_for(Component.MATERIALS)] == [1, 2, 3]
    empty_blocks = [record for _, record in sink.blocks if record.block.node_id == "b-empty"]
    assert empty_blocks
    assert empty_blocks[0].occurrences == ()

    # Offsets agree with original block text.
    for _, record in sink.blocks:
        for occurrence in record.occurrences:
            if isinstance(occurrence, DictionaryOccurrence):
                validate_match_against_block(occurrence.location, record.block)
                assert (
                    record.block.text[occurrence.location.start_char : occurrence.location.end_char]
                    == occurrence.location.matched_text
                )


def test_combined_preset_and_full_selection(tmp_path: Path) -> None:
    materials_qty = _config(
        tmp_path / "mq",
        presets=(Preset.MATERIALS_WITH_QUANTITIES,),
        components=(),
    )
    sink_mq = RecordingSink()
    result_mq = run_lexical_extraction(materials_qty, sink_mq)
    assert result_mq.extraction is not None
    assert result_mq.extraction.overall is ExtractionOutcome.COMPLETED
    completed_mq = {
        item.component
        for item in result_mq.extraction.components
        if item.outcome is ExtractionOutcome.COMPLETED
    }
    assert completed_mq == {
        Component.MATERIALS,
        Component.QUANTITY_EXPRESSIONS,
        Component.UNITS,
    }

    full = _config(tmp_path / "full", presets=(Preset.FULL,), components=())
    sink_full = RecordingSink()
    result_full = run_lexical_extraction(full, sink_full)
    assert result_full.extraction is not None
    assert result_full.extraction.overall is ExtractionOutcome.COMPLETED
    completed = [
        item.component
        for item in result_full.extraction.components
        if item.outcome is ExtractionOutcome.COMPLETED
    ]
    assert completed == list(resolve_components((Preset.FULL,), ()))


def test_dictionary_and_l10_no_duplicate_parameter_or_value(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        presets=(Preset.EQUIPMENT_WITH_PARAMETERS,),
        components=(),
    )
    sink = RecordingSink()
    result = run_lexical_extraction(config, sink)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED

    param_occ_ids: list[str] = []
    value_keys: list[tuple[str, int, int]] = []
    for component, record in sink.blocks:
        if component is Component.PARAMETER_NAMES:
            for occurrence in record.occurrences:
                if isinstance(occurrence, DictionaryOccurrence):
                    param_occ_ids.append(occurrence.occurrence_id)
        if component in {
            Component.QUANTITY_EXPRESSIONS,
            Component.PARAMETER_VALUE_EXPRESSIONS,
        }:
            for occurrence in record.occurrences:
                if isinstance(occurrence, ValueOccurrence):
                    span = occurrence.expression.span
                    value_keys.append((record.block.node_id, span.start_char, span.end_char))
    assert len(param_occ_ids) == len(set(param_occ_ids))
    assert len(value_keys) == len(set(value_keys))


def test_fuzzy_off_on_and_units_remain_non_fuzzy(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="b1">'
        '<p data-node-id="b1">Presure at 10 rpm</p></article></section>'
    )
    off = _config(
        tmp_path / "off",
        components=(Component.PARAMETER_NAMES, Component.UNITS),
        fuzzy_enabled=False,
        html_text=html,
    )
    sink_off = RecordingSink()
    result_off = run_lexical_extraction(off, sink_off)
    assert _outcome_for(result_off, Component.PARAMETER_NAMES).match_count == 0

    on = _config(
        tmp_path / "on",
        components=(Component.PARAMETER_NAMES, Component.UNITS),
        fuzzy_enabled=True,
        html_text=html,
    )
    sink_on = RecordingSink()
    result_on = run_lexical_extraction(on, sink_on)
    assert (_outcome_for(result_on, Component.PARAMETER_NAMES).match_count or 0) >= 1

    unit_methods: set[str] = set()
    for component, record in sink_on.blocks:
        if component is not Component.UNITS:
            continue
        for occurrence in record.occurrences:
            if isinstance(occurrence, UnitOccurrence):
                unit_methods.add(occurrence.mention.evidence.method)
                assert occurrence.mention.evidence.method in {"exact", "normalized_exact"}
    assert "fuzzy" not in unit_methods
    assert unit_methods <= {"exact", "normalized_exact"}


def test_completed_zero_for_miss_component(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="b1">'
        '<p data-node-id="b1">no catalogue hits here</p></article></section>'
    )
    config = _config(tmp_path, components=(Component.MATERIALS,), html_text=html)
    sink = RecordingSink()
    result = run_lexical_extraction(config, sink)
    materials = _outcome_for(result, Component.MATERIALS)
    assert materials.outcome is ExtractionOutcome.COMPLETED
    assert materials.match_count == 0
    assert Component.MATERIALS in result.monitoring.zero_result_components
    assert Component.MATERIALS in sink.completed_components


def test_isolated_component_failure_preserves_completed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.EQUIPMENT),
    )
    sink = RecordingSink(fail_on_component_write=Component.EQUIPMENT)
    result = run_lexical_extraction(config, sink)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.PARTIAL
    assert _outcome_for(result, Component.MATERIALS).outcome is ExtractionOutcome.COMPLETED
    assert _outcome_for(result, Component.EQUIPMENT).outcome is ExtractionOutcome.FAILED
    assert Component.MATERIALS in sink.completed_components
    assert any(component is Component.EQUIPMENT for component, _ in sink.aborted_components)
    assert Component.EQUIPMENT not in sink.completed_components


def test_shared_preflight_failures(tmp_path: Path) -> None:
    missing_html = _config(tmp_path / "missing-html", components=(Component.MATERIALS,))
    missing_html.input.reviewed_html_path.unlink()
    sink_html = RecordingSink()
    result_html = run_lexical_extraction(missing_html, sink_html)
    assert result_html.pre_validation is not None
    assert result_html.validated_input is None
    assert result_html.provenance is None
    assert sink_html.run_aborted is not None

    bad_snap = _config(tmp_path / "bad-snap", components=(Component.MATERIALS, Component.UNITS))
    (bad_snap.knowledge.snapshot_directory / "manifest.json").write_text("{", encoding="utf-8")
    sink_snap = RecordingSink()
    result_snap = run_lexical_extraction(bad_snap, sink_snap)
    assert result_snap.pre_validation is None
    assert result_snap.validated_input is not None
    assert result_snap.provenance is None
    assert result_snap.extraction is not None
    assert result_snap.extraction.overall is ExtractionOutcome.FAILED
    assert all(
        item.outcome is ExtractionOutcome.FAILED
        for item in result_snap.extraction.components
        if item.outcome is not ExtractionOutcome.NOT_REQUESTED
    )


def test_mid_replay_identity_change(tmp_path: Path) -> None:
    config = _config(tmp_path, components=(Component.MATERIALS,))
    original = config.input.reviewed_html_path.read_bytes()

    class MutatingSink(RecordingSink):
        def begin_component(self, component: Component) -> None:
            super().begin_component(component)
            # Change bytes after HTML validation pinned the digest.
            config.input.reviewed_html_path.write_bytes(original + b" ")

    sink = MutatingSink()
    result = run_lexical_extraction(config, sink)
    assert result.extraction is not None
    materials = _outcome_for(result, Component.MATERIALS)
    assert materials.outcome is ExtractionOutcome.FAILED
    assert materials.error is not None
    assert materials.error.code in {
        "REPLAY_IDENTITY_CHANGED",
        "BLOCK_READ_FAILED",
        "REPLAY_INCOMPLETE",
    }
    assert Component.MATERIALS not in sink.completed_components


def test_sink_failure_and_early_abort(tmp_path: Path) -> None:
    config = _config(tmp_path, components=(Component.MATERIALS,))
    sink = RecordingSink(fail_on_nth_block_write=1)
    result = run_lexical_extraction(config, sink)
    materials = _outcome_for(result, Component.MATERIALS)
    assert materials.outcome is ExtractionOutcome.FAILED
    assert materials.error is not None
    assert materials.error.code == "SINK_WRITE_FAILED"
    assert Component.MATERIALS not in sink.completed_components
    assert any(component is Component.MATERIALS for component, _ in sink.aborted_components)


def test_stable_evidence_and_provenance_digests(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.UNITS),
    )
    sink_a = RecordingSink()
    sink_b = RecordingSink()
    first = run_lexical_extraction(config, sink_a)
    second = run_lexical_extraction(config, sink_b)
    assert first.provenance is not None and second.provenance is not None
    assert first.provenance.run_id != second.provenance.run_id
    assert first.provenance.configuration_sha256 == effective_configuration_sha256(config)
    assert first.provenance.rules_sha256 == fixed_rules_sha256()
    assert first.provenance.rules_sha256 == second.provenance.rules_sha256
    assert first.validated_input == second.validated_input
    assert first.knowledge == second.knowledge

    def _evidence_fingerprint(sink: RecordingSink) -> list[tuple[object, ...]]:
        items: list[tuple[object, ...]] = []
        for component, record in sink.blocks:
            if component not in sink.completed_components:
                continue
            for occurrence in record.occurrences:
                if isinstance(occurrence, DictionaryOccurrence):
                    items.append(
                        (
                            component.value,
                            record.block.node_id,
                            occurrence.location.start_char,
                            occurrence.location.end_char,
                            occurrence.location.matched_text,
                            tuple(c.row_id for c in occurrence.candidates),
                        )
                    )
                elif isinstance(occurrence, UnitOccurrence):
                    items.append(
                        (
                            component.value,
                            record.block.node_id,
                            occurrence.mention.span.start_char,
                            occurrence.mention.span.end_char,
                            occurrence.mention.span.matched_text,
                        )
                    )
        return sorted(items)

    assert _evidence_fingerprint(sink_a) == _evidence_fingerprint(sink_b)
    assert first.monitoring.peak_memory_method in {
        "windows_psapi_peak_working_set",
        "posix_resource_ru_maxrss",
        "unavailable",
    }
    if first.monitoring.peak_memory_method == "unavailable":
        assert first.monitoring.peak_process_memory_bytes is None


def test_config_path_entry_and_log_redaction(tmp_path: Path) -> None:
    config = _config(tmp_path, components=(Component.MATERIALS,))
    yaml_path = tmp_path / "run.yaml"
    yaml_path.write_text(
        "schema_version: 1\n"
        f"input:\n  reviewed_html_path: {config.input.reviewed_html_path.as_posix()}\n"
        f"knowledge:\n  snapshot_directory: {config.knowledge.snapshot_directory.as_posix()}\n"
        f"output:\n  directory: {config.output.directory.as_posix()}\n"
        "extraction:\n  presets: []\n  components: [materials]\n  fuzzy_enabled: false\n"
        "resources:\n"
        "  sqlite_read_batch_rows: 100\n"
        "  sqlite_cache_kib: 1024\n"
        "  max_terms_per_shard: 1000\n"
        "  max_term_codepoints_per_shard: 100000\n"
        "  result_buffer_records: 1000\n",
        encoding="utf-8",
    )
    sink = RecordingSink()
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture()
    runner_logger = logging.getLogger("app.lexical_extraction.runner")
    previous_level = runner_logger.level
    runner_logger.setLevel(logging.INFO)
    runner_logger.addHandler(handler)
    try:
        result = run_lexical_extraction_from_config_path(yaml_path, sink)
    finally:
        runner_logger.removeHandler(handler)
        runner_logger.setLevel(previous_level)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED
    joined = " ".join(captured)
    assert "Mixing Water" not in joined
    assert str(config.input.reviewed_html_path) not in joined
    assert "run_id=" in joined


def test_evidence_sink_is_protocol() -> None:
    assert isinstance(RecordingSink(), EvidenceSink)


def test_bounded_eligible_row_counting_without_row_id_set() -> None:
    def terms() -> list[EligibleSearchTerm]:
        items: list[EligibleSearchTerm] = []
        for index in range(500):
            row_id = f"row-{index}"
            items.append(
                EligibleSearchTerm(
                    literal=f"Term{index}A",
                    component=Component.MATERIALS,
                    term_role="material_name",
                    source_table="materials_fda_ema",
                    source_field="material_name",
                    row_id=row_id,
                )
            )
            items.append(
                EligibleSearchTerm(
                    literal=f"Term{index}B",
                    component=Component.MATERIALS,
                    term_role="alias_name",
                    source_table="materials_fda_ema",
                    source_field="alias_name",
                    row_id=row_id,
                )
            )
        # A later table row, still consecutive by key.
        items.append(
            EligibleSearchTerm(
                literal="OnlyOne",
                component=Component.MATERIALS,
                term_role="material_name",
                source_table="materials_chebi",
                source_field="material_name",
                row_id="chebi-only",
            )
        )
        return items

    # Conceptual source rows with no eligible terms never enter the stream.
    counter = EligibleTermCounter(terms())
    consumed = list(counter)
    assert len(consumed) == 1001
    assert counter.term_count == 1001
    assert counter.row_count == 501
    assert not hasattr(counter, "row_keys")
    assert set(counter.__dict__) <= {"terms", "term_count", "row_count"}


def test_component_scoped_pages_for_combined_l10(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.PARAMETER_NAMES, Component.UNITS),
    )
    sink = RecordingSink()
    result = run_lexical_extraction(config, sink)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED
    assert result.run_error is None

    for component in (Component.PARAMETER_NAMES, Component.UNITS):
        pages = sink.pages_for(component)
        assert [page.page_number for page in pages] == [1, 2, 3]
        assert pages[1].page_number == 2  # empty page preserved
        assert len(pages) == 3

    assert len(sink.pages_for(Component.PARAMETER_NAMES)) == 3
    assert len(sink.pages_for(Component.UNITS)) == 3


def test_l10_second_complete_preserves_first_committed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.PARAMETER_NAMES, Component.UNITS),
    )
    sink = RecordingSink(fail_complete_component=Component.UNITS)
    result = run_lexical_extraction(config, sink)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.PARTIAL
    assert _outcome_for(result, Component.PARAMETER_NAMES).outcome is ExtractionOutcome.COMPLETED
    assert _outcome_for(result, Component.UNITS).outcome is ExtractionOutcome.FAILED
    assert Component.PARAMETER_NAMES in sink.completed_components
    assert Component.UNITS not in sink.completed_components
    assert any(component is Component.UNITS for component, _ in sink.aborted_components)
    assert all(
        component is not Component.PARAMETER_NAMES for component, _ in sink.aborted_components
    )


def test_complete_run_failure_preserves_identities_and_outcomes(tmp_path: Path) -> None:
    config = _config(tmp_path, components=(Component.MATERIALS,))
    sink = RecordingSink(fail_complete_run=True)
    result = run_lexical_extraction(config, sink)
    assert result.validated_input is not None
    assert result.knowledge is not None
    assert result.provenance is not None
    assert result.extraction is not None
    assert result.run_error is not None
    assert result.run_error.code == "SINK_COMPLETE_RUN_FAILED"
    assert _outcome_for(result, Component.MATERIALS).outcome is ExtractionOutcome.COMPLETED
    assert Component.MATERIALS in sink.completed_components
    assert sink.run_completed is False
    assert sink.run_aborted is not None
    assert sink.run_aborted.code == "SINK_COMPLETE_RUN_FAILED"
