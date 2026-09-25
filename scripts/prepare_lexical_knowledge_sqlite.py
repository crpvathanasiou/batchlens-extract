"""Build one flat SQLite snapshot from the four knowledge CSVs.

Each source file becomes one TEXT table. Cells, column names, and source row
ids are preserved. The published snapshot is the runtime knowledge input.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard, cast

csv.field_size_limit(16 * 1024 * 1024)

FLAT_SCHEMA_VERSION = 1
PREPARATION_VERSION = "flat-sqlite-1"
DEFAULT_BATCH_SIZE = 5000
DEFAULT_CACHE_KIB = 65536
MAX_FIELD_BYTES = 16 * 1024 * 1024
CONTRACT_NAME = "FLAT_SQLITE_CONTRACT.md"
LOGGER = logging.getLogger("prepare_lexical_knowledge_sqlite")

UO_POLICY_TERMS = (
    "cell culture expansion",
    "liquid bottle filling",
    "controlled rate freezing",
)


class PreparationError(Exception):
    """Fail-closed preparation error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class DatasetSpec:
    logical_name: str
    relative_path: str
    headers: tuple[str, ...]
    historical_rows: int
    historical_columns: int
    historical_bytes: int

    @property
    def table_name(self) -> str:
        return self.logical_name


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        logical_name="materials_fda_ema",
        relative_path="Materials/final/Unified_Materials_with_SMS.csv",
        headers=(
            "UNII",
            "material_name",
            "CAS_NUMBER",
            "alias_name",
            "alias_type",
            "SMS_ID",
            "Language",
            "Is_Preferred_Name",
            "source",
            "match_status",
            "row_id",
            "lexical_term_id",
        ),
        historical_rows=1_111_030,
        historical_columns=12,
        historical_bytes=186_152_422,
    ),
    DatasetSpec(
        logical_name="materials_chebi",
        relative_path="Materials/final/ChEBI_Materials.csv",
        headers=(
            "CHEBI_ID",
            "material_name",
            "CAS_NUMBER",
            "alias_name",
            "alias_type",
            "alias_category",
            "alias_source",
            "source",
            "source_version",
            "source_record",
            "star_rating",
            "row_id",
            "lexical_term_id",
        ),
        historical_rows=604_363,
        historical_columns=13,
        historical_bytes=166_345_767,
    ),
    DatasetSpec(
        logical_name="equipment",
        relative_path="Equipment/final/Equipment.csv",
        headers=(
            "Equipment type (EN)",
            "Τύπος εξοπλισμού (GR)",
            "Brand / Manufacturer",
            "Model",
            "Operating parameter (EN)",
            "Παράμετρος λειτουργίας (GR)",
            "Unit",
            "Published range",
            "Source / section",
            "row_id",
            "equipment_type_id",
            "manufacturer_id",
            "model_id",
            "parameter_id",
        ),
        historical_rows=415,
        historical_columns=14,
        historical_bytes=186_240,
    ),
    DatasetSpec(
        logical_name="unit_operations",
        relative_path="Unit-Operations/final/UnitOperations.csv",
        headers=(
            "record_type",
            "row_id",
            "category_id",
            "process_step_id",
            "lexical_term_id",
            "source_evidence_id",
            "link_id",
            "link_direction",
            "Category",
            "Unit operation (EN)",
            "Unit operation (GR)",
            "Purpose (EN)",
            "Purpose (GR)",
            "Process step (EN)",
            "Process step (GR)",
            "Relationship / order",
            "Source / supporting evidence",
            "Source layer",
            "Original operation label",
            "Language / review note",
            "Operation ID",
            "Operation role",
            "Search term (EN)",
            "Normalized search key",
            "Canonical unit operation",
            "Term relation",
            "Match policy",
            "Index this row",
            "Provenance / source",
            "Scope / ambiguity rule",
            "Review status",
            "Operation ID A",
            "Operation A",
            "Relationship type",
            "Operation ID B",
            "Operation B",
            "Inference rule",
        ),
        historical_rows=2_597,
        historical_columns=37,
        historical_bytes=2_324_980,
    ),
)


