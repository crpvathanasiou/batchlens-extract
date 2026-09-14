"""Tests for the application factory."""

import logging

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from app.main import create_app
from app.settings import AppEnvironment, Settings


class IsolatedSettings(Settings):
    """Settings that never load the developer's real `.env` file."""

    model_config = SettingsConfigDict(env_file=None)


def _make_settings(app_env: AppEnvironment = "local", app_version: str = "0.1.0") -> Settings:
    return IsolatedSettings(app_env=app_env, app_version=app_version)


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app(_make_settings())
    assert isinstance(app, FastAPI)
    assert app.title == "BatchLens Extract"


def test_injected_settings_take_effect() -> None:
    app = create_app(_make_settings(app_env="staging", app_version="9.9.9"))
    assert app.version == "9.9.9"

    client = TestClient(app)
    assert client.get("/ready").json() == {
        "status": "ready",
        "environment": "staging",
        "version": "9.9.9",
    }
    assert client.get("/version").json() == {"version": "9.9.9"}


def test_multiple_instances_do_not_share_settings_or_duplicate_routes() -> None:
    app_one = create_app(_make_settings(app_env="dev", app_version="1.0.0"))
    app_two = create_app(_make_settings(app_env="prod", app_version="2.0.0"))

    body_one = TestClient(app_one).get("/ready").json()
    body_two = TestClient(app_two).get("/ready").json()
    assert body_one == {"status": "ready", "environment": "dev", "version": "1.0.0"}
    assert body_two == {"status": "ready", "environment": "prod", "version": "2.0.0"}

    for app in (app_one, app_two):
        paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
        for system_path in ("/health", "/ready", "/version"):
            assert paths.count(system_path) == 1


def test_repeated_create_app_leaves_single_logging_handler() -> None:
    for _ in range(3):
        create_app(_make_settings())
    handlers = logging.getLogger("app").handlers
    assert len(handlers) == 1
