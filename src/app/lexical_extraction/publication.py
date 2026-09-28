"""Filesystem evidence publication for lexical extraction (L13).

Implements the L12 ``EvidenceSink`` against a run directory under
``output.directory``, stages page/block evidence with bounded memory, commits
per-component artifacts atomically, and finalizes a versioned run manifest last.
Does not open reviewed HTML, query the knowledge snapshot, or run matching.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import shutil
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Final, Literal, cast

from app.lexical_extraction.contracts import (
    RECORD_SCHEMA_VERSION,
    BlockRecord,
    Component,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FinalManifestClaim,
    PageEvidence,
    PublicationRecord,
    PublicationStatus,
    SafeStructuredError,
    occurrence_spans,
)
from app.lexical_extraction.monitoring import RunMonitoringSummary
from app.lexical_extraction.runner import LexicalRunResult

COMPONENT_ARTIFACT_SCHEMA_VERSION: Final = "batchlens.lexical-component-artifact.v1"
RUN_MANIFEST_SCHEMA_VERSION: Final = "batchlens.lexical-run-manifest.v1"
MANIFEST_FILE_NAME: Final = "manifest.json"
ARTIFACTS_DIR_NAME: Final = "artifacts"
STAGING_DIR_NAME: Final = ".staging"
_READ_CHUNK: Final = 64 * 1024

_MAX_ERROR_MESSAGE: Final = 200

CliExitCode = Literal[0, 1, 2, 3]
# 0 = extraction completed + publication completed
# 1 = extraction partial + publication completed
# 2 = extraction failed (truthful final manifest may exist) or pre-validation
# 3 = publication failed / interrupted (no completed publication claim)


class PublicationError(Exception):
    """Bounded publication or sink lifecycle failure."""

    def __init__(self, code: str, message: str) -> None:
        if not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("publication error message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self, component: Component | None = None) -> SafeStructuredError:
        return SafeStructuredError(
            code=self.code,
            message=self.message,
            component=component,
            retryable=False,
        )


@dataclass(frozen=True)
class ArtifactDescriptor:
    """Committed component artifact identity relative to the run directory."""

    component: Component
    relative_path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class PublicationResult:
    """Outcome of final-manifest publication after a sealed L12 run."""

    run_id: str
    run_directory: Path
    publication: PublicationRecord
    manifest_path: Path | None
    artifacts: tuple[ArtifactDescriptor, ...]
    exit_code: CliExitCode
    error: SafeStructuredError | None = None


@dataclass
class StreamedComponentPage:
    """One page skeleton plus a one-shot block iterator.

    Retains only the current ``PageEvidence``. Blocks are yielded one at a time.
    Closing ``iter_blocks`` early still drains remaining block JSON so the parent
    stream stays aligned; ``drain()`` is then a no-op.
    """

    page: PageEvidence
    _blocks: Iterator[BlockRecord]
    _drained: bool = False

    @property
    def drained(self) -> bool:
        return self._drained

    def iter_blocks(self) -> Generator[BlockRecord, None, None]:
        if self._drained:
            return
        try:
            for record in self._blocks:  # noqa: UP028 - finally must drain remainder
                yield record
        finally:
            for _ in self._blocks:
                pass
            self._drained = True

    def drain(self) -> None:
        if self._drained:
            return
        for _ in self.iter_blocks():
            pass


@dataclass
class _ComponentStaging:
    """Disk-backed staging with finite in-memory counters only."""

    component: Component
    directory: Path
    pages_path: Path
    blocks_dir: Path
    page_count: int = 0


def _bounded_message(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE:
        return message
    return message[: _MAX_ERROR_MESSAGE - 3] + "..."


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_all(fd: int, chunk: bytes) -> None:
    """Write every byte of ``chunk``; treat zero/short progress as failure."""

    view = memoryview(chunk)
    offset = 0
    length = len(chunk)
    while offset < length:
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise PublicationError(
                "WRITE_SHORT",
                "component artifact write returned zero bytes",
            )
        offset += written


def atomic_replace_file(source: Path, destination: Path) -> None:
    """Atomically replace ``destination`` with an already-flushed ``source`` file."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    _fsync_directory(destination.parent)


def _mkstemp_sibling(path: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )


def _fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _model_payload(model: object) -> dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if dump is None:
        raise TypeError("expected a pydantic model")
    payload = dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("model dump must be an object")
    return cast(dict[str, Any], payload)


def _monitoring_payload(summary: RunMonitoringSummary) -> dict[str, Any]:
    return {
        "pages_observed": summary.pages_observed,
        "blocks_observed": summary.blocks_observed,
        "completed_components": [item.value for item in summary.completed_components],
        "failed_components": [item.value for item in summary.failed_components],
        "zero_result_components": [item.value for item in summary.zero_result_components],
        "matches_by_component": dict(summary.matches_by_component),
        "matches_by_method": dict(summary.matches_by_method),
        "eligible_terms": summary.eligible_terms,
        "eligible_rows": summary.eligible_rows,
        "candidates": summary.candidates,
        "timings": [_model_payload(item) for item in summary.timings],
        "resource_limits": dict(summary.resource_limits),
        "peak_process_memory_bytes": summary.peak_process_memory_bytes,
        "peak_memory_method": summary.peak_memory_method,
        "measurements": [_model_payload(item) for item in summary.measurements],
    }


def component_artifact_relative_path(component: Component) -> str:
    return f"{ARTIFACTS_DIR_NAME}/component-{component.value}.json"


