"""Explicit SDK composition, called from application lifespan or worker main only."""

from threading import BoundedSemaphore
from typing import Any

import boto3

from app.document_conversion.aws import BoundedSdkClient, TextractAdapter, sdk_config
from app.document_jobs.service import JobService
from app.document_jobs.settings import DocumentSettings
from app.document_jobs.storage import DynamoJobStore, S3ObjectStore, SqsQueue


def build_service(settings: DocumentSettings) -> JobService:
    session: Any = boto3.Session(region_name=settings.region)
    config = sdk_config(settings.sdk_io_concurrency)
    s3 = session.client(
        "s3", config=config, endpoint_url=f"https://s3.{settings.region}.amazonaws.com"
    )
    dynamo = session.client("dynamodb", config=config)
    sqs = session.client("sqs", config=config)
    textract = session.client("textract", config=config)
    gate = BoundedSemaphore(settings.sdk_io_concurrency)
    return JobService(
        DynamoJobStore(BoundedSdkClient(dynamo, gate), settings.table),
        S3ObjectStore(BoundedSdkClient(s3, gate), settings),
        SqsQueue(BoundedSdkClient(sqs, gate), settings.queue_url, settings.dlq_url),
        TextractAdapter(
            BoundedSdkClient(textract, gate),
            settings.region,
            settings.max_blocks,
            settings.max_json_bytes,
        ),
        settings,
    )
