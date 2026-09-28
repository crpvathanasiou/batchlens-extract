"""Read-only flat SQLite snapshot preflight, paging, and row_id lookup."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from app.lexical_extraction.configuration import (
    MAX_SQLITE_CACHE_KIB,
    MAX_SQLITE_READ_BATCH_ROWS,
    EffectiveExecutionConfiguration,
    ExtractionRequest,
    InputPaths,
    KnowledgePaths,
    OutputPaths,
    ResourceLimits,
    resolve_components,
)
from app.lexical_extraction.contracts import Preset, SafeStructuredError
from app.lexical_extraction.knowledge_snapshot import (
    FLAT_SOURCE_TABLES,
    KnowledgeSnapshot,
    SnapshotReadError,
    derive_snapshot_id,
    open_knowledge_snapshot,
    open_knowledge_snapshot_from_configuration,
)

_Mutator = Callable[[dict[str, Any]], None]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row(headers: tuple[str, ...], row_id: str, **overrides: str) -> tuple[str, ...]:
    values = dict.fromkeys(headers, "")
    values["row_id"] = row_id
    values.update(overrides)
    return tuple(values[header] for header in headers)


def _sample_rows() -> dict[str, list[tuple[str, ...]]]:
    headers = dict(FLAT_SOURCE_TABLES)
    fda = headers["materials_fda_ema"]
    chebi = headers["materials_chebi"]
    equipment = headers["equipment"]
    unit = headers["unit_operations"]
    return {
        "materials_fda_ema": [
            _row(
                fda,
                "fda-b",
                material_name="Water",
                UNII="N/A",
                Is_Preferred_Name="FALSE",
                lexical_term_id="same-term",
            ),
            _row(
                fda,
                "shared",
                material_name="Water",
                alias_name="  spaced  ",
                lexical_term_id="same-term",
            ),
            _row(fda, "fda-c", material_name="α-γλυκόζη", alias_name="alpha, (punct)"),
        ],
        "materials_chebi": [_row(chebi, "chebi-1", material_name="aqua")],
        "equipment": [
            _row(
                equipment,
                "shared",
                **{
                    "Equipment type (EN)": "Pump",
                    "Τύπος εξοπλισμού (GR)": "αντλία",
                    "Model": "N/A",
                    "manufacturer_id": "",
                    "model_id": "MOD",
                },
            ),
            _row(
                equipment,
                "eq-2",
                **{
                    "Equipment type (EN)": "Pump",
                    "Τύπος εξοπλισμού (GR)": "αντλία",
                    "Model": "N/A",
                    "manufacturer_id": "MFR",
                    "model_id": "MOD",
                },
            ),
        ],
        "unit_operations": [
            _row(
                unit,
                "uo-1",
                **{
                    "Search term (EN)": "cell check",
                    "Index this row": "FALSE",
                    "Unit operation (GR)": "ψύξη",
                    "Operation role": "step_cue",
                },
            )
        ],
    }


def _create_database(
    path: Path,
    rows: dict[str, list[tuple[str, ...]]],
    *,
    user_version: int = 1,
    not_null: bool = True,
    without_rowid: frozenset[str] = frozenset(),
    extra_table: bool = False,
) -> None:
    connection = sqlite3.connect(path)
    try:
        for table_name, headers in FLAT_SOURCE_TABLES:
            columns: list[str] = []
            for header in headers:
                null_sql = " NOT NULL" if not_null else ""
                primary = " PRIMARY KEY" if header == "row_id" else ""
                columns.append(f"{_quote(header)} TEXT{null_sql}{primary}")
            suffix = " WITHOUT ROWID" if table_name in without_rowid else ""
            connection.execute(f"CREATE TABLE {_quote(table_name)} ({', '.join(columns)}){suffix}")
            table_rows = rows.get(table_name, [])
            if table_rows:
                placeholders = ", ".join("?" for _ in headers)
                names = ", ".join(_quote(header) for header in headers)
                connection.executemany(
                    f"INSERT INTO {_quote(table_name)} ({names}) VALUES ({placeholders})",
                    table_rows,
                )
        if extra_table:
            connection.execute("CREATE TABLE extra (row_id TEXT NOT NULL PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {user_version}")
        connection.commit()
    finally:
        connection.close()


def _dump(path: Path, payload: object) -> None:
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def _load(path: Path) -> dict[str, Any]:
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError("test companion is not an object")
    return cast(dict[str, Any], loaded)


def _write_companions(
    directory: Path, rows: dict[str, list[tuple[str, ...]]], contract: str
) -> None:
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
    (directory / "FLAT_SQLITE_CONTRACT.md").write_text(contract, encoding="utf-8")


def _publish(
    directory: Path,
    *,
    rows: dict[str, list[tuple[str, ...]]] | None = None,
    contract: str = "synthetic flat contract\n",
    user_version: int = 1,
    not_null: bool = True,
    without_rowid: frozenset[str] = frozenset(),
    extra_table: bool = False,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    chosen = _sample_rows() if rows is None else rows
    _create_database(
        directory / "knowledge.sqlite",
        chosen,
        user_version=user_version,
        not_null=not_null,
        without_rowid=without_rowid,
        extra_table=extra_table,
    )
    _write_companions(directory, chosen, contract)
    return directory


def _refresh_database(directory: Path) -> None:
    manifest = _load(directory / "manifest.json")
    database = (directory / "knowledge.sqlite").read_bytes()
    database_record = manifest["database"]
    if not isinstance(database_record, dict):
        raise AssertionError("database record missing")
    record = cast(dict[str, Any], database_record)
    record["sha256"] = _sha256(database)
    record["size_bytes"] = len(database)
    _dump(directory / "manifest.json", manifest)


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


def _open(directory: Path, *, batch: int = 10, cache: int = 64) -> KnowledgeSnapshot:
    return open_knowledge_snapshot(directory, read_batch_rows=batch, cache_kib=cache)


def test_module_does_not_load_or_prepare_the_database() -> None:
    source = Path(open_knowledge_snapshot.__code__.co_filename).read_text(encoding="utf-8")
    assert "read_bytes(" not in source
    assert "prepare_lexical_knowledge_sqlite" not in source


def test_preflight_identity_read_only_cleanup_and_missing_csv(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    for table_name, _headers in FLAT_SOURCE_TABLES:
        assert not (directory / "missing" / f"{table_name}.csv").exists()
    before = _names(directory)
    database_bytes = (directory / "knowledge.sqlite").read_bytes()
    manifest_bytes = (directory / "manifest.json").read_bytes()
    expected_id = cast(dict[str, Any], json.loads(manifest_bytes.decode("utf-8")))["snapshot_id"]
    with _open(directory) as handle:
        identity = handle.identity
        assert identity.snapshot_id == expected_id
        assert identity.snapshot_id.startswith("flat-v1-")
        assert len(identity.snapshot_id) == len("flat-v1-") + 20
        assert identity.preparation_version == "flat-sqlite-1"
        assert identity.schema_user_version == 1
        assert identity.database_sha256 == _sha256(database_bytes)
        assert identity.manifest_sha256 == _sha256(manifest_bytes)
        assert handle.snapshot_directory == directory.resolve()
        equipment = list(handle.iter_batches("equipment"))
        assert equipment[-1].rows == ()
        assert [row.row_id for batch in equipment for row in batch.rows] == ["shared", "eq-2"]
    assert handle.identity == identity
    with pytest.raises(SnapshotReadError) as closed:
        handle.read_batch("equipment")
    assert closed.value.code == "SNAPSHOT_NOT_OPEN"
    assert _names(directory) == before
    for suffix in ("-wal", "-shm", "-journal"):
        assert not (directory / f"knowledge.sqlite{suffix}").exists()
    assert (directory / "knowledge.sqlite").read_bytes() == database_bytes
    uri = (directory / "knowledge.sqlite").resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "delete"
    finally:
        connection.close()
    reopened = _open(directory)
    reopened.close()


def test_pagination_lookup_and_exact_source_text(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    handle = _open(directory, batch=10)
    try:
        first = handle.read_batch("materials_fda_ema", after_rowid=0, batch_size=2)
        second = handle.read_batch(
            "materials_fda_ema",
            after_rowid=first.next_after_rowid,
            batch_size=2,
        )
        third = handle.read_batch(
            "materials_fda_ema",
            after_rowid=second.next_after_rowid,
            batch_size=2,
        )
        assert [row.row_id for row in first.rows] == ["fda-b", "shared"]
        assert [row.scan_cursor for row in first.rows] == [1, 2]
        assert [row.row_id for row in second.rows] == ["fda-c"]
        assert second.rows[0].scan_cursor == 3
        assert third.rows == ()
        assert third.next_after_rowid == second.next_after_rowid
        rows = (*first.rows, *second.rows)
        assert all(str(row.scan_cursor) != row.row_id for row in rows)
        by_id = {row.row_id: dict(row.values) for row in rows}
        assert by_id["fda-b"]["material_name"] == "Water"
        assert by_id["fda-b"]["alias_name"] == ""
        assert by_id["fda-b"]["UNII"] == "N/A"
        assert by_id["fda-b"]["Is_Preferred_Name"] == "FALSE"
        assert by_id["shared"]["material_name"] == "Water"
        assert by_id["shared"]["alias_name"] == "  spaced  "
        assert by_id["fda-c"]["material_name"] == "α-γλυκόζη"
        assert by_id["fda-c"]["alias_name"] == "alpha, (punct)"
        found = handle.lookup("materials_fda_ema", "fda-c")
        assert found is not None
        assert found.scan_cursor == 3
        assert dict(found.values) == by_id["fda-c"]
        assert handle.lookup("materials_fda_ema", "missing") is None
        assert handle.lookup("materials_fda_ema", "fda-b' OR '1'='1") is None
        equipment = [
            row for batch in handle.iter_batches("equipment", batch_size=1) for row in batch.rows
        ]
        assert [row.row_id for row in equipment] == ["shared", "eq-2"]
        assert [dict(row.values)["model_id"] for row in equipment] == ["MOD", "MOD"]
        assert dict(equipment[0].values)["Τύπος εξοπλισμού (GR)"] == "αντλία"
        assert dict(equipment[0].values)["manufacturer_id"] == ""
        assert dict(equipment[0].values)["Model"] == "N/A"
        shared_fda = handle.lookup("materials_fda_ema", "shared")
        shared_equipment = handle.lookup("equipment", "shared")
        assert shared_fda is not None and shared_equipment is not None
        assert dict(shared_fda.values)["material_name"] == "Water"
        assert dict(shared_equipment.values)["Equipment type (EN)"] == "Pump"
        unit = handle.lookup("unit_operations", "uo-1")
        assert unit is not None
        assert dict(unit.values)["Index this row"] == "FALSE"
        assert dict(unit.values)["Unit operation (GR)"] == "ψύξη"
        assert "α-γλυκόζη" not in {value for row in equipment for _name, value in row.values}
    finally:
        handle.close()


def test_invalid_requests_do_not_close_a_valid_handle(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    handle = _open(directory, batch=2)
    try:
        with pytest.raises(SnapshotReadError) as invalid_table:
            handle.read_batch("equipment; DROP TABLE materials_fda_ema")
        assert invalid_table.value.code == "INVALID_TABLE"
        with pytest.raises(SnapshotReadError) as oversize:
            handle.read_batch("materials_fda_ema", batch_size=3)
        assert oversize.value.code == "INVALID_LIMIT"
        with pytest.raises(SnapshotReadError) as zero:
            handle.read_batch("equipment", batch_size=0)
        assert zero.value.code == "INVALID_LIMIT"
        with pytest.raises(SnapshotReadError) as flagged:
            handle.read_batch("equipment", batch_size=cast(int, True))
        assert flagged.value.code == "INVALID_LIMIT"
        with pytest.raises(SnapshotReadError) as negative:
            handle.read_batch("equipment", after_rowid=-1)
        assert negative.value.code == "INVALID_LIMIT"
        with pytest.raises(SnapshotReadError) as row_id:
            handle.lookup("equipment", cast(str, 15))
        assert row_id.value.code == "INVALID_ROW_ID"
        page = handle.read_batch("materials_fda_ema")
        assert len(page.rows) == 2
        assert handle.lookup("equipment", "eq-2") is not None
    finally:
        handle.close()


def test_reads_before_preflight_and_after_close_fail(tmp_path: Path) -> None:
    unopened = KnowledgeSnapshot(tmp_path, read_batch_rows=1, cache_kib=1)
    with pytest.raises(SnapshotReadError) as before:
        unopened.read_batch("equipment")
    assert before.value.code == "SNAPSHOT_NOT_OPEN"
    with pytest.raises(SnapshotReadError) as identity:
        _ = unopened.identity
    assert identity.value.code == "SNAPSHOT_NOT_OPEN"
    directory = _publish(tmp_path / "snap")
    handle = _open(directory)
    handle.close()
    with pytest.raises(SnapshotReadError) as after:
        handle.lookup("equipment", "eq-2")
    assert after.value.code == "SNAPSHOT_NOT_OPEN"


def test_limits_and_configuration_adapter(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    before = _names(directory)
    with pytest.raises(SnapshotReadError) as batch:
        _open(directory, batch=0)
    assert batch.value.code == "INVALID_LIMIT"
    with pytest.raises(SnapshotReadError) as cache:
        _open(directory, cache=MAX_SQLITE_CACHE_KIB + 1)
    assert cache.value.code == "INVALID_LIMIT"
    with pytest.raises(SnapshotReadError) as huge:
        _open(directory, batch=MAX_SQLITE_READ_BATCH_ROWS + 1)
    assert huge.value.code == "INVALID_LIMIT"
    assert _names(directory) == before
    config = EffectiveExecutionConfiguration(
        input=InputPaths(reviewed_html_path=(tmp_path / "reviewed.html").resolve()),
        knowledge=KnowledgePaths(snapshot_directory=directory.resolve()),
        output=OutputPaths(directory=(tmp_path / "out").resolve()),
        extraction=ExtractionRequest(presets=(Preset.EQUIPMENT,), components=()),
        resolved_components=resolve_components((Preset.EQUIPMENT,), ()),
        resources=ResourceLimits(sqlite_read_batch_rows=2, sqlite_cache_kib=128),
    )
    handle = open_knowledge_snapshot_from_configuration(config)
    try:
        assert handle.read_batch_rows == 2
        assert handle.cache_kib == 128
        assert len(handle.read_batch("equipment").rows) == 2
        assert not (tmp_path / "out").exists()
    finally:
        handle.close()


def test_snapshot_change_after_open_keeps_the_old_identity(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    handle = _open(directory)
    identity = handle.identity
    manifest = directory / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(SnapshotReadError) as changed:
        handle.read_batch("materials_fda_ema")
    assert changed.value.code == "SNAPSHOT_CHANGED"
    assert handle.identity.database_sha256 == identity.database_sha256
    assert handle.identity.manifest_sha256 == identity.manifest_sha256
    with pytest.raises(SnapshotReadError) as closed:
        handle.lookup("materials_fda_ema", "fda-b")
    assert closed.value.code == "SNAPSHOT_NOT_OPEN"


def test_database_replacement_after_open_is_rejected(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap")
    handle = _open(directory)
    identity = handle.identity
    database = directory / "knowledge.sqlite"
    database.write_bytes(database.read_bytes() + b"\n")
    with pytest.raises(SnapshotReadError) as changed:
        handle.lookup("equipment", "eq-2")
    assert changed.value.code == "SNAPSHOT_CHANGED"
    assert handle.identity == identity


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("knowledge.sqlite", "COMPANION_MISSING"),
        ("manifest.json", "COMPANION_MISSING"),
        ("validation_report.json", "COMPANION_MISSING"),
        ("FLAT_SQLITE_CONTRACT.md", "COMPANION_MISSING"),
    ],
)
def test_missing_companion_is_rejected(tmp_path: Path, name: str, code: str) -> None:
    directory = _publish(tmp_path / "snap")
    (directory / name).unlink()
    before = _names(directory)
    with pytest.raises(SnapshotReadError) as caught:
        _open(directory)
    assert caught.value.code == code
    assert _names(directory) == before


def test_blank_contract_is_rejected(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "snap", contract=" \n\t")
    with pytest.raises(SnapshotReadError) as caught:
        _open(directory)
    assert caught.value.code == "CONTRACT_EMPTY"


@pytest.mark.parametrize(
    ("filename", "payload", "code"),
    [
        ("manifest.json", b"[", "MANIFEST_INVALID"),
        ("manifest.json", b"[]", "MANIFEST_INVALID"),
        ("validation_report.json", b"{", "REPORT_INVALID"),
        ("validation_report.json", b"null", "REPORT_INVALID"),
    ],
)
def test_malformed_companions_are_rejected(
    tmp_path: Path,
    filename: str,
    payload: bytes,
    code: str,
) -> None:
    directory = _publish(tmp_path / "snap")
    (directory / filename).write_bytes(payload)
    with pytest.raises(SnapshotReadError) as caught:
        _open(directory)
    assert caught.value.code == code


def _boolean_root_schema(payload: dict[str, Any]) -> None:
    payload["flat_schema_version"] = True


def _boolean_identity_schema(payload: dict[str, Any]) -> None:
    identity = cast(dict[str, Any], payload["snapshot_identity"])
    identity["flat_schema_version"] = True


def _boolean_user_version(payload: dict[str, Any]) -> None:
    database = cast(dict[str, Any], payload["database"])
    database["user_version"] = True


def _mismatch_snapshot_id(payload: dict[str, Any]) -> None:
    payload["snapshot_id"] = "flat-v1-unrelated"


def _reorder_identity_sources(payload: dict[str, Any]) -> None:
    identity = cast(dict[str, Any], payload["snapshot_identity"])
    sources = cast(list[dict[str, Any]], identity["sources"])
    # Keep the original producer-derived snapshot_id. A reordered list must not
    # still validate under that same ID.
    sources[0], sources[1] = sources[1], sources[0]


def _set_incomplete(payload: dict[str, Any]) -> None:
    payload["completion_status"] = "incomplete"


def _stringify_schema(payload: dict[str, Any]) -> None:
    payload["flat_schema_version"] = "1"


def _stringify_user_version(payload: dict[str, Any]) -> None:
    database = cast(dict[str, Any], payload["database"])
    database["user_version"] = "1"


def _diverge_identity(payload: dict[str, Any]) -> None:
    identity = cast(dict[str, Any], payload["snapshot_identity"])
    sources = cast(list[dict[str, Any]], identity["sources"])
    sources[0]["sha256"] = "ab" * 32


def _rename_source(payload: dict[str, Any]) -> None:
    sources = cast(list[dict[str, Any]], payload["sources"])
    identity = cast(dict[str, Any], payload["snapshot_identity"])
    identity_sources = cast(list[dict[str, Any]], identity["sources"])
    sources[0]["logical_name"] = "materials"
    identity_sources[0]["logical_name"] = "materials"


def _swap_headers(payload: dict[str, Any]) -> None:
    sources = cast(list[dict[str, Any]], payload["sources"])
    headers = cast(list[str], sources[0]["headers"])
    headers[0], headers[1] = headers[1], headers[0]


def _stringify_count(payload: dict[str, Any]) -> None:
    sources = cast(list[dict[str, Any]], payload["sources"])
    sources[0]["row_count"] = str(sources[0]["row_count"])


def _wrong_hash(payload: dict[str, Any]) -> None:
    database = cast(dict[str, Any], payload["database"])
    database["sha256"] = "ab" * 32


def _wrong_size(payload: dict[str, Any]) -> None:
    database = cast(dict[str, Any], payload["database"])
    database["size_bytes"] = cast(int, database["size_bytes"]) + 1


def _stringify_digest_flag(payload: dict[str, Any]) -> None:
    payload["content_digests_match"] = "true"


def _numeric_wal_flag(payload: dict[str, Any]) -> None:
    payload["wal_sidecar_absent"] = 1


def _upper_integrity(payload: dict[str, Any]) -> None:
    payload["integrity_check"] = "OK"


def _disagree_count(payload: dict[str, Any]) -> None:
    tables = cast(list[dict[str, Any]], payload["tables"])
    tables[0]["imported_rows"] = cast(int, tables[0]["imported_rows"]) + 1


def _stringify_column_count(payload: dict[str, Any]) -> None:
    tables = cast(list[dict[str, Any]], payload["tables"])
    tables[0]["column_count"] = str(tables[0]["column_count"])


@pytest.mark.parametrize(
    ("filename", "mutate", "code"),
    [
        ("manifest.json", _set_incomplete, "MANIFEST_INVALID"),
        ("manifest.json", _stringify_schema, "MANIFEST_INVALID"),
        ("manifest.json", _boolean_root_schema, "MANIFEST_INVALID"),
        ("manifest.json", _boolean_identity_schema, "MANIFEST_INVALID"),
        ("manifest.json", _boolean_user_version, "MANIFEST_INVALID"),
        ("manifest.json", _mismatch_snapshot_id, "MANIFEST_INVALID"),
        ("manifest.json", _reorder_identity_sources, "MANIFEST_INVALID"),
        ("manifest.json", _stringify_user_version, "MANIFEST_INVALID"),
        ("manifest.json", _diverge_identity, "MANIFEST_INVALID"),
        ("manifest.json", _rename_source, "MANIFEST_INVALID"),
        ("manifest.json", _swap_headers, "SCHEMA_MISMATCH"),
        ("manifest.json", _stringify_count, "MANIFEST_INVALID"),
        ("manifest.json", _wrong_hash, "HASH_MISMATCH"),
        ("manifest.json", _wrong_size, "SIZE_MISMATCH"),
        ("validation_report.json", _stringify_digest_flag, "REPORT_INVALID"),
        ("validation_report.json", _numeric_wal_flag, "REPORT_INVALID"),
        ("validation_report.json", _upper_integrity, "REPORT_INVALID"),
        ("validation_report.json", _disagree_count, "COUNT_MISMATCH"),
        ("validation_report.json", _stringify_column_count, "REPORT_INVALID"),
    ],
)
def test_provenance_types_and_disagreements_are_rejected(
    tmp_path: Path,
    filename: str,
    mutate: _Mutator,
    code: str,
) -> None:
    directory = _publish(tmp_path / "snap")
    payload = _load(directory / filename)
    mutate(payload)
    _dump(directory / filename, payload)
    with pytest.raises(SnapshotReadError) as caught:
        _open(directory)
    assert caught.value.code == code
    structured = caught.value.to_structured_error()
    assert isinstance(structured, SafeStructuredError)
    assert structured.code == code
    assert structured.retryable is False


def test_schema_count_integrity_and_wal_failures(tmp_path: Path) -> None:
    mismatched = _publish(tmp_path / "nullable", not_null=False)
    with pytest.raises(SnapshotReadError) as nullable:
        _open(mismatched)
    assert nullable.value.code == "SCHEMA_MISMATCH"

    extra = _publish(tmp_path / "extra", extra_table=True)
    with pytest.raises(SnapshotReadError) as extra_table:
        _open(extra)
    assert extra_table.value.code == "SCHEMA_MISMATCH"

    without_rowid = _publish(
        tmp_path / "without-rowid",
        without_rowid=frozenset({"materials_chebi"}),
    )
    with pytest.raises(SnapshotReadError) as rowid:
        _open(without_rowid)
    assert rowid.value.code == "SCHEMA_MISMATCH"

    version = _publish(tmp_path / "version", user_version=2)
    with pytest.raises(SnapshotReadError) as user_version:
        _open(version)
    assert user_version.value.code == "SCHEMA_MISMATCH"

    counted = _publish(tmp_path / "counted")
    manifest = _load(counted / "manifest.json")
    sources = cast(list[dict[str, Any]], manifest["sources"])
    sources[0]["row_count"] = cast(int, sources[0]["row_count"]) + 5
    report = _load(counted / "validation_report.json")
    tables = cast(list[dict[str, Any]], report["tables"])
    tables[0]["imported_rows"] = sources[0]["row_count"]
    _dump(counted / "manifest.json", manifest)
    _dump(counted / "validation_report.json", report)
    with pytest.raises(SnapshotReadError) as count:
        _open(counted)
    assert count.value.code == "COUNT_MISMATCH"

    corrupt = _publish(tmp_path / "corrupt")
    database = corrupt / "knowledge.sqlite"
    payload = bytearray(database.read_bytes())
    payload[100:300] = b"\xff" * 200
    database.write_bytes(payload)
    _refresh_database(corrupt)
    with pytest.raises(SnapshotReadError) as integrity:
        _open(corrupt)
    assert integrity.value.code == "INTEGRITY_CHECK_FAILED"

    garbage = _publish(tmp_path / "garbage")
    (garbage / "knowledge.sqlite").write_bytes(b"not a sqlite database")
    _refresh_database(garbage)
    with pytest.raises(SnapshotReadError) as unreadable:
        _open(garbage)
    assert unreadable.value.code == "INTEGRITY_CHECK_FAILED"

    wal = _publish(tmp_path / "wal")
    (wal / "knowledge.sqlite-wal").write_bytes(b"wal")
    with pytest.raises(SnapshotReadError) as sidecar:
        _open(wal)
    assert sidecar.value.code == "WAL_PRESENT"
    assert _names(wal) == {
        "knowledge.sqlite",
        "knowledge.sqlite-wal",
        "manifest.json",
        "validation_report.json",
        "FLAT_SQLITE_CONTRACT.md",
    }


def test_wal_header_is_rejected_without_creating_a_sidecar(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "wal-mode")
    database = directory / "knowledge.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.commit()
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    _refresh_database(directory)
    before = _names(directory)
    with pytest.raises(SnapshotReadError) as caught:
        _open(directory)
    assert caught.value.code == "WAL_PRESENT"
    assert _names(directory) == before
    assert not (directory / "knowledge.sqlite-wal").exists()
    assert not (directory / "knowledge.sqlite-shm").exists()


def test_producer_snapshot_id_derivation_and_directory_independence(tmp_path: Path) -> None:
    directory = _publish(tmp_path / "mounted-elsewhere")
    manifest = _load(directory / "manifest.json")
    identity = cast(dict[str, Any], manifest["snapshot_identity"])
    derived = derive_snapshot_id(
        {
            "flat_schema_version": identity["flat_schema_version"],
            "preparation_version": identity["preparation_version"],
            "sources": [
                {"logical_name": item["logical_name"], "sha256": item["sha256"]}
                for item in cast(list[dict[str, Any]], identity["sources"])
            ],
        }
    )
    assert manifest["snapshot_id"] == derived
    assert directory.name != derived
    handle = _open(directory)
    try:
        assert handle.identity.snapshot_id == derived
    finally:
        handle.close()


def test_production_manifest_shape_derives_recorded_snapshot_id() -> None:
    """Positive check against the published manifest without opening the large DB."""

    production = Path(
        r"C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared"
        r"\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed\manifest.json"
    )
    if not production.is_file():
        pytest.skip("published snapshot manifest is not available")
    manifest = _load(production)
    identity = cast(dict[str, Any], manifest["snapshot_identity"])
    assert manifest["flat_schema_version"] is not True
    assert identity["flat_schema_version"] is not True
    assert cast(dict[str, Any], manifest["database"])["user_version"] is not True
    assert isinstance(manifest["flat_schema_version"], int)
    assert isinstance(identity["flat_schema_version"], int)
    assert isinstance(cast(dict[str, Any], manifest["database"])["user_version"], int)
    sources = cast(list[dict[str, Any]], identity["sources"])
    assert [item["logical_name"] for item in sources] == [
        table_name for table_name, _headers in FLAT_SOURCE_TABLES
    ]
    derived = derive_snapshot_id(
        {
            "flat_schema_version": identity["flat_schema_version"],
            "preparation_version": identity["preparation_version"],
            "sources": [
                {"logical_name": item["logical_name"], "sha256": item["sha256"]} for item in sources
            ],
        }
    )
    assert derived == manifest["snapshot_id"]
    assert derived == "flat-v1-a39c0b393ffdbd4e97ed"
