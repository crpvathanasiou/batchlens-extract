"""L09 read-only early full-Materials feasibility measurement helper.

Uses accepted L03→L04→L05→L07→L08 APIs unchanged. This is not a product runner,
CLI product surface, second matcher, or result publisher. It measures one
Materials component pass over explicit local reviewed-HTML and snapshot paths
under two caller-chosen ``max_terms_per_shard`` settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from app.lexical_extraction.configuration import ResourceLimits
from app.lexical_extraction.contracts import BlockRecord, Component
from app.lexical_extraction.dictionary_aggregation import (
    DictionaryAggregationError,
    iter_aggregated_block_records,
)
from app.lexical_extraction.dictionary_matcher import (
    DictionaryMatchError,
    ReviewedHtmlBlockReplay,
    iter_raw_discoveries,
)
from app.lexical_extraction.field_mapping import iter_eligible_terms
from app.lexical_extraction.html_reader import ReviewedHtmlReadError, open_reviewed_html
from app.lexical_extraction.knowledge_snapshot import (
    SnapshotReadError,
    open_knowledge_snapshot,
)

UNAVAILABLE: Literal["unavailable"] = "unavailable"

# Declared against the local MSI MS-7D25 host (~128 GiB physical RAM). Leaves
# substantial headroom for OS and other processes while allowing large Aho–Corasick
# shard peaks. Exceeding this budget is an explicit L09 feasibility failure.
DEFAULT_PEAK_PROCESS_MEMORY_BUDGET_BYTES = 32 * 1024 * 1024 * 1024

DEFAULT_SQLITE_READ_BATCH_ROWS = 5_000
DEFAULT_SQLITE_CACHE_KIB = 65_536
DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD = 50_000_000
DEFAULT_RESULT_BUFFER_RECORDS = 50_000

# Two finite shard settings for the real measurement; other limits stay fixed.
SHARD_SETTING_A = 500_000
SHARD_SETTING_B = 2_000_000

_HASH_CHUNK = 1024 * 1024
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class MeasurementError(Exception):
    """Fail-closed measurement boundary. Not a product extraction outcome."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class SnapshotSidecarState:
    wal_present: bool
    shm_present: bool
    journal_present: bool


@dataclass(frozen=True)
class HtmlIdentity:
    path: str
    size_bytes: int
    sha256: str
    page_count: int
    block_count: int


@dataclass
class MeasurementCounts:
    eligible_terms: int = 0
    raw_discoveries: int = 0
    blocks_emitted: int = 0
    dictionary_occurrences: int = 0
    candidates: int = 0
    unique_occurrences: int | Literal["unavailable"] = UNAVAILABLE


@dataclass
class MemorySample:
    method: str
    baseline_working_set_bytes: int | Literal["unavailable"]
    peak_working_set_bytes: int | Literal["unavailable"]
    budget_bytes: int
    budget_exceeded: bool | Literal["unavailable"]


@dataclass
class TimingSample:
    snapshot_preflight_seconds: float
    matching_plus_aggregation_seconds: float
    total_seconds: float
    indexing_seconds: Literal["unavailable"] = UNAVAILABLE
    search_seconds: Literal["unavailable"] = UNAVAILABLE
    aggregation_seconds: Literal["unavailable"] = UNAVAILABLE


@dataclass
class MeasurementReport:
    status: str
    run_label: str
    component: str
    fuzzy_enabled: bool
    reviewed_html: HtmlIdentity
    snapshot_id: str
    snapshot_directory: str
    database: FileIdentity
    manifest: FileIdentity
    validation_report: FileIdentity
    contract: FileIdentity
    resources: dict[str, int]
    peak_memory_budget_bytes: int
    os_cache_note: str
    hardware: dict[str, str | int | Literal["unavailable"]]
    counts: MeasurementCounts
    semantic_digest_sha256: str
    timings: TimingSample
    memory: MemorySample
    temporary_spool_peak_bytes: Literal["unavailable"]
    hashes_before: dict[str, str]
    hashes_after: dict[str, str]
    hashes_unchanged: bool
    sidecars_before: SnapshotSidecarState
    sidecars_after: SnapshotSidecarState
    knowledge_write_detected: bool
    publication_claimed: bool
    error_code: str | None = None
    error_message: str | None = None
    notes: list[str] = field(default_factory=lambda: [])

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


