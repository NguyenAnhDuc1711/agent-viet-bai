"""
End-to-end integration tests for the Blog Writer Agent.

Tests the full pipeline flow with all external APIs mocked:
  - Webhook -> orchestrator -> phases -> docs -> sheet update
  - Quality gate retry flow
  - Batch processing with error isolation
  - Fixture-based responses (TEST-1 compliance)

All tests use unittest.mock.patch — no live API credentials required.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.models import RowData, PipelineResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str):
    path = FIXTURES_DIR / name
    text = path.read_text()
    if name.endswith(".json"):
        return json.loads(text)
    return text


def _make_row(row_number: int = 1, keyword: str = "best running shoes") -> RowData:
    return RowData(row_number=row_number, keyword=keyword)


def _patch_all_phases(monkeypatch, *, phase3_results=None, docs_url=None):
    """Patch all 4 phases, gemini client, and docs service for integration tests.

    Returns (phase1_mock, phase2_mock, phase3_mock, phase4_mock, sheets_mock, docs_mock).
    """
    import app.pipeline.orchestrator as orch

    phase1_data = _load_fixture("gemini_phase1_response.json")
    phase2_data = _load_fixture("gemini_phase2_response.txt")
    phase3_pass = _load_fixture("gemini_phase3_pass.json")
    phase4_data = _load_fixture("gemini_phase4_response.json")

    phase1_mock = AsyncMock(return_value=phase1_data)
    phase2_mock = AsyncMock(return_value=phase2_data)

    if phase3_results is None:
        phase3_results = [phase3_pass]
    if not isinstance(phase3_results, list):
        phase3_results = [phase3_results]
    phase3_mock = AsyncMock(side_effect=phase3_results)

    phase4_mock = AsyncMock(return_value=phase4_data)

    monkeypatch.setattr("app.pipeline.phase1_research.run_phase1", phase1_mock)
    monkeypatch.setattr("app.pipeline.phase2_writing.run_phase2", phase2_mock)
    monkeypatch.setattr("app.pipeline.phase3_quality.run_phase3", phase3_mock)
    monkeypatch.setattr("app.pipeline.phase4_metadata.run_phase4", phase4_mock)
    monkeypatch.setattr(orch, "_gemini_client", MagicMock())

    # Docs service
    doc_url = docs_url or "https://docs.google.com/document/d/integration-test/edit"
    docs_mock = MagicMock()
    docs_mock.create_formatted_doc = AsyncMock(return_value=doc_url)
    monkeypatch.setattr(orch, "_get_docs_service", lambda: docs_mock)

    # Sheets service
    sheets_mock = MagicMock()
    sheets_mock.update_status = MagicMock()
    sheets_mock.update_output_columns = MagicMock()
    sheets_mock.update_error = MagicMock()

    return phase1_mock, phase2_mock, phase3_mock, phase4_mock, sheets_mock, docs_mock


# ---------------------------------------------------------------------------
# 1. Full pipeline: webhook -> phases -> doc -> sheet update (fixture-based)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_with_fixtures(monkeypatch):
    """End-to-end: all 4 phases run using fixture data, doc created, sheet updated to Done."""
    import app.pipeline.orchestrator as orch

    phase1, phase2, phase3, phase4, sheets, docs = _patch_all_phases(monkeypatch)

    row = _make_row()
    result = await orch._run_pipeline(row, sheets=sheets)

    # All phases called
    phase1.assert_awaited_once()
    phase2.assert_awaited_once()
    phase3.assert_awaited_once()
    phase4.assert_awaited_once()

    # Doc created
    docs.create_formatted_doc.assert_awaited_once()

    # Sheet updated
    sheets.update_status.assert_any_call(1, "Processing")
    sheets.update_status.assert_any_call(1, "Done")
    sheets.update_output_columns.assert_called_once()

    # Result is correct
    assert result.status == "Done"
    assert result.doc_url == "https://docs.google.com/document/d/integration-test/edit"
    assert result.title == "Best Running Shoes for Marathon Training Guide Here"
    assert result.url_slug == "best-running-shoes"
    assert result.word_count == 2500


# ---------------------------------------------------------------------------
# 2. Quality gate retry flow with fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_gate_retry_with_fixtures(monkeypatch):
    """Phase 3 fails first attempt (fixture), passes on retry => Done."""
    import app.pipeline.orchestrator as orch

    phase3_fail = _load_fixture("gemini_phase3_fail.json")
    phase3_pass = _load_fixture("gemini_phase3_pass.json")
    phase2_text = _load_fixture("gemini_phase2_response.txt")

    phase1, phase2, phase3, phase4, sheets, docs = _patch_all_phases(
        monkeypatch,
        phase3_results=[phase3_fail, phase3_pass],
    )
    # Phase 2 needs to be callable twice
    phase2.side_effect = [phase2_text, phase2_text]

    row = _make_row()
    result = await orch._run_pipeline(row, sheets=sheets)

    assert result.status == "Done"
    assert phase2.await_count == 2, "Phase 2 should be called twice (original + retry)"
    assert phase3.await_count == 2, "Phase 3 should be called twice"
    phase4.assert_awaited_once()

    # Verify feedback from fail fixture was passed to phase2 retry
    retry_call = phase2.await_args_list[1]
    # feedback= keyword arg or 4th positional
    has_feedback = (
        retry_call.kwargs.get("feedback", "") != ""
        or (len(retry_call.args) >= 4 and retry_call.args[3] != "")
    )
    assert has_feedback, "Retry Phase 2 call should include feedback from failed Phase 3"


# ---------------------------------------------------------------------------
# 3. Double quality gate failure with fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_quality_gate_failure_with_fixtures(monkeypatch):
    """Phase 3 fails twice => Error, Phase 4 not called, sheet updated."""
    import app.pipeline.orchestrator as orch

    phase3_fail = _load_fixture("gemini_phase3_fail.json")
    phase2_text = _load_fixture("gemini_phase2_response.txt")

    phase1, phase2, phase3, phase4, sheets, docs = _patch_all_phases(
        monkeypatch,
        phase3_results=[phase3_fail, phase3_fail],
    )
    phase2.side_effect = [phase2_text, phase2_text]

    row = _make_row()
    result = await orch._run_pipeline(row, sheets=sheets)

    assert result.status == "Error"
    assert "Quality gate failed" in result.error
    phase4.assert_not_awaited()
    docs.create_formatted_doc.assert_not_awaited()
    sheets.update_status.assert_any_call(1, "Error")
    sheets.update_error.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Batch processing: 5 rows, max 3 concurrent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_5_rows_max_3_concurrent(monkeypatch):
    """5 rows processed concurrently with semaphore limit 3; all complete."""
    import app.pipeline.orchestrator as orch

    active = 0
    peak = 0

    async def fake_pipeline(row, sheets=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    rows = [_make_row(i, f"keyword-{i}") for i in range(1, 6)]
    results = await orch.process_rows(rows)

    assert len(results) == 5
    assert all(r.status == "success" for r in results)
    assert peak <= 3, f"Peak concurrency was {peak}, should be <= 3"


# ---------------------------------------------------------------------------
# 5. Error isolation in batch: one failure, others succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_error_isolation(monkeypatch):
    """One row fails, other rows complete successfully."""
    import app.pipeline.orchestrator as orch

    async def fake_pipeline(row, sheets=None):
        if row.row_number == 3:
            raise RuntimeError("row 3 explosion")
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    rows = [_make_row(i, f"keyword-{i}") for i in range(1, 6)]
    results = await orch.process_rows(rows)

    by_row = {r.row_number: r for r in results}
    assert by_row[1].status == "success"
    assert by_row[2].status == "success"
    assert by_row[3].status == "error"
    assert "row 3 explosion" in by_row[3].error
    assert by_row[4].status == "success"
    assert by_row[5].status == "success"


# ---------------------------------------------------------------------------
# 6. Timing is recorded (NFR-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_timing_recorded(monkeypatch, caplog):
    """Per-phase and total durations appear in logs."""
    import logging
    import app.pipeline.orchestrator as orch

    phase1, phase2, phase3, phase4, sheets, docs = _patch_all_phases(monkeypatch)

    row = _make_row()
    with caplog.at_level(logging.INFO, logger="app.pipeline.orchestrator"):
        result = await orch._run_pipeline(row, sheets=sheets)

    messages = [r.message for r in caplog.records]
    assert any("Phase 1/4 complete" in m for m in messages)
    assert any("Phase 2/4 complete" in m for m in messages)
    assert any("Phase 3/4 complete" in m for m in messages)
    assert any("Phase 4/4 complete" in m for m in messages)
    assert any("Pipeline completed" in m for m in messages)
    assert result.status == "Done"


# ---------------------------------------------------------------------------
# 7. Webhook endpoint triggers background processing
# ---------------------------------------------------------------------------


def test_webhook_spawns_background_task(monkeypatch):
    """POST /webhook returns 200 immediately; asyncio.create_task is called."""
    import importlib
    import app.config as cfg_module
    import app.pipeline.orchestrator as orch
    from fastapi.testclient import TestClient

    cfg_module.settings = cfg_module._build_settings()
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    importlib.reload(__import__("app.main", fromlist=["app"]))
    from app.main import app

    client = TestClient(app)
    payload = {
        "rows": [
            {"row_number": 1, "keyword": "test keyword 1"},
            {"row_number": 2, "keyword": "test keyword 2"},
        ]
    }
    headers = {"X-API-Key": "test-api-key-12345"}

    start = time.monotonic()
    response = client.post("/webhook", json=payload, headers=headers)
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["rows"] == 2
    assert elapsed < 1.0, f"Webhook took {elapsed:.3f}s, should be < 1s"


# ---------------------------------------------------------------------------
# 8. Fixtures exist for all phases (TEST-1 compliance)
# ---------------------------------------------------------------------------


def test_fixtures_exist():
    """All required fixture files exist and are valid."""
    required = [
        "gemini_phase1_response.json",
        "gemini_phase2_response.txt",
        "gemini_phase3_pass.json",
        "gemini_phase3_fail.json",
        "gemini_phase4_response.json",
        "sheets_row_data.json",
    ]
    for name in required:
        path = FIXTURES_DIR / name
        assert path.exists(), f"Missing fixture: {name}"
        content = path.read_text()
        assert len(content) > 0, f"Empty fixture: {name}"
        if name.endswith(".json"):
            data = json.loads(content)
            assert isinstance(data, dict), f"Fixture {name} should be a JSON object"


# ---------------------------------------------------------------------------
# 9. Per-task timeout with semaphore release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_releases_semaphore(monkeypatch):
    """A timed-out row returns Error and releases the semaphore for others."""
    import app.config as cfg
    import app.pipeline.orchestrator as orch

    # Patch the settings object that orchestrator actually references at runtime
    monkeypatch.setattr(orch, "settings", MagicMock(task_timeout_seconds=1, concurrency_limit=1))
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(orch, "_semaphore", sem)

    call_order = []

    async def fake_pipeline(row, sheets=None):
        call_order.append(row.row_number)
        if row.row_number == 1:
            await asyncio.sleep(15)  # will timeout
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)

    rows = [_make_row(1), _make_row(2)]
    results = await orch.process_rows(rows)

    by_row = {r.row_number: r for r in results}
    assert by_row[1].status == "error"
    assert "timeout" in by_row[1].error.lower()
    # Row 2 should complete even with semaphore=1 because row 1 released it
    assert by_row[2].status == "success"
