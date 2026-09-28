"""Compact operational monitoring helpers for the L12 lexical runner.

Measurements are in-memory summaries for a later L13 publisher. This module does
not open HTML or SQLite, adapt limits to physical RAM, or start a telemetry
server. Unavailable counters are omitted or marked unavailable — never guessed
as zero.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Final, Literal

from app.lexical_extraction.contracts import (
    AvailableMeasurement,
    Component,
    ElapsedTiming,
    ExtractionOutcome,
)

UNAVAILABLE: Final = "unavailable"
MemoryMethod = Literal[
    "windows_psapi_peak_working_set",
    "posix_resource_ru_maxrss",
    "unavailable",
]


def _empty_method_counts() -> dict[str, int]:
    return {}


def _empty_component_stats() -> dict[Component, ComponentMatchStats]:
    return {}


def _empty_components() -> list[Component]:
    return []


def _empty_stage_timings() -> dict[str, int]:
    return {}


def _empty_resource_limits() -> dict[str, int]:
    return {}


@dataclass
class ComponentMatchStats:
    """Observed match counts for one requested component."""

    match_count: int = 0
    by_method: dict[str, int] = field(default_factory=_empty_method_counts)

    def add_method(self, method: str, *, count: int = 1) -> None:
        self.by_method[method] = self.by_method.get(method, 0) + count
        self.match_count += count


@dataclass
class RunMonitoringAccumulator:
    """Mutable collector filled during one runner invocation."""

    pages_observed: int | None = None
    blocks_observed: int | None = None
    eligible_terms: int | None = None
    eligible_rows: int | None = None
    candidates: int | None = None
    component_matches: dict[Component, ComponentMatchStats] = field(
        default_factory=_empty_component_stats
    )
    completed_components: list[Component] = field(default_factory=_empty_components)
    failed_components: list[Component] = field(default_factory=_empty_components)
    zero_result_components: list[Component] = field(default_factory=_empty_components)
    stage_timings_ms: dict[str, int] = field(default_factory=_empty_stage_timings)
    resource_limits: dict[str, int] = field(default_factory=_empty_resource_limits)
    peak_process_memory_bytes: int | None = None
    peak_memory_method: MemoryMethod = UNAVAILABLE

    def record_stage(self, name: str, elapsed_ms: int) -> None:
        self.stage_timings_ms[name] = elapsed_ms

    def ensure_component(self, component: Component) -> ComponentMatchStats:
        stats = self.component_matches.get(component)
        if stats is None:
            stats = ComponentMatchStats()
            self.component_matches[component] = stats
        return stats

    def mark_component_outcome(
        self,
        component: Component,
        outcome: ExtractionOutcome,
        *,
        match_count: int | None,
    ) -> None:
        if outcome is ExtractionOutcome.COMPLETED:
            if component not in self.completed_components:
                self.completed_components.append(component)
            if match_count == 0 and component not in self.zero_result_components:
                self.zero_result_components.append(component)
        elif outcome is ExtractionOutcome.FAILED:
            if component not in self.failed_components:
                self.failed_components.append(component)

    def freeze(self) -> RunMonitoringSummary:
        measurements: list[AvailableMeasurement] = []
        if self.pages_observed is not None:
            measurements.append(
                AvailableMeasurement(name="pages_observed", value=str(self.pages_observed))
            )
        if self.blocks_observed is not None:
            measurements.append(
                AvailableMeasurement(name="blocks_observed", value=str(self.blocks_observed))
            )
        if self.eligible_terms is not None:
            measurements.append(
                AvailableMeasurement(name="eligible_terms", value=str(self.eligible_terms))
            )
        if self.eligible_rows is not None:
            measurements.append(
                AvailableMeasurement(name="eligible_rows", value=str(self.eligible_rows))
            )
        if self.candidates is not None:
            measurements.append(AvailableMeasurement(name="candidates", value=str(self.candidates)))
        if self.peak_process_memory_bytes is not None:
            measurements.append(
                AvailableMeasurement(
                    name="peak_process_memory_bytes",
                    value=str(self.peak_process_memory_bytes),
                )
            )
        match_by_component = {
            component.value: stats.match_count
            for component, stats in self.component_matches.items()
        }
        match_by_method: dict[str, int] = {}
        for stats in self.component_matches.values():
            for method, count in stats.by_method.items():
                match_by_method[method] = match_by_method.get(method, 0) + count
        return RunMonitoringSummary(
            pages_observed=self.pages_observed,
            blocks_observed=self.blocks_observed,
            completed_components=tuple(self.completed_components),
            failed_components=tuple(self.failed_components),
            zero_result_components=tuple(self.zero_result_components),
            matches_by_component=match_by_component,
            matches_by_method=match_by_method,
            eligible_terms=self.eligible_terms,
            eligible_rows=self.eligible_rows,
            candidates=self.candidates,
            timings=tuple(
                ElapsedTiming(name=name, elapsed_ms=value)
                for name, value in self.stage_timings_ms.items()
            ),
            resource_limits=dict(self.resource_limits),
            peak_process_memory_bytes=self.peak_process_memory_bytes,
            peak_memory_method=self.peak_memory_method,
            measurements=tuple(measurements),
        )


@dataclass(frozen=True)
class RunMonitoringSummary:
    """Compact monitoring snapshot for one L12 run.

    Omitted optional integers mean unavailable, not zero. ``matches_by_*`` maps
    contain only observed keys.
    """

    pages_observed: int | None
    blocks_observed: int | None
    completed_components: tuple[Component, ...]
    failed_components: tuple[Component, ...]
    zero_result_components: tuple[Component, ...]
    matches_by_component: dict[str, int]
    matches_by_method: dict[str, int]
    eligible_terms: int | None
    eligible_rows: int | None
    candidates: int | None
    timings: tuple[ElapsedTiming, ...]
    resource_limits: dict[str, int]
    peak_process_memory_bytes: int | None
    peak_memory_method: MemoryMethod
    measurements: tuple[AvailableMeasurement, ...]


def measure_peak_process_memory() -> tuple[int | None, MemoryMethod]:
    """Return peak process memory when a supported nonprivileged method works."""

    if sys.platform == "win32":
        value = _windows_peak_working_set_bytes()
        if value is None:
            return None, UNAVAILABLE
        return value, "windows_psapi_peak_working_set"
    value = _posix_peak_rss_bytes()
    if value is None:
        return None, UNAVAILABLE
    return value, "posix_resource_ru_maxrss"


def _windows_peak_working_set_bytes() -> int | None:
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
            return None
        return int(counters.PeakWorkingSetSize)
    except Exception:
        return None


def _posix_peak_rss_bytes() -> int | None:
    try:
        import resource as resource_mod

        getrusage = getattr(resource_mod, "getrusage", None)
        rusage_self = getattr(resource_mod, "RUSAGE_SELF", None)
        if getrusage is None or rusage_self is None:
            return None
        usage = getrusage(rusage_self)
        rss = int(getattr(usage, "ru_maxrss", 0))
        if rss <= 0:
            return None
        # Linux reports KiB; macOS reports bytes.
        if sys.platform == "darwin":
            return rss
        return rss * 1024
    except Exception:
        return None