@dataclass(frozen=True)
class PrepareResult:
    snapshot_dir: Path
    reused: bool
    manifest: dict[str, Any]
    validation_report: dict[str, Any]


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_token(cells: Sequence[str]) -> bytes:
    payload = json.dumps(list(cells), ensure_ascii=False, separators=(",", ":"))
    return payload.encode("utf-8") + b"\n"


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def peak_memory() -> dict[str, Any]:
    if sys.platform == "win32":
        return _windows_peak_memory()
    return _posix_peak_memory()


def _windows_peak_memory() -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not get_info(handle, ctypes.byref(counters), counters.cb):
        return {
            "method": "unavailable",
            "bytes": None,
            "limitation": (
                "GetProcessMemoryInfo failed; Python allocations are not process peak memory."
            ),
        }
    return {
        "method": "windows_psapi_peak_working_set",
        "bytes": int(counters.PeakWorkingSetSize),
        "limitation": None,
    }


def _posix_peak_memory() -> dict[str, Any]:
    try:
        import resource
    except ImportError:
        return {
            "method": "unavailable",
            "bytes": None,
            "limitation": (
                "resource.getrusage is unavailable; Python allocations are not process peak memory."
            ),
        }
    getrusage = getattr(resource, "getrusage", None)
    rusage_self = getattr(resource, "RUSAGE_SELF", None)
    if not callable(getrusage) or rusage_self is None:
        return {
            "method": "unavailable",
            "bytes": None,
            "limitation": (
                "resource.getrusage is unavailable; Python allocations are not process peak memory."
            ),
        }
    usage: Any = getrusage(rusage_self)
    maxrss = int(usage.ru_maxrss)
    # Linux reports KiB. macOS reports bytes.
    nbytes = maxrss if sys.platform == "darwin" else maxrss * 1024
    return {"method": "posix_rusage_maxrss", "bytes": nbytes, "limitation": None}


def contract_path() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / CONTRACT_NAME


def code_identity() -> str:
    return sha256_file(Path(__file__).resolve())


def snapshot_identity(source_hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "flat_schema_version": FLAT_SCHEMA_VERSION,
        "preparation_version": PREPARATION_VERSION,
        "sources": [
            {"logical_name": spec.logical_name, "sha256": source_hashes[spec.logical_name]}
            for spec in DATASETS
        ],
    }


def snapshot_dirname(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:20]
    return f"flat-v{FLAT_SCHEMA_VERSION}-{digest}"


def connect(path: Path, *, readonly: bool, cache_kib: int) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(f"PRAGMA cache_size = {-cache_kib}")
    connection.row_factory = sqlite3.Row
    return connection


def validate_headers(spec: DatasetSpec, actual: Sequence[str]) -> None:
    if any(header.strip() == "" for header in actual) or len(actual) != len(set(actual)):
        raise PreparationError(
            "INVALID_HEADER",
            f"{spec.logical_name}: blank or duplicate header",
        )
    if tuple(actual) != spec.headers:
        raise PreparationError(
            "SCHEMA_MISMATCH",
            f"{spec.logical_name}: header does not match the flat contract",
        )


def is_fully_blank(cells: Sequence[str]) -> bool:
    return all(cell.strip() == "" for cell in cells)


def open_csv(path: Path) -> tuple[Any, Any]:
    handle = path.open("r", encoding="utf-8-sig", newline="")
    return csv.reader(handle, strict=True), handle


def parser_error(dataset_name: str, exc: csv.Error) -> PreparationError:
    message = str(exc)
    code = "FIELD_TOO_LARGE" if "field larger than field limit" in message else "MALFORMED_RECORD"
    return PreparationError(code, f"{dataset_name}: {message}")


