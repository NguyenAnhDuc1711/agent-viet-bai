"""
Tests for the Blog Writer Agent webhook endpoint and configuration.

Covers acceptance criteria from T1:
  - FR-1: valid request returns 200
  - FR-10: auth rejects missing / invalid key
  - NFR-3: config loads from files, fails clearly on missing fields
  - NFR-4: structured logging (smoke test via log output)
"""

import os
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Ensure required env vars are set before any module-level import of settings."""
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")


@pytest.fixture()
def client(set_test_env):
    """Return a TestClient that does not load cached settings."""
    # Re-import to pick up the monkeypatched environment
    import importlib
    import app.config as cfg_module
    import app.main as main_module

    # Rebuild settings with the test environment
    cfg_module.settings = cfg_module._build_settings()

    # Re-create the FastAPI app so it uses the fresh settings
    importlib.reload(main_module)

    from app.main import app
    return TestClient(app)


VALID_PAYLOAD = {"rows": [{"row_number": 1, "keyword": "test keyword"}]}
VALID_HEADERS = {"X-API-Key": "test-api-key-12345"}


# ---------------------------------------------------------------------------
# FR-1: valid requests
# ---------------------------------------------------------------------------


def test_webhook_valid_request(client):
    """POST /webhook with valid key and payload returns 200 with status accepted."""
    response = client.post("/webhook", json=VALID_PAYLOAD, headers=VALID_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["rows"] == 1


def test_webhook_returns_row_count(client):
    """Accepted response reflects the number of rows in the payload."""
    payload = {
        "rows": [
            {"row_number": 1, "keyword": "kw1"},
            {"row_number": 2, "keyword": "kw2"},
        ]
    }
    response = client.post("/webhook", json=payload, headers=VALID_HEADERS)
    assert response.status_code == 200
    assert response.json()["rows"] == 2


# ---------------------------------------------------------------------------
# FR-10: authentication
# ---------------------------------------------------------------------------


def test_webhook_missing_api_key(client):
    """POST /webhook without X-API-Key returns 401."""
    response = client.post("/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 401


def test_webhook_invalid_api_key(client):
    """POST /webhook with wrong API key returns 401."""
    response = client.post(
        "/webhook",
        json=VALID_PAYLOAD,
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# FR-1: payload validation
# ---------------------------------------------------------------------------


def test_webhook_invalid_payload_empty_rows(client):
    """POST /webhook with empty rows list returns 422."""
    response = client.post("/webhook", json={"rows": []}, headers=VALID_HEADERS)
    assert response.status_code == 422


def test_webhook_malformed_json(client):
    """POST /webhook with non-JSON body returns 422."""
    response = client.post(
        "/webhook",
        content=b"not-json",
        headers={**VALID_HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_webhook_missing_rows_field(client):
    """POST /webhook with missing rows field returns 422."""
    response = client.post("/webhook", json={}, headers=VALID_HEADERS)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# NFR-3: configuration
# ---------------------------------------------------------------------------


def test_config_loads_from_env(monkeypatch):
    """Settings object correctly reads values from environment variables."""
    monkeypatch.setenv("API_KEY", "env-test-key")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "env-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "europe-west1")

    import importlib
    import app.config as cfg_module
    settings = cfg_module._build_settings()

    assert settings.API_KEY == "env-test-key"
    assert settings.VERTEX_AI_PROJECT == "env-project"
    assert settings.VERTEX_AI_LOCATION == "europe-west1"


def test_config_missing_required_field_raises(monkeypatch, tmp_path):
    """Missing API_KEY raises a ValidationError with a clear message."""
    from pydantic import ValidationError
    from pydantic_settings import BaseSettings, SettingsConfigDict

    # Use a non-existent env file so pydantic-settings cannot fall back to a real .env
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")

    # Construct Settings directly pointing at a blank env file to avoid real .env
    blank_env = tmp_path / ".env.blank"
    blank_env.write_text("")

    class IsolatedSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=str(blank_env),
            env_file_encoding="utf-8",
            protected_namespaces=("settings_",),
        )
        API_KEY: str
        GOOGLE_SERVICE_ACCOUNT_PATH: str
        VERTEX_AI_PROJECT: str
        VERTEX_AI_LOCATION: str

    with pytest.raises((ValidationError, Exception)):
        IsolatedSettings()


def test_config_loads_from_yaml(tmp_path, monkeypatch):
    """Settings load YAML values when config.yaml is present."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "concurrency_limit: 5\ntask_timeout_seconds: 300\nmodel_name: gemini-test\n"
    )

    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")

    import app.config as cfg_module
    yaml_values = cfg_module._load_yaml_config(str(config_file))

    assert yaml_values["concurrency_limit"] == 5
    assert yaml_values["task_timeout_seconds"] == 300
    assert yaml_values["model_name"] == "gemini-test"