def output_is_inside_snapshot(output_directory: Path, snapshot_directory: Path) -> bool:
    """True when resolved output equals or is contained by the snapshot directory."""

    output = output_directory.resolve()
    snapshot = snapshot_directory.resolve()
    if output == snapshot:
        return True
    return output.is_relative_to(snapshot)


def guard_output_outside_snapshot(output_directory: Path, snapshot_directory: Path) -> None:
    """Refuse an output root that would write into the read-only snapshot tree."""

    if output_is_inside_snapshot(output_directory, snapshot_directory):
        raise PublicationError(
            "OUTPUT_INSIDE_SNAPSHOT",
            "output.directory must not equal or lie inside the knowledge snapshot",
        )


def _page_block_path(staging: _ComponentStaging, page_number: int) -> Path:
    return staging.blocks_dir / f"page-{page_number:05d}.jsonl"


def _page_meta_path(staging: _ComponentStaging, page_number: int) -> Path:
    return staging.blocks_dir / f"page-{page_number:05d}.meta"


def _read_page_meta(path: Path) -> tuple[int, str | None, int]:
    """Return (last_order, last_node_id|None, block_count) from a tiny meta file."""

    if not path.exists():
        return -1, None, 0
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return -1, None, 0
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise PublicationError("STAGING_CORRUPT", "page meta must be an object")
    data = cast(dict[str, Any], payload)
    last_order = int(data["last_order"])
    last_node = data.get("last_node_id")
    last_node_id = str(last_node) if last_node is not None else None
    block_count = int(data["block_count"])
    return last_order, last_node_id, block_count


def _write_page_meta(
    path: Path,
    *,
    last_order: int,
    last_node_id: str | None,
    block_count: int,
) -> None:
    payload = {
        "last_order": last_order,
        "last_node_id": last_node_id,
        "block_count": block_count,
    }
    path.write_bytes(_canonical_json_bytes(payload) + b"\n")