def string_row(row: Any) -> list[str]:
    if not isinstance(row, list):
        raise PreparationError("MALFORMED_RECORD", "CSV record is not a list of fields")
    cells: list[str] = []
    for item in cast(list[Any], row):
        if not isinstance(item, str):
            raise PreparationError("MALFORMED_RECORD", "CSV field is not text")
        cells.append(item)
    return cells


def iter_records(spec: DatasetSpec, path: Path) -> Iterable[tuple[int, list[str]]]:
    reader, handle = open_csv(path)
    try:
        try:
            header = string_row(next(reader))
        except StopIteration as exc:
            raise PreparationError(
                "SCHEMA_MISMATCH", f"{spec.logical_name}: missing header"
            ) from exc
        except csv.Error as exc:
            raise parser_error(spec.logical_name, exc) from exc
        validate_headers(spec, header)
        for record_number, raw_row in enumerate(cast(Iterable[Any], reader), start=1):
            row = string_row(raw_row)
            if len(row) != len(spec.headers):
                raise PreparationError(
                    "MALFORMED_RECORD",
                    (
                        f"{spec.logical_name}: record {record_number} has {len(row)} fields, "
                        f"expected {len(spec.headers)}"
                    ),
                )
            yield record_number, row
    except csv.Error as exc:
        raise parser_error(spec.logical_name, exc) from exc
    finally:
        handle.close()


def create_table(connection: sqlite3.Connection, spec: DatasetSpec) -> None:
    columns: list[str] = []
    for header in spec.headers:
        column = f"{quote_ident(header)} TEXT NOT NULL"
        if header == "row_id":
            column += " PRIMARY KEY"
        columns.append(column)
    connection.execute(f"CREATE TABLE {quote_ident(spec.table_name)} ({', '.join(columns)})")


def insert_sql(spec: DatasetSpec) -> str:
    names = ", ".join(quote_ident(header) for header in spec.headers)
    placeholders = ", ".join("?" for _ in spec.headers)
    return f"INSERT INTO {quote_ident(spec.table_name)} ({names}) VALUES ({placeholders})"


def flush_batch(
    connection: sqlite3.Connection,
    spec: DatasetSpec,
    sql: str,
    batch: list[tuple[str, ...]],
    row_id_index: int,
) -> None:
    if not batch:
        return
    try:
        connection.executemany(sql, batch)
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        for cells in batch:
            try:
                connection.execute(sql, cells)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise PreparationError(
                    "DUPLICATE_ROW_ID",
                    f"{spec.logical_name}: duplicate row_id {cells[row_id_index]!r}",
                ) from exc
        raise PreparationError(
            "DUPLICATE_ROW_ID",
            f"{spec.logical_name}: duplicate row_id rejected by SQLite",
        ) from None
    batch.clear()


def import_dataset(
    connection: sqlite3.Connection,
    spec: DatasetSpec,
    path: Path,
    batch_size: int,
) -> dict[str, Any]:
    create_table(connection, spec)
    sql = insert_sql(spec)
    row_id_index = spec.headers.index("row_id")
    digest = hashlib.sha256()
    imported = 0
    skipped = 0
    batch: list[tuple[str, ...]] = []
    started = time.perf_counter()
    LOGGER.info("import start dataset=%s", spec.logical_name)
    for record_number, row in iter_records(spec, path):
        if is_fully_blank(row):
            skipped += 1
            continue
        row_id = row[row_id_index]
        if row_id.strip() == "":
            raise PreparationError(
                "ROW_ID_BLANK",
                f"{spec.logical_name}: record {record_number} has a blank row_id",
            )
        cells = tuple(row)
        digest.update(row_token(cells))
        batch.append(cells)
        imported += 1
        if len(batch) >= batch_size:
            flush_batch(connection, spec, sql, batch, row_id_index)
            LOGGER.info(
                "import progress dataset=%s rows=%s elapsed_seconds=%.3f",
                spec.logical_name,
                imported,
                time.perf_counter() - started,
            )
    flush_batch(connection, spec, sql, batch, row_id_index)
    elapsed = time.perf_counter() - started
    LOGGER.info(
        "import done dataset=%s rows=%s blank_skipped=%s elapsed_seconds=%.3f",
        spec.logical_name,
        imported,
        skipped,
        elapsed,
    )
    return {
        "imported_rows": imported,
        "blank_records_skipped": skipped,
        "content_digest_sha256": digest.hexdigest(),
        "elapsed_seconds": round(elapsed, 3),
    }


