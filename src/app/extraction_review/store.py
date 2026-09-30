"""Local JSON persistence for the Stage 3 current extraction-review state.

Persists only ``current-review.json`` per local lexical job workspace. No revision
history, approval ledgers, SQLite, or version listing.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from app.extraction_review.contracts import (
    ApproveExtractionResultCommand,
    ApproveExtractionResultResult,
    ExtractionReviewState,
    InitializeReviewCommand,
    SaveReviewEditsCommand,
    SaveReviewEditsResult,
    TransitionOutcomeKind,
)
from app.extraction_review.transitions import (
    approve_extraction_result,
    initialize_review_workspace,
    save_review_edits,
)

REVIEWS_DIR_NAME = "extraction-reviews"
CURRENT_REVIEW_FILENAME = "current-review.json"


class ExtractionReviewNotFoundError(FileNotFoundError):
    """No current-review.json exists for the requested local lexical job."""


class ExtractionReviewAlreadyExistsError(FileExistsError):
    """Refuse to overwrite an existing current extraction-review state."""


class ExtractionReviewStore:
    """Single-local-process store for one current ``ExtractionReviewState`` per local job."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser().resolve()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def workspace_key(self, local_job_id: str) -> str:
        return derive_workspace_key(local_job_id)

    def current_path(self, local_job_id: str) -> Path:
        return (
            self._data_dir
            / REVIEWS_DIR_NAME
            / derive_workspace_key(local_job_id)
            / CURRENT_REVIEW_FILENAME
        )

    def create(
        self,
        local_job_id: str,
        command: InitializeReviewCommand,
    ) -> ExtractionReviewState:
        result = initialize_review_workspace(command)
        path = self.current_path(local_job_id)
        if path.is_file():
            raise ExtractionReviewAlreadyExistsError(
                f"extraction review already exists for local_job_id={local_job_id!r}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic_json(path, result.state)
        return result.state

    def load(self, local_job_id: str) -> ExtractionReviewState:
        path = self.current_path(local_job_id)
        if not path.is_file():
            raise ExtractionReviewNotFoundError(
                f"extraction review not found for local_job_id={local_job_id!r}"
            )
        payload = _read_json(path)
        return ExtractionReviewState.model_validate(payload)

    def save_edits(
        self,
        local_job_id: str,
        command: SaveReviewEditsCommand,
        *,
        new_revision_id: str,
    ) -> SaveReviewEditsResult:
        state = self.load(local_job_id)
        outcome = save_review_edits(state, command, new_revision_id=new_revision_id)
        if outcome.outcome is TransitionOutcomeKind.CHANGED:
            assert outcome.state is not None
            _write_atomic_json(self.current_path(local_job_id), outcome.state)
        return outcome

    def approve(
        self,
        local_job_id: str,
        command: ApproveExtractionResultCommand,
    ) -> ApproveExtractionResultResult:
        state = self.load(local_job_id)
        outcome = approve_extraction_result(state, command)
        if outcome.outcome is TransitionOutcomeKind.CHANGED:
            assert outcome.state is not None
            _write_atomic_json(self.current_path(local_job_id), outcome.state)
        return outcome


def derive_workspace_key(local_job_id: str) -> str:
    """Deterministic filesystem-safe SHA-256 hex key from ``local_job_id`` only."""

    if not local_job_id:
        raise ValueError("local_job_id must be non-empty")
    return hashlib.sha256(local_job_id.encode("utf-8")).hexdigest()


def _write_atomic_json(path: Path, state: ExtractionReviewState) -> None:
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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)
