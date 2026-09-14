"""System endpoints: liveness, readiness, and version."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.settings import AppEnvironment, Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    environment: AppEnvironment
    version: str


class VersionResponse(BaseModel):
    version: str


def get_current_settings(request: Request) -> Settings:
    # Narrow typed framework boundary: Starlette's State is dynamically typed by
    # design and the application factory is the only writer of app.state.settings.
    return cast(Settings, request.app.state.settings)


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready")
def ready(settings: Annotated[Settings, Depends(get_current_settings)]) -> ReadinessResponse:
    return ReadinessResponse(
        status="ready",
        environment=settings.app_env,
        version=settings.app_version,
    )


@router.get("/version")
def version(settings: Annotated[Settings, Depends(get_current_settings)]) -> VersionResponse:
    return VersionResponse(version=settings.app_version)