class FilesystemEvidenceSink:
    """Component-scoped filesystem sink with provisional staging and atomic commits.

    ``complete_run`` seals the sink only. Call ``finalize_publication`` after the
    runner returns ``LexicalRunResult`` to write the final manifest.
    """

    def __init__(
        self,
        output_directory: Path,
        *,
        snapshot_directory: Path | None = None,
        fail_on_component_write: Component | None = None,
        fail_on_nth_block_write: int | None = None,
        fail_complete_component: Component | None = None,
        fail_complete_run: bool = False,
        fail_artifact_rename: Component | None = None,
        fail_manifest_write: bool = False,
        fail_manifest_rename: bool = False,
        fail_short_write_after: int | None = None,
    ) -> None:
        self.output_directory = output_directory.resolve()
        self.snapshot_directory = (
            None if snapshot_directory is None else snapshot_directory.resolve()
        )
        self.fail_on_component_write = fail_on_component_write
        self.fail_on_nth_block_write = fail_on_nth_block_write
        self.fail_complete_component = fail_complete_component
        self.fail_complete_run = fail_complete_run
        self.fail_artifact_rename = fail_artifact_rename
        self.fail_manifest_write = fail_manifest_write
        self.fail_manifest_rename = fail_manifest_rename
        self.fail_short_write_after = fail_short_write_after
        self.run_id: str | None = None
        self.run_directory: Path | None = None
        self._sealed = False
        self._aborted: SafeStructuredError | None = None
        self._active: dict[Component, _ComponentStaging] = {}
        self._committed: dict[Component, ArtifactDescriptor] = {}
        self._block_writes = 0
        self._bytes_written_this_artifact = 0

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def aborted(self) -> SafeStructuredError | None:
        return self._aborted

    @property
    def has_provisional_components(self) -> bool:
        return bool(self._active)

    @property
    def committed_artifacts(self) -> Mapping[Component, ArtifactDescriptor]:
        return dict(self._committed)

    def begin_run(self, run_id: str) -> None:
        if self.run_id is not None:
            raise PublicationError("SINK_STATE", "begin_run called more than once")
        if not run_id:
            raise PublicationError("SINK_STATE", "run_id must be nonempty")
        if self.snapshot_directory is not None:
            guard_output_outside_snapshot(self.output_directory, self.snapshot_directory)
        self.run_id = run_id
        self.run_directory = self.output_directory / run_id
        if self.run_directory.exists():
            raise PublicationError(
                "RUN_DIRECTORY_EXISTS",
                "refusing to replace an existing lexical run directory",
            )
        try:
            self.run_directory.mkdir(parents=True, exist_ok=False)
            (self.run_directory / ARTIFACTS_DIR_NAME).mkdir()
            (self.run_directory / STAGING_DIR_NAME).mkdir()
        except OSError as exc:
            raise PublicationError(
                "RUN_DIRECTORY_CREATE_FAILED",
                _bounded_message(f"could not create run directory: {type(exc).__name__}"),
            ) from exc

    def begin_component(self, component: Component) -> None:
        self._require_open_run()
        if self._sealed or self._aborted is not None:
            raise PublicationError("SINK_STATE", "cannot begin a component after run finalization")
        if component in self._active:
            raise PublicationError("SINK_STATE", "component stream is already provisional")
        if component in self._committed:
            raise PublicationError("SINK_STATE", "component artifact already committed")
        assert self.run_directory is not None
        staging_dir = self.run_directory / STAGING_DIR_NAME / component.value
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        blocks_dir = staging_dir / "blocks"
        blocks_dir.mkdir(parents=True)
        pages_path = staging_dir / "pages.jsonl"
        pages_path.write_bytes(b"")
        self._active[component] = _ComponentStaging(
            component=component,
            directory=staging_dir,
            pages_path=pages_path,
            blocks_dir=blocks_dir,
        )

    def write_page(self, component: Component, page: PageEvidence) -> None:
        staging = self._require_active(component)
        block_path = _page_block_path(staging, page.page_number)
        if block_path.exists() or _page_meta_path(staging, page.page_number).exists():
            raise PublicationError(
                "PAGE_DUPLICATE",
                "duplicate page skeleton for the active component",
            )
        expected_order = staging.page_count
        if page.order != expected_order:
            raise PublicationError(
                "PAGE_ORDER",
                "page skeleton order is not contiguous for the active component",
            )
        staging.page_count += 1
        block_path.write_bytes(b"")
        _write_page_meta(
            block_path.with_suffix(".meta"), last_order=-1, last_node_id=None, block_count=0
        )
        line = _canonical_json_bytes(_model_payload(page)) + b"\n"
        with staging.pages_path.open("ab") as handle:
            handle.write(line)

    def write_block(self, component: Component, record: BlockRecord) -> None:
        staging = self._require_active(component)
        self._block_writes += 1
        if self.fail_on_component_write is component:
            raise RuntimeError("injected sink component failure")
        if (
            self.fail_on_nth_block_write is not None
            and self._block_writes >= self.fail_on_nth_block_write
        ):
            raise RuntimeError("injected sink block failure")
        page_number = record.block.page_number
        block_path = _page_block_path(staging, page_number)
        meta_path = _page_meta_path(staging, page_number)
        if not block_path.exists():
            raise PublicationError(
                "BLOCK_PAGE_UNKNOWN",
                "block page_number has no page skeleton for the active component",
            )
        last_order, last_node_id, block_count = _read_page_meta(meta_path)
        order = record.block.order
        node_id = record.block.node_id
        if last_node_id is None:
            if order < 0:
                raise PublicationError("BLOCK_ORDER", "block order must be non-negative")
        else:
            if (order, node_id) <= (last_order, last_node_id):
                raise PublicationError(
                    "BLOCK_ORDER",
                    "blocks must arrive in ascending (order, node_id) without reordering",
                )
        line = _canonical_json_bytes(_model_payload(record)) + b"\n"
        with block_path.open("ab") as handle:
            handle.write(line)
        _write_page_meta(
            meta_path,
            last_order=order,
            last_node_id=node_id,
            block_count=block_count + 1,
        )

    def complete_component(self, component: Component) -> None:
        staging = self._require_active(component)
        if self.fail_complete_component is component:
            self._discard_staging(staging)
            del self._active[component]
            raise RuntimeError("injected complete failure")
        assert self.run_directory is not None
        assert self.run_id is not None
        relative = component_artifact_relative_path(component)
        destination = self.run_directory / relative
        temporary: Path | None = None
        try:
            temporary = self._materialize_component_artifact(
                staging,
                destination=destination,
                run_id=self.run_id,
            )
            if self.fail_artifact_rename is component:
                raise RuntimeError("injected artifact rename failure")
            byte_size = temporary.stat().st_size
            digest = _sha256_file(temporary)
            atomic_replace_file(temporary, destination)
            temporary = None
        except PublicationError:
            self._discard_staging(staging)
            del self._active[component]
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            self._discard_staging(staging)
            del self._active[component]
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if isinstance(exc, RuntimeError) and str(exc).startswith("injected"):
                raise
            raise PublicationError(
                "COMPONENT_ARTIFACT_FAILED",
                _bounded_message(f"component artifact finalization failed: {type(exc).__name__}"),
            ) from exc
        self._discard_staging(staging)
        del self._active[component]
        self._committed[component] = ArtifactDescriptor(
            component=component,
            relative_path=relative.replace("\\", "/"),
            byte_size=byte_size,
            sha256=digest,
        )

    def abort_component(self, component: Component, error: SafeStructuredError) -> None:
        if component in self._committed:
            raise PublicationError(
                "SINK_STATE",
                "abort_component called for a committed component",
            )
        staging = self._active.pop(component, None)
        if staging is not None:
            self._discard_staging(staging)
        _ = error

    def complete_run(self) -> None:
        self._require_open_run()
        if self._aborted is not None:
            raise PublicationError("SINK_STATE", "complete_run after abort_run")
        if self._active:
            raise PublicationError(
                "SINK_STATE",
                "complete_run with an outstanding provisional component",
            )
        if self.fail_complete_run:
            raise RuntimeError("injected complete_run failure")
        self._sealed = True

    def abort_run(self, error: SafeStructuredError) -> None:
        for staging in list(self._active.values()):
            self._discard_staging(staging)
        self._active.clear()
        self._sealed = False
        self._aborted = error

    def _require_open_run(self) -> None:
        if self.run_id is None or self.run_directory is None:
            raise PublicationError("SINK_STATE", "begin_run has not been called")

    def _require_active(self, component: Component) -> _ComponentStaging:
        self._require_open_run()
        if self._sealed or self._aborted is not None:
            raise PublicationError("SINK_STATE", "run is no longer accepting writes")
        staging = self._active.get(component)
        if staging is None:
            raise PublicationError("SINK_STATE", "no provisional stream for component")
        return staging

    def _discard_staging(self, staging: _ComponentStaging) -> None:
        if staging.directory.exists():
            shutil.rmtree(staging.directory, ignore_errors=True)

    def _write_checked(self, fd: int, chunk: bytes) -> None:
        if self.fail_short_write_after is not None:
            remaining = self.fail_short_write_after - self._bytes_written_this_artifact
            if remaining <= 0:
                raise PublicationError(
                    "WRITE_SHORT",
                    "injected short write while publishing component artifact",
                )
            if len(chunk) > remaining:
                _write_all(fd, chunk[:remaining])
                self._bytes_written_this_artifact += remaining
                raise PublicationError(
                    "WRITE_SHORT",
                    "injected short write while publishing component artifact",
                )
        _write_all(fd, chunk)
        self._bytes_written_this_artifact += len(chunk)

    def _materialize_component_artifact(
        self,
        staging: _ComponentStaging,
        *,
        destination: Path,
        run_id: str,
    ) -> Path:
        fd, temporary_name = _mkstemp_sibling(destination)
        temporary = Path(temporary_name)
        closed = False
        self._bytes_written_this_artifact = 0
        try:

            def write_raw(chunk: bytes) -> None:
                self._write_checked(fd, chunk)

            write_raw(b'{"schema_version":')
            write_raw(_canonical_json_bytes(COMPONENT_ARTIFACT_SCHEMA_VERSION))
            write_raw(b',"record_schema_version":')
            write_raw(_canonical_json_bytes(RECORD_SCHEMA_VERSION))
            write_raw(b',"run_id":')
            write_raw(_canonical_json_bytes(run_id))
            write_raw(b',"component":')
            write_raw(_canonical_json_bytes(staging.component.value))
            write_raw(b',"page_count":')
            write_raw(_canonical_json_bytes(staging.page_count))
            write_raw(b',"pages":[')

            pages_seen = 0
            with staging.pages_path.open("rb") as pages_handle:
                for raw_line in pages_handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    page = PageEvidence.model_validate_json(line)
                    if pages_seen:
                        write_raw(b",")
                    self._stream_write_page(write_raw, staging, page)
                    pages_seen += 1

            if pages_seen != staging.page_count:
                raise PublicationError(
                    "PAGE_INCOMPLETE",
                    "staged page count does not match written page skeletons",
                )
            write_raw(b"]}")
            os.fsync(fd)
            os.close(fd)
            closed = True
            return temporary
        except Exception:
            if not closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            temporary.unlink(missing_ok=True)
            raise

    def _stream_write_page(
        self,
        write_raw: Any,
        staging: _ComponentStaging,
        page: PageEvidence,
    ) -> None:
        """Serialize one page and its blocks without retaining a block list."""

        write_raw(b'{"page":')
        write_raw(_canonical_json_bytes(_model_payload(page)))
        write_raw(b',"blocks":[')
        meta_path = _page_meta_path(staging, page.page_number)
        _, _, expected = _read_page_meta(meta_path)
        written = 0
        first = True
        for record in self._iter_staged_blocks(staging, page.page_number):
            if record.block.page_number != page.page_number:
                raise PublicationError(
                    "BLOCK_PAGE_MISMATCH",
                    "staged block page_number does not match its page skeleton",
                )
            if first:
                first = False
            else:
                write_raw(b",")
            write_raw(_canonical_json_bytes(_model_payload(record)))
            written += 1
        if written != expected:
            raise PublicationError(
                "BLOCK_INCOMPLETE",
                "staged block count does not match writes for a page",
            )
        write_raw(b"]}")

    def _iter_staged_blocks(
        self,
        staging: _ComponentStaging,
        page_number: int,
    ) -> Iterator[BlockRecord]:
        """Yield validated blocks in write order (fail-closed at write time)."""

        path = _page_block_path(staging, page_number)
        if not path.exists():
            return
        with path.open("rb") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                yield BlockRecord.model_validate_json(line)


