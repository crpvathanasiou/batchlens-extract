"""Application factory and Uvicorn entry point for the FastAPI production starter."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.system import router as system_router
from app.logging_config import configure_logging
from app.settings import Settings, get_settings

logger = logging.getLogger("app.main")


class DocumentHeaders:
    """No-store and browser isolation for feature endpoints, without changing system routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(("/documents", "/api/v1/documents")):
            await self.app(scope, receive, send)
            return

        async def headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; "
                        b"style-src 'self'; connect-src 'self' https://*.amazonaws.com; "
                        b"worker-src 'self'; img-src 'self' data:; font-src 'self'; "
                        b"frame-ancestors 'none'; object-src 'none'; "
                        b"base-uri 'none'; form-action 'self'",
                    ),
                ]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance.

    Injected settings always win; the cached default provider is consulted only
    when nothing is injected. No network calls, clients, or workers are created.
    """
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if resolved.document_conversion_enabled:
            from app.document_jobs.auth import CognitoAuth
            from app.document_jobs.composition import build_service
            from app.document_jobs.settings import load_document_settings
            from app.document_review.composition import build_review_service

            feature = load_document_settings()
            app.state.document_settings = feature
            app.state.document_service = await run_in_threadpool(build_service, feature)
            app.state.document_review_service = await run_in_threadpool(
                build_review_service, feature, app.state.document_service.store
            )
            app.state.document_auth = CognitoAuth(
                feature.region,
                feature.cognito_pool_id,
                feature.cognito_client_id,
            )
        yield

    app = FastAPI(title="BatchLens Extract", version=resolved.app_version, lifespan=lifespan)
    app.state.settings = resolved
    app.include_router(system_router)
    if resolved.document_conversion_enabled:
        from app.api.document_reviews import install_errors as install_review_errors
        from app.api.document_reviews import router as document_review_router
        from app.api.documents import install_errors
        from app.api.documents import router as document_router

        app.include_router(document_router)
        app.include_router(document_review_router)
        install_errors(app)
        install_review_errors(app)
        app.add_middleware(DocumentHeaders)

    logger.info(
        "application_created service=batchlens-extract environment=%s version=%s",
        resolved.app_env,
        resolved.app_version,
    )
    return app


app = create_app()
