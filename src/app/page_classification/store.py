"""Local JSON persistence for the current page-classification state.

Persists only ``current-classification.json`` per reviewed-HTML identity.
No classification history, approval records, or generic job ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from pydantic import ValidationError

from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.page_classification.contracts import CurrentClassificationState

CLASSIFICATIONS_DIR_NAME = "page-classifications"
CURRENT_CLASSIFICATION_FILENAME = "current-classification.json"
_REPLACE_ATTEMPTS = 12
_REPLACE_INITIAL_DELAY_SECONDS = 0.01


class PageClassificationStoreError(ValueError):
    """Fail-closed persistence or binding error for current classification state."""


class PageClassificationStore:
    """Single-local-process store for one current classification per reviewed HTML."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser().resolve()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def identity_key(self, reviewed_html: ReviewedHtmlV1Input) -> str:
        return derive_reviewed_html_identity_key(reviewed_html)

    def current_path(self, reviewed_html: ReviewedHtmlV1Input) -> Path:
        return (
            self._data_dir
            / CLASSIFICATIONS_DIR_NAME
            / derive_reviewed_html_identity_key(reviewed_html)
            / CURRENT_CLASSIFICATION_FILENAME
        )

    def save(self, state: CurrentClassificationState) -> CurrentClassificationState:
        """Atomically write the current classification state for its reviewed HTML."""

        path = self.current_path(state.reviewed_html)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic_json(path, state)
        return state

    def load(
        self,
        reviewed_html: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState | None:
        """Return the current state for ``reviewed_html``, or ``None`` if absent.

        Malformed JSON and binding mismatches fail closed.
        """

        path = self.current_path(reviewed_html)
        if not path.is_file():
            return None
        payload = _read_json(path)
        try:
            state = CurrentClassificationState.model_validate(payload)
        except ValidationError as exc:
            raise PageClassificationStoreError(
                "current classification state is malformed or unknown"
            ) from exc
        if state.reviewed_html != reviewed_html:
            raise PageClassificationStoreError(
                "persisted classification binding does not match the requested reviewed HTML"
            )
        return state

    def iter_current_paths(self) -> list[Path]:
        """Return existing current-classification.json paths under the data directory."""

        root = self._data_dir / CLASSIFICATIONS_DIR_NAME
        if not root.is_dir():
            return []
        paths: list[Path] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            candidate = child / CURRENT_CLASSIFICATION_FILENAME
            if candidate.is_file():
                paths.append(candidate)
        return paths

    def load_path(self, path: Path) -> CurrentClassificationState:
        """Validate and load one current-classification.json path."""

        payload = _read_json(path)
        try:
            return CurrentClassificationState.model_validate(payload)
        except ValidationError as exc:
            raise PageClassificationStoreError(
                "current classification state is malformed or unknown"
            ) from exc


def derive_reviewed_html_identity_key(reviewed_html: ReviewedHtmlV1Input) -> str:
    """Deterministic filesystem-safe SHA-256 key from the full reviewed-HTML binding.

    Canonical JSON includes every ``ReviewedHtmlV1Input`` field, including
    ``html_sha256``. The digest is local to this store and is not a generic
    identity framework.
    """

    payload = reviewed_html.model_dump(mode="json")
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def canonical_classification_snapshot_bytes(state: CurrentClassificationState) -> bytes:
    """UTF-8 canonical JSON bytes for one current classification state snapshot."""

    payload = state.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def classification_snapshot_sha256(state: CurrentClassificationState) -> str:
    """Lower-case SHA-256 of the canonical classification snapshot bytes."""

    return hashlib.sha256(canonical_classification_snapshot_bytes(state)).hexdigest()


def _write_atomic_json(path: Path, state: CurrentClassificationState) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    payload = state.model_dump(mode="json")
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
    """Replace ``path`` with ``temporary``, retrying Windows sharing violations."""

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
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
    assert last_error is not None
    raise last_error


def _read_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise PageClassificationStoreError(
            "current classification state is malformed or unknown"
        ) from exc