def finalize_publication(
    sink: FilesystemEvidenceSink,
    result: LexicalRunResult,
) -> PublicationResult:
    """Write the final run manifest after a sealed L12 result.

    Requires sink-sealed state, matching run IDs, no ``run_error``, no provisional
    component, and artifact/outcome agreement. Never hashes the manifest as though
    its own bytes were already known.
    """

    run_directory = sink.run_directory
    if run_directory is None or sink.run_id is None:
        error = SafeStructuredError(
            code="PUBLICATION_STATE",
            message="publication finalize called before begin_run",
            component=None,
            retryable=False,
        )
        return PublicationResult(
            run_id=result.run_id,
            run_directory=sink.output_directory / result.run_id,
            publication=PublicationRecord(status=PublicationStatus.FAILED),
            manifest_path=None,
            artifacts=(),
            exit_code=3,
            error=error,
        )

    if result.run_id != sink.run_id:
        error = SafeStructuredError(
            code="PUBLICATION_RUN_MISMATCH",
            message="runner run_id does not match the sealed evidence sink",
            component=None,
            retryable=False,
        )
        return _failed_publication(sink, result, error)

    if result.run_error is not None:
        return _failed_publication(sink, result, result.run_error)

    if sink.aborted is not None or not sink.sealed:
        error = sink.aborted or SafeStructuredError(
            code="PUBLICATION_NOT_SEALED",
            message="evidence sink is not sealed for final-manifest publication",
            component=None,
            retryable=False,
        )
        return _failed_publication(sink, result, error)

    if sink.has_provisional_components:
        error = SafeStructuredError(
            code="PUBLICATION_PROVISIONAL",
            message="outstanding provisional component blocks final-manifest publication",
            component=None,
            retryable=False,
        )
        return _failed_publication(sink, result, error)

    if result.pre_validation is not None:
        error = SafeStructuredError(
            code="PUBLICATION_PRE_VALIDATION",
            message="pre-validation failure cannot claim completed publication",
            component=None,
            retryable=False,
        )
        return PublicationResult(
            run_id=result.run_id,
            run_directory=run_directory,
            publication=PublicationRecord(status=PublicationStatus.FAILED),
            manifest_path=None,
            artifacts=(),
            exit_code=2,
            error=error,
        )

    if (
        result.validated_input is None
        or result.knowledge is None
        or result.provenance is None
        or result.extraction is None
    ):
        error = SafeStructuredError(
            code="PUBLICATION_IDENTITY_MISSING",
            message="final manifest requires validated HTML, snapshot, provenance, and extraction",
            component=None,
            retryable=False,
        )
        return _failed_publication(sink, result, error)

    try:
        artifacts = _agree_artifacts_with_outcomes(sink, result.extraction)
    except PublicationError as exc:
        return _failed_publication(sink, result, exc.to_structured_error())

    manifest_id = f"manifest-{result.run_id}"
    publication = PublicationRecord(
        status=PublicationStatus.COMPLETED,
        final_manifest=FinalManifestClaim(
            manifest_id=manifest_id,
            publication_status="completed",
        ),
    )
    artifact_payloads = [
        {
            "component": item.component.value,
            "relative_path": item.relative_path,
            "byte_size": item.byte_size,
            "sha256": item.sha256,
        }
        for item in artifacts
    ]
    payload: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "run_id": result.run_id,
        "validated_input": _model_payload(result.validated_input),
        "knowledge": _model_payload(result.knowledge),
        "provenance": _model_payload(result.provenance),
        "extraction": _model_payload(result.extraction),
        "publication": _model_payload(publication),
        "artifacts": artifact_payloads,
        "monitoring": _monitoring_payload(result.monitoring),
        "run_status": result.extraction.overall.value,
        "errors": _manifest_errors(result.extraction),
    }
    manifest_path = run_directory / MANIFEST_FILE_NAME
    body = _canonical_json_bytes(payload)
    temporary: Path | None = None
    try:
        if sink.fail_manifest_write:
            raise RuntimeError("injected manifest write failure")
        fd, temporary_name = _mkstemp_sibling(manifest_path)
        temporary = Path(temporary_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        if sink.fail_manifest_rename:
            raise RuntimeError("injected manifest rename failure")
        atomic_replace_file(temporary, manifest_path)
        temporary = None
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        error = SafeStructuredError(
            code="MANIFEST_PUBLICATION_FAILED",
            message=_bounded_message(f"final manifest publication failed: {type(exc).__name__}"),
            component=None,
            retryable=False,
        )
        return PublicationResult(
            run_id=result.run_id,
            run_directory=run_directory,
            publication=PublicationRecord(status=PublicationStatus.FAILED),
            manifest_path=None,
            artifacts=artifacts,
            exit_code=3,
            error=error,
        )

    exit_code = _exit_code_for_extraction(result.extraction.overall)
    return PublicationResult(
        run_id=result.run_id,
        run_directory=run_directory,
        publication=publication,
        manifest_path=manifest_path,
        artifacts=artifacts,
        exit_code=exit_code,
        error=None,
    )


def _agree_artifacts_with_outcomes(
    sink: FilesystemEvidenceSink,
    extraction: ExtractionOutcomeRecord,
) -> tuple[ArtifactDescriptor, ...]:
    committed = dict(sink.committed_artifacts)
    ordered: list[ArtifactDescriptor] = []
    for item in extraction.components:
        if item.outcome is ExtractionOutcome.COMPLETED:
            artifact = committed.pop(item.component, None)
            if artifact is None:
                raise PublicationError(
                    "ARTIFACT_MISSING",
                    "completed component is missing a committed artifact",
                )
            ordered.append(artifact)
        elif item.component in committed:
            raise PublicationError(
                "ARTIFACT_UNEXPECTED",
                "non-completed component has a committed artifact",
            )
    if committed:
        raise PublicationError(
            "ARTIFACT_UNEXPECTED",
            "committed artifact is not listed in extraction outcomes",
        )
    return tuple(ordered)


def _manifest_errors(extraction: ExtractionOutcomeRecord) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for item in extraction.components:
        if item.error is not None:
            errors.append(_model_payload(item.error))
    return errors


def _exit_code_for_extraction(overall: ExtractionOutcome) -> CliExitCode:
    if overall is ExtractionOutcome.COMPLETED:
        return 0
    if overall is ExtractionOutcome.PARTIAL:
        return 1
    return 2


def _failed_publication(
    sink: FilesystemEvidenceSink,
    result: LexicalRunResult,
    error: SafeStructuredError,
) -> PublicationResult:
    run_directory = sink.run_directory or (sink.output_directory / result.run_id)
    return PublicationResult(
        run_id=result.run_id,
        run_directory=run_directory,
        publication=PublicationRecord(status=PublicationStatus.FAILED),
        manifest_path=None,
        artifacts=tuple(sink.committed_artifacts.values()),
        exit_code=3,
        error=error,
    )


def load_final_manifest(path: Path) -> dict[str, Any]:
    """Load and lightly validate a published final run manifest."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PublicationError("MANIFEST_INVALID", "final manifest root must be an object")
    payload = cast(dict[str, Any], raw)
    if payload.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        raise PublicationError("MANIFEST_SCHEMA", "unsupported final manifest schema version")
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        raise PublicationError("MANIFEST_INVALID", "publication object is required")
    PublicationRecord.model_validate(cast(dict[str, Any], publication))
    return payload


def verify_artifact_hashes(
    manifest: Mapping[str, Any],
    run_directory: Path,
) -> tuple[ArtifactDescriptor, ...]:
    """Verify each referenced artifact exists with matching size and SHA-256."""

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise PublicationError("MANIFEST_INVALID", "artifacts must be a list")
    verified: list[ArtifactDescriptor] = []
    for raw_item in cast(list[object], raw_artifacts):
        if not isinstance(raw_item, dict):
            raise PublicationError("MANIFEST_INVALID", "artifact entry must be an object")
        item = cast(dict[str, Any], raw_item)
        component = Component(str(item["component"]))
        relative = str(item["relative_path"])
        expected_size = int(item["byte_size"])
        expected_sha = str(item["sha256"])
        path = run_directory / relative
        if not path.is_file():
            raise PublicationError("ARTIFACT_MISSING", "referenced artifact file is missing")
        size = path.stat().st_size
        if size != expected_size:
            raise PublicationError("ARTIFACT_SIZE_MISMATCH", "artifact byte size does not match")
        digest = _sha256_file(path)
        if digest != expected_sha:
            raise PublicationError("ARTIFACT_HASH_MISMATCH", "artifact SHA-256 does not match")
        verified.append(
            ArtifactDescriptor(
                component=component,
                relative_path=relative.replace("\\", "/"),
                byte_size=size,
                sha256=digest,
            )
        )
    return tuple(verified)


class _BytesReadTracker:
    """Binary file wrapper that records how many bytes have been read."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        self.bytes_read += len(chunk)
        return chunk

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> _BytesReadTracker:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _Utf8JsonStream:
    """Incremental UTF-8 + JSON text buffer that discards consumed characters."""

    def __init__(self, binary: _BytesReadTracker) -> None:
        self._binary = binary
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buf = ""
        self._eof = False
        self.peak_retained_chars = 0
        self._json = json.JSONDecoder()

    def _note_peak(self) -> None:
        size = len(self._buf)
        if size > self.peak_retained_chars:
            self.peak_retained_chars = size

    def compact(self, index: int) -> int:
        if index <= 0:
            return 0
        self._buf = self._buf[index:]
        self._note_peak()
        return 0

    def fill(self) -> bool:
        """Pull more bytes. Returns False at EOF after finalizing the decoder."""

        if self._eof:
            return False
        chunk = self._binary.read(_READ_CHUNK)
        if not chunk:
            try:
                tail = self._decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise PublicationError(
                    "ARTIFACT_UTF8",
                    "component artifact contains invalid UTF-8",
                ) from exc
            if tail:
                self._buf += tail
                self._note_peak()
            self._eof = True
            return False
        try:
            text = self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise PublicationError(
                "ARTIFACT_UTF8",
                "component artifact contains invalid UTF-8",
            ) from exc
        if text:
            self._buf += text
            self._note_peak()
        return True

    def ensure(self, index: int, minimum: int = 1) -> int:
        while index + minimum > len(self._buf):
            if not self.fill():
                break
        return index

    def skip_ws(self, index: int) -> int:
        while True:
            index = self.ensure(index)
            if index >= len(self._buf):
                self.compact(len(self._buf))
                index = 0
                if not self.fill():
                    return 0
                continue
            if self._buf[index] not in " \t\r\n":
                return self.compact(index)
            index += 1

    def peek(self, index: int) -> str | None:
        index = self.ensure(index)
        if index >= len(self._buf):
            return None
        return self._buf[index]

    def expect_char(self, index: int, expected: str, *, allow_ws: bool = True) -> int:
        if allow_ws:
            index = self.skip_ws(index)
        index = self.ensure(index)
        if index >= len(self._buf) or self._buf[index] != expected:
            raise PublicationError(
                "ARTIFACT_INVALID",
                f"expected {expected!r} in component artifact stream",
            )
        return self.compact(index + 1)

    def expect_key(self, index: int, key: str) -> int:
        literal = f'"{key}"'
        while True:
            index = self.skip_ws(index)
            index = self.ensure(index, minimum=len(literal) + 2)
            if self._buf.startswith(literal, index):
                index = self.compact(index + len(literal))
                return self.expect_char(index, ":")
            if not self.fill():
                raise PublicationError(
                    "ARTIFACT_INVALID",
                    f"expected key {key!r} in component artifact stream",
                )

    def raw_decode_value(self, index: int) -> tuple[object, int]:
        while True:
            index = self.skip_ws(index)
            index = self.ensure(index)
            try:
                value, end = self._json.raw_decode(self._buf, index)
                return value, self.compact(end)
            except json.JSONDecodeError:
                if not self.fill():
                    raise PublicationError(
                        "ARTIFACT_TRUNCATED",
                        "component artifact truncated while decoding a JSON value",
                    ) from None

    def read_until_pages_array(self) -> dict[str, Any]:
        """Consume the object header through ``"pages":[`` and return parsed header."""

        while True:
            self.ensure(0, minimum=1)
            if not self._buf.lstrip().startswith("{"):
                if not self.fill() and not self._buf.strip():
                    raise PublicationError(
                        "ARTIFACT_TRUNCATED",
                        "component artifact ended before pages",
                    )
                if self._buf.lstrip() and not self._buf.lstrip().startswith("{"):
                    raise PublicationError(
                        "ARTIFACT_INVALID",
                        "component artifact root must be an object",
                    )
                continue
            marker = '"pages"'
            pos = self._buf.find(marker)
            if pos < 0:
                if not self.fill():
                    raise PublicationError(
                        "ARTIFACT_TRUNCATED",
                        "pages array marker not found",
                    )
                # Keep buffer bounded while searching: drop only pure leading whitespace.
                stripped = self._buf.lstrip()
                if len(stripped) < len(self._buf):
                    self._buf = stripped
                    self._note_peak()
                continue
            after = self._buf[pos + len(marker) :]
            after_stripped = after.lstrip()
            if not after_stripped.startswith(":"):
                if not self.fill():
                    raise PublicationError("ARTIFACT_INVALID", "pages field is malformed")
                continue
            after_colon = after_stripped[1:].lstrip()
            if not after_colon.startswith("["):
                if not self.fill():
                    raise PublicationError("ARTIFACT_INVALID", "pages must be a JSON array")
                continue
            prefix = self._buf[:pos].rstrip()
            if prefix.endswith(","):
                prefix = prefix[:-1]
            header_json = prefix + "}"
            try:
                parsed, _ = self._json.raw_decode(header_json)
            except json.JSONDecodeError as exc:
                if not self.fill():
                    raise PublicationError(
                        "ARTIFACT_INVALID",
                        "component artifact header is not valid JSON",
                    ) from exc
                continue
            if not isinstance(parsed, dict):
                raise PublicationError(
                    "ARTIFACT_INVALID",
                    "component artifact header must be an object",
                )
            header = cast(dict[str, Any], parsed)
            absolute_bracket = pos + len(marker) + (len(after) - len(after_colon))
            # Position just after '[' of pages array.
            self.compact(absolute_bracket + 1)
            return header

    def finish_envelope(self, index: int) -> None:
        """Require ``}`` then only whitespace through finalized EOF."""

        index = self.expect_char(index, "}")
        index = self.skip_ws(index)
        while self.fill():
            index = self.skip_ws(index)
        index = self.skip_ws(index)
        if index < len(self._buf) and self._buf[index:].strip():
            raise PublicationError(
                "ARTIFACT_INVALID",
                "trailing data after component artifact envelope",
            )
        if not self._eof:
            self.fill()
        # Final decoder already run by fill(); nothing else expected.
        _ = index


@dataclass
class ComponentArtifactStream:
    """Open component-artifact handle used by streaming page iteration and tests."""

    tracker: _BytesReadTracker
    text: _Utf8JsonStream
    header: dict[str, Any]
    file_size: int

    @property
    def bytes_read(self) -> int:
        return self.tracker.bytes_read

    @property
    def peak_retained_chars(self) -> int:
        return self.text.peak_retained_chars

    def close(self) -> None:
        self.tracker.close()


def open_component_artifact_stream(artifact_path: Path) -> ComponentArtifactStream:
    """Open a component artifact and parse only the header before pages."""

    handle = artifact_path.open("rb")
    tracker = _BytesReadTracker(handle)
    text = _Utf8JsonStream(tracker)
    try:
        header = text.read_until_pages_array()
    except Exception:
        tracker.close()
        raise
    if header.get("schema_version") != COMPONENT_ARTIFACT_SCHEMA_VERSION:
        tracker.close()
        raise PublicationError("ARTIFACT_SCHEMA", "unsupported component artifact schema")
    return ComponentArtifactStream(
        tracker=tracker,
        text=text,
        header=header,
        file_size=artifact_path.stat().st_size,
    )


def iter_component_pages_from_stream(
    stream: ComponentArtifactStream,
) -> Iterator[StreamedComponentPage]:
    """Iterate pages from an already-opened artifact stream."""

    yield from _iter_streamed_pages(stream)


def _iter_streamed_pages(
    stream: ComponentArtifactStream,
) -> Iterator[StreamedComponentPage]:
    """Stream page skeletons and per-block records with a compacting text buffer."""

    text = stream.text
    expected_pages = stream.header.get("page_count")
    if not isinstance(expected_pages, int) or expected_pages < 0:
        raise PublicationError("ARTIFACT_INVALID", "page_count must be a non-negative integer")
    index = 0
    pages_seen = 0
    first_page = True
    while True:
        index = text.skip_ws(index)
        ch = text.peek(index)
        if ch == "]":
            index = text.compact(index + 1)
            break
        if not first_page:
            index = text.expect_char(index, ",")
            index = text.skip_ws(index)
            if text.peek(index) == "]":
                raise PublicationError(
                    "ARTIFACT_INVALID",
                    "trailing comma in pages array",
                )
        elif ch == ",":
            raise PublicationError(
                "ARTIFACT_INVALID",
                "leading comma before first page is not allowed",
            )
        first_page = False
        index = text.expect_char(index, "{")
        index = text.expect_key(index, "page")
        page_raw, index = text.raw_decode_value(index)
        if not isinstance(page_raw, dict):
            raise PublicationError("ARTIFACT_INVALID", "page evidence must be an object")
        page = PageEvidence.model_validate(cast(dict[str, Any], page_raw))
        index = text.expect_char(index, ",")
        index = text.expect_key(index, "blocks")
        index = text.expect_char(index, "[")

        def _blocks(
            start_index: int = index,
            page_number: int = page.page_number,
        ) -> Iterator[BlockRecord]:
            nonlocal index
            index = start_index
            first_block = True
            while True:
                index = text.skip_ws(index)
                block_ch = text.peek(index)
                if block_ch == "]":
                    index = text.compact(index + 1)
                    index = text.expect_char(index, "}")
                    return
                if not first_block:
                    index = text.expect_char(index, ",")
                    index = text.skip_ws(index)
                    if text.peek(index) == "]":
                        raise PublicationError(
                            "ARTIFACT_INVALID",
                            "trailing comma in page blocks array",
                        )
                elif block_ch == ",":
                    raise PublicationError(
                        "ARTIFACT_INVALID",
                        "leading comma in page blocks array",
                    )
                first_block = False
                block_raw, index = text.raw_decode_value(index)
                if not isinstance(block_raw, dict):
                    raise PublicationError("ARTIFACT_INVALID", "block entry must be an object")
                record = BlockRecord.model_validate(cast(dict[str, Any], block_raw))
                if record.block.page_number != page_number:
                    raise PublicationError(
                        "BLOCK_PAGE_MISMATCH",
                        "block page_number does not match its page skeleton",
                    )
                yield record

        view = StreamedComponentPage(page=page, _blocks=_blocks())
        pages_seen += 1
        yield view
        view.drain()

    if pages_seen != expected_pages:
        raise PublicationError(
            "ARTIFACT_PAGE_COUNT",
            "component artifact page_count does not match pages array length",
        )
    text.finish_envelope(index)


def iter_component_pages(artifact_path: Path) -> Iterator[StreamedComponentPage]:
    """Yield pages incrementally without loading the whole artifact first.

    Each yielded page exposes ``iter_blocks()`` for one-at-a-time block access.
    Unconsumed blocks are drained before the next page is yielded. Parses one
    page/block JSON value at a time from the ``pages`` array with a compacting
    UTF-8 buffer; never ``json.loads`` the entire file.
    """

    stream = open_component_artifact_stream(artifact_path)
    try:
        yield from _iter_streamed_pages(stream)
    finally:
        stream.close()


def locate_hit(
    artifact_path: Path,
    *,
    page_number: int,
    node_id: str,
    start_char: int,
    end_char: int,
) -> tuple[PageEvidence, BlockRecord] | None:
    """Locate one block by page, node, and exact occurrence span offsets.

    Returns ``None`` when the node is missing, the block is empty of matching
    spans, or no occurrence span equals ``(start_char, end_char)``. Nested
    value/unit spans are included via ``occurrence_spans``.
    """

    for streamed in iter_component_pages(artifact_path):
        if streamed.page.page_number != page_number:
            streamed.drain()
            continue
        for record in streamed.iter_blocks():
            if record.block.node_id != node_id:
                continue
            for occurrence in record.occurrences:
                for span in occurrence_spans(occurrence):
                    if span.start_char == start_char and span.end_char == end_char:
                        return streamed.page, record
        return None
    return None


def format_cli_summary(
    result: LexicalRunResult,
    publication: PublicationResult,
) -> str:
    """Compact operator summary without source text or unrestricted paths."""

    lines: list[str] = [f"run_id={result.run_id}"]
    if result.pre_validation is not None:
        lines.append("extraction_status=pre_validation_failed")
        lines.append(f"error_code={result.pre_validation.error.code}")
    elif result.extraction is not None:
        lines.append(f"extraction_status={result.extraction.overall.value}")
        for item in result.extraction.components:
            if item.outcome is ExtractionOutcome.NOT_REQUESTED:
                continue
            if item.outcome is ExtractionOutcome.COMPLETED:
                lines.append(f"component.{item.component.value}=completed:{item.match_count}")
            elif item.error is not None:
                lines.append(f"component.{item.component.value}=failed:{item.error.code}")
            else:
                lines.append(f"component.{item.component.value}={item.outcome.value}")
    else:
        lines.append("extraction_status=unavailable")
    if result.run_error is not None:
        lines.append(f"run_error={result.run_error.code}")
    lines.append(f"publication_status={publication.publication.status.value}")
    peak = result.monitoring.peak_process_memory_bytes
    method = result.monitoring.peak_memory_method
    if peak is None:
        lines.append(f"peak_memory_bytes=unavailable method={method}")
    else:
        lines.append(f"peak_memory_bytes={peak} method={method}")
    if publication.manifest_path is not None:
        lines.append(f"manifest_path={publication.manifest_path}")
    elif publication.error is not None:
        lines.append(f"publication_error={publication.error.code}")
    lines.append(f"exit_code={publication.exit_code}")
    return "\n".join(lines)


def publish_lexical_run(
    config_path: Path,
    *,
    sink: FilesystemEvidenceSink | None = None,
) -> tuple[LexicalRunResult, PublicationResult]:
    """Load L02 YAML, run L12, then finalize L13 publication."""

    from app.lexical_extraction.configuration import load_execution_configuration
    from app.lexical_extraction.runner import run_lexical_extraction

    config = load_execution_configuration(config_path)
    guard_output_outside_snapshot(config.output.directory, config.knowledge.snapshot_directory)
    owned_sink = sink or FilesystemEvidenceSink(
        config.output.directory,
        snapshot_directory=config.knowledge.snapshot_directory,
    )
    if owned_sink.snapshot_directory is None:
        owned_sink.snapshot_directory = config.knowledge.snapshot_directory.resolve()
        guard_output_outside_snapshot(owned_sink.output_directory, owned_sink.snapshot_directory)
    result = run_lexical_extraction(config, owned_sink)
    publication = finalize_publication(owned_sink, result)
    return result, publication
