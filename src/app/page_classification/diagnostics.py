"""Bounded local diagnostic bundles for page-classification attempts.

Creates immutable-on-completion troubleshooting artifacts under
``page-classification-diagnostics/<classification-run-id>/``. Not classifier
history, not an approval ledger, and not a generic logging framework.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.page_classification.contracts import (
    CallOutcome,
    ClassifierCallId,
    CompletedPageClassificationResult,
    CurrentClassificationState,
    persist_call_outcome,
)

DIAGNOSTICS_DIR_NAME: Final = "page-classification-diagnostics"
DIAGNOSTIC_SCHEMA_VERSION: Final = "batchlens.page-classification-diagnostics.v1"
MANIFEST_FILENAME: Final = "manifest.json"
_RETENTION_LIMIT: Final = 5
_REPLACE_ATTEMPTS: Final = 12
_REPLACE_INITIAL_DELAY_SECONDS: Final = 0.01
_MAX_SAFE_REASON: Final = 200

_PACKAGE_ROOT: Final = Path(__file__).resolve().parent
_PROMPTS_DIR: Final = _PACKAGE_ROOT / "prompts"
_SCHEMAS_DIR: Final = _PACKAGE_ROOT / "json_schemas"

_PROMPT_ASSETS: Final[tuple[tuple[ClassifierCallId, str, str], ...]] = (
    (1, "01-materials-equipment.txt", "MaterialEquipmentResponse"),
    (2, "02-process-operations-controls.txt", "ProcessOperationsResponse"),
    (3, "03-document-supporting-records.txt", "DocumentSupportingResponse"),
)
_SCHEMA_ASSETS: Final[tuple[tuple[ClassifierCallId, str], ...]] = (
    (1, "01-materials-equipment.schema.json"),
    (2, "02-process-operations-controls.schema.json"),
    (3, "03-document-supporting-records.schema.json"),
)

DiagnosticLifecycleStatus = Literal["running", "completed", "failed", "interrupted"]
_SUPPORTED_MANIFEST_STATUSES: Final[frozenset[str]] = frozenset(
    {"running", "completed", "failed", "interrupted"}
)


class DiagnosticPersistenceError(RuntimeError):
    """Diagnostic bundle could not be written; classification must not claim success."""

    def __init__(self, message: str) -> None:
        super().__init__(_bounded_reason(message))
        self.safe_reason = _bounded_reason(message)


def new_classification_run_id() -> str:
    return str(uuid.uuid4())


def diagnostics_root(data_dir: Path) -> Path:
    return Path(data_dir).expanduser().resolve() / DIAGNOSTICS_DIR_NAME


def bundle_directory(data_dir: Path, classification_run_id: str) -> Path:
    run_id = _require_run_id(classification_run_id)
    root = diagnostics_root(data_dir)
    path = (root / run_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DiagnosticPersistenceError("diagnostic path escapes diagnostic root") from exc
    return path


def page_directory_name(page_number: int) -> str:
    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    return f"page-{page_number:03d}"


class ClassificationDiagnosticSession:
    """One local diagnostic bundle for a single classification attempt."""

    def __init__(
        self,
        data_dir: Path,
        *,
        classification_run_id: str,
        reviewed_html: ReviewedHtmlV1Input,
        total_pages: int,
        effective_settings: Mapping[str, Any],
        clock: Any,
    ) -> None:
        self._data_dir = Path(data_dir).expanduser().resolve()
        self.classification_run_id = _require_run_id(classification_run_id)
        self._reviewed_html = reviewed_html
        self._total_pages = total_pages
        self._settings = dict(effective_settings)
        self._clock = clock
        self._root = diagnostics_root(self._data_dir)
        self._bundle = bundle_directory(self._data_dir, self.classification_run_id)
        self._asset_hashes: dict[str, str] = {}
        self._page_inventory: list[dict[str, Any]] = []
        self._created_at = self._clock()
        self._status: DiagnosticLifecycleStatus = "running"
        self._terminal_reason: str | None = None
        self._finished_at: datetime | None = None
        self._completed_pages = 0
        self._current_page_number: int | None = 1 if total_pages > 0 else None

    @property
    def bundle_path(self) -> Path:
        return self._bundle

    def initialize(self) -> None:
        """Create the bundle, copy locked assets, and write the running manifest."""

        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._bundle.mkdir(parents=False, exist_ok=False)
            prompts_dir = self._bundle / "assets" / "prompts"
            schemas_dir = self._bundle / "assets" / "schemas"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            schemas_dir.mkdir(parents=True, exist_ok=True)
            for _call_id, filename, _schema_name in _PROMPT_ASSETS:
                source = _PROMPTS_DIR / filename
                destination = prompts_dir / filename
                shutil.copyfile(source, destination)
                self._asset_hashes[f"prompts/{filename}"] = _sha256_file(destination)
            for _call_id, filename in _SCHEMA_ASSETS:
                source = _SCHEMAS_DIR / filename
                destination = schemas_dir / filename
                shutil.copyfile(source, destination)
                self._asset_hashes[f"schemas/{filename}"] = _sha256_file(destination)
            self._write_manifest()
            prune_diagnostic_bundles(
                self._data_dir,
                keep=_RETENTION_LIMIT,
                protect_run_id=self.classification_run_id,
            )
        except DiagnosticPersistenceError:
            self._cleanup_failed_init()
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed before any LLM call
            self._cleanup_failed_init()
            raise DiagnosticPersistenceError(
                "page classification diagnostic bundle could not be created"
            ) from exc

    def write_call_request(
        self,
        *,
        page_number: int,
        page_html_id: str,
        call_id: ClassifierCallId,
        system_prompt: str,
        page_html_fragment: str,
        response_schema_name: str,
    ) -> None:
        prompt_name = _PROMPT_ASSETS[call_id - 1][1]
        schema_name = _SCHEMA_ASSETS[call_id - 1][1]
        record = {
            "classification_run_id": self.classification_run_id,
            "page_number": page_number,
            "page_html_id": page_html_id,
            "call_id": call_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": page_html_fragment},
            ],
            "response_schema_name": response_schema_name,
            "response_schema_sha256": self._asset_hashes[f"schemas/{schema_name}"],
            "prompt_artifact": f"assets/prompts/{prompt_name}",
            "prompt_sha256": self._asset_hashes[f"prompts/{prompt_name}"],
            "schema_artifact": f"assets/schemas/{schema_name}",
            "model": self._settings["model"],
            "temperature": self._settings["temperature"],
            "timeout_seconds": self._settings["timeout_seconds"],
            "max_retries": self._settings["max_retries"],
            "max_output_tokens": self._settings["max_output_tokens"],
            "output_token_limit_configured": self._settings["output_token_limit_configured"],
        }
        path = self._page_dir(page_number) / f"call-{call_id}-request.json"
        self._write_json(path, record)

    def write_call_response_success(
        self,
        *,
        page_number: int,
        call_id: ClassifierCallId,
        model_name: str,
        raw_text: str,
        parsed_payload: dict[str, Any] | None,
        attempts: int,
        latency_ms: float,
        outcome: CallOutcome,
    ) -> None:
        record = {
            "classification_run_id": self.classification_run_id,
            "page_number": page_number,
            "call_id": call_id,
            "model_name": model_name,
            "raw_text": raw_text,
            "parsed": parsed_payload,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "call_outcome": persist_call_outcome(outcome).model_dump(mode="json"),
        }
        path = self._page_dir(page_number) / f"call-{call_id}-response.json"
        self._write_json(path, record)

    def write_call_response_failure(
        self,
        *,
        page_number: int,
        call_id: ClassifierCallId,
        error_code: str,
        error_message: str,
        outcome: CallOutcome,
        parse_diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "classification_run_id": self.classification_run_id,
            "page_number": page_number,
            "call_id": call_id,
            "error": {
                "code": error_code,
                "message": _bounded_reason(error_message),
            },
            "call_outcome": persist_call_outcome(outcome).model_dump(mode="json"),
        }
        if parse_diagnostics is not None:
            record["model_name"] = parse_diagnostics.get("model_name")
            record["raw_text"] = parse_diagnostics.get("raw_text")
            record["refusal_text"] = parse_diagnostics.get("refusal_text")
            record["attempts"] = parse_diagnostics.get("attempts")
            record["latency_ms"] = parse_diagnostics.get("latency_ms")
            record["structured_output_error"] = parse_diagnostics.get("structured_output_error")
        path = self._page_dir(page_number) / f"call-{call_id}-response.json"
        self._write_json(path, record)

    def write_page_result(self, result: CompletedPageClassificationResult) -> None:
        page_number = result.binding.page_number
        path = self._page_dir(page_number) / "result.json"
        self._write_json(path, result.model_dump(mode="json"))
        self._completed_pages += 1
        self._current_page_number = None
        self._page_inventory.append(
            {
                "page_number": page_number,
                "page_html_id": result.binding.page_html_id,
                "kind": result.kind,
                "requires_review": result.requires_review,
                "eligible_for_extraction": result.eligibility.eligible_for_extraction,
            }
        )
        self._write_manifest()

    def mark_page_progress(self, *, current_page_number: int | None, completed_pages: int) -> None:
        self._current_page_number = current_page_number
        self._completed_pages = completed_pages
        self._write_manifest()

    def finalize(
        self,
        status: DiagnosticLifecycleStatus,
        *,
        terminal_reason: str | None = None,
        completed_pages: int | None = None,
    ) -> None:
        if status == "running":
            raise ValueError("cannot finalize diagnostic bundle as running")
        if self._status == status:
            return
        # Allow compensation completed -> failed when the completed current-state
        # save fails after a successful completed-manifest write.
        if self._status != "running" and not (self._status == "completed" and status == "failed"):
            return

        previous_status = self._status
        previous_finished_at = self._finished_at
        previous_current_page = self._current_page_number
        previous_completed_pages = self._completed_pages
        previous_terminal_reason = self._terminal_reason

        self._status = status
        self._finished_at = self._clock()
        self._current_page_number = None
        if completed_pages is not None:
            self._completed_pages = completed_pages
        if terminal_reason is None:
            self._terminal_reason = None
        else:
            self._terminal_reason = _bounded_reason(terminal_reason)

        try:
            self._write_manifest()
        except DiagnosticPersistenceError:
            # Revert in-memory lifecycle so a later failure finalize remains possible
            # when the completed-manifest write itself failed.
            self._status = previous_status
            self._finished_at = previous_finished_at
            self._current_page_number = previous_current_page
            self._completed_pages = previous_completed_pages
            self._terminal_reason = previous_terminal_reason
            raise

        prune_diagnostic_bundles(
            self._data_dir,
            keep=_RETENTION_LIMIT,
            protect_run_id=None,
        )

    def _page_dir(self, page_number: int) -> Path:
        path = self._bundle / "pages" / page_directory_name(page_number)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_manifest(self) -> None:
        payload = {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "classification_run_id": self.classification_run_id,
            "status": self._status,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._clock().isoformat(),
            "finished_at": None if self._finished_at is None else self._finished_at.isoformat(),
            "terminal_reason": self._terminal_reason,
            "reviewed_html": self._reviewed_html.model_dump(mode="json"),
            "html_sha256": self._reviewed_html.html_sha256,
            "progress": {
                "total_pages": self._total_pages,
                "completed_pages": self._completed_pages,
                "current_page_number": self._current_page_number,
            },
            "effective_settings": {
                "model": self._settings["model"],
                "temperature": self._settings["temperature"],
                "timeout_seconds": self._settings["timeout_seconds"],
                "max_retries": self._settings["max_retries"],
                "max_output_tokens": self._settings["max_output_tokens"],
                "output_token_limit_configured": self._settings["output_token_limit_configured"],
            },
            "asset_sha256": dict(self._asset_hashes),
            "pages": list(self._page_inventory),
        }
        self._write_json(self._bundle / MANIFEST_FILENAME, payload)

    def _write_json(self, path: Path, payload: Mapping[str, Any] | dict[str, Any]) -> None:
        try:
            _write_atomic_json(path, dict(payload))
        except Exception as exc:  # noqa: BLE001 - surface as safe diagnostic failure
            raise DiagnosticPersistenceError(
                "page classification diagnostic artifact could not be written"
            ) from exc

    def _cleanup_failed_init(self) -> None:
        if self._bundle.exists():
            shutil.rmtree(self._bundle, ignore_errors=True)


def effective_wrapper_settings(wrapper: Any) -> dict[str, Any]:
    """Capture non-secret effective classifier settings from the injected wrapper."""

    model = getattr(wrapper, "default_model", None)
    if not isinstance(model, str) or not model.strip():
        model = "unknown"
    temperature = getattr(wrapper, "default_temperature", 0.0)
    timeout_seconds = getattr(wrapper, "timeout_seconds", 20.0)
    max_retries = getattr(wrapper, "max_retries", 2)
    # PageClassificationRunner does not pass an output-token limit to generate_structured.
    return {
        "model": model,
        "temperature": float(temperature),
        "timeout_seconds": float(timeout_seconds),
        "max_retries": int(max_retries),
        "max_output_tokens": None,
        "output_token_limit_configured": False,
    }


def begin_classification_diagnostics(
    data_dir: Path,
    *,
    classification_run_id: str,
    reviewed_html: ReviewedHtmlV1Input,
    total_pages: int,
    wrapper: Any,
    clock: Any | None = None,
) -> ClassificationDiagnosticSession:
    session = ClassificationDiagnosticSession(
        data_dir,
        classification_run_id=classification_run_id,
        reviewed_html=reviewed_html,
        total_pages=total_pages,
        effective_settings=effective_wrapper_settings(wrapper),
        clock=clock or _utc_now,
    )
    session.initialize()
    return session


def finalize_matching_interrupted_bundle(
    data_dir: Path,
    state: CurrentClassificationState,
    *,
    clock: Any | None = None,
) -> None:
    """Mark a matching running diagnostic bundle interrupted when recovery runs."""

    run_id = state.classification_run_id
    if run_id is None:
        return
    canonical_run_id = _try_canonical_run_id(run_id)
    if canonical_run_id is None:
        return
    root = diagnostics_root(data_dir).resolve()
    bundle_path = (root / canonical_run_id).resolve()
    try:
        bundle_path.relative_to(root)
    except ValueError:
        return
    path = bundle_path / MANIFEST_FILENAME
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not _manifest_identifies_bundle(payload, bundle_path.name):
        return
    if payload.get("status") != "running":
        return
    now = (clock or _utc_now)()
    payload["status"] = "interrupted"
    payload["updated_at"] = now.isoformat()
    payload["finished_at"] = now.isoformat()
    payload["terminal_reason"] = state.terminal_reason or (
        "page classification was interrupted by service restart"
    )
    progress = payload.get("progress")
    if isinstance(progress, dict):
        progress["current_page_number"] = None
    try:
        _write_atomic_json(path, payload)
    except Exception:  # noqa: BLE001 - recovery remains best-effort for diagnostics
        return
    prune_diagnostic_bundles(data_dir, keep=_RETENTION_LIMIT, protect_run_id=None)


def prune_diagnostic_bundles(
    data_dir: Path,
    *,
    keep: int = _RETENTION_LIMIT,
    protect_run_id: str | None,
) -> None:
    """Retain the newest ``keep`` valid bundles; never delete non-bundle directories."""

    root = diagnostics_root(data_dir)
    if not root.is_dir():
        return
    root = root.resolve()
    entries: list[tuple[datetime, str, Path]] = []
    for child in root.iterdir():
        entry = _valid_bundle_entry(child, root)
        if entry is not None:
            entries.append(entry)
    if len(entries) <= keep:
        return
    entries.sort(key=lambda item: (item[0], item[1]), reverse=True)
    protected = None if protect_run_id is None else _try_canonical_run_id(protect_run_id)
    retained: list[Path] = []
    if protected is not None:
        for _created, name, path in entries:
            if name == protected:
                retained.append(path)
                break
    for _created, _name, path in entries:
        if path in retained:
            continue
        if len(retained) >= keep:
            break
        retained.append(path)
    retained_set = {path for path in retained}
    for _created, name, path in entries:
        if path in retained_set:
            continue
        if protected is not None and name == protected:
            continue
        shutil.rmtree(path, ignore_errors=True)


def _try_canonical_run_id(value: str) -> str | None:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError):
        return None
    canonical = str(parsed)
    if canonical != value:
        return None
    return canonical


def _manifest_identifies_bundle(payload: Mapping[str, Any], directory_name: str) -> bool:
    if payload.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION:
        return False
    run_id = payload.get("classification_run_id")
    if not isinstance(run_id, str) or run_id != directory_name:
        return False
    status = payload.get("status")
    if not isinstance(status, str) or status not in _SUPPORTED_MANIFEST_STATUSES:
        return False
    return True


def _valid_bundle_entry(child: Path, root: Path) -> tuple[datetime, str, Path] | None:
    if not child.is_dir() or child.name.startswith("."):
        return None
    if child.is_symlink():
        return None
    canonical_id = _try_canonical_run_id(child.name)
    if canonical_id is None:
        return None
    try:
        resolved = child.resolve()
        resolved.relative_to(root)
    except ValueError:
        return None
    manifest_path = resolved / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not _manifest_identifies_bundle(cast(Mapping[str, Any], payload), canonical_id):
        return None
    return (_bundle_sort_key(manifest_path, resolved), canonical_id, resolved)


def _bundle_sort_key(manifest_path: Path, directory: Path) -> datetime:
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key in ("finished_at", "updated_at", "created_at"):
                raw = payload.get(key)
                if isinstance(raw, str) and raw:
                    return datetime.fromisoformat(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)


def _require_run_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticPersistenceError("classification_run_id must be a UUID") from exc
    return str(parsed)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    body = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_atomic(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_atomic(temporary: Path, path: Path) -> None:
    delay = _REPLACE_INITIAL_DELAY_SECONDS
    last_error: PermissionError | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                break
            import time

            time.sleep(delay)
            delay = min(delay * 2, 0.25)
    assert last_error is not None
    raise last_error


def _bounded_reason(message: str) -> str:
    if 1 <= len(message) <= _MAX_SAFE_REASON:
        return message
    if not message:
        return "page classification diagnostic persistence failed"
    return message[: _MAX_SAFE_REASON - 3] + "..."


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)
