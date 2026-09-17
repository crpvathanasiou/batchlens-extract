"""Explicit production review-service composition for DynamoDB and S3 adapters."""

from threading import BoundedSemaphore
from typing import Any

import boto3

from app.document_conversion.aws import BoundedSdkClient, sdk_config
from app.document_jobs.contracts import JobStore
from app.document_jobs.settings import DocumentSettings
from app.document_review.service import ReviewService
from app.document_review.storage import DynamoReviewStore, S3ObjectStore


def build_review_service(
    settings: DocumentSettings,
    jobs: JobStore,
    *,
    session: Any | None = None,
) -> ReviewService:
    aws: Any = session if session is not None else boto3.Session(region_name=settings.region)
    config = sdk_config(settings.sdk_io_concurrency)
    gate = BoundedSemaphore(settings.sdk_io_concurrency)
    dynamo = aws.client("dynamodb", config=config)
    s3 = aws.client("s3", config=config, endpoint_url=f"https://s3.{settings.region}.amazonaws.com")
    return ReviewService(
        jobs,
        DynamoReviewStore(BoundedSdkClient(dynamo, gate), settings.table),
        S3ObjectStore(BoundedSdkClient(s3, gate), settings),
    )
