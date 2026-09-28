"""Focused synthetic checks for the L09 measurement helper.

These do not satisfy the real full-Materials L09 measurement.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import tests.lexical_extraction.acceptance as acceptance_mod
from app.lexical_extraction.contracts import (
    BlockEvidence,
    BlockRecord,
    CharSpan,
    Component,
    DictionaryOccurrence,
    ExactEvidence,
    FdaEmaMaterialCandidate,
)
from app.lexical_extraction.knowledge_snapshot import FLAT_SOURCE_TABLES, derive_snapshot_id
from tests.lexical_extraction.acceptance import (
    FileIdentity,
    MeasurementError,
    SnapshotSidecarState,
    canonical_block_record_bytes,
    compare_measurement_digests,
    evaluate_post_run_integrity,
    finalize_reviewed_html_identity,
    report_claims_completed_integrity,
    run_materials_feasibility_measurement,
    update_semantic_digest,
)

_FDA_HEADERS = dict(FLAT_SOURCE_TABLES)["materials_fda_ema"]
_CHEBI_HEADERS = dict(FLAT_SOURCE_TABLES)["materials_chebi"]
_EQUIP_HEADERS = dict(FLAT_SOURCE_TABLES)["equipment"]
_UO_HEADERS = dict(FLAT_SOURCE_TABLES)["unit_operations"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _dump(path: Path, payload: object) -> None:
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def _reviewed_html(text_block: str = "Lactose monohydrate is present.") -> str:
    return (
        "<!doctype html>"
        '<html data-review-html-version="1" data-job-id="job-l09" '
        'data-review-revision-id="00000000-0000-4000-8000-000000000099" '
        'data-review-generation="1" data-conversion-status="SUCCEEDED">'
        '<head><meta charset="utf-8"><title>L09 fixture</title></head>'
        "<body>"
        '<header class="summary" data-generated="true"><h1>Reviewed</h1></header>'
        '<main><section class="page" id="source-page-1" data-page="1">'
        '<h2 data-generated="true">Page 1</h2>'
        '<article class="element" data-element-id="el-1" data-kind="text">'
        f'<p data-node-id="node-1">{text_block}</p>'
        "</article>"
        "</section></main></body></html>"
    )


def _blank_row(headers: tuple[str, ...], row_id: str, **overrides: str) -> tuple[str, ...]:
    values = {header: "" for header in headers}
    values["row_id"] = row_id
    values.update(overrides)
    return tuple(values[header] for header in headers)


def _create_database(path: Path, rows: dict[str, list[tuple[str, ...]]]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA user_version = 1")
        for table_name, headers in FLAT_SOURCE_TABLES:
            cols = ", ".join(f'"{header}" TEXT NOT NULL' for header in headers)
            connection.execute(f'CREATE TABLE "{table_name}" ({cols}, PRIMARY KEY ("row_id"))')
            table_rows = rows.get(table_name, [])
            if not table_rows:
                continue
            placeholders = ", ".join("?" for _ in headers)
            connection.executemany(
                f'INSERT INTO "{table_name}" VALUES ({placeholders})',
                table_rows,
            )
        connection.commit()
    finally:
        connection.close()


def _write_companions(directory: Path, rows: dict[str, list[tuple[str, ...]]]) -> None:
    database = directory / "knowledge.sqlite"
    database_bytes = database.read_bytes()
    sources: list[dict[str, Any]] = []
    identity_sources: list[dict[str, str]] = []
    tables: list[dict[str, Any]] = []
    for table_name, headers in FLAT_SOURCE_TABLES:
        source_sha = hashlib.sha256(table_name.encode("utf-8")).hexdigest()
        row_count = len(rows.get(table_name, []))
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
    snapshot_identity = {
        "flat_schema_version": 1,
        "preparation_version": "flat-sqlite-1",
        "sources": identity_sources,
    }
    manifest: dict[str, Any] = {
        "flat_schema_version": 1,
        "preparation_version": "flat-sqlite-1",
        "snapshot_id": derive_snapshot_id(snapshot_identity),
        "snapshot_identity": snapshot_identity,
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
    contract = directory / "FLAT_SQLITE_CONTRACT.md"
    contract.write_text("synthetic flat contract\n", encoding="utf-8")


def _publish_materials_snapshot(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fda = _blank_row(
        _FDA_HEADERS,
        "fda-1",
        material_name="Lactose monohydrate",
        alias_name="",
        UNII="EWQ57Q8I5X",
        SMS_ID="",
    )
    chebi = _blank_row(
        _CHEBI_HEADERS,
        "chebi-1",
        material_name="water",
        alias_name="",
        CHEBI_ID="CHEBI:15377",
    )
    rows = {
        "materials_fda_ema": [fda],
        "materials_chebi": [chebi],
        "equipment": [],
        "unit_operations": [],
    }
    # Satisfy schema with empty tables — still need zero-row tables present.
    _ = (_EQUIP_HEADERS, _UO_HEADERS)
    _create_database(directory / "knowledge.sqlite", rows)
    _write_companions(directory, rows)
    return directory


def _write_html(path: Path, body: str | None = None) -> Path:
    path.write_text(body if body is not None else _reviewed_html(), encoding="utf-8")
    return path


def _sample_block_record(*, matched: str = "Lactose monohydrate") -> BlockRecord:
    span = CharSpan(start_char=0, end_char=len(matched), matched_text=matched)
    candidate = FdaEmaMaterialCandidate(
        matched_term=matched,
        canonical_display_name=matched,
        snapshot_id="fixture",
        row_id="fda-1",
        supporting_row_ids=(),
        evidence=ExactEvidence(),
        source_field="material_name",
        unii="EWQ57Q8I5X",
    )
    occurrence = DictionaryOccurrence(
        occurrence_id="occ-1",
        block_node_id="node-1",
        location=span,
        applies_to=(Component.MATERIALS,),
        candidates=(candidate,),
    )
    block = BlockEvidence(
        node_id="node-1",
        kind="paragraph",
        text=matched,
        page_number=1,
        order=0,
        element_id="el-1",
    )
    return BlockRecord(block=block, occurrences=(occurrence,))


def test_streaming_semantic_digest_is_stable_and_order_sensitive() -> None:
    first = _sample_block_record()
    second = _sample_block_record(matched="water")
    digest_a = hashlib.sha256()
    update_semantic_digest(digest_a, first)
    update_semantic_digest(digest_a, second)
    digest_b = hashlib.sha256()
    update_semantic_digest(digest_b, first)
    update_semantic_digest(digest_b, second)
    assert digest_a.hexdigest() == digest_b.hexdigest()

    digest_c = hashlib.sha256()
    update_semantic_digest(digest_c, second)
    update_semantic_digest(digest_c, first)
    assert digest_c.hexdigest() != digest_a.hexdigest()
    assert canonical_block_record_bytes(first).startswith(b"{")


def test_finalize_reviewed_html_identity_and_missing_invalid(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    identity = finalize_reviewed_html_identity(html_path)
    assert identity.page_count == 1
    assert identity.block_count == 1
    assert identity.sha256 == _sha256(html_path.read_bytes())

    with pytest.raises(MeasurementError) as missing:
        finalize_reviewed_html_identity(tmp_path / "absent.html")
    assert missing.value.code == "MISSING_REVIEWED_HTML"

    bad = tmp_path / "bad.html"
    bad.write_text("<html><body><p>no provenance</p></body></html>", encoding="utf-8")
    with pytest.raises(MeasurementError) as invalid:
        finalize_reviewed_html_identity(bad)
    assert invalid.value.code == "INVALID_REVIEWED_HTML"


def test_helper_invokes_apis_and_reports_metrics(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    snapshot_dir = _publish_materials_snapshot(tmp_path / "snap")
    report = run_materials_feasibility_measurement(
        reviewed_html_path=html_path,
        snapshot_directory=snapshot_dir,
        max_terms_per_shard=100,
        peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
        run_label="synthetic-a",
        os_cache_note="synthetic",
    )
    assert report.status == "completed"
    assert report.error_code is None
    assert report.component == Component.MATERIALS.value
    assert report.fuzzy_enabled is False
    assert report.publication_claimed is False
    assert report.hashes_unchanged is True
    assert report.knowledge_write_detected is False
    assert report_claims_completed_integrity(report.to_jsonable()) is True
    assert report.counts.eligible_terms >= 2
    assert report.counts.blocks_emitted == 1
    assert report.counts.raw_discoveries >= 1
    assert report.counts.dictionary_occurrences >= 1
    assert report.counts.candidates >= 1
    assert len(report.semantic_digest_sha256) == 64
    assert report.temporary_spool_peak_bytes == "unavailable"
    assert report.timings.indexing_seconds == "unavailable"
    assert report.timings.search_seconds == "unavailable"
    assert report.timings.aggregation_seconds == "unavailable"
    assert report.memory.method in {"windows_psapi_peak_working_set", "unavailable"}
    if isinstance(report.memory.peak_working_set_bytes, int):
        assert report.memory.peak_working_set_bytes > 0


def test_helper_digest_stable_across_shard_settings(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    snapshot_dir = _publish_materials_snapshot(tmp_path / "snap")
    first = run_materials_feasibility_measurement(
        reviewed_html_path=html_path,
        snapshot_directory=snapshot_dir,
        max_terms_per_shard=1,
        peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
        run_label="synthetic-shard-1",
    )
    second = run_materials_feasibility_measurement(
        reviewed_html_path=html_path,
        snapshot_directory=snapshot_dir,
        max_terms_per_shard=10_000,
        peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
        run_label="synthetic-shard-2",
    )
    equal, issues = compare_measurement_digests(first.to_jsonable(), second.to_jsonable())
    assert equal, issues


def test_helper_fails_closed_on_snapshot_error(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    empty = tmp_path / "empty-snap"
    empty.mkdir()
    with pytest.raises(MeasurementError) as exc:
        run_materials_feasibility_measurement(
            reviewed_html_path=html_path,
            snapshot_directory=empty,
            max_terms_per_shard=10,
        )
    assert exc.value.code == "SNAPSHOT_ERROR"


def test_evaluate_post_run_integrity_html_only_vs_knowledge() -> None:
    before = {
        "reviewed_html": "aa" * 32,
        "database": "bb" * 32,
        "manifest": "cc" * 32,
        "validation_report": "dd" * 32,
        "contract": "ee" * 32,
    }
    html_after = dict(before)
    html_after["reviewed_html"] = "ff" * 32
    html_only = evaluate_post_run_integrity(
        before,
        html_after,
        SnapshotSidecarState(False, False, False),
    )
    assert html_only.failure_status == "integrity_failed"
    assert html_only.error_code == "HTML_INPUT_CHANGED"
    assert html_only.knowledge_write_detected is False
    assert html_only.hashes_unchanged is False

    snap_after = dict(before)
    snap_after["manifest"] = "11" * 32
    snap_only = evaluate_post_run_integrity(
        before,
        snap_after,
        SnapshotSidecarState(False, False, False),
    )
    assert snap_only.failure_status == "integrity_failed"
    assert snap_only.error_code == "KNOWLEDGE_WRITE_DETECTED"
    assert snap_only.knowledge_write_detected is True

    sidecar = evaluate_post_run_integrity(
        before,
        before,
        SnapshotSidecarState(True, False, False),
    )
    assert sidecar.failure_status == "integrity_failed"
    assert sidecar.error_code == "KNOWLEDGE_WRITE_DETECTED"
    assert sidecar.knowledge_write_detected is True
    assert sidecar.hashes_unchanged is True

    ok = evaluate_post_run_integrity(
        before,
        before,
        SnapshotSidecarState(False, False, False),
    )
    assert ok.failure_status is None
    assert ok.error_code is None
    assert ok.knowledge_write_detected is False
    assert ok.hashes_unchanged is True


def test_helper_html_change_fails_integrity_without_knowledge_write(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    snapshot_dir = _publish_materials_snapshot(tmp_path / "snap")
    real_hash = acceptance_mod.hash_file
    html_reads = {"n": 0}

    def hashing(path: Path) -> FileIdentity:
        identity = real_hash(path)
        if Path(path).resolve() == html_path.resolve():
            html_reads["n"] += 1
            if html_reads["n"] >= 2:
                return FileIdentity(
                    path=identity.path,
                    size_bytes=identity.size_bytes,
                    sha256="ab" * 32,
                )
        return identity

    with patch.object(acceptance_mod, "hash_file", side_effect=hashing):
        report = run_materials_feasibility_measurement(
            reviewed_html_path=html_path,
            snapshot_directory=snapshot_dir,
            max_terms_per_shard=100,
            peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
            run_label="synthetic-html-change",
        )
    assert report.status == "integrity_failed"
    assert report.error_code == "HTML_INPUT_CHANGED"
    assert report.knowledge_write_detected is False
    assert report.hashes_unchanged is False
    assert report_claims_completed_integrity(report.to_jsonable()) is False


def test_helper_snapshot_companion_change_fails_integrity(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    snapshot_dir = _publish_materials_snapshot(tmp_path / "snap")
    manifest_path = (snapshot_dir / "manifest.json").resolve()
    real_hash = acceptance_mod.hash_file
    manifest_reads = {"n": 0}

    def hashing(path: Path) -> FileIdentity:
        identity = real_hash(path)
        if Path(path).resolve() == manifest_path:
            manifest_reads["n"] += 1
            if manifest_reads["n"] >= 2:
                return FileIdentity(
                    path=identity.path,
                    size_bytes=identity.size_bytes,
                    sha256="cd" * 32,
                )
        return identity

    with patch.object(acceptance_mod, "hash_file", side_effect=hashing):
        report = run_materials_feasibility_measurement(
            reviewed_html_path=html_path,
            snapshot_directory=snapshot_dir,
            max_terms_per_shard=100,
            peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
            run_label="synthetic-manifest-change",
        )
    assert report.status == "integrity_failed"
    assert report.error_code == "KNOWLEDGE_WRITE_DETECTED"
    assert report.knowledge_write_detected is True
    assert report.hashes_unchanged is False
    assert report_claims_completed_integrity(report.to_jsonable()) is False


def test_helper_sidecar_detection_fails_integrity(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path / "reviewed.html")
    snapshot_dir = _publish_materials_snapshot(tmp_path / "snap")
    sidecar_calls = {"n": 0}

    def sidecars(_database_path: Path) -> SnapshotSidecarState:
        sidecar_calls["n"] += 1
        if sidecar_calls["n"] >= 2:
            return SnapshotSidecarState(
                wal_present=True,
                shm_present=False,
                journal_present=False,
            )
        return SnapshotSidecarState(False, False, False)

    with patch.object(acceptance_mod, "snapshot_sidecar_state", side_effect=sidecars):
        report = run_materials_feasibility_measurement(
            reviewed_html_path=html_path,
            snapshot_directory=snapshot_dir,
            max_terms_per_shard=100,
            peak_memory_budget_bytes=2 * 1024 * 1024 * 1024,
            run_label="synthetic-sidecar",
        )
    assert report.status == "integrity_failed"
    assert report.error_code == "KNOWLEDGE_WRITE_DETECTED"
    assert report.knowledge_write_detected is True
    assert report.sidecars_after.wal_present is True
    assert report_claims_completed_integrity(report.to_jsonable()) is False


def test_compare_measurement_digests_detects_unequal() -> None:
    left = {
        "status": "completed",
        "hashes_unchanged": True,
        "knowledge_write_detected": False,
        "error_code": None,
        "semantic_digest_sha256": "a" * 64,
        "counts": {
            "eligible_terms": 1,
            "raw_discoveries": 1,
            "blocks_emitted": 1,
            "dictionary_occurrences": 1,
            "candidates": 1,
        },
        "reviewed_html": {"sha256": "b" * 64},
        "snapshot_id": "snap",
    }
    right = dict(left)
    right["semantic_digest_sha256"] = "c" * 64
    equal, issues = compare_measurement_digests(left, right)
    assert equal is False
    assert any("semantic digests differ" in item for item in issues)


def test_compare_measurement_digests_rejects_integrity_failed() -> None:
    completed = {
        "status": "completed",
        "hashes_unchanged": True,
        "knowledge_write_detected": False,
        "error_code": None,
        "semantic_digest_sha256": "a" * 64,
        "counts": {
            "eligible_terms": 1,
            "raw_discoveries": 1,
            "blocks_emitted": 1,
            "dictionary_occurrences": 1,
            "candidates": 1,
        },
        "reviewed_html": {"sha256": "b" * 64},
        "snapshot_id": "snap",
    }
    failed = dict(completed)
    failed["status"] = "integrity_failed"
    failed["error_code"] = "HTML_INPUT_CHANGED"
    failed["hashes_unchanged"] = False
    equal, issues = compare_measurement_digests(completed, failed)
    assert equal is False
    assert any("completed integrity" in item for item in issues)

    sneaky = dict(completed)
    sneaky["status"] = "completed"
    sneaky["hashes_unchanged"] = False
    sneaky["knowledge_write_detected"] = False
    equal_sneaky, issues_sneaky = compare_measurement_digests(completed, sneaky)
    assert equal_sneaky is False
    assert any("completed integrity" in item for item in issues_sneaky)
