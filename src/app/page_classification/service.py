"""Local page-classification service with current-state persistence.

Prepares one reviewed HTML document, classifies pages through the injected
runner/wrapper, and persists one truthful current state. No UI, API, or
Stage 2 routing.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.llm import AsyncOpenAIWrapper
from app.page_classification.contracts import (
    ClassificationProgress,
    CompletedPageClassificationResult,
    CurrentClassificationState,
    PreparedDocument,
)
from app.page_classification.diagnostics import (
    ClassificationDiagnosticSession,
    DiagnosticPersistenceError,
    begin_classification_diagnostics,
    finalize_matching_interrupted_bundle,
    new_classification_run_id,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.runner import PageClassificationRunner
from app.page_classification.store import PageClassificationStore

_FIXED_INTERRUPT_REASON = "page classification was interrupted by service restart"
_FIXED_WORKER_FAILURE_REASON = "page classification failed unexpectedly"
_FIXED_DIAGNOSTIC_FAILURE_REASON = "page classification diagnostic persistence failed"
_FIXED_CURRENT_STATE_FAILURE_REASON = "page classification current-state persistence failed"
_MAX_TERMINAL_REASON = 200

_BUSY_DATA_DIRS: set[Path] = set()
_BUSY_LOCK = threading.Lock()


class PageClassificationBusyError(RuntimeError):
    """A classifier worker is already active for this data directory."""


class PageClassificationService:
    """Concrete local owner of current page classification under one data directory."""

    def __init__(
        self,
        data_dir: Path,
        wrapper: AsyncOpenAIWrapper,
        *,
        runner: PageClassificationRunner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._data_dir = data_dir.expanduser().resolve()
        self._wrapper = wrapper
        self._runner = runner or PageClassificationRunner(wrapper)
        self._clock = clock or _utc_now
        self._store = PageClassificationStore(self._data_dir)
        self._lock = threading.RLock()
        self._worker_thread: threading.Thread | None = None
        self._active_diagnostics: ClassificationDiagnosticSession | None = None
        self._interrupt_abandoned_classifications()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def store(self) -> PageClassificationStore:
        return self._store

    def get_current(
        self,
        reviewed_html: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState | None:
        """Return the persisted current classification for the reviewed HTML binding."""

        return self._store.load(reviewed_html)

    def start_classification(
        self,
        reviewed_html_path: Path,
        *,
        expected: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState:
        """Prepare the document once, replace current state as running, and start a worker.

        Returns immediately after the background worker is started. A second start
        for the same data directory is rejected while a worker is active.
        """

        prepared = prepare_reviewed_document(Path(reviewed_html_path), expected=expected)
        now = self._clock()
        run_id = new_classification_run_id()
        try:
            diagnostics = begin_classification_diagnostics(
                self._data_dir,
                classification_run_id=run_id,
                reviewed_html=prepared.reviewed_html,
                total_pages=len(prepared.pages),
                wrapper=self._wrapper,
                clock=self._clock,
            )
        except DiagnosticPersistenceError as exc:
            failed = CurrentClassificationState(
                reviewed_html=prepared.reviewed_html,
                status="failed",
                created_at=now,
                updated_at=now,
                finished_at=now,
                progress=ClassificationProgress(
                    total_pages=len(prepared.pages),
                    completed_pages=0,
                    current_page_number=None,
                ),
                page_results=(),
                terminal_reason=_bounded_reason(exc.safe_reason),
                classification_run_id=run_id,
            )
            self._store.save(failed)
            return failed

        initial = CurrentClassificationState(
            reviewed_html=prepared.reviewed_html,
            status="running",
            created_at=now,
            updated_at=now,
            finished_at=None,
            progress=ClassificationProgress(
                total_pages=len(prepared.pages),
                completed_pages=0,
                current_page_number=(
                    prepared.pages[0].binding.page_number if prepared.pages else None
                ),
            ),
            page_results=(),
            terminal_reason=None,
            classification_run_id=run_id,
        )

        with _BUSY_LOCK:
            if self._data_dir in _BUSY_DATA_DIRS:
                diagnostics.finalize(
                    "failed",
                    terminal_reason="a page classification worker is already active",
                )
                raise PageClassificationBusyError(
                    "a page classification worker is already active for this data directory"
                )
            worker = self._worker_thread
            if worker is not None and worker.is_alive():
                diagnostics.finalize(
                    "failed",
                    terminal_reason="a page classification worker is already active",
                )
                raise PageClassificationBusyError(
                    "a page classification worker is already active for this data directory"
                )
            _BUSY_DATA_DIRS.add(self._data_dir)

        try:
            self._store.save(initial)
            with self._lock:
                self._active_diagnostics = diagnostics
            thread = threading.Thread(
                target=self._run_worker,
                name="page-classification-worker",
                args=(prepared, diagnostics),
                daemon=True,
            )
            with self._lock:
                self._worker_thread = thread
            thread.start()
        except Exception:
            with _BUSY_LOCK:
                _BUSY_DATA_DIRS.discard(self._data_dir)
            with self._lock:
                self._worker_thread = None
                self._active_diagnostics = None
            try:
                diagnostics.finalize(
                    "failed",
                    terminal_reason=_FIXED_DIAGNOSTIC_FAILURE_REASON,
                )
            except Exception:  # noqa: BLE001 - best-effort diagnostic finalize
                pass
            raise
        return initial

    def _run_worker(
        self,
        prepared: PreparedDocument,
        diagnostics: ClassificationDiagnosticSession,
    ) -> None:
        reviewed_html = prepared.reviewed_html
        try:
            asyncio.run(self._classify_async(prepared, diagnostics))
        except DiagnosticPersistenceError as exc:
            self._mark_failed(reviewed_html, exc.safe_reason, diagnostics=diagnostics)
        except Exception:
            self._mark_failed(
                reviewed_html,
                _FIXED_WORKER_FAILURE_REASON,
                diagnostics=diagnostics,
            )
        finally:
            with _BUSY_LOCK:
                _BUSY_DATA_DIRS.discard(self._data_dir)
            with self._lock:
                self._worker_thread = None
                if self._active_diagnostics is diagnostics:
                    self._active_diagnostics = None

    async def _classify_async(
        self,
        prepared: PreparedDocument,
        diagnostics: ClassificationDiagnosticSession,
    ) -> None:
        reviewed_html = prepared.reviewed_html
        state = self._require_current(reviewed_html)
        completed: list[CompletedPageClassificationResult] = list(state.page_results)

        for index, page in enumerate(prepared.pages):
            state = self._require_current(reviewed_html)
            now = self._clock()
            state = state.model_copy(
                update={
                    "updated_at": now,
                    "progress": ClassificationProgress(
                        total_pages=len(prepared.pages),
                        completed_pages=len(completed),
                        current_page_number=page.binding.page_number,
                    ),
                }
            )
            self._store.save(state)
            diagnostics.mark_page_progress(
                current_page_number=page.binding.page_number,
                completed_pages=len(completed),
            )

            result = await self._runner.classify_page(page, diagnostics=diagnostics)
            completed.append(result)
            now = self._clock()
            if index + 1 == len(prepared.pages):
                self._complete_classification(
                    reviewed_html=reviewed_html,
                    created_at=state.created_at,
                    completed=completed,
                    classification_run_id=state.classification_run_id,
                    diagnostics=diagnostics,
                    now=now,
                )
                return

            next_page = prepared.pages[index + 1].binding.page_number
            state = state.model_copy(
                update={
                    "updated_at": now,
                    "progress": ClassificationProgress(
                        total_pages=len(prepared.pages),
                        completed_pages=len(completed),
                        current_page_number=next_page,
                    ),
                    "page_results": tuple(completed),
                }
            )
            self._store.save(state)

        now = self._clock()
        self._complete_classification(
            reviewed_html=reviewed_html,
            created_at=state.created_at,
            completed=completed,
            classification_run_id=state.classification_run_id,
            diagnostics=diagnostics,
            now=now,
        )

    def _complete_classification(
        self,
        *,
        reviewed_html: ReviewedHtmlV1Input,
        created_at: datetime,
        completed: list[CompletedPageClassificationResult],
        classification_run_id: str | None,
        diagnostics: ClassificationDiagnosticSession,
        now: datetime,
    ) -> None:
        """Finalize the diagnostic completed manifest before claiming current completed."""

        final = CurrentClassificationState(
            reviewed_html=reviewed_html,
            status="completed",
            created_at=created_at,
            updated_at=now,
            finished_at=now,
            progress=ClassificationProgress(
                total_pages=len(completed),
                completed_pages=len(completed),
                current_page_number=None,
            ),
            page_results=tuple(completed),
            terminal_reason=None,
            classification_run_id=classification_run_id,
        )
        # Fail closed: never persist completed current-state until the required
        # completed diagnostic manifest write succeeds.
        diagnostics.finalize("completed", completed_pages=len(completed))
        try:
            self._store.save(final)
        except Exception:
            try:
                diagnostics.finalize(
                    "failed",
                    terminal_reason=_FIXED_CURRENT_STATE_FAILURE_REASON,
                    completed_pages=len(completed),
                )
            except Exception:  # noqa: BLE001 - best-effort compensation
                pass
            self._mark_failed(
                reviewed_html,
                _FIXED_CURRENT_STATE_FAILURE_REASON,
                diagnostics=None,
            )

    def _mark_failed(
        self,
        reviewed_html: ReviewedHtmlV1Input,
        reason: str,
        *,
        diagnostics: ClassificationDiagnosticSession | None = None,
    ) -> None:
        try:
            state = self._store.load(reviewed_html)
        except Exception:  # noqa: BLE001 - best-effort terminal persistence
            return
        if state is None:
            return
        if state.status in {"completed", "failed", "interrupted"}:
            if diagnostics is not None:
                try:
                    diagnostics.finalize(
                        "failed",
                        terminal_reason=_bounded_reason(reason),
                        completed_pages=state.progress.completed_pages,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return
        now = self._clock()
        failed = state.model_copy(
            update={
                "status": "failed",
                "updated_at": now,
                "finished_at": now,
                "terminal_reason": _bounded_reason(reason),
                "progress": ClassificationProgress(
                    total_pages=state.progress.total_pages,
                    completed_pages=state.progress.completed_pages,
                    current_page_number=None,
                ),
            }
        )
        try:
            self._store.save(failed)
        except Exception:  # noqa: BLE001 - best-effort terminal persistence
            return
        if diagnostics is not None:
            try:
                diagnostics.finalize(
                    "failed",
                    terminal_reason=_bounded_reason(reason),
                    completed_pages=failed.progress.completed_pages,
                )
            except Exception:  # noqa: BLE001
                return

    def _require_current(
        self,
        reviewed_html: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState:
        state = self._store.load(reviewed_html)
        if state is None:
            raise RuntimeError("current classification state is missing during worker execution")
        return state

    def _interrupt_abandoned_classifications(self) -> None:
        # Same-process active worker owns this data directory: do not rewrite its
        # truthful running state during construction of another service instance.
        with _BUSY_LOCK:
            if self._data_dir in _BUSY_DATA_DIRS:
                return
        now = self._clock()
        for path in self._store.iter_current_paths():
            try:
                state = self._store.load_path(path)
            except Exception:  # noqa: BLE001 - skip unreadable abandoned files
                continue
            if state.status != "running":
                continue
            interrupted = state.model_copy(
                update={
                    "status": "interrupted",
                    "updated_at": now,
                    "finished_at": now,
                    "terminal_reason": _FIXED_INTERRUPT_REASON,
                    "progress": ClassificationProgress(
                        total_pages=state.progress.total_pages,
                        completed_pages=state.progress.completed_pages,
                        current_page_number=None,
                    ),
                }
            )
            self._store.save(interrupted)
            finalize_matching_interrupted_bundle(
                self._data_dir,
                interrupted,
                clock=self._clock,
            )


def _bounded_reason(message: str) -> str:
    if 1 <= len(message) <= _MAX_TERMINAL_REASON:
        return message
    if not message:
        return _FIXED_WORKER_FAILURE_REASON
    return message[: _MAX_TERMINAL_REASON - 3] + "..."


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)
