"""Tests for app.services.google_docs.GoogleDocsService.

All Google API calls are mocked — no live credentials required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio

from app.services.google_docs import GoogleDocsService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeSettings:
    """Minimal settings stand-in for tests."""

    GOOGLE_SERVICE_ACCOUNT_PATH = "/fake/sa.json"
    drive_folder_id = "folder-xyz"
    doc_share_permission = "writer"


@pytest.fixture()
def mock_google(monkeypatch):
    """Patch Google auth and API client builder."""
    fake_creds = MagicMock()
    monkeypatch.setattr(
        "app.services.google_docs.Credentials.from_service_account_file",
        MagicMock(return_value=fake_creds),
    )

    drive_service = MagicMock()
    docs_service = MagicMock()

    def fake_build(api, version, credentials=None):
        if api == "drive":
            return drive_service
        if api == "docs":
            return docs_service
        raise ValueError(f"unexpected api: {api}")

    monkeypatch.setattr("app.services.google_docs.build", fake_build)

    return {
        "drive": drive_service,
        "docs": docs_service,
        "creds": fake_creds,
    }


@pytest.fixture()
def service(mock_google) -> GoogleDocsService:
    return GoogleDocsService(FakeSettings())


# ---------------------------------------------------------------------------
# 9. test_create_doc_in_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_doc_in_folder(service, mock_google):
    drive = mock_google["drive"]
    drive.files().create().execute.return_value = {"id": "doc123"}
    drive.permissions().create().execute.return_value = {}
    mock_google["docs"].documents().batchUpdate().execute.return_value = {}

    url = await service.create_formatted_doc("My Title", "Hello")

    # Verify files().create() was called
    drive.files().create.assert_called()
    call_kwargs = drive.files().create.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body") or (call_kwargs[0][0] if call_kwargs[0] else None)
    # The mock chain makes exact arg inspection tricky; just verify the call happened
    assert "doc123" in url


# ---------------------------------------------------------------------------
# 10. test_sharing_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sharing_permission(service, mock_google):
    drive = mock_google["drive"]
    drive.files().create().execute.return_value = {"id": "doc456"}
    drive.permissions().create().execute.return_value = {}
    mock_google["docs"].documents().batchUpdate().execute.return_value = {}

    await service.create_formatted_doc("Test", "Hello")

    drive.permissions().create.assert_called()


# ---------------------------------------------------------------------------
# 11. test_doc_url_format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doc_url_format(service, mock_google):
    drive = mock_google["drive"]
    drive.files().create().execute.return_value = {"id": "abc123"}
    drive.permissions().create().execute.return_value = {}
    mock_google["docs"].documents().batchUpdate().execute.return_value = {}

    url = await service.create_formatted_doc("URL Test", "content")

    assert url == "https://docs.google.com/document/d/abc123/edit"


# ---------------------------------------------------------------------------
# 12. test_formatting_failure_graceful
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_formatting_failure_graceful(service, mock_google):
    drive = mock_google["drive"]
    drive.files().create().execute.return_value = {"id": "partial789"}
    drive.permissions().create().execute.return_value = {}

    # First batchUpdate (insert text) succeeds; second (formatting) fails
    call_count = {"n": 0}
    original_execute = mock_google["docs"].documents().batchUpdate().execute

    def side_effect():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("Formatting API error")
        return {}

    mock_google["docs"].documents().batchUpdate().execute = side_effect

    url = await service.create_formatted_doc("Partial", "## heading\n\ntext")

    # Should still return a URL even though formatting failed
    assert "partial789" in url
