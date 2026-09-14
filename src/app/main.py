"""Application factory and Uvicorn entry point for the FastAPI production starter."""

import logging

from fastapi import FastAPI

from app.api.system import router as system_router
from app.logging_config import configure_logging
from app.settings import Settings, get_settings

logger = logging.getLogger("app.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance.

    Injected settings always win; the cached default provider is consulted only
    when nothing is injected. No network calls, clients, or workers are created.
    """
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)

    app = FastAPI(title="BatchLens Extract", version=resolved.app_version)
    app.state.settings = resolved
    app.include_router(system_router)

    logger.info(
        "application_created service=batchlens-extract environment=%s version=%s",
        resolved.app_env,
        resolved.app_version,
    )
    return app


app = create_app()
