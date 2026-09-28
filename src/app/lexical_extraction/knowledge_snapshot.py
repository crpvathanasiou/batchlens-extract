"""Read-only access to one validated flat SQLite knowledge snapshot.

Preflight checks the snapshot companions once, pins that build, and opens a
single ``mode=ro`` connection. Later callers page one allowlisted table or
look up one source ``row_id``. This module does not interpret search fields,
normalize terms, match document text, parse values, or publish artifacts.

The database file is hashed in finite chunks. Catalogue scans stay inside the
configured batch limit and are not deduplicated. ``scan_cursor`` is the
SQLite ``rowid`` for this pinned file. It is not the source ``row_id``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn, cast

from pydantic import ValidationError

from app.lexical_extraction.configuration import (
    MAX_SQLITE_CACHE_KIB,
    MAX_SQLITE_READ_BATCH_ROWS,
    EffectiveExecutionConfiguration,
)
from app.lexical_extraction.contracts import (
    FLAT_SQLITE_PREPARATION_VERSION,
    FLAT_SQLITE_USER_VERSION,
    KnowledgeSnapshotIdentity,
    SafeStructuredError,
)

DATABASE_NAME: Final = "knowledge.sqlite"
MANIFEST_NAME: Final = "manifest.json"
REPORT_NAME: Final = "validation_report.json"
CONTRACT_NAME: Final = "FLAT_SQLITE_CONTRACT.md"
_HASH_CHUNK_BYTES: Final = 1024 * 1024
_SQLITE_HEADER: Final = b"SQLite format 3\x00"
_WAL_WRITE_VERSION: Final = 2
_MAX_ROWID: Final = 2**63 - 1
_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")

# Fixed v1 source headers from docs/FLAT_SQLITE_CONTRACT.md, in source order.
# L04 returns these cells unchanged. It does not choose search fields.
FLAT_SOURCE_TABLES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "materials_fda_ema",
        (
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
    ),
    (
        "materials_chebi",
        (
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
    ),
    (
        "equipment",
        (
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
    ),
    (
        "unit_operations",
        (
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
    ),
)

_TABLE_HEADERS: Final[Mapping[str, tuple[str, ...]]] = dict(FLAT_SOURCE_TABLES)
_TABLE_NAMES: Final[frozenset[str]] = frozenset(_TABLE_HEADERS)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _compile_sql() -> tuple[dict[str, str], dict[str, str]]:
    scan: dict[str, str] = {}
    lookup: dict[str, str] = {}
    for table_name, headers in FLAT_SOURCE_TABLES:
        columns = ", ".join(_quote_ident(header) for header in headers)
        quoted_table = _quote_ident(table_name)
        scan[table_name] = (
            f"SELECT rowid AS scan_cursor, {columns} FROM {quoted_table} "
            "WHERE rowid > ? ORDER BY rowid LIMIT ?"
        )
        lookup[table_name] = (
            f"SELECT rowid AS scan_cursor, {columns} FROM {quoted_table} "
            f"WHERE {_quote_ident('row_id')} = ?"
        )
    return scan, lookup


_SCAN_SQL, _LOOKUP_SQL = _compile_sql()


class SnapshotReadError(Exception):
    """Bounded flat-snapshot read/validation failure.

    ``code`` and ``message`` map to :class:`SafeStructuredError`. A failure is
    not a successful validation and is not an empty catalogue result.
    """

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= 200:
            raise ValueError("snapshot error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class SourceRow:
    """One flat source row from a single allowlisted table.

    ``values`` keeps every source column, in contract order, as stored text.
    ``scan_cursor`` is this snapshot's SQLite ``rowid``. ``row_id`` is the
    source primary key and may differ from ``scan_cursor``.
    """

    table_name: str
    scan_cursor: int
    row_id: str
    values: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SourceBatch:
    """One bounded page. An empty ``rows`` tuple is the end of the scan."""

    table_name: str
    after_rowid: int
    rows: tuple[SourceRow, ...]

    @property
    def next_after_rowid(self) -> int:
        """Cursor for the next page. Unchanged when this page is empty."""

        if not self.rows:
            return self.after_rowid
        return self.rows[-1].scan_cursor


@dataclass(frozen=True)
class _Pin:
    path: Path
    size: int
    mtime_ns: int
    sha256: str
    rehash: bool


@dataclass(frozen=True)
class _Limits:
    read_batch_rows: int
    cache_kib: int


@dataclass(frozen=True)
class _ManifestFacts:
    snapshot_id: str
    counts: dict[str, int]
    database_sha256: str
    database_size: int


@dataclass(frozen=True)
class _Companions:
    directory: Path
    database: Path
    manifest: Path
    report: Path
    contract: Path


def _error(code: str, message: str) -> SnapshotReadError:
    return SnapshotReadError(code, message)


def _require_row_id(value: object) -> str:
    if not isinstance(value, str):
        raise _error("INVALID_ROW_ID", "row_id must be text")
    return value


def _require_limit(value: object, *, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error("INVALID_LIMIT", f"{what} must be an integer")
    return value


def _validate_limits(read_batch_rows: object, cache_kib: object) -> _Limits:
    batch = _require_limit(read_batch_rows, what="read batch")
    cache = _require_limit(cache_kib, what="cache size")
    if not 1 <= batch <= MAX_SQLITE_READ_BATCH_ROWS:
        raise _error("INVALID_LIMIT", "read batch is outside the configured range")
    if not 1 <= cache <= MAX_SQLITE_CACHE_KIB:
        raise _error("INVALID_LIMIT", "cache size is outside the configured range")
    return _Limits(read_batch_rows=batch, cache_kib=cache)


def _as_object(value: object, code: str, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _error(code, message)
    parsed: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise _error(code, message)
        parsed[key] = item
    return parsed


def _as_objects(value: object, code: str, message: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _error(code, message)
    return [_as_object(item, code, message) for item in cast(list[object], value)]


def _require_text(value: object, code: str, message: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise _error(code, message)
    return value


def _require_exact(value: object, expected: object, code: str, message: str) -> None:
    if value != expected:
        raise _error(code, message)


def _require_int(value: object, code: str, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(code, message)
    return value


def _require_version_one(value: object, code: str, message: str) -> None:
    """Require the exact JSON integer ``1``. Booleans and numeric strings fail."""

    if _require_int(value, code, message) != FLAT_SQLITE_USER_VERSION:
        raise _error(code, message)


def _require_sha256(value: object, code: str, message: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise _error(code, message)
    return value


def derive_snapshot_id(snapshot_identity: Mapping[str, object]) -> str:
    """Return the producer ``snapshot_id`` for one validated snapshot identity.

    Uses the locked flat-v1 formula: ``flat-v1-`` plus the first 20 lowercase
    hex characters of SHA-256 over UTF-8
    ``json.dumps(..., sort_keys=True, separators=(",", ":"))``.
    """

    encoded = json.dumps(snapshot_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"flat-v{FLAT_SQLITE_USER_VERSION}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _read_companion(path: Path) -> bytes:
    try:
        chunks: list[bytes] = []
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise _error("COMPANION_UNREADABLE", f"{path.name} is not readable") from exc
    return b"".join(chunks)


def _parse_json_object(payload: bytes, code: str, message: str) -> dict[str, object]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _error(code, message) from exc
    return _as_object(parsed, code, message)


def _companions(snapshot_directory: Path) -> _Companions:
    directory = snapshot_directory.resolve()
    return _Companions(
        directory=directory,
        database=directory / DATABASE_NAME,
        manifest=directory / MANIFEST_NAME,
        report=directory / REPORT_NAME,
        contract=directory / CONTRACT_NAME,
    )


def _require_companions(companions: _Companions) -> None:
    for path in (
        companions.database,
        companions.manifest,
        companions.report,
        companions.contract,
    ):
        if not path.is_file():
            raise _error("COMPANION_MISSING", f"missing {path.name}")


def _sidecar_paths(database: Path) -> tuple[Path, Path, Path]:
    return (
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
        database.with_name(database.name + "-journal"),
    )


def _reject_sidecars(database: Path) -> None:
    for path in _sidecar_paths(database):
        if path.exists():
            raise _error("WAL_PRESENT", "database sidecar is present")


def _reject_wal_header(database: Path) -> None:
    try:
        with database.open("rb") as handle:
            header = handle.read(100)
    except OSError as exc:
        raise _error("COMPANION_UNREADABLE", "knowledge.sqlite is not readable") from exc
    if len(header) >= 19 and header.startswith(_SQLITE_HEADER) and header[18] == _WAL_WRITE_VERSION:
        raise _error("WAL_PRESENT", "database is in WAL mode")


def _indexed_records(
    records: list[dict[str, object]],
    *,
    name_key: str,
    code: str,
    message: str,
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for record in records:
        name = record.get(name_key)
        if not isinstance(name, str) or name not in _TABLE_NAMES or name in indexed:
            raise _error(code, message)
        indexed[name] = record
    if frozenset(indexed) != _TABLE_NAMES:
        raise _error(code, message)
    return indexed


def _ordered_identity_sources(value: object) -> list[tuple[str, str]]:
    """Return producer-ordered ``(logical_name, sha256)`` pairs from identity sources."""

    records = _as_objects(
        value,
        "MANIFEST_INVALID",
        "snapshot identity sources are invalid",
    )
    if len(records) != len(FLAT_SOURCE_TABLES):
        raise _error("MANIFEST_INVALID", "snapshot identity sources are invalid")
    ordered: list[tuple[str, str]] = []
    for index, (table_name, _headers) in enumerate(FLAT_SOURCE_TABLES):
        record = records[index]
        name = record.get("logical_name")
        if name != table_name:
            raise _error(
                "MANIFEST_INVALID",
                "snapshot identity sources are not in producer order",
            )
        digest = _require_sha256(
            record.get("sha256"),
            "MANIFEST_INVALID",
            "source hash is invalid",
        )
        ordered.append((table_name, digest))
    return ordered


def _canonical_snapshot_identity(
    sources: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "flat_schema_version": FLAT_SQLITE_USER_VERSION,
        "preparation_version": FLAT_SQLITE_PREPARATION_VERSION,
        "sources": [{"logical_name": name, "sha256": digest} for name, digest in sources],
    }


def _header_tuple(value: object, code: str, message: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _error(code, message)
    headers: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise _error(code, message)
        headers.append(item)
    return tuple(headers)


def _validate_documents(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
) -> _ManifestFacts:
    _require_version_one(
        manifest.get("flat_schema_version"),
        "MANIFEST_INVALID",
        "flat schema version is not 1",
    )
    _require_exact(
        manifest.get("preparation_version"),
        FLAT_SQLITE_PREPARATION_VERSION,
        "MANIFEST_INVALID",
        "preparation version is not flat-sqlite-1",
    )
    _require_exact(
        manifest.get("completion_status"),
        "complete",
        "MANIFEST_INVALID",
        "completion_status is not complete",
    )
    snapshot_id = _require_text(
        manifest.get("snapshot_id"),
        "MANIFEST_INVALID",
        "snapshot_id is missing",
    )
    identity = _as_object(
        manifest.get("snapshot_identity"),
        "MANIFEST_INVALID",
        "snapshot identity is missing",
    )
    _require_version_one(
        identity.get("flat_schema_version"),
        "MANIFEST_INVALID",
        "snapshot identity schema version is not 1",
    )
    _require_exact(
        identity.get("preparation_version"),
        FLAT_SQLITE_PREPARATION_VERSION,
        "MANIFEST_INVALID",
        "snapshot identity preparation version is not flat-sqlite-1",
    )
    identity_sources = _ordered_identity_sources(identity.get("sources"))
    canonical_identity = _canonical_snapshot_identity(identity_sources)
    expected_snapshot_id = derive_snapshot_id(canonical_identity)
    if snapshot_id != expected_snapshot_id:
        raise _error("MANIFEST_INVALID", "snapshot_id does not match snapshot identity")
    identity_hashes = dict(identity_sources)
    manifest_sources = _indexed_records(
        _as_objects(
            manifest.get("sources"),
            "MANIFEST_INVALID",
            "manifest sources are invalid",
        ),
        name_key="logical_name",
        code="MANIFEST_INVALID",
        message="manifest sources are invalid",
    )
    database = _as_object(
        manifest.get("database"),
        "MANIFEST_INVALID",
        "database record is missing",
    )
    _require_exact(
        database.get("file_name"),
        DATABASE_NAME,
        "MANIFEST_INVALID",
        "database file name is not knowledge.sqlite",
    )
    database_sha = _require_sha256(
        database.get("sha256"),
        "MANIFEST_INVALID",
        "database hash is invalid",
    )
    database_size = _require_int(
        database.get("size_bytes"),
        "MANIFEST_INVALID",
        "database size is invalid",
    )
    if database_size < 0:
        raise _error("MANIFEST_INVALID", "database size is invalid")
    _require_version_one(
        database.get("user_version"),
        "MANIFEST_INVALID",
        "database user version is not 1",
    )
    _require_exact(
        report.get("integrity_check"), "ok", "REPORT_INVALID", "integrity_check is not ok"
    )
    if report.get("content_digests_match") is not True:
        raise _error("REPORT_INVALID", "content digest flag is not true")
    if report.get("source_files_unchanged") is not True:
        raise _error("REPORT_INVALID", "source preservation flag is not true")
    if report.get("wal_sidecar_absent") is not True:
        raise _error("REPORT_INVALID", "WAL absence flag is not true")
    report_tables = _indexed_records(
        _as_objects(report.get("tables"), "REPORT_INVALID", "report tables are invalid"),
        name_key="table",
        code="REPORT_INVALID",
        message="report tables are invalid",
    )
    counts: dict[str, int] = {}
    for table_name, headers in FLAT_SOURCE_TABLES:
        source = manifest_sources[table_name]
        source_sha = _require_sha256(
            source.get("sha256"),
            "MANIFEST_INVALID",
            "source hash is invalid",
        )
        if source_sha != identity_hashes[table_name]:
            raise _error("MANIFEST_INVALID", "snapshot identity does not match sources")
        actual_headers = _header_tuple(
            source.get("headers"),
            "MANIFEST_INVALID",
            "manifest headers are invalid",
        )
        if actual_headers != headers:
            raise _error("SCHEMA_MISMATCH", "manifest headers do not match the flat contract")
        row_count = _require_int(
            source.get("row_count"),
            "MANIFEST_INVALID",
            "manifest row count is invalid",
        )
        if row_count < 0:
            raise _error("MANIFEST_INVALID", "manifest row count is invalid")
        table = report_tables[table_name]
        report_headers = _header_tuple(
            table.get("columns"),
            "REPORT_INVALID",
            "report columns are invalid",
        )
        if report_headers != headers:
            raise _error("SCHEMA_MISMATCH", "report columns do not match the flat contract")
        column_count = _require_int(
            table.get("column_count"),
            "REPORT_INVALID",
            "report column count is invalid",
        )
        if column_count != len(headers):
            raise _error("SCHEMA_MISMATCH", "report column count does not match the header")
        imported_rows = _require_int(
            table.get("imported_rows"),
            "REPORT_INVALID",
            "report row count is invalid",
        )
        if imported_rows != row_count:
            raise _error("COUNT_MISMATCH", "report row count does not match the manifest")
        counts[table_name] = row_count
    return _ManifestFacts(
        snapshot_id=snapshot_id,
        counts=counts,
        database_sha256=database_sha,
        database_size=database_size,
    )


def _match_database_file(
    database_sha: str,
    database_size: int,
    digest: str,
    size: int,
) -> None:
    if size != database_size:
        raise _error("SIZE_MISMATCH", "knowledge.sqlite size does not match the manifest")
    if digest != database_sha:
        raise _error("HASH_MISMATCH", "knowledge.sqlite hash does not match the manifest")


def _stat_pair(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise _error("COMPANION_UNREADABLE", f"{path.name} is not readable") from exc
    return stat.st_size, stat.st_mtime_ns


def _pin_file(path: Path, sha256: str, *, rehash: bool) -> _Pin:
    size, mtime_ns = _stat_pair(path)
    return _Pin(path=path, size=size, mtime_ns=mtime_ns, sha256=sha256, rehash=rehash)


def _require_stable(path: Path, before: tuple[int, int], hashed_size: int) -> tuple[int, int]:
    after = _stat_pair(path)
    if before != after or before[0] != hashed_size:
        raise _error("SNAPSHOT_CHANGED", "snapshot files changed during preflight")
    return after


def _connect(database: Path, cache_kib: int) -> sqlite3.Connection:
    uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.text_factory = str
        connection.isolation_level = None
        connection.execute("PRAGMA query_only = ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only is None or query_only[0] != 1:
            raise _error("READ_FAILED", "read-only mode was not enabled")
        connection.execute(f"PRAGMA cache_size = {-cache_kib}")
        connection.execute("PRAGMA temp_store = MEMORY")
    except BaseException:
        connection.close()
        raise
    return connection


def _validate_sqlite(
    connection: sqlite3.Connection,
    counts: Mapping[str, int],
) -> None:
    journal = connection.execute("PRAGMA journal_mode").fetchone()
    if journal is None or not isinstance(journal[0], str):
        raise _error("SCHEMA_MISMATCH", "journal mode is not delete")
    journal_mode = journal[0].lower()
    if journal_mode == "wal":
        raise _error("WAL_PRESENT", "database is in WAL mode")
    if journal_mode != "delete":
        raise _error("SCHEMA_MISMATCH", "journal mode is not delete")
    version = connection.execute("PRAGMA user_version").fetchone()
    if version is None or version[0] != FLAT_SQLITE_USER_VERSION:
        raise _error("SCHEMA_MISMATCH", "user version is not 1")
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if [str(row[0]) for row in integrity] != ["ok"]:
        raise _error("INTEGRITY_CHECK_FAILED", "PRAGMA integrity_check did not return ok")
    master = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = sorted(str(row["name"]) for row in master if str(row["type"]) == "table")
    extras = [row for row in master if str(row["type"]) != "table"]
    if tables != sorted(_TABLE_NAMES) or extras:
        raise _error("SCHEMA_MISMATCH", "snapshot tables do not match the flat contract")
    for table_name, headers in FLAT_SOURCE_TABLES:
        _validate_table(connection, table_name, headers, counts[table_name])


def _validate_table(
    connection: sqlite3.Connection,
    table_name: str,
    headers: tuple[str, ...],
    expected_count: int,
) -> None:
    definition = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if definition is None or not isinstance(definition[0], str):
        raise _error("SCHEMA_MISMATCH", "table definition is missing")
    if "WITHOUT ROWID" in definition[0].upper():
        raise _error("SCHEMA_MISMATCH", "table is not a rowid table")
    info = connection.execute(f"PRAGMA table_info({_quote_ident(table_name)})").fetchall()
    if len(info) != len(headers):
        raise _error("SCHEMA_MISMATCH", "table columns do not match the flat contract")
    for column, header in zip(info, headers, strict=True):
        name = column["name"]
        declared = column["type"]
        not_null = column["notnull"]
        primary_key = column["pk"]
        if name != header or not isinstance(declared, str) or declared.upper() != "TEXT":
            raise _error("SCHEMA_MISMATCH", "table columns do not match the flat contract")
        if not_null != 1:
            raise _error("SCHEMA_MISMATCH", "source column is not TEXT NOT NULL")
        expected_pk = 1 if header == "row_id" else 0
        if primary_key != expected_pk:
            raise _error("SCHEMA_MISMATCH", "row_id is not the only primary key")
    probe = connection.execute(
        f"SELECT rowid FROM {_quote_ident(table_name)} WHERE rowid > ? ORDER BY rowid LIMIT ?",
        (0, 1),
    ).fetchone()
    if probe is not None and (isinstance(probe[0], bool) or not isinstance(probe[0], int)):
        raise _error("SCHEMA_MISMATCH", "table is not a rowid table")
    counted = connection.execute(f"SELECT COUNT(*) FROM {_quote_ident(table_name)}").fetchone()
    if counted is None or counted[0] != expected_count:
        raise _error("COUNT_MISMATCH", "database row count does not match the manifest")


def _source_row(table_name: str, row: sqlite3.Row) -> SourceRow:
    headers = _TABLE_HEADERS[table_name]
    cursor = row["scan_cursor"]
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
        raise _error("READ_FAILED", "scan cursor is not a positive integer")
    values: list[tuple[str, str]] = []
    row_id = ""
    for header in headers:
        cell = row[header]
        if not isinstance(cell, str):
            raise _error("SCHEMA_MISMATCH", "source cell is not text")
        values.append((header, cell))
        if header == "row_id":
            row_id = cell
    return SourceRow(
        table_name=table_name,
        scan_cursor=cursor,
        row_id=row_id,
        values=tuple(values),
    )


class KnowledgeSnapshot:
    """One pinned flat snapshot. Construct it with :func:`open_knowledge_snapshot`.

    A directly constructed instance is not open. Scans and lookups fail until
    preflight succeeds, and they fail again after :meth:`close`.
    """

    def __init__(self, snapshot_directory: Path, *, read_batch_rows: int, cache_kib: int) -> None:
        self._directory = snapshot_directory
        self._read_batch_rows = read_batch_rows
        self._cache_kib = cache_kib
        self._connection: sqlite3.Connection | None = None
        self._identity: KnowledgeSnapshotIdentity | None = None
        self._pins: tuple[_Pin, ...] = ()
        self._closed = False

    @property
    def snapshot_directory(self) -> Path:
        return self._directory

    @property
    def read_batch_rows(self) -> int:
        return self._read_batch_rows

    @property
    def cache_kib(self) -> int:
        return self._cache_kib

    @property
    def identity(self) -> KnowledgeSnapshotIdentity:
        """Identity from the successful preflight. Absent before preflight."""

        if self._identity is None:
            raise _error("SNAPSHOT_NOT_OPEN", "snapshot is not open")
        return self._identity

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._closed = True
        if connection is not None:
            connection.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def __enter__(self) -> KnowledgeSnapshot:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()

    def read_batch(
        self,
        table_name: str,
        *,
        after_rowid: int = 0,
        batch_size: int | None = None,
    ) -> SourceBatch:
        """Return the next page of one allowlisted table.

        Pages use ``rowid > after_rowid ORDER BY rowid LIMIT batch_size``,
        starting at zero. ``batch_size`` defaults to the validated read limit
        and cannot exceed it.
        """

        connection = self._require_connection()
        self._require_table(table_name)
        limit = self._require_batch_size(batch_size)
        cursor = self._require_after_rowid(after_rowid)
        try:
            self._require_unchanged()
            fetched = connection.execute(_SCAN_SQL[table_name], (cursor, limit)).fetchall()
            rows: list[SourceRow] = []
            previous = cursor
            for raw in fetched:
                source = _source_row(table_name, raw)
                if source.scan_cursor <= previous:
                    raise _error("READ_FAILED", "scan cursor did not advance")
                previous = source.scan_cursor
                rows.append(source)
            return SourceBatch(table_name=table_name, after_rowid=cursor, rows=tuple(rows))
        except SnapshotReadError as exc:
            self._fail(exc)
        except sqlite3.Error as exc:
            self._fail(_error("READ_FAILED", "sqlite read failed"), exc)

    def iter_batches(
        self,
        table_name: str,
        *,
        batch_size: int | None = None,
    ) -> Iterator[SourceBatch]:
        """Yield pages of one table, including the empty page that ends the scan."""

        after = 0
        while True:
            batch = self.read_batch(table_name, after_rowid=after, batch_size=batch_size)
            yield batch
            if not batch.rows:
                return
            after = batch.next_after_rowid

    def lookup(self, table_name: str, row_id: str) -> SourceRow | None:
        """Return the source row for ``row_id``, or None when it is absent.

        The lookup uses that table's primary key. ``None`` is the absent
        result. It is not a validation failure and it does not scan other tables.
        """

        connection = self._require_connection()
        self._require_table(table_name)
        source_row_id = _require_row_id(row_id)
        try:
            self._require_unchanged()
            fetched = connection.execute(_LOOKUP_SQL[table_name], (source_row_id,)).fetchone()
            if fetched is None:
                return None
            return _source_row(table_name, fetched)
        except SnapshotReadError as exc:
            self._fail(exc)
        except sqlite3.Error as exc:
            self._fail(_error("READ_FAILED", "sqlite read failed"), exc)

    def _require_connection(self) -> sqlite3.Connection:
        if self._closed or self._connection is None:
            raise _error("SNAPSHOT_NOT_OPEN", "snapshot is not open")
        return self._connection

    def _require_table(self, table_name: object) -> None:
        if not isinstance(table_name, str) or table_name not in _TABLE_NAMES:
            raise _error("INVALID_TABLE", "table is not in the flat snapshot allowlist")

    def _require_batch_size(self, batch_size: int | None) -> int:
        if batch_size is None:
            return self._read_batch_rows
        limit = _require_limit(batch_size, what="batch size")
        if not 1 <= limit <= self._read_batch_rows:
            raise _error("INVALID_LIMIT", "batch size exceeds the configured read limit")
        return limit

    def _require_after_rowid(self, after_rowid: object) -> int:
        cursor = _require_limit(after_rowid, what="after_rowid")
        if cursor < 0 or cursor > _MAX_ROWID:
            raise _error("INVALID_LIMIT", "after_rowid is outside the rowid range")
        return cursor

    def _require_unchanged(self) -> None:
        database = self._directory / DATABASE_NAME
        _reject_sidecars(database)
        for pin in self._pins:
            try:
                stat = pin.path.stat()
            except OSError as exc:
                raise _error("SNAPSHOT_CHANGED", "snapshot files changed after preflight") from exc
            if stat.st_size != pin.size or stat.st_mtime_ns != pin.mtime_ns:
                raise _error("SNAPSHOT_CHANGED", "snapshot files changed after preflight")
            if pin.rehash:
                digest, size = _hash_file(pin.path)
                if digest != pin.sha256 or size != pin.size:
                    raise _error("SNAPSHOT_CHANGED", "snapshot files changed after preflight")

    def _fail(self, exc: SnapshotReadError, cause: BaseException | None = None) -> NoReturn:
        self.close()
        if cause is None:
            raise exc
        raise exc from cause

    def _bind(
        self,
        connection: sqlite3.Connection,
        identity: KnowledgeSnapshotIdentity,
        pins: tuple[_Pin, ...],
    ) -> None:
        self._connection = connection
        self._identity = identity
        self._pins = pins


def open_knowledge_snapshot(
    snapshot_directory: Path,
    *,
    read_batch_rows: int,
    cache_kib: int,
) -> KnowledgeSnapshot:
    """Validate one flat snapshot directory and return a pinned read-only handle.

    Preflight runs once. The returned handle reads only the four flat source
    tables. Original CSV paths named in the manifest are not required.
    """

    limits = _validate_limits(read_batch_rows, cache_kib)
    companions = _companions(snapshot_directory)
    _require_companions(companions)
    _reject_sidecars(companions.database)
    manifest_before = _stat_pair(companions.manifest)
    report_before = _stat_pair(companions.report)
    contract_before = _stat_pair(companions.contract)
    database_before = _stat_pair(companions.database)
    manifest_bytes = _read_companion(companions.manifest)
    report_bytes = _read_companion(companions.report)
    contract_bytes = _read_companion(companions.contract)
    try:
        contract_text = contract_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise _error("COMPANION_UNREADABLE", "FLAT_SQLITE_CONTRACT.md is not readable") from exc
    if contract_text.strip() == "":
        raise _error("CONTRACT_EMPTY", "FLAT_SQLITE_CONTRACT.md is empty")
    manifest = _parse_json_object(
        manifest_bytes,
        "MANIFEST_INVALID",
        "manifest.json is not a JSON object",
    )
    report = _parse_json_object(
        report_bytes,
        "REPORT_INVALID",
        "validation_report.json is not a JSON object",
    )
    facts = _validate_documents(manifest, report)
    manifest_sha, manifest_size = _hash_file(companions.manifest)
    report_sha, report_size = _hash_file(companions.report)
    contract_sha, contract_size = _hash_file(companions.contract)
    database_sha, database_size = _hash_file(companions.database)
    if manifest_sha != hashlib.sha256(manifest_bytes).hexdigest() or manifest_size != len(
        manifest_bytes
    ):
        raise _error("SNAPSHOT_CHANGED", "snapshot files changed during preflight")
    if report_sha != hashlib.sha256(report_bytes).hexdigest() or report_size != len(report_bytes):
        raise _error("SNAPSHOT_CHANGED", "snapshot files changed during preflight")
    if contract_sha != hashlib.sha256(contract_bytes).hexdigest() or contract_size != len(
        contract_bytes
    ):
        raise _error("SNAPSHOT_CHANGED", "snapshot files changed during preflight")
    _require_stable(companions.manifest, manifest_before, manifest_size)
    _require_stable(companions.report, report_before, report_size)
    _require_stable(companions.contract, contract_before, contract_size)
    _require_stable(companions.database, database_before, database_size)
    _match_database_file(facts.database_sha256, facts.database_size, database_sha, database_size)
    _reject_wal_header(companions.database)
    _reject_sidecars(companions.database)
    try:
        identity = KnowledgeSnapshotIdentity(
            snapshot_id=facts.snapshot_id,
            database_sha256=database_sha,
            manifest_sha256=manifest_sha,
        )
    except ValidationError as exc:
        raise _error("MANIFEST_INVALID", "snapshot identity is not valid") from exc
    try:
        connection = _connect(companions.database, limits.cache_kib)
    except SnapshotReadError:
        raise
    except sqlite3.Error as exc:
        raise _error("INTEGRITY_CHECK_FAILED", "database failed integrity check") from exc
    accepted = False
    try:
        try:
            _validate_sqlite(connection, facts.counts)
        except sqlite3.Error as exc:
            raise _error("INTEGRITY_CHECK_FAILED", "database failed integrity check") from exc
        _reject_sidecars(companions.database)
        pins = (
            _pin_file(companions.database, database_sha, rehash=False),
            _pin_file(companions.manifest, manifest_sha, rehash=True),
            _pin_file(companions.report, report_sha, rehash=True),
            _pin_file(companions.contract, contract_sha, rehash=True),
        )
        handle = KnowledgeSnapshot(
            companions.directory,
            read_batch_rows=limits.read_batch_rows,
            cache_kib=limits.cache_kib,
        )
        handle._bind(connection, identity, pins)  # pyright: ignore[reportPrivateUsage]
        accepted = True
        return handle
    finally:
        if not accepted:
            connection.close()


def open_knowledge_snapshot_from_configuration(
    configuration: EffectiveExecutionConfiguration,
) -> KnowledgeSnapshot:
    """Open the snapshot directory and SQLite limits from an L02 configuration."""

    return open_knowledge_snapshot(
        configuration.knowledge.snapshot_directory,
        read_batch_rows=configuration.resources.sqlite_read_batch_rows,
        cache_kib=configuration.resources.sqlite_cache_kib,
    )
