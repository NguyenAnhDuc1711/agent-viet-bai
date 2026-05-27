"""
Tests for app/pipeline/orchestrator.py

Covers acceptance criteria from T2:
  - concurrent-processing: at most concurrency_limit rows run simultaneously
  - error-isolation: failures in one row do not affect other rows
  - immediate-response: webhook returns 200 without awaiting background tasks
  - timeout-protection: timed-out rows return Error status; semaphore is released
  - semaphore-released-on-error: subsequent rows can acquire the semaphore
  - batch-summary-logging: log contains succeeded/failed counts
"""

import asyncio
import logging
import os
import time

import pytest

# ---------------------------------------------------------------------------
# Environment setup — must happen before any app module is imported
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


def make_rows(n: int):
    from app.models import RowData

    return [RowData(row_number=i, keyword=f"keyword-{i}") for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# test_concurrent_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_limit(monkeypatch):
    """At most concurrency_limit (3) rows run simultaneously."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    # Track peak concurrency via a shared counter
    active = 0
    peak = 0

    async def fake_pipeline(row):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)  # hold slot briefly
        active -= 1
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    # Reset semaphore to configured limit (3)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    rows = make_rows(10)
    results = await orch.process_rows(rows)

    assert len(results) == 10
    assert all(r.status == "success" for r in results)
    assert peak <= 3, f"Peak concurrency was {peak}, expected <= 3"


# ---------------------------------------------------------------------------
# test_error_isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_isolation(monkeypatch):
    """A failure in one row does not prevent other rows from completing."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    async def fake_pipeline(row):
        if row.row_number == 2:
            raise ValueError("intentional failure")
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    rows = make_rows(3)
    results = await orch.process_rows(rows)

    by_row = {r.row_number: r for r in results}
    assert by_row[1].status == "success"
    assert by_row[2].status == "error"
    assert "intentional failure" in by_row[2].error
    assert by_row[3].status == "success"


# ---------------------------------------------------------------------------
# test_timeout_handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_handling(monkeypatch):
    """A row that hangs longer than the timeout returns an Error within ~1 s."""
    import app.config as cfg
    import app.pipeline.orchestrator as orch
    from app.models import RowData

    # Set a very short timeout
    monkeypatch.setattr(cfg.settings, "task_timeout_seconds", 1)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    async def slow_pipeline(row):
        await asyncio.sleep(15)  # deliberately exceeds timeout
        from app.models import PipelineResult
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", slow_pipeline)

    row = RowData(row_number=1, keyword="slow")
    start = time.monotonic()
    result = await orch.process_single_row(row)
    elapsed = time.monotonic() - start

    assert result.status == "error"
    assert "timeout" in result.error.lower()
    # Should complete in well under 5 seconds (the 1-second timeout + margin)
    assert elapsed < 5, f"Timed out test took too long: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# test_immediate_webhook_response
# ---------------------------------------------------------------------------


def test_immediate_webhook_response(monkeypatch):
    """POST /webhook returns 200 in < 500 ms — background tasks are not awaited."""
    import importlib
    import app.config as cfg_module
    import app.pipeline.orchestrator as orch
    from fastapi.testclient import TestClient

    # Rebuild settings with test environment
    cfg_module.settings = cfg_module._build_settings()
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    importlib.reload(__import__("app.main", fromlist=["app"]))
    from app.main import app

    client = TestClient(app)
    payload = {"rows": [{"row_number": i, "keyword": f"kw-{i}"} for i in range(1, 6)]}
    headers = {"X-API-Key": "test-api-key-12345"}

    start = time.monotonic()
    response = client.post("/webhook", json=payload, headers=headers)
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert elapsed < 0.5, f"Webhook took {elapsed:.3f}s — should be < 500 ms"


# ---------------------------------------------------------------------------
# test_semaphore_released_on_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semaphore_released_on_error(monkeypatch):
    """After a row raises an exception, subsequent rows can still acquire the semaphore."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    call_count = 0

    async def fake_pipeline(row):
        nonlocal call_count
        call_count += 1
        if row.row_number == 1:
            raise RuntimeError("row 1 always fails")
        return PipelineResult(row_number=row.row_number, status="success")

    # Use a limit of 1 to make the semaphore-release check obvious
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(orch, "_semaphore", sem)

    rows = make_rows(4)
    results = await orch.process_rows(rows)

    # All 4 rows must have been attempted
    assert call_count == 4
    # First row is Error; rest succeed
    by_row = {r.row_number: r for r in results}
    assert by_row[1].status == "error"
    assert by_row[2].status == "success"
    assert by_row[3].status == "success"
    assert by_row[4].status == "success"


# ---------------------------------------------------------------------------
# test_batch_summary_logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_summary_logging(monkeypatch, caplog):
    """process_rows emits a summary log with correct succeeded/failed counts."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    async def fake_pipeline(row):
        if row.row_number == 2:
            raise ValueError("oops")
        return PipelineResult(row_number=row.row_number, status="success")

    monkeypatch.setattr(orch, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    rows = make_rows(3)

    with caplog.at_level(logging.INFO, logger="app.pipeline.orchestrator"):
        await orch.process_rows(rows)

    summary_logs = [r.message for r in caplog.records if "2 succeeded" in r.message or "1 failed" in r.message]
    assert summary_logs, (
        "Expected a batch summary log containing succeeded/failed counts. "
        f"Captured log messages: {[r.message for r in caplog.records]}"
    )
