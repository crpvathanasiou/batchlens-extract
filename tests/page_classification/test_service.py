"""Local page-classification service lifecycle tests."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.llm.openai_wrapper import LLMCallResult
from app.page_classification.contracts import (
    ClassificationProgress,
    CurrentClassificationState,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.runner import PageClassificationRunner
from app.page_classification.service import (
    PageClassificationBusyError,
    PageClassificationService,
)
from app.page_classification.store import (
    CURRENT_CLASSIFICATION_FILENAME,
    PageClassificationStore,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"
FIXED_NOW = datetime(2026, 9, 30, 18, 0, 0, tzinfo=UTC)


def _wait_for(predicate: Any, *, timeout: float = 15.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


class EmptyWrapper:
    default_model = "gpt-4.1-mini"
    default_temperature = 0.0
    timeout_seconds = 20.0
    max_retries = 2

    async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        schema = kwargs["response_schema"]
        parsed = schema.model_validate({"labels": [], "status": "empty", "evidence": []})
        return LLMCallResult(
            model_name=self.default_model,
            raw_text="{}",
            parsed=parsed,
            attempts=1,
            latency_ms=1.0,
        )


class BlockingRunner:
    """Runner that waits until released; used to prove non-blocking start."""

    def __init__(self, inner: PageClassificationRunner) -> None:
        self._inner = inner
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def classify_page(
        self,
        page: Any,
        *,
        on_complete: Any = None,
        diagnostics: Any = None,
    ) -> Any:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=60.0)
        return await self._inner.classify_page(
            page,
            on_complete=on_complete,
            diagnostics=diagnostics,
        )

    async def classify_document(
        self,
        document: Any,
        *,
        on_page_complete: Any = None,
        diagnostics: Any = None,
    ) -> Any:
        return await self._inner.classify_document(
            document,
            on_page_complete=on_page_complete,
            diagnostics=diagnostics,
        )


class ExplodingRunner:
    def __init__(self, inner: PageClassificationRunner, *, fail_after: int) -> None:
        self._inner = inner
        self._fail_after = fail_after
        self._completed = 0

    async def classify_page(
        self,
        page: Any,
        *,
        on_complete: Any = None,
        diagnostics: Any = None,
    ) -> Any:
        if self._completed >= self._fail_after:
            raise RuntimeError("worker boom sk-secret")
        result = await self._inner.classify_page(
            page,
            on_complete=on_complete,
            diagnostics=diagnostics,
        )
        self._completed += 1
        return result


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "reviewed.html"
    path.write_bytes(FIXTURE.read_bytes())
    return path


def test_start_returns_without_blocking_and_rejects_second_start(tmp_path: Path) -> None:
    html_path = _write_fixture(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    wrapper = EmptyWrapper()
    inner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    blocking = BlockingRunner(inner)
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        runner=blocking,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = service.start_classification(html_path, expected=prepared.reviewed_html)
    assert started.status == "running"
    assert blocking.entered.wait(timeout=5.0)

    with pytest.raises(PageClassificationBusyError):
        service.start_classification(html_path, expected=prepared.reviewed_html)

    blocking.release.set()
    _wait_for(
        lambda: (service.get_current(prepared.reviewed_html) or started).status == "completed",
        timeout=30.0,
    )
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    assert final.status == "completed"
    assert final.progress.completed_pages == final.progress.total_pages == 3
    assert len(final.page_results) == 3
    assert [item.binding.page_number for item in final.page_results] == [1, 2, 3]


def test_worker_failure_preserves_completed_pages(tmp_path: Path) -> None:
    html_path = _write_fixture(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    wrapper = EmptyWrapper()
    inner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    exploding = ExplodingRunner(inner, fail_after=1)
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        runner=exploding,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)

    def _failed() -> bool:
        current = service.get_current(prepared.reviewed_html)
        return current is not None and current.status == "failed"

    _wait_for(_failed)
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.progress.completed_pages == 1
    assert len(state.page_results) == 1
    assert state.page_results[0].binding.page_number == 1
    assert state.terminal_reason == "page classification failed unexpectedly"
    assert "sk-secret" not in (state.terminal_reason or "")


def test_restart_marks_running_interrupted_without_calls(tmp_path: Path) -> None:
    html_path = _write_fixture(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    store = PageClassificationStore(tmp_path / "data")
    abandoned = CurrentClassificationState(
        reviewed_html=prepared.reviewed_html,
        status="running",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=3,
            completed_pages=0,
            current_page_number=1,
        ),
        page_results=(),
    )
    store.save(abandoned)

    calls = {"count": 0}

    class CountingWrapper:
        default_model = "gpt-4.1-mini"
        default_temperature = 0.0
        timeout_seconds = 20.0
        max_retries = 2

        async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
            calls["count"] += 1
            schema = kwargs["response_schema"]
            parsed = schema.model_validate({"labels": [], "status": "empty", "evidence": []})
            return LLMCallResult(model_name=self.default_model, raw_text="{}", parsed=parsed)

    service = PageClassificationService(
        tmp_path / "data",
        CountingWrapper(),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "interrupted"
    assert state.terminal_reason == "page classification was interrupted by service restart"
    assert state.progress.current_page_number is None
    assert calls["count"] == 0


def test_reclassification_replaces_only_current_state(tmp_path: Path) -> None:
    html_path = _write_fixture(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    wrapper = EmptyWrapper()
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)

    def _completed() -> bool:
        current = service.get_current(prepared.reviewed_html)
        return current is not None and current.status == "completed"

    _wait_for(_completed)
    first = service.get_current(prepared.reviewed_html)
    assert first is not None
    assert first.status == "completed"

    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_for(_completed)
    second = service.get_current(prepared.reviewed_html)
    assert second is not None
    assert second.status == "completed"
    workspace = (
        PageClassificationStore(tmp_path / "data").current_path(prepared.reviewed_html).parent
    )
    names = sorted(path.name for path in workspace.iterdir())
    assert names == [CURRENT_CLASSIFICATION_FILENAME]


def test_service_does_not_import_stage2_or_api() -> None:
    import app.page_classification.service as service_module

    source = Path(service_module.__file__).read_text(encoding="utf-8")
    assert "extraction_review" not in source
    assert "lexical_extraction.runner" not in source
    assert "document_review" not in source
    assert "fastapi" not in source.lower()
    assert "api/v1" not in source


def test_start_prepares_document_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_path = _write_fixture(tmp_path)
    expected = prepare_reviewed_document(html_path).reviewed_html
    calls = {"count": 0}
    real_prepare = prepare_reviewed_document

    def counting_prepare(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(
        "app.page_classification.service.prepare_reviewed_document",
        counting_prepare,
    )
    wrapper = EmptyWrapper()
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=expected)

    def _completed() -> bool:
        current = service.get_current(expected)
        return current is not None and current.status == "completed"

    _wait_for(_completed)
    assert calls["count"] == 1
    final = service.get_current(expected)
    assert final is not None
    assert final.status == "completed"
    assert len(final.page_results) == 3


def test_second_service_does_not_interrupt_active_same_process_worker(
    tmp_path: Path,
) -> None:
    html_path = _write_fixture(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    data_dir = tmp_path / "data"
    wrapper = EmptyWrapper()
    inner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    blocking = BlockingRunner(inner)
    first = PageClassificationService(
        data_dir,
        wrapper,  # type: ignore[arg-type]
        runner=blocking,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = first.start_classification(html_path, expected=prepared.reviewed_html)
    assert started.status == "running"
    assert blocking.entered.wait(timeout=5.0)

    second = PageClassificationService(
        first.data_dir,
        EmptyWrapper(),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    current = first.get_current(prepared.reviewed_html)
    assert current is not None
    assert current.status == "running"
    assert current.terminal_reason is None
    assert second.get_current(prepared.reviewed_html) is not None
    assert second.get_current(prepared.reviewed_html).status == "running"  # type: ignore[union-attr]

    with pytest.raises(PageClassificationBusyError):
        second.start_classification(html_path, expected=prepared.reviewed_html)

    still_running = first.get_current(prepared.reviewed_html)
    assert still_running is not None
    assert still_running.status == "running"

    blocking.release.set()

    def _terminal() -> bool:
        state = first.get_current(prepared.reviewed_html)
        return state is not None and state.status in {"completed", "failed", "interrupted"}

    _wait_for(_terminal, timeout=30.0)
    final = first.get_current(prepared.reviewed_html)
    assert final is not None
    assert final.status == "completed", (
        f"expected completed after release, got {final.status!r} "
        f"reason={final.terminal_reason!r}"
    )
    assert len(final.page_results) == 3