def hash_file(path: Path) -> FileIdentity:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return FileIdentity(path=str(path.resolve()), size_bytes=size, sha256=digest.hexdigest())


def snapshot_sidecar_state(database_path: Path) -> SnapshotSidecarState:
    return SnapshotSidecarState(
        wal_present=(database_path.parent / f"{database_path.name}-wal").exists()
        or Path(str(database_path) + "-wal").exists(),
        shm_present=(database_path.parent / f"{database_path.name}-shm").exists()
        or Path(str(database_path) + "-shm").exists(),
        journal_present=(database_path.parent / f"{database_path.name}-journal").exists()
        or Path(str(database_path) + "-journal").exists(),
    )


def process_working_set_bytes() -> int | Literal["unavailable"]:
    if sys.platform != "win32":
        return UNAVAILABLE
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
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
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        ok = bool(
            get_process_memory_info(
                get_current_process(),
                ctypes.byref(counters),
                counters.cb,
            )
        )
        if not ok:
            return UNAVAILABLE
        return int(counters.WorkingSetSize)
    except Exception:  # noqa: BLE001 — measurement must not invent a peak
        return UNAVAILABLE


def process_peak_working_set_bytes() -> int | Literal["unavailable"]:
    if sys.platform != "win32":
        return UNAVAILABLE
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
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
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        ok = bool(
            get_process_memory_info(
                get_current_process(),
                ctypes.byref(counters),
                counters.cb,
            )
        )
        if not ok:
            return UNAVAILABLE
        return int(counters.PeakWorkingSetSize)
    except Exception:  # noqa: BLE001 — measurement must not invent a peak
        return UNAVAILABLE


def memory_method_label() -> str:
    if sys.platform == "win32":
        return "windows_psapi_peak_working_set"
    return UNAVAILABLE


def local_hardware_facts() -> dict[str, str | int | Literal["unavailable"]]:
    facts: dict[str, str | int | Literal["unavailable"]] = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "processor": platform.processor() or UNAVAILABLE,
        "total_physical_memory_bytes": UNAVAILABLE,
        "manufacturer": UNAVAILABLE,
        "model": UNAVAILABLE,
    }
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                facts["total_physical_memory_bytes"] = int(status.ullTotalPhys)
                facts["available_physical_memory_bytes"] = int(status.ullAvailPhys)
        except Exception:  # noqa: BLE001
            pass
    return facts


def finalize_reviewed_html_identity(html_path: Path) -> HtmlIdentity:
    """Complete one L03 pass and return the finalized full-file digest."""

    if not html_path.is_file():
        raise MeasurementError("MISSING_REVIEWED_HTML", f"reviewed HTML not found: {html_path}")
    try:
        reader = open_reviewed_html(html_path)
    except ReviewedHtmlReadError as exc:
        raise MeasurementError("INVALID_REVIEWED_HTML", f"{exc.code}: {exc.message}") from exc
    except OSError as exc:
        raise MeasurementError("MISSING_REVIEWED_HTML", str(exc)) from exc

    pages = 0
    blocks = 0
    try:
        for page in reader.iter_pages():
            pages += 1
            blocks += len(page.blocks)
    except ReviewedHtmlReadError as exc:
        raise MeasurementError("INVALID_REVIEWED_HTML", f"{exc.code}: {exc.message}") from exc

    if not reader.completed:
        raise MeasurementError(
            "INVALID_REVIEWED_HTML",
            "reviewed HTML pass ended without a finalized validated input digest",
        )
    try:
        digest = reader.validated_input.html_sha256
    except ReviewedHtmlReadError as exc:
        raise MeasurementError("INVALID_REVIEWED_HTML", f"{exc.code}: {exc.message}") from exc

    return HtmlIdentity(
        path=str(html_path.resolve()),
        size_bytes=reader.bytes_consumed,
        sha256=digest,
        page_count=pages,
        block_count=blocks,
    )


