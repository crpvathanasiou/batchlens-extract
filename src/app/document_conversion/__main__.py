"""Offline conversion and explicit submit/resume CLI. No hidden output/cache directories."""

import argparse
import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from app.document_conversion import Source
from app.document_conversion.adapter import (
    convert_and_render,
    render_full_document_html,
    render_individual_pages,
)
from app.document_conversion.aws import (
    JobHandle,
    S3Source,
    TextractAdapter,
    WaitTimeout,
    sdk_config,
)
from app.document_conversion.aws import stage_pdf as upload_pdf


def write_outputs(raw: object, source: Source, output: Path) -> None:
    """Convert raw Textract response and write document.json, document.html,
    and page-NNNN.html artifacts into the output directory.

    Single-threaded; no parallel page processing.
    """
    result = convert_and_render(raw, source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "document.json").write_text(
        result.document.model_dump_json(indent=2), encoding="utf-8"
    )
    (output / "document.html").write_text(render_full_document_html(result), encoding="utf-8")
    for page_number, html_page in render_individual_pages(result).items():
        (output / f"page-{page_number:04d}.html").write_text(html_page, encoding="utf-8")


def save_handle(path: Path, handle: JobHandle) -> None:
    """Replace a checkpoint atomically; leave the old complete intent on interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            f.write(handle.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    offline = commands.add_parser("offline")
    offline.add_argument("response", type=Path)
    offline.add_argument("--output", type=Path, required=True)
    offline.add_argument("--source-id", default="saved-textract-response")
    # --page-workers is accepted for CLI compatibility but ignored; the
    # Textractor adapter renders pages single-threaded.
    offline.add_argument("--page-workers", type=int, default=1)
    submit = commands.add_parser("submit")
    submit.add_argument("--region", required=True)
    submit.add_argument("--bucket", required=True)
    choice = submit.add_mutually_exclusive_group(required=True)
    choice.add_argument("--pdf", type=Path)
    choice.add_argument("--key")
    submit.add_argument("--version")
    submit.add_argument("--prefix", default="document-cli")
    submit.add_argument("--kms-key-id")
    submit.add_argument("--request-token", default=None)
    submit.add_argument("--handle", type=Path, required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("--handle", type=Path, required=True)
    resume.add_argument("--output", type=Path, required=True)
    resume.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args()
    if args.command == "offline":
        write_outputs(
            json.loads(args.response.read_text(encoding="utf-8")),
            Source(identity=args.source_id),
            args.output,
        )
        return
    import boto3

    if args.command == "submit":
        # Refuse to overwrite an existing handle/intent; use resume instead.
        if args.handle.exists():
            parser.error("Handle already exists; use resume.")
        session: Any = boto3.Session(region_name=args.region)
        if args.pdf:
            s3 = session.client(
                "s3", config=sdk_config(), endpoint_url=f"https://s3.{args.region}.amazonaws.com"
            )
            source = upload_pdf(
                s3,
                args.pdf,
                args.bucket,
                args.prefix,
                args.region,
                encryption="aws:kms" if args.kms_key_id else "AES256",
                kms_key_id=args.kms_key_id,
            )
        else:
            source = S3Source(
                bucket=args.bucket, key=args.key, version=args.version, region=args.region
            )
        intent = JobHandle(
            job_id="pending",
            submitted_at=int(time.time()),
            source=source,
            request_token=args.request_token or uuid4().hex,
        )
        args.handle.parent.mkdir(parents=True, exist_ok=True)
        save_handle(args.handle, intent)
        adapter = TextractAdapter(session.client("textract", config=sdk_config()), args.region)
        handle = adapter.submit(source, intent.request_token)
        save_handle(args.handle, handle)
        print("Submitted. Handle saved; use resume to collect.")
    else:
        handle = JobHandle.model_validate_json(args.handle.read_text(encoding="utf-8"))
        if not handle.submitted_at or time.time() - handle.submitted_at > 6 * 86400:
            parser.error(
                "Handle is too old for safe resume. Review provider state before a new job."
            )
        session = boto3.Session(region_name=handle.source.region)
        adapter = TextractAdapter(
            session.client("textract", config=sdk_config()), handle.source.region
        )
        if handle.job_id == "pending":
            handle = adapter.submit(handle.source, handle.request_token)
            save_handle(args.handle, handle)
        try:
            result = adapter.wait_collect(handle, timeout_seconds=args.timeout_seconds)
        except WaitTimeout:
            print("Still running. Handle retained; run resume again.")
            return
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "textract.json").write_text(
            json.dumps(result.raw, ensure_ascii=False), encoding="utf-8"
        )
        write_outputs(result.raw, handle.source.document_source(), args.output)
        print("Collected raw JSON, structured document and HTML.")


if __name__ == "__main__":
    main()
