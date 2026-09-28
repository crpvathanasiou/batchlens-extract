"""L13 filesystem publication and CLI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.lexical_extraction import __main__ as lexical_main
from app.lexical_extraction.configuration import (
    EffectiveExecutionConfiguration,
    ExtractionRequest,
    InputPaths,
    KnowledgePaths,
    OutputPaths,
    ResourceLimits,
    resolve_components,
)
from app.lexical_extraction.contracts import (
    BlockEvidence,
    BlockRecord,
    CharSpan,
    Component,
    DictionaryOccurrence,
    ExactEvidence,
    ExtractionOutcome,
    FdaEmaMaterialCandidate,
    PageCoverage,
    PageEvidence,
    Preset,
    PublicationStatus,
    validate_match_against_block,
)
from app.lexical_extraction.knowledge_snapshot import (
    FLAT_SOURCE_TABLES,
    derive_snapshot_id,
)
from app.lexical_extraction.publication import (
    COMPONENT_ARTIFACT_SCHEMA_VERSION,
    MANIFEST_FILE_NAME,
    FilesystemEvidenceSink,
    PublicationError,
    finalize_publication,
    guard_output_outside_snapshot,
    iter_component_pages,
    load_final_manifest,
    locate_hit,
    open_component_artifact_stream,
    publish_lexical_run,
    verify_artifact_hashes,
)
from app.lexical_extraction.runner import run_lexical_extraction

REVISION_ID = "00000000-0000-4000-8000-000000000001"


def _collect_pages(
    artifact_path: Path,
) -> list[tuple[PageEvidence, list[BlockRecord]]]:
    """Materialize streamed pages for small fixtures only."""

    collected: list[tuple[PageEvidence, list[BlockRecord]]] = []
    for streamed in iter_component_pages(artifact_path):
        collected.append((streamed.page, list(streamed.iter_blocks())))
    return collected


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _root(
    *,
    version: str = "1",
    job_id: str = "job-l13",
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


def _publish_snapshot(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    chosen = _fixture_rows()
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


def _unicode_html() -> str:
    return _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="u1">'
        '<p data-node-id="u1">Water café Water</p></article></section>'
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
    html_text: str | None = None,
) -> EffectiveExecutionConfiguration:
    tmp_path.mkdir(parents=True, exist_ok=True)
    html_body = html_text if html_text is not None else _sample_html()
    html_path = _write(tmp_path / "reviewed.html", html_body)
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


def _write_yaml(path: Path, config: EffectiveExecutionConfiguration) -> Path:
    fuzzy = "true" if config.extraction.fuzzy_enabled else "false"
    presets = ", ".join(item.value for item in config.extraction.presets)
    components = ", ".join(item.value for item in config.extraction.components)
    text = (
        "schema_version: 1\n"
        "input:\n"
        f"  reviewed_html_path: {config.input.reviewed_html_path.as_posix()}\n"
        "knowledge:\n"
        f"  snapshot_directory: {config.knowledge.snapshot_directory.as_posix()}\n"
        "output:\n"
        f"  directory: {config.output.directory.as_posix()}\n"
        "extraction:\n"
        f"  presets: [{presets}]\n"
        f"  components: [{components}]\n"
        f"  fuzzy_enabled: {fuzzy}\n"
        "resources:\n"
        f"  sqlite_read_batch_rows: {config.resources.sqlite_read_batch_rows}\n"
        f"  sqlite_cache_kib: {config.resources.sqlite_cache_kib}\n"
        f"  max_terms_per_shard: {config.resources.max_terms_per_shard}\n"
        f"  max_term_codepoints_per_shard: {config.resources.max_term_codepoints_per_shard}\n"
        f"  result_buffer_records: {config.resources.result_buffer_records}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


def test_one_component_round_trip_and_empty_pages(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sink = FilesystemEvidenceSink(config.output.directory)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)

    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED
    assert publication.publication.status is PublicationStatus.COMPLETED
    assert publication.manifest_path is not None
    assert publication.exit_code == 0
    assert publication.manifest_path.name == MANIFEST_FILE_NAME

    manifest = load_final_manifest(publication.manifest_path)
    artifacts = verify_artifact_hashes(manifest, publication.run_directory)
    assert len(artifacts) == 1
    assert artifacts[0].component is Component.MATERIALS

    pages = _collect_pages(publication.run_directory / artifacts[0].relative_path)
    assert [page.page_number for page, _ in pages] == [1, 2, 3]
    assert pages[1][1] == () or pages[1][1] == []  # empty page retained
    empty = [block for _, blocks in pages for block in blocks if block.block.node_id == "b-empty"]
    assert empty and empty[0].occurrences == ()
    for _, blocks in pages:
        for record in blocks:
            for occurrence in record.occurrences:
                if isinstance(occurrence, DictionaryOccurrence):
                    validate_match_against_block(occurrence.location, record.block)


def test_combined_and_full_selection(tmp_path: Path) -> None:
    combined = _config(
        tmp_path / "combined",
        presets=(Preset.MATERIALS_WITH_QUANTITIES,),
        components=(),
    )
    sink = FilesystemEvidenceSink(combined.output.directory)
    result = run_lexical_extraction(combined, sink)
    publication = finalize_publication(sink, result)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.COMPLETED
    assert publication.exit_code == 0
    assert {item.component for item in publication.artifacts} == {
        Component.MATERIALS,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
    }

    full = _config(tmp_path / "full", presets=(Preset.FULL,), components=())
    sink_full = FilesystemEvidenceSink(full.output.directory)
    result_full = run_lexical_extraction(full, sink_full)
    publication_full = finalize_publication(sink_full, result_full)
    assert result_full.extraction is not None
    assert result_full.extraction.overall is ExtractionOutcome.COMPLETED
    assert publication_full.exit_code == 0
    assert len(publication_full.artifacts) == 8


def test_unicode_overlap_and_locate_hit(tmp_path: Path) -> None:
    config = _config(tmp_path, html_text=_unicode_html())
    sink = FilesystemEvidenceSink(config.output.directory)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert publication.manifest_path is not None
    artifact = publication.run_directory / publication.artifacts[0].relative_path
    pages = _collect_pages(artifact)
    assert pages[0][0].page_number == 1
    text = pages[0][1][0].block.text
    assert "café" in text
    # Overlapping / repeated Water spans remain distinct occurrences when present.
    water_spans: list[tuple[int, int]] = []
    for record in pages[0][1]:
        for occurrence in record.occurrences:
            if isinstance(occurrence, DictionaryOccurrence):
                if occurrence.location.matched_text == "Water":
                    water_spans.append(
                        (occurrence.location.start_char, occurrence.location.end_char)
                    )
                    validate_match_against_block(occurrence.location, record.block)
    assert water_spans
    first = water_spans[0]
    found = locate_hit(
        artifact,
        page_number=1,
        node_id="u1",
        start_char=first[0],
        end_char=first[1],
    )
    assert found is not None


def test_deterministic_artifact_bytes(tmp_path: Path) -> None:
    config_a = _config(tmp_path / "a")
    config_b = _config(tmp_path / "b")
    # Pin identical HTML/snapshot bytes by copying A's inputs into B's paths already created.
    config_b.input.reviewed_html_path.write_bytes(config_a.input.reviewed_html_path.read_bytes())
    companion_names = (
        "knowledge.sqlite",
        "manifest.json",
        "validation_report.json",
        "FLAT_SQLITE_CONTRACT.md",
    )
    for name in companion_names:
        (config_b.knowledge.snapshot_directory / name).write_bytes(
            (config_a.knowledge.snapshot_directory / name).read_bytes()
        )

    sink_a = FilesystemEvidenceSink(config_a.output.directory)
    result_a = run_lexical_extraction(config_a, sink_a)
    publication_a = finalize_publication(sink_a, result_a)
    sink_b = FilesystemEvidenceSink(config_b.output.directory)
    result_b = run_lexical_extraction(config_b, sink_b)
    publication_b = finalize_publication(sink_b, result_b)

    bytes_a = (publication_a.run_directory / publication_a.artifacts[0].relative_path).read_bytes()
    bytes_b = (publication_b.run_directory / publication_b.artifacts[0].relative_path).read_bytes()
    payload_a = json.loads(bytes_a.decode("utf-8"))
    payload_b = json.loads(bytes_b.decode("utf-8"))
    payload_a.pop("run_id")
    payload_b.pop("run_id")
    assert payload_a == payload_b
    assert payload_a["schema_version"] == COMPONENT_ARTIFACT_SCHEMA_VERSION


def test_completed_zero_component(tmp_path: Path) -> None:
    html = _wrap(
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="z1">'
        '<p data-node-id="z1">No catalogue terms here</p></article></section>'
    )
    config = _config(tmp_path, components=(Component.EQUIPMENT,), html_text=html)
    sink = FilesystemEvidenceSink(config.output.directory)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert result.extraction is not None
    equipment = next(
        item for item in result.extraction.components if item.component is Component.EQUIPMENT
    )
    assert equipment.outcome is ExtractionOutcome.COMPLETED
    assert equipment.match_count == 0
    assert publication.exit_code == 0
    assert len(publication.artifacts) == 1
    artifact_path = publication.run_directory / publication.artifacts[0].relative_path
    pages = _collect_pages(artifact_path)
    assert pages
    assert all(not record.occurrences for _, blocks in pages for record in blocks)


def test_failed_component_after_completed_publishes_partial(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.EQUIPMENT),
    )
    sink = FilesystemEvidenceSink(
        config.output.directory,
        fail_complete_component=Component.EQUIPMENT,
    )
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.PARTIAL
    assert publication.publication.status is PublicationStatus.COMPLETED
    assert publication.exit_code == 1
    assert [item.component for item in publication.artifacts] == [Component.MATERIALS]
    manifest = load_final_manifest(publication.manifest_path)  # type: ignore[arg-type]
    assert manifest["run_status"] == "partial"
    assert len(manifest["artifacts"]) == 1
    failed = next(
        item for item in result.extraction.components if item.component is Component.EQUIPMENT
    )
    assert failed.outcome is ExtractionOutcome.FAILED


def test_failed_sink_write_no_success_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sink = FilesystemEvidenceSink(
        config.output.directory,
        fail_on_component_write=Component.MATERIALS,
    )
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.FAILED
    # All-failed sealed run may still publish a truthful empty-artifact manifest.
    if publication.manifest_path is not None:
        manifest = load_final_manifest(publication.manifest_path)
        assert manifest["artifacts"] == []
        assert publication.exit_code == 2
    else:
        assert publication.exit_code == 3
        assert not (publication.run_directory / MANIFEST_FILE_NAME).exists()


def test_failed_second_component_completion_keeps_first(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.UNIT_OPERATIONS),
    )
    sink = FilesystemEvidenceSink(
        config.output.directory,
        fail_complete_component=Component.UNIT_OPERATIONS,
    )
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert publication.exit_code == 1
    assert Component.MATERIALS in {item.component for item in publication.artifacts}
    assert Component.UNIT_OPERATIONS not in {item.component for item in publication.artifacts}


def test_failed_complete_run_no_final_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sink = FilesystemEvidenceSink(config.output.directory, fail_complete_run=True)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert result.run_error is not None
    assert result.run_error.code == "SINK_COMPLETE_RUN_FAILED"
    assert publication.publication.status is PublicationStatus.FAILED
    assert publication.manifest_path is None
    assert publication.exit_code == 3
    assert not (publication.run_directory / MANIFEST_FILE_NAME).exists()
    # Committed component artifact may remain, but is not a published run.
    assert publication.artifacts


def test_failed_artifact_rename_treats_component_failed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.EQUIPMENT),
    )
    sink = FilesystemEvidenceSink(
        config.output.directory,
        fail_artifact_rename=Component.EQUIPMENT,
    )
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert result.extraction is not None
    assert result.extraction.overall is ExtractionOutcome.PARTIAL
    assert publication.exit_code == 1
    assert [item.component for item in publication.artifacts] == [Component.MATERIALS]


def test_failed_manifest_write_and_rename(tmp_path: Path) -> None:
    config = _config(tmp_path / "write")
    sink = FilesystemEvidenceSink(config.output.directory, fail_manifest_write=True)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert publication.manifest_path is None
    assert publication.exit_code == 3
    assert publication.publication.status is PublicationStatus.FAILED
    assert not (publication.run_directory / MANIFEST_FILE_NAME).exists()

    config2 = _config(tmp_path / "rename")
    sink2 = FilesystemEvidenceSink(config2.output.directory, fail_manifest_rename=True)
    result2 = run_lexical_extraction(config2, sink2)
    publication2 = finalize_publication(sink2, result2)
    assert publication2.manifest_path is None
    assert publication2.exit_code == 3
    assert not (publication2.run_directory / MANIFEST_FILE_NAME).exists()


def test_incomplete_staging_without_final_manifest(tmp_path: Path) -> None:
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("run-crash")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    # Crash before complete_component / complete_run.
    assert sink.run_directory is not None
    assert not (sink.run_directory / MANIFEST_FILE_NAME).exists()
    assert list((sink.run_directory / "artifacts").iterdir()) == []


def test_prior_run_preservation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sink1 = FilesystemEvidenceSink(config.output.directory)
    result1 = run_lexical_extraction(config, sink1)
    publication1 = finalize_publication(sink1, result1)
    assert publication1.manifest_path is not None
    first_bytes = publication1.manifest_path.read_bytes()

    sink2 = FilesystemEvidenceSink(config.output.directory)
    result2 = run_lexical_extraction(config, sink2)
    publication2 = finalize_publication(sink2, result2)
    assert publication2.manifest_path is not None
    assert publication1.run_directory != publication2.run_directory
    assert publication1.manifest_path.read_bytes() == first_bytes
    assert publication1.manifest_path.exists()


def test_artifact_tamper_detection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sink = FilesystemEvidenceSink(config.output.directory)
    result = run_lexical_extraction(config, sink)
    publication = finalize_publication(sink, result)
    assert publication.manifest_path is not None
    manifest = load_final_manifest(publication.manifest_path)
    verify_artifact_hashes(manifest, publication.run_directory)
    artifact_path = publication.run_directory / publication.artifacts[0].relative_path
    artifact_path.write_bytes(artifact_path.read_bytes() + b" ")
    with pytest.raises(Exception) as caught:
        verify_artifact_hashes(manifest, publication.run_directory)
    assert "HASH" in str(caught.value) or "SIZE" in str(caught.value)


def test_cli_completed_and_no_leaked_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    yaml_path = _write_yaml(tmp_path / "execution.yaml", config)
    code = lexical_main.main(["--config", str(yaml_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "run_id=" in captured.out
    assert "extraction_status=completed" in captured.out
    assert "publication_status=completed" in captured.out
    assert "manifest_path=" in captured.out
    assert "Mixing Water" not in captured.out
    assert "Mixing Water" not in captured.err


def test_manual_page_block_serialization_round_trip(tmp_path: Path) -> None:
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("fixture-run")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    block = BlockEvidence(
        node_id="node-1",
        kind="line",
        text="Water Water",
        page_number=1,
        order=0,
    )
    sink.write_block(Component.MATERIALS, BlockRecord(block=block, occurrences=()))
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert Component.MATERIALS in sink.committed_artifacts
    assert sink.run_directory is not None
    artifact = sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path
    pages = _collect_pages(artifact)
    assert pages[0][1][0].block.text == "Water Water"
    assert pages[0][0].coverage is PageCoverage.COMPLETE


def test_cli_partial_exit_code(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        components=(Component.MATERIALS, Component.EQUIPMENT),
    )
    yaml_path = _write_yaml(tmp_path / "execution.yaml", config)
    sink = FilesystemEvidenceSink(
        config.output.directory,
        fail_complete_component=Component.EQUIPMENT,
    )
    result, publication = publish_lexical_run(yaml_path, sink=sink)
    assert publication.exit_code == 1
    from app.lexical_extraction.publication import format_cli_summary

    text = format_cli_summary(result, publication)
    assert "extraction_status=partial" in text
    assert "Mixing" not in text


def _material_occurrence(node_id: str, start: int, end: int, text: str) -> DictionaryOccurrence:
    return DictionaryOccurrence(
        occurrence_id=f"occ-{start}-{end}",
        block_node_id=node_id,
        location=CharSpan(start_char=start, end_char=end, matched_text=text),
        applies_to=(Component.MATERIALS,),
        candidates=(
            FdaEmaMaterialCandidate(
                matched_term=text,
                source_field="material_name",
                snapshot_id="fixture-snapshot",
                row_id="row-1",
                evidence=ExactEvidence(),
            ),
        ),
    )


def test_streaming_reader_first_page_before_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lexical_extraction import publication as pub
    from app.lexical_extraction.publication import iter_component_pages_from_stream

    monkeypatch.setattr(pub, "_READ_CHUNK", 32)
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("stream-run")
    sink.begin_component(Component.MATERIALS)
    for page_number in range(1, 6):
        sink.write_page(
            Component.MATERIALS,
            PageEvidence(
                page_number=page_number,
                order=page_number - 1,
                coverage=PageCoverage.COMPLETE,
            ),
        )
        sink.write_block(
            Component.MATERIALS,
            BlockRecord(
                block=BlockEvidence(
                    node_id=f"n{page_number}",
                    kind="line",
                    text=f"page-{page_number}-" + ("x" * 80),
                    page_number=page_number,
                    order=0,
                ),
                occurrences=(),
            ),
        )
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert sink.run_directory is not None
    artifact = sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path
    file_size = artifact.stat().st_size
    tracked = open_component_artifact_stream(artifact)
    try:
        iterator = iter_component_pages_from_stream(tracked)
        first_page = next(iterator)
        assert first_page.page.page_number == 1
        assert tracked.bytes_read < file_size
        blocks = list(first_page.iter_blocks())
        assert len(blocks) == 1
    finally:
        tracked.close()


def test_large_page_materialize_and_read_without_block_list(tmp_path: Path) -> None:
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("large-page")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=2, order=1, coverage=PageCoverage.COMPLETE),
    )
    for index in range(120):
        sink.write_block(
            Component.MATERIALS,
            BlockRecord(
                block=BlockEvidence(
                    node_id=f"b{index:04d}",
                    kind="line",
                    text=f"row-{index}",
                    page_number=1,
                    order=index,
                ),
                occurrences=(),
            ),
        )
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert sink.run_directory is not None
    artifact = sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path

    page_one_blocks = 0
    for streamed in iter_component_pages(artifact):
        count = 0
        for _record in streamed.iter_blocks():
            count += 1
        if streamed.page.page_number == 1:
            page_one_blocks = count
        else:
            assert count == 0
    assert page_one_blocks == 120


def test_short_write_does_not_commit_component(tmp_path: Path) -> None:
    sink = FilesystemEvidenceSink(tmp_path / "out", fail_short_write_after=40)
    sink.begin_run("short-write")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    sink.write_block(
        Component.MATERIALS,
        BlockRecord(
            block=BlockEvidence(
                node_id="n1",
                kind="line",
                text="Water",
                page_number=1,
                order=0,
            ),
            occurrences=(),
        ),
    )
    with pytest.raises(PublicationError) as caught:
        sink.complete_component(Component.MATERIALS)
    assert caught.value.code == "WRITE_SHORT"
    assert Component.MATERIALS not in sink.committed_artifacts
    assert sink.run_directory is not None
    artifact_dir = sink.run_directory / "artifacts"
    assert list(artifact_dir.iterdir()) == []


def test_locate_hit_requires_exact_span(tmp_path: Path) -> None:
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("locate")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    filled = BlockRecord(
        block=BlockEvidence(
            node_id="hit-node",
            kind="line",
            text="Water solvent",
            page_number=1,
            order=0,
        ),
        occurrences=(_material_occurrence("hit-node", 0, 5, "Water"),),
    )
    empty = BlockRecord(
        block=BlockEvidence(
            node_id="empty-node",
            kind="line",
            text="",
            page_number=1,
            order=1,
        ),
        occurrences=(),
    )
    other = BlockRecord(
        block=BlockEvidence(
            node_id="other-node",
            kind="line",
            text="Water",
            page_number=1,
            order=2,
        ),
        occurrences=(_material_occurrence("other-node", 0, 5, "Water"),),
    )
    sink.write_block(Component.MATERIALS, filled)
    sink.write_block(Component.MATERIALS, empty)
    sink.write_block(Component.MATERIALS, other)
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert sink.run_directory is not None
    artifact = sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path

    assert (
        locate_hit(artifact, page_number=1, node_id="hit-node", start_char=0, end_char=5)
        is not None
    )
    assert locate_hit(artifact, page_number=1, node_id="hit-node", start_char=1, end_char=5) is None
    assert (
        locate_hit(artifact, page_number=1, node_id="other-node", start_char=0, end_char=5)
        is not None
    )
    assert (
        locate_hit(artifact, page_number=1, node_id="empty-node", start_char=0, end_char=5) is None
    )
    assert locate_hit(artifact, page_number=1, node_id="missing", start_char=0, end_char=5) is None


def test_output_inside_snapshot_refused_before_begin_run(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    nested_out = snapshot / "results"
    before = {path.name for path in snapshot.iterdir()}
    with pytest.raises(PublicationError) as caught:
        guard_output_outside_snapshot(nested_out, snapshot)
    assert caught.value.code == "OUTPUT_INSIDE_SNAPSHOT"

    sink = FilesystemEvidenceSink(nested_out, snapshot_directory=snapshot)
    with pytest.raises(PublicationError):
        sink.begin_run("must-not-create")
    assert not nested_out.exists()
    assert {path.name for path in snapshot.iterdir()} == before

    sibling = tmp_path / "results"
    guard_output_outside_snapshot(sibling, snapshot)
    ok_sink = FilesystemEvidenceSink(sibling, snapshot_directory=snapshot)
    ok_sink.begin_run("ok-run")
    assert (sibling / "ok-run").is_dir()


def _publish_manual_pages(
    tmp_path: Path,
    *,
    pages: int,
    blocks_per_page: int,
    text_prefix: str = "row",
) -> Path:
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("manual")
    sink.begin_component(Component.MATERIALS)
    for page_number in range(1, pages + 1):
        sink.write_page(
            Component.MATERIALS,
            PageEvidence(
                page_number=page_number,
                order=page_number - 1,
                coverage=PageCoverage.COMPLETE,
            ),
        )
        for block_i in range(blocks_per_page):
            sink.write_block(
                Component.MATERIALS,
                BlockRecord(
                    block=BlockEvidence(
                        node_id=f"p{page_number}-b{block_i}",
                        kind="line",
                        text=f"{text_prefix}-{page_number}-{block_i}",
                        page_number=page_number,
                        order=block_i,
                    ),
                    occurrences=(),
                ),
            )
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert sink.run_directory is not None
    return sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path


def test_reader_retained_buffer_stays_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lexical_extraction import publication as pub
    from app.lexical_extraction.publication import iter_component_pages_from_stream

    monkeypatch.setattr(pub, "_READ_CHUNK", 64)
    artifact = _publish_manual_pages(tmp_path, pages=80, blocks_per_page=5)
    file_size = artifact.stat().st_size
    stream = open_component_artifact_stream(artifact)
    try:
        page_count = 0
        block_count = 0
        for streamed in iter_component_pages_from_stream(stream):
            page_count += 1
            for _ in streamed.iter_blocks():
                block_count += 1
        assert page_count == 80
        assert block_count == 400
        # Retained parser text must not scale with previously consumed records.
        assert stream.peak_retained_chars < 8_192
        assert stream.peak_retained_chars < file_size // 4
    finally:
        stream.close()


def test_utf8_character_split_across_read_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lexical_extraction import publication as pub

    monkeypatch.setattr(pub, "_READ_CHUNK", 1)
    text = "αβγ Water"  # multibyte Greek letters before ASCII
    sink = FilesystemEvidenceSink(tmp_path / "out")
    sink.begin_run("utf8")
    sink.begin_component(Component.MATERIALS)
    sink.write_page(
        Component.MATERIALS,
        PageEvidence(page_number=1, order=0, coverage=PageCoverage.COMPLETE),
    )
    start = text.index("Water")
    end = start + len("Water")
    sink.write_block(
        Component.MATERIALS,
        BlockRecord(
            block=BlockEvidence(
                node_id="greek-node",
                kind="line",
                text=text,
                page_number=1,
                order=0,
            ),
            occurrences=(_material_occurrence("greek-node", start, end, "Water"),),
        ),
    )
    sink.complete_component(Component.MATERIALS)
    sink.complete_run()
    assert sink.run_directory is not None
    artifact = sink.run_directory / sink.committed_artifacts[Component.MATERIALS].relative_path
    pages = _collect_pages(artifact)
    assert pages[0][1][0].block.text == text
    hit = locate_hit(
        artifact,
        page_number=1,
        node_id="greek-node",
        start_char=start,
        end_char=end,
    )
    assert hit is not None
    assert hit[1].block.text[start:end] == "Water"

    # Invalid UTF-8 bytes fail closed.
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"schema_version":"batchlens.lexical-component-artifact.v1"\xff')
    with pytest.raises(PublicationError) as caught:
        open_component_artifact_stream(bad)
    assert caught.value.code in {"ARTIFACT_UTF8", "ARTIFACT_TRUNCATED", "ARTIFACT_INVALID"}


def test_truncated_and_page_count_mismatches_rejected(tmp_path: Path) -> None:
    artifact = _publish_manual_pages(tmp_path / "ok", pages=2, blocks_per_page=1)
    raw = artifact.read_bytes()
    # Truncate after the pages array closes, before the root object closes.
    cut = raw.rfind(b"]")
    assert cut > 0
    truncated = tmp_path / "truncated.json"
    truncated.write_bytes(raw[: cut + 1])
    with pytest.raises(PublicationError) as truncated_err:
        list(iter_component_pages(truncated))
    assert truncated_err.value.code in {"ARTIFACT_INVALID", "ARTIFACT_TRUNCATED"}

    # Wrong page_count in header vs actual pages.
    text = raw.decode("utf-8")
    mutated = text.replace('"page_count":2', '"page_count":3', 1)
    assert mutated != text
    wrong_count = tmp_path / "wrong-count.json"
    wrong_count.write_text(mutated, encoding="utf-8")
    with pytest.raises(PublicationError) as count_err:
        list(iter_component_pages(wrong_count))
    assert count_err.value.code == "ARTIFACT_PAGE_COUNT"


def test_early_block_iterator_close_still_advances_pages(tmp_path: Path) -> None:
    from collections.abc import Generator

    artifact = _publish_manual_pages(tmp_path, pages=2, blocks_per_page=3)
    pages = iter_component_pages(artifact)
    first = next(pages)
    assert first.page.page_number == 1
    block_iter = first.iter_blocks()
    assert isinstance(block_iter, Generator)
    first_block = next(block_iter)
    assert first_block.block.order == 0
    block_iter.close()  # early close before remaining blocks
    assert first.drained is True
    second = next(pages)
    assert second.page.page_number == 2
    remaining = list(second.iter_blocks())
    assert len(remaining) == 3
    with pytest.raises(StopIteration):
        next(pages)
