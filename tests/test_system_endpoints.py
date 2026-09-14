"""Contract tests for the /health, /ready, and /version system endpoints."""

from fastapi.testclient import TestClient
from pydantic_settings import SettingsConfigDict

from app.main import create_app
from app.settings import AppEnvironment, Settings


class IsolatedSettings(Settings):
    """Settings that never load the developer's real `.env` file."""

    model_config = SettingsConfigDict(env_file=None)


def _client(app_env: AppEnvironment = "local", app_version: str = "0.1.0") -> TestClient:
    settings = IsolatedSettings(app_env=app_env, app_version=app_version)
    return TestClient(create_app(settings))


def test_health_contract() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_contract() -> None:
    response = _client(app_env="staging", app_version="7.7.7").get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "environment": "staging", "version": "7.7.7"}


def test_version_contract() -> None:
    response = _client(app_version="4.5.6").get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "4.5.6"}