def source_digest(spec: DatasetSpec, path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for _record_number, row in iter_records(spec, path):
        if is_fully_blank(row):
            continue
        digest.update(row_token(row))
        count += 1
    return digest.hexdigest(), count


def database_digest(connection: sqlite3.Connection, spec: DatasetSpec) -> tuple[str, int]:
    columns = ", ".join(quote_ident(header) for header in spec.headers)
    digest = hashlib.sha256()
    count = 0
    cursor = connection.execute(
        f"SELECT {columns} FROM {quote_ident(spec.table_name)} ORDER BY rowid"
    )
    while True:
        rows = cursor.fetchmany(DEFAULT_BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            cells = tuple(str(value) for value in row)
            digest.update(row_token(cells))
            count += 1
    return digest.hexdigest(), count


def profile_difference(spec: DatasetSpec, imported_rows: int, source_bytes: int) -> str:
    same_rows = imported_rows == spec.historical_rows
    same_columns = len(spec.headers) == spec.historical_columns
    same_bytes = source_bytes == spec.historical_bytes
    if same_rows and same_columns and same_bytes:
        return (
            "Actual bytes, column count, and nonblank rows match the 2026-09-25 profile reference."
        )
    return (
        "Differs from the 2026-09-25 profile reference: "
        f"rows {imported_rows} vs {spec.historical_rows}, "
        f"columns {len(spec.headers)} vs {spec.historical_columns}, "
        f"bytes {source_bytes} vs {spec.historical_bytes}. "
        "Counts use this build's nonblank-record rule."
    )


def lookup_plan(connection: sqlite3.Connection, spec: DatasetSpec) -> str:
    rows = connection.execute(
        f"EXPLAIN QUERY PLAN SELECT * FROM {quote_ident(spec.table_name)} WHERE row_id = ?",
        ("example",),
    ).fetchall()
    return " | ".join(str(row["detail"]) for row in rows)


def bounded_scan_count(connection: sqlite3.Connection, spec: DatasetSpec) -> int:
    rows = connection.execute(
        f"SELECT rowid FROM {quote_ident(spec.table_name)} WHERE rowid > ? ORDER BY rowid LIMIT ?",
        (0, 2),
    ).fetchall()
    return len(rows)


def table_columns(connection: sqlite3.Connection, spec: DatasetSpec) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({quote_ident(spec.table_name)})").fetchall()
    return [str(row["name"]) for row in rows]


def uo_policy_observations(connection: sqlite3.Connection) -> list[dict[str, str]]:
    placeholders = ", ".join("?" for _ in UO_POLICY_TERMS)
    sql = (
        "SELECT row_id, "
        '"Operation ID", "Search term (EN)", "Match policy", "Index this row", '
        '"Scope / ambiguity rule" '
        f'FROM unit_operations WHERE "Search term (EN)" IN ({placeholders}) '
        "ORDER BY rowid"
    )
    rows = connection.execute(sql, UO_POLICY_TERMS).fetchall()
    return [{key: str(row[key]) for key in row.keys()} for row in rows]


def verify_database(
    connection: sqlite3.Connection,
    sources: Mapping[str, Path],
    import_stats: Mapping[str, Mapping[str, Any]],
    source_bytes: Mapping[str, int],
) -> list[dict[str, Any]]:
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if [str(row[0]) for row in integrity] != ["ok"]:
        raise PreparationError("INTEGRITY_CHECK_FAILED", "PRAGMA integrity_check did not return ok")
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    expected_tables = sorted(spec.logical_name for spec in DATASETS)
    if tables != expected_tables:
        raise PreparationError("SCHEMA_MISMATCH", f"unexpected tables: {tables}")
    reports: list[dict[str, Any]] = []
    for spec in DATASETS:
        path = sources[spec.logical_name]
        source_hash, source_count = source_digest(spec, path)
        db_hash, db_count = database_digest(connection, spec)
        imported = int(import_stats[spec.logical_name]["imported_rows"])
        import_hash = str(import_stats[spec.logical_name]["content_digest_sha256"])
        columns = table_columns(connection, spec)
        if columns != list(spec.headers):
            raise PreparationError(
                "SCHEMA_MISMATCH", f"{spec.logical_name}: stored column order changed"
            )
        if not (source_hash == db_hash == import_hash and source_count == db_count == imported):
            raise PreparationError(
                "CONTENT_MISMATCH",
                f"{spec.logical_name}: source and database content digests differ",
            )
        plan = lookup_plan(connection, spec)
        if "row_id" not in plan:
            raise PreparationError(
                "LOOKUP_PLAN_UNEXPECTED",
                f"{spec.logical_name}: row_id lookup plan was {plan}",
            )
        reports.append(
            {
                "table": spec.logical_name,
                "columns": columns,
                "column_count": len(columns),
                "imported_rows": imported,
                "blank_records_skipped": import_stats[spec.logical_name]["blank_records_skipped"],
                "source_bytes": source_bytes[spec.logical_name],
                "content_digest_sha256": db_hash,
                "historical_profile": {
                    "rows": spec.historical_rows,
                    "columns": spec.historical_columns,
                    "bytes": spec.historical_bytes,
                },
                "profile_difference": profile_difference(
                    spec, imported, source_bytes[spec.logical_name]
                ),
                "row_id_lookup_plan": plan,
                "bounded_scan_rows": bounded_scan_count(connection, spec),
            }
        )
    return reports


def fingerprints(sources: Mapping[str, Path]) -> dict[str, tuple[int, str]]:
    return {name: (path.stat().st_size, sha256_file(path)) for name, path in sources.items()}


def require_unchanged(
    before: Mapping[str, tuple[int, str]],
    sources: Mapping[str, Path],
) -> None:
    after = fingerprints(sources)
    if after != before:
        raise PreparationError(
            "SOURCE_CHANGED",
            "a source file changed during import or verification",
        )


def read_json(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PreparationError("SNAPSHOT_INVALID", f"{path.name} is not an object")
    parsed: dict[str, Any] = {}
    for key, value in cast(dict[Any, Any], payload).items():
        if not isinstance(key, str):
            raise PreparationError("SNAPSHOT_INVALID", f"{path.name} has a non-text key")
        parsed[key] = value
    return parsed


@dataclass(frozen=True)
class ReusableSnapshot:
    manifest: dict[str, Any]
    validation_report: dict[str, Any]


def _is_json_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    parsed: dict[str, Any] = {}
    for key, item in cast(dict[Any, Any], value).items():
        if not isinstance(key, str):
            return None
        parsed[key] = item
    return parsed


def _json_objects(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(cast(list[Any], value)) != len(DATASETS):
        return None
    objects: list[dict[str, Any]] = []
    for item in cast(list[Any], value):
        parsed = _json_object(item)
        if parsed is None:
            return None
        objects.append(parsed)
    return objects


def _report_matches_manifest(manifest: Mapping[str, Any], report: Mapping[str, Any]) -> bool:
    if report.get("integrity_check") != "ok":
        return False
    if report.get("content_digests_match") is not True:
        return False
    if report.get("source_files_unchanged") is not True:
        return False
    if report.get("wal_sidecar_absent") is not True:
        return False
    tables = _json_objects(report.get("tables"))
    sources = _json_objects(manifest.get("sources"))
    if tables is None or sources is None:
        return False
    source_counts: dict[str, int] = {}
    for source in sources:
        name = source.get("logical_name")
        count = source.get("row_count")
        if not isinstance(name, str) or not _is_json_int(count):
            return False
        source_counts[name] = count
    seen: set[str] = set()
    for table in tables:
        name = table.get("table")
        count = table.get("imported_rows")
        if not isinstance(name, str) or not _is_json_int(count):
            return False
        if source_counts.get(name) != count:
            return False
        seen.add(name)
    expected = {spec.logical_name for spec in DATASETS}
    return seen == expected and set(source_counts) == expected


def reusable_snapshot(snapshot_dir: Path, identity: Mapping[str, Any]) -> ReusableSnapshot | None:
    manifest_path = snapshot_dir / "manifest.json"
    database_path = snapshot_dir / "knowledge.sqlite"
    report_path = snapshot_dir / "validation_report.json"
    contract_file = snapshot_dir / CONTRACT_NAME
    required = (manifest_path, database_path, report_path, contract_file)
    if not all(path.is_file() for path in required):
        return None
    if database_path.with_name(database_path.name + "-wal").exists():
        return None
    try:
        manifest = read_json(manifest_path)
        report = read_json(report_path)
        contract_text = contract_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, PreparationError):
        return None
    if contract_text.strip() == "":
        return None
    if manifest.get("completion_status") != "complete":
        return None
    if manifest.get("snapshot_identity") != identity:
        return None
    if not _report_matches_manifest(manifest, report):
        return None
    database = _json_object(manifest.get("database"))
    if database is None or not isinstance(database.get("sha256"), str):
        return None
    try:
        if database["sha256"] != sha256_file(database_path):
            return None
    except OSError:
        return None
    try:
        connection = connect(database_path, readonly=True, cache_kib=DEFAULT_CACHE_KIB)
    except sqlite3.Error:
        return None
    try:
        user_version = connection.execute("PRAGMA user_version").fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if user_version is None or int(user_version[0]) != FLAT_SCHEMA_VERSION:
            return None
        if integrity is None or str(integrity[0]) != "ok":
            return None
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return ReusableSnapshot(manifest=manifest, validation_report=report)


def next_snapshot_dir(parent: Path, dirname: str) -> Path:
    primary = parent / dirname
    if not primary.exists():
        return primary
    suffix = 2
    while True:
        candidate = parent / f"{dirname}--{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def resolve_sources(data_root: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for spec in DATASETS:
        path = data_root / spec.relative_path
        if not path.is_file():
            raise PreparationError("SOURCE_MISSING", f"missing {spec.relative_path}")
        sources[spec.logical_name] = path
    return sources


def prepare(
    data_root: Path,
    output_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    cache_kib: int = DEFAULT_CACHE_KIB,
) -> PrepareResult:
    if batch_size < 1 or cache_kib < 1:
        raise PreparationError("INVALID_ARGUMENT", "batch size and cache must be positive")
    contract = contract_path()
    if not contract.is_file():
        raise PreparationError("CONTRACT_MISSING", f"missing {contract}")
    sources = resolve_sources(data_root)
    before = fingerprints(sources)
    for spec in DATASETS:
        reader, handle = open_csv(sources[spec.logical_name])
        try:
            try:
                header = string_row(next(reader))
            except StopIteration as exc:
                raise PreparationError(
                    "SCHEMA_MISMATCH", f"{spec.logical_name}: missing header"
                ) from exc
            except csv.Error as exc:
                raise parser_error(spec.logical_name, exc) from exc
        finally:
            handle.close()
        validate_headers(spec, header)
    source_hashes = {name: digest for name, (_size, digest) in before.items()}
    identity = snapshot_identity(source_hashes)
    dirname = snapshot_dirname(identity)
    output_dir.mkdir(parents=True, exist_ok=True)
    primary = output_dir / dirname
    reusable = reusable_snapshot(primary, identity) if primary.exists() else None
    if reusable is not None:
        LOGGER.info("reuse snapshot=%s", primary)
        return PrepareResult(
            snapshot_dir=primary,
            reused=True,
            manifest=reusable.manifest,
            validation_report=reusable.validation_report,
        )
    destination = primary if not primary.exists() else next_snapshot_dir(output_dir, dirname)
    temp_dir = output_dir / f".tmp-{destination.name}-{os.getpid()}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    started = time.perf_counter()
    try:
        database_path = temp_dir / "knowledge.sqlite"
        connection = connect(database_path, readonly=False, cache_kib=cache_kib)
        import_stats: dict[str, dict[str, Any]] = {}
        try:
            for spec in DATASETS:
                import_stats[spec.logical_name] = import_dataset(
                    connection,
                    spec,
                    sources[spec.logical_name],
                    batch_size,
                )
            require_unchanged(before, sources)
            source_bytes = {name: size for name, (size, _digest) in before.items()}
            table_reports = verify_database(connection, sources, import_stats, source_bytes)
            observations = uo_policy_observations(connection)
            connection.execute(f"PRAGMA user_version = {FLAT_SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()
        require_unchanged(before, sources)
        for suffix in ("-wal", "-shm"):
            if database_path.with_name(database_path.name + suffix).exists():
                raise PreparationError(
                    "WAL_PRESENT", "published database must not have a WAL sidecar"
                )
        database_hash = sha256_file(database_path)
        database_size = database_path.stat().st_size
        completed_at = datetime.now(UTC).isoformat()
        manifest: dict[str, Any] = {
            "flat_schema_version": FLAT_SCHEMA_VERSION,
            "preparation_version": PREPARATION_VERSION,
            "snapshot_id": dirname,
            "snapshot_identity": identity,
            "code_identity_sha256": code_identity(),
            "completed_at": completed_at,
            "completion_status": "complete",
            "sources": [
                {
                    "logical_name": spec.logical_name,
                    "relative_path": spec.relative_path,
                    "sha256": source_hashes[spec.logical_name],
                    "size_bytes": before[spec.logical_name][0],
                    "headers": list(spec.headers),
                    "row_count": import_stats[spec.logical_name]["imported_rows"],
                    "blank_records_skipped": import_stats[spec.logical_name][
                        "blank_records_skipped"
                    ],
                }
                for spec in DATASETS
            ],
            "database": {
                "file_name": "knowledge.sqlite",
                "sha256": database_hash,
                "size_bytes": database_size,
                "user_version": FLAT_SCHEMA_VERSION,
            },
            "settings": {
                "batch_size": batch_size,
                "cache_kib": cache_kib,
                "journal_mode": "DELETE",
                "synchronous": "FULL",
                "max_field_bytes": MAX_FIELD_BYTES,
            },
        }
        validation_report: dict[str, Any] = {
            "integrity_check": "ok",
            "content_digests_match": True,
            "source_files_unchanged": True,
            "wal_sidecar_absent": True,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "peak_memory": peak_memory(),
            "tables": table_reports,
            "uo_policy_observations": observations,
            "blank_record_rule": (
                "A record is fully blank when every cell is empty or whitespace-only. "
                "Those records are skipped and counted. They are not inserted."
            ),
        }
        write_json(temp_dir / "manifest.json", manifest)
        write_json(temp_dir / "validation_report.json", validation_report)
        shutil.copyfile(contract, temp_dir / CONTRACT_NAME)
        os.replace(temp_dir, destination)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    LOGGER.info(
        "published snapshot=%s bytes=%s elapsed_seconds=%.3f",
        destination,
        destination.joinpath("knowledge.sqlite").stat().st_size,
        time.perf_counter() - started,
    )
    return PrepareResult(
        snapshot_dir=destination,
        reused=False,
        manifest=manifest,
        validation_report=validation_report,
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the flat knowledge SQLite snapshot")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--cache-kib", type=int, default=DEFAULT_CACHE_KIB)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = prepare(
            args.data_root,
            args.output_dir,
            batch_size=args.batch_size,
            cache_kib=args.cache_kib,
        )
    except PreparationError as exc:
        LOGGER.error("%s", exc)
        return 1
    LOGGER.info("snapshot=%s reused=%s", result.snapshot_dir, result.reused)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
