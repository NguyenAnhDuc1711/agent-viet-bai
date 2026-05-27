"""
Shared pytest fixtures for the Blog Writer Agent test suite.

Provides:
- Environment variable setup (autouse)
- Fixture file loaders for recorded API responses
- Mock factory helpers for GeminiClient, SheetsService, GoogleDocsService
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Environment — must be set before any app module import
# ---------------------------------------------------------------------------


@pytest.fixture()
def set_test_env(monkeypatch):
    """Ensure required env vars are present. Not autouse — individual test files
    that already define their own env setup fixture should not be affected."""
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")


# ---------------------------------------------------------------------------
# Fixture file loaders
# ---------------------------------------------------------------------------


@pytest.fixture()
def phase1_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "gemini_phase1_response.json").read_text())


@pytest.fixture()
def phase2_fixture() -> str:
    return (FIXTURES_DIR / "gemini_phase2_response.txt").read_text()


@pytest.fixture()
def phase3_pass_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "gemini_phase3_pass.json").read_text())


@pytest.fixture()
def phase3_fail_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "gemini_phase3_fail.json").read_text())


@pytest.fixture()
def phase4_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "gemini_phase4_response.json").read_text())


@pytest.fixture()
def sheets_row_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "sheets_row_data.json").read_text())


# ---------------------------------------------------------------------------
# Mock service factories
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_gemini_client():
    """A MagicMock standing in for GeminiClient."""
    client = MagicMock()
    client.generate = AsyncMock(return_value="")
    client.generate_json = AsyncMock(return_value={})
    return client


@pytest.fixture()
def mock_sheets_service():
    """A MagicMock standing in for SheetsService."""
    svc = MagicMock()
    svc.update_status = MagicMock()
    svc.update_output_columns = MagicMock()
    svc.update_error = MagicMock()
    svc.check_idempotency = MagicMock(return_value=False)
    svc.detect_stale_rows = MagicMock(return_value=[])
    svc.mark_stale_rows = MagicMock()
    return svc


@pytest.fixture()
def mock_docs_service():
    """A MagicMock standing in for GoogleDocsService."""
    svc = MagicMock()
    svc.create_formatted_doc = AsyncMock(
        return_value="https://docs.google.com/document/d/fixture-doc-id/edit"
    )
    return svc