def canonical_block_record_bytes(record: BlockRecord) -> bytes:
    """Stable UTF-8 JSON for one BlockRecord semantic payload."""

    material = record.model_dump(mode="json")
    return json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class _Sha256Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


def update_semantic_digest(digest: _Sha256Digest, record: BlockRecord) -> None:
    digest.update(canonical_block_record_bytes(record))
    digest.update(b"\n")


_KNOWLEDGE_HASH_KEYS: tuple[str, ...] = (
    "database",
    "manifest",
    "validation_report",
    "contract",
)


@dataclass(frozen=True)
class IntegrityOutcome:
    """Post-run integrity classification for the measurement report."""

    hashes_unchanged: bool
    knowledge_write_detected: bool
    failure_status: str | None
    error_code: str | None
    error_message: str | None


def evaluate_post_run_integrity(
    hashes_before: Mapping[str, str],
    hashes_after: Mapping[str, str],
    sidecars_after: SnapshotSidecarState,
) -> IntegrityOutcome:
    """Classify HTML vs knowledge integrity after a measurement run.

    An HTML-only hash change fails integrity without claiming a knowledge write.
    Snapshot companion/database hash changes or a WAL/SHM/journal sidecar fail
    with ``knowledge_write_detected=True``. Neither case may claim
    ``status=completed``.
    """

    html_changed = hashes_before.get("reviewed_html") != hashes_after.get("reviewed_html")
    snapshot_changed = any(
        hashes_before.get(key) != hashes_after.get(key) for key in _KNOWLEDGE_HASH_KEYS
    )
    sidecar_present = (
        sidecars_after.wal_present or sidecars_after.shm_present or sidecars_after.journal_present
    )
    knowledge_write = snapshot_changed or sidecar_present
    hashes_unchanged = (not html_changed) and (not snapshot_changed)

    if knowledge_write:
        details: list[str] = []
        if snapshot_changed:
            details.append("knowledge snapshot companion or database hash changed")
        if sidecar_present:
            details.append("SQLite WAL/SHM/journal sidecar present after measurement")
        return IntegrityOutcome(
            hashes_unchanged=hashes_unchanged,
            knowledge_write_detected=True,
            failure_status="integrity_failed",
            error_code="KNOWLEDGE_WRITE_DETECTED",
            error_message="; ".join(details),
        )
    if html_changed:
        return IntegrityOutcome(
            hashes_unchanged=False,
            knowledge_write_detected=False,
            failure_status="integrity_failed",
            error_code="HTML_INPUT_CHANGED",
            error_message="reviewed HTML SHA-256 changed during measurement",
        )
    return IntegrityOutcome(
        hashes_unchanged=True,
        knowledge_write_detected=False,
        failure_status=None,
        error_code=None,
        error_message=None,
    )


def report_claims_completed_integrity(report: Mapping[str, Any]) -> bool:
    """True only when a report may be treated as a successful integrity claim."""

    return (
        report.get("status") == "completed"
        and report.get("hashes_unchanged") is True
        and report.get("knowledge_write_detected") is not True
        and report.get("error_code") in (None, "")
    )


