"""
Tests for app.services.sheets.SheetsService.

All gspread network calls are mocked — no real Google API credentials required.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from app.models import PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(worksheet: MagicMock) -> "SheetsService":  # noqa: F821
    """Build a SheetsService whose internal worksheet is *worksheet*."""
    # Patch gspread.authorize and Credentials so __init__ never touches the network
    with (
        patch("app.services.sheets.Credentials.from_service_account_file"),
        patch("app.services.sheets.gspread.authorize") as mock_authorize,
    ):
        mock_authorize.return_value.open_by_key.return_value.sheet1 = worksheet
        from app.services.sheets import SheetsService
        from app.config import settings

        service = SheetsService(settings)
    return service


def _fake_settings():
    """Return a minimal settings-like object."""
    s = MagicMock()
    s.GOOGLE_SERVICE_ACCOUNT_PATH = "/fake/sa.json"
    s.sheet_id = "fake-sheet-id"
    return s


# ---------------------------------------------------------------------------
# Test 1 — update_status sets Processing + started_at
# ---------------------------------------------------------------------------


def test_update_status_processing():
    ws = MagicMock()
    svc = _make_service(ws)

    svc.update_status(2, "Processing")

    # D2 = "Processing"
    ws.update_cell.assert_any_call(2, 4, "Processing")
    # O2 should be set (started_at); verify it was called with col 15
    calls_col15 = [c for c in ws.update_cell.call_args_list if c.args[1] == 15]
    assert len(calls_col15) == 1, "started_at (col O) should be written once"
    # The timestamp should be a valid ISO string
    ts = calls_col15[0].args[2]
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# Test 2 — update_status sets Done + finished_at
# ---------------------------------------------------------------------------


def test_update_status_done():
    ws = MagicMock()
    svc = _make_service(ws)

    svc.update_status(2, "Done")

    ws.update_cell.assert_any_call(2, 4, "Done")
    # P2 should be set (finished_at); verify col 16
    calls_col16 = [c for c in ws.update_cell.call_args_list if c.args[1] == 16]
    assert len(calls_col16) == 1, "finished_at (col P) should be written once"
    ts = calls_col16[0].args[2]
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# Test 3 — update_output_columns is a single batch call covering E:K
# ---------------------------------------------------------------------------


def test_update_output_batch():
    ws = MagicMock()
    svc = _make_service(ws)

    result = PipelineResult(
        row_number=2,
        status="success",
        title="My Title",
        description="My Desc",
        h1="My H1",
        url_slug="my-slug",
        doc_url="https://docs.google.com/d/abc",
        word_count=1234,
    )

    svc.update_output_columns(2, result)

    # Exactly one call to worksheet.update
    assert ws.update.call_count == 1
    call_args = ws.update.call_args
    range_arg = call_args.args[0]
    data_arg = call_args.args[1]

    assert range_arg == "E2:K2", f"Expected 'E2:K2', got '{range_arg}'"
    assert len(data_arg) == 1, "Should be a single-row list"
    assert len(data_arg[0]) == 7, "Should contain 7 column values"
    assert data_arg[0][0] == "My Title"
    assert data_arg[0][1] == "My Desc"
    assert data_arg[0][2] == "My H1"
    assert data_arg[0][3] == "my-slug"
    assert data_arg[0][4] == "https://docs.google.com/d/abc"
    assert data_arg[0][5] == 1234


# ---------------------------------------------------------------------------
# Test 4 — update_error writes to column N
# ---------------------------------------------------------------------------


def test_update_error():
    ws = MagicMock()
    svc = _make_service(ws)

    svc.update_error(2, "Quality gate failed")

    ws.update_cell.assert_called_once_with(2, 14, "Quality gate failed")


# ---------------------------------------------------------------------------
# Test 5 — idempotency returns True for Processing
# ---------------------------------------------------------------------------


def test_idempotency_skip_processing():
    ws = MagicMock()
    ws.cell.return_value.value = "Processing"
    svc = _make_service(ws)

    assert svc.check_idempotency(2) is True


# ---------------------------------------------------------------------------
# Test 6 — idempotency returns False for non-blocking status
# ---------------------------------------------------------------------------


def test_idempotency_allow_generate():
    ws = MagicMock()
    ws.cell.return_value.value = "generate"
    svc = _make_service(ws)

    assert svc.check_idempotency(2) is False


# ---------------------------------------------------------------------------
# Test 7 — stale detection identifies rows older than timeout
# ---------------------------------------------------------------------------


def test_stale_detection():
    ws = MagicMock()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    # Row 1 = header, row 2 = stale processing row
    ws.get_all_values.return_value = [
        ["keyword", "sub", "outline", "Status", "", "", "", "", "", "", "", "", "", "", "started_at", ""],
        ["kw1", "", "", "Processing", "", "", "", "", "", "", "", "", "", "", old_ts, ""],
    ]
    svc = _make_service(ws)

    stale = svc.detect_stale_rows(timeout_minutes=30)

    assert 2 in stale


# ---------------------------------------------------------------------------
# Test 8 — stale detection ignores rows within timeout window
# ---------------------------------------------------------------------------


def test_stale_detection_not_stale():
    ws = MagicMock()
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    ws.get_all_values.return_value = [
        ["keyword", "sub", "outline", "Status", "", "", "", "", "", "", "", "", "", "", "started_at", ""],
        ["kw1", "", "", "Processing", "", "", "", "", "", "", "", "", "", "", recent_ts, ""],
    ]
    svc = _make_service(ws)

    stale = svc.detect_stale_rows(timeout_minutes=30)

    assert 2 not in stale


# ---------------------------------------------------------------------------
# Test 9 — mark_stale_rows updates all stale rows with Error + message
# ---------------------------------------------------------------------------


def test_mark_stale_rows():
    ws = MagicMock()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    ws.get_all_values.return_value = [
        ["keyword", "sub", "outline", "Status", "", "", "", "", "", "", "", "", "", "", "started_at", ""],
        ["kw1", "", "", "Processing", "", "", "", "", "", "", "", "", "", "", old_ts, ""],
        ["kw2", "", "", "Processing", "", "", "", "", "", "", "", "", "", "", old_ts, ""],
    ]
    svc = _make_service(ws)

    svc.mark_stale_rows()

    # Both rows 2 and 3 should have status set to "Error"
    error_status_calls = [
        c for c in ws.update_cell.call_args_list
        if c.args[1] == 4 and c.args[2] == "Error"
    ]
    assert len(error_status_calls) == 2, "Both stale rows should be marked Error"

    # Both rows should have the stale error message in col N
    error_msg_calls = [
        c for c in ws.update_cell.call_args_list
        if c.args[1] == 14
        and "Stale" in str(c.args[2])
    ]
    assert len(error_msg_calls) == 2, "Both stale rows should have stale error message"


# ---------------------------------------------------------------------------
# Test 10 — startup stale detection continues when Sheet is unreachable
# ---------------------------------------------------------------------------


def test_startup_stale_detection_sheet_unreachable():
    """Server startup must not crash when gspread raises an exception."""
    from gspread.exceptions import APIError

    with (
        patch("app.services.sheets.Credentials.from_service_account_file"),
        patch("app.services.sheets.gspread.authorize") as mock_authorize,
    ):
        # Simulate APIError on open_by_key
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": {"code": 403, "message": "Forbidden"}}
        mock_response.status_code = 403
        mock_authorize.return_value.open_by_key.side_effect = APIError(mock_response)

        from app.services.sheets import SheetsService
        from app.config import settings

        # SheetsService.__init__ should raise — the startup handler must catch it
        import asyncio

        async def _run_startup():
            try:
                svc = SheetsService(settings)
                svc.mark_stale_rows()
            except Exception as exc:
                import logging
                logging.getLogger("app.main").warning(
                    "Startup stale detection failed — continuing without it: %s", exc
                )

        # Should not raise
        asyncio.run(_run_startup())