def compare_measurement_digests(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Compare two completed measurement reports for semantic equality.

    Integrity-failed, memory-budget, or otherwise non-completed reports are never
    treated as a successful comparison, even when digests happen to match.
    """

    issues: list[str] = []
    if not report_claims_completed_integrity(first) or not report_claims_completed_integrity(
        second
    ):
        issues.append(
            "both reports must claim completed integrity "
            "(status=completed, hashes unchanged, no knowledge write, no error_code)"
        )
        return (False, issues)
    if first.get("semantic_digest_sha256") != second.get("semantic_digest_sha256"):
        issues.append("semantic digests differ")
    first_counts_obj = first.get("counts")
    second_counts_obj = second.get("counts")
    if not isinstance(first_counts_obj, Mapping) or not isinstance(second_counts_obj, Mapping):
        issues.append("counts missing")
    else:
        first_counts = cast(Mapping[str, Any], first_counts_obj)
        second_counts = cast(Mapping[str, Any], second_counts_obj)
        for key in (
            "eligible_terms",
            "raw_discoveries",
            "blocks_emitted",
            "dictionary_occurrences",
            "candidates",
        ):
            if first_counts.get(key) != second_counts.get(key):
                issues.append(f"count mismatch for {key}")
    first_html = first.get("reviewed_html")
    second_html = second.get("reviewed_html")
    first_html_sha: Any | None = None
    second_html_sha: Any | None = None
    if isinstance(first_html, Mapping):
        first_html_sha = cast(Mapping[str, Any], first_html).get("sha256")
    if isinstance(second_html, Mapping):
        second_html_sha = cast(Mapping[str, Any], second_html).get("sha256")
    if first_html_sha != second_html_sha:
        issues.append("HTML identity differs")
    if first.get("snapshot_id") != second.get("snapshot_id"):
        issues.append("snapshot_id differs")
    return (not issues, issues)


@dataclass
class _Counter:
    value: int = 0


def _counting(
    items: Iterable[Any],
    counter: _Counter,
    *,
    label: str | None = None,
    every: int = 250_000,
) -> Iterator[Any]:
    for item in items:
        counter.value += 1
        if label is not None and counter.value % every == 0:
            print(f"{label}: {counter.value}", flush=True)
        yield item
    if label is not None:
        print(f"{label}: total {counter.value}", flush=True)


def _resource_limits(*, max_terms_per_shard: int) -> ResourceLimits:
    return ResourceLimits(
        sqlite_read_batch_rows=DEFAULT_SQLITE_READ_BATCH_ROWS,
        sqlite_cache_kib=DEFAULT_SQLITE_CACHE_KIB,
        max_terms_per_shard=max_terms_per_shard,
        max_term_codepoints_per_shard=DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD,
        result_buffer_records=DEFAULT_RESULT_BUFFER_RECORDS,
    )


def run_materials_feasibility_measurement(
    *,
    reviewed_html_path: Path | str,
    snapshot_directory: Path | str,
    max_terms_per_shard: int,
    peak_memory_budget_bytes: int = DEFAULT_PEAK_PROCESS_MEMORY_BUDGET_BYTES,
    run_label: str = "run",
    os_cache_note: str = "unlabeled",
) -> MeasurementReport:
    """Execute one complete Materials L03→L08 measurement and return metrics."""

    html_path = Path(reviewed_html_path)
    snap_dir = Path(snapshot_directory)
    database_path = snap_dir / "knowledge.sqlite"
    started = time.perf_counter()
    notes: list[str] = [
        "Materials component only; fuzzy disabled; no publication claim.",
        "Temporary L08 spool peak size is unavailable without instrumenting accepted modules.",
        "Indexing/search/aggregation phase split is unavailable without changing L07/L08.",
    ]

    if not html_path.is_file():
        raise MeasurementError("MISSING_REVIEWED_HTML", f"reviewed HTML not found: {html_path}")
    if not snap_dir.is_dir():
        raise MeasurementError("SNAPSHOT_ERROR", f"snapshot directory not found: {snap_dir}")
    if not database_path.is_file():
        raise MeasurementError("SNAPSHOT_ERROR", f"knowledge.sqlite not found: {database_path}")
    if max_terms_per_shard < 1:
        raise MeasurementError("INVALID_LIMIT", "max_terms_per_shard must be positive")
    if peak_memory_budget_bytes < 1:
        raise MeasurementError("INVALID_LIMIT", "peak_memory_budget_bytes must be positive")

    html_before = hash_file(html_path)
    database_before = hash_file(database_path)
    manifest_before = hash_file(snap_dir / "manifest.json")
    report_before = hash_file(snap_dir / "validation_report.json")
    contract_before = hash_file(snap_dir / "FLAT_SQLITE_CONTRACT.md")
    sidecars_before = snapshot_sidecar_state(database_path)
    hashes_before = {
        "reviewed_html": html_before.sha256,
        "database": database_before.sha256,
        "manifest": manifest_before.sha256,
        "validation_report": report_before.sha256,
        "contract": contract_before.sha256,
    }

    baseline_ws = process_working_set_bytes()
    hardware = local_hardware_facts()
    limits = _resource_limits(max_terms_per_shard=max_terms_per_shard)

    preflight_started = time.perf_counter()
    try:
        snapshot = open_knowledge_snapshot(
            snap_dir,
            read_batch_rows=limits.sqlite_read_batch_rows,
            cache_kib=limits.sqlite_cache_kib,
        )
    except SnapshotReadError as exc:
        raise MeasurementError("SNAPSHOT_ERROR", f"{exc.code}: {exc.message}") from exc
    preflight_seconds = time.perf_counter() - preflight_started

    try:
        html_identity = finalize_reviewed_html_identity(html_path)
        if html_identity.sha256 != html_before.sha256:
            raise MeasurementError(
                "INPUT_CHANGED",
                "reviewed HTML SHA-256 changed between pre-hash and L03 finalization",
            )

        blocks = ReviewedHtmlBlockReplay(html_path)
        term_counter = _Counter()
        terms = _counting(
            iter_eligible_terms(
                snapshot,
                (Component.MATERIALS,),
                batch_size=limits.sqlite_read_batch_rows,
            ),
            term_counter,
            label=f"{run_label}:eligible_terms",
        )

        match_started = time.perf_counter()
        discoveries = iter_raw_discoveries(terms, blocks, limits)
        stream = iter_aggregated_block_records(
            discoveries,
            blocks,
            snapshot,
            limits,
            expected_source_identity=html_identity.sha256,
        )

        digest = hashlib.sha256()
        discovery_proxy_count = 0
        try:
            for record in stream:
                update_semantic_digest(digest, record)
            coverage = stream.coverage
        except DictionaryAggregationError as exc:
            raise MeasurementError("AGGREGATION_FAILED", f"{exc.code}: {exc.message}") from exc
        except DictionaryMatchError as exc:
            raise MeasurementError("MATCH_FAILED", f"{exc.code}: {exc.message}") from exc
        finally:
            stream.close()

        match_seconds = time.perf_counter() - match_started
        if coverage.source_identity != html_identity.sha256:
            raise MeasurementError(
                "REPLAY_IDENTITY_CHANGED",
                "L08 coverage identity does not match the finalized L03 HTML digest",
            )

        peak_ws = process_peak_working_set_bytes()
        budget_exceeded: bool | Literal["unavailable"]
        if isinstance(peak_ws, int):
            budget_exceeded = peak_ws > peak_memory_budget_bytes
        else:
            budget_exceeded = UNAVAILABLE

        html_after = hash_file(html_path)
        database_after = hash_file(database_path)
        manifest_after = hash_file(snap_dir / "manifest.json")
        report_after = hash_file(snap_dir / "validation_report.json")
        contract_after = hash_file(snap_dir / "FLAT_SQLITE_CONTRACT.md")
        sidecars_after = snapshot_sidecar_state(database_path)
        hashes_after = {
            "reviewed_html": html_after.sha256,
            "database": database_after.sha256,
            "manifest": manifest_after.sha256,
            "validation_report": report_after.sha256,
            "contract": contract_after.sha256,
        }
        integrity = evaluate_post_run_integrity(hashes_before, hashes_after, sidecars_after)

        status = "completed"
        error_code: str | None = None
        error_message: str | None = None
        if budget_exceeded is True:
            status = "memory_budget_exceeded"
            error_code = "MEMORY_BUDGET_EXCEEDED"
            error_message = f"peak working set {peak_ws} exceeded budget {peak_memory_budget_bytes}"
            notes.append("Measurement completed consumption but exceeded the declared peak budget.")
        # Integrity failure overrides any successful-path claim, including memory status.
        if integrity.failure_status is not None:
            status = integrity.failure_status
            error_code = integrity.error_code
            error_message = integrity.error_message
            notes.append(
                "Post-run integrity failed; report must not be treated as a completed "
                "feasibility claim."
            )

        counts = MeasurementCounts(
            eligible_terms=term_counter.value,
            raw_discoveries=coverage.discoveries_consumed,
            blocks_emitted=coverage.blocks_emitted,
            dictionary_occurrences=coverage.dictionary_occurrences,
            candidates=coverage.candidates,
            unique_occurrences=coverage.dictionary_occurrences,
        )
        # discovery_proxy_count kept for clarity that discoveries are counted via coverage.
        _ = discovery_proxy_count

        return MeasurementReport(
            status=status,
            run_label=run_label,
            component=Component.MATERIALS.value,
            fuzzy_enabled=False,
            reviewed_html=html_identity,
            snapshot_id=snapshot.identity.snapshot_id,
            snapshot_directory=str(snap_dir.resolve()),
            database=database_after if integrity.hashes_unchanged else database_before,
            manifest=manifest_after if integrity.hashes_unchanged else manifest_before,
            validation_report=report_after if integrity.hashes_unchanged else report_before,
            contract=contract_after if integrity.hashes_unchanged else contract_before,
            resources={
                "sqlite_read_batch_rows": limits.sqlite_read_batch_rows,
                "sqlite_cache_kib": limits.sqlite_cache_kib,
                "max_terms_per_shard": limits.max_terms_per_shard,
                "max_term_codepoints_per_shard": limits.max_term_codepoints_per_shard,
                "result_buffer_records": limits.result_buffer_records,
            },
            peak_memory_budget_bytes=peak_memory_budget_bytes,
            os_cache_note=os_cache_note,
            hardware=hardware,
            counts=counts,
            semantic_digest_sha256=digest.hexdigest(),
            timings=TimingSample(
                snapshot_preflight_seconds=preflight_seconds,
                matching_plus_aggregation_seconds=match_seconds,
                total_seconds=time.perf_counter() - started,
            ),
            memory=MemorySample(
                method=memory_method_label(),
                baseline_working_set_bytes=baseline_ws,
                peak_working_set_bytes=peak_ws,
                budget_bytes=peak_memory_budget_bytes,
                budget_exceeded=budget_exceeded,
            ),
            temporary_spool_peak_bytes=UNAVAILABLE,
            hashes_before=hashes_before,
            hashes_after=hashes_after,
            hashes_unchanged=integrity.hashes_unchanged,
            sidecars_before=sidecars_before,
            sidecars_after=sidecars_after,
            knowledge_write_detected=integrity.knowledge_write_detected,
            publication_claimed=False,
            error_code=error_code,
            error_message=error_message,
            notes=notes,
        )
    finally:
        snapshot.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "L09 read-only Materials feasibility measurement "
            "(not a product runner; no publication)."
        )
    )
    parser.add_argument("--reviewed-html", type=Path, required=True)
    parser.add_argument("--snapshot-directory", type=Path, required=True)
    parser.add_argument("--max-terms-per-shard", type=int, required=True)
    parser.add_argument(
        "--peak-budget-bytes",
        type=int,
        default=DEFAULT_PEAK_PROCESS_MEMORY_BUDGET_BYTES,
    )
    parser.add_argument("--run-label", type=str, default="run")
    parser.add_argument(
        "--os-cache-note",
        type=str,
        default="unlabeled",
        help="Label first/second-run OS cache effects for the evidence report.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the JSON measurement report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = run_materials_feasibility_measurement(
            reviewed_html_path=args.reviewed_html,
            snapshot_directory=args.snapshot_directory,
            max_terms_per_shard=args.max_terms_per_shard,
            peak_memory_budget_bytes=args.peak_budget_bytes,
            run_label=args.run_label,
            os_cache_note=args.os_cache_note,
        )
    except MeasurementError as exc:
        payload = {
            "status": "failed",
            "error_code": exc.code,
            "error_message": exc.message,
            "publication_claimed": False,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if args.output_json is not None:
            args.output_json.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return 2

    payload = report.to_jsonable()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.output_json is not None:
        args.output_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if report.status != "completed":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
