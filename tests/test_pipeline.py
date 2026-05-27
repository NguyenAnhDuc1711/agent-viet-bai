"""
Tests for app/pipeline/orchestrator.py

Covers acceptance criteria from T2:
  - concurrent-processing: at most concurrency_limit rows run simultaneously
  - error-isolation: failures in one row do not affect other rows
  - immediate-response: webhook returns 200 without awaiting background tasks
  - timeout-protection: timed-out rows return Error status; semaphore is released
  - semaphore-released-on-error: subsequent rows can acquire the semaphore
  - batch-summary-logging: log contains succeeded/failed counts

Covers acceptance criteria from T5 (orchestration):
  - quality-gate-pass: all phases run, result is Done
  - quality-gate-retry-success: Phase 2/3 retried once on first failure
  - quality-gate-double-fail: Error with score breakdown; Phase 4 skipped
  - feedback-passed-to-retry: feedback from Phase 3 flows into Phase 2 retry
  - phase1-failure: immediate Error without calling Phase 2/3/4
  - timing-logged: per-phase and total durations appear in logs
  - error-message-format: double failure message matches expected format
"""

import asyncio
import logging
import os
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

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


def make_row(keyword: str = "test-keyword", row_number: int = 1):
    from app.models import RowData

    return RowData(row_number=row_number, keyword=keyword)


def _quality_pass(total: int = 80, scores: Optional[dict] = None) -> dict:
    """Return a quality result that passes the dual threshold."""
    if scores is None:
        scores = {"content": 25, "seo": 20, "eeat": 12, "technical": 12, "ai_citation": 11}
    return {"passed": True, "total": total, "scores": scores, "feedback": ""}


def _quality_fail(total: int = 50, feedback: str = "low content score") -> dict:
    """Return a quality result that fails."""
    scores = {"content": 10, "seo": 15, "eeat": 8, "technical": 9, "ai_citation": 8}
    return {"passed": False, "total": total, "scores": scores, "feedback": feedback}


# ---------------------------------------------------------------------------
# ── T2 tests (unchanged acceptance criteria) ────────────────────────────────
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_limit(monkeypatch):
    """At most concurrency_limit (3) rows run simultaneously."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    # Track peak concurrency via a shared counter
    active = 0
    peak = 0

    async def fake_pipeline(row, sheets=None):
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


@pytest.mark.asyncio
async def test_error_isolation(monkeypatch):
    """A failure in one row does not prevent other rows from completing."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    async def fake_pipeline(row, sheets=None):
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


@pytest.mark.asyncio
async def test_timeout_handling(monkeypatch):
    """A row that hangs longer than the timeout returns an Error within ~1 s."""
    import app.config as cfg
    import app.pipeline.orchestrator as orch
    from app.models import RowData

    # Set a very short timeout
    monkeypatch.setattr(cfg.settings, "task_timeout_seconds", 1)
    monkeypatch.setattr(orch, "_semaphore", asyncio.Semaphore(3))

    async def slow_pipeline(row, sheets=None):
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


@pytest.mark.asyncio
async def test_semaphore_released_on_error(monkeypatch):
    """After a row raises an exception, subsequent rows can still acquire the semaphore."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    call_count = 0

    async def fake_pipeline(row, sheets=None):
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


@pytest.mark.asyncio
async def test_batch_summary_logging(monkeypatch, caplog):
    """process_rows emits a summary log with correct succeeded/failed counts."""
    import app.pipeline.orchestrator as orch
    from app.models import PipelineResult

    async def fake_pipeline(row, sheets=None):
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


# ---------------------------------------------------------------------------
# ── T5 tests: full pipeline orchestration ───────────────────────────────────
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sheets():
    """Return a MagicMock that behaves like SheetsService."""
    sheets = MagicMock()
    sheets.update_status = MagicMock()
    sheets.update_output_columns = MagicMock()
    sheets.update_error = MagicMock()
    return sheets


@pytest.fixture
def mock_docs_service():
    """Return an AsyncMock that behaves like GoogleDocsService."""
    svc = MagicMock()
    svc.create_formatted_doc = AsyncMock(return_value="https://docs.google.com/document/d/abc123/edit")
    return svc


def _patch_pipeline_deps(monkeypatch, *, phase1_result, phase2_results, phase3_results, docs_svc=None):
    """
    Patch run_phase1, run_phase2, run_phase3, run_phase4, and docs service.

    phase2_results / phase3_results may be lists (called sequentially) or a
    single value (called once).
    """
    import app.pipeline.orchestrator as orch

    # Phase 1
    phase1_mock = AsyncMock(return_value=phase1_result)
    monkeypatch.setattr("app.pipeline.phase1_research.run_phase1", phase1_mock)

    # Phase 2 — support multiple sequential return values
    if not isinstance(phase2_results, list):
        phase2_results = [phase2_results]
    phase2_mock = AsyncMock(side_effect=phase2_results)
    monkeypatch.setattr("app.pipeline.phase2_writing.run_phase2", phase2_mock)

    # Phase 3
    if not isinstance(phase3_results, list):
        phase3_results = [phase3_results]
    phase3_mock = AsyncMock(side_effect=phase3_results)
    monkeypatch.setattr("app.pipeline.phase3_quality.run_phase3", phase3_mock)

    # Phase 4
    metadata = {
        "title": "A" * 55,
        "description": "B" * 155,
        "h1": "Some heading",
        "url_slug": "some-slug",
    }
    phase4_mock = AsyncMock(return_value=metadata)
    monkeypatch.setattr("app.pipeline.phase4_metadata.run_phase4", phase4_mock)

    # GeminiClient — return a dummy so _get_gemini_client() doesn't call Vertex AI
    monkeypatch.setattr(orch, "_gemini_client", MagicMock())

    # Docs service
    if docs_svc is not None:
        monkeypatch.setattr(orch, "_get_docs_service", lambda: docs_svc)

    return phase1_mock, phase2_mock, phase3_mock, phase4_mock


# ── test_pipeline_all_phases_pass ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_all_phases_pass(monkeypatch, mock_sheets, mock_docs_service):
    """All 4 phases run in order; result has status='Done'."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500  # > 2000 words

    phase1, phase2, phase3, phase4 = _patch_pipeline_deps(
        monkeypatch,
        phase1_result=research,
        phase2_results=article,
        phase3_results=_quality_pass(),
        docs_svc=mock_docs_service,
    )

    row = make_row()
    result = await orch._run_pipeline(row, sheets=mock_sheets)

    assert result.status == "Done"
    assert result.row_number == 1
    phase1.assert_awaited_once()
    phase2.assert_awaited_once()
    phase3.assert_awaited_once()
    phase4.assert_awaited_once()
    mock_sheets.update_status.assert_any_call(1, "Done")


# ── test_pipeline_quality_gate_retry_success ─────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_quality_gate_retry_success(monkeypatch, mock_sheets, mock_docs_service):
    """Phase 3 fails first, passes on retry; Phase 2 called twice, Phase 4 called once."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500

    phase1, phase2, phase3, phase4 = _patch_pipeline_deps(
        monkeypatch,
        phase1_result=research,
        phase2_results=[article, article],  # two calls
        phase3_results=[_quality_fail(), _quality_pass()],  # fail then pass
        docs_svc=mock_docs_service,
    )

    row = make_row()
    result = await orch._run_pipeline(row, sheets=mock_sheets)

    assert result.status == "Done"
    assert phase2.await_count == 2, f"Expected 2 Phase 2 calls, got {phase2.await_count}"
    assert phase3.await_count == 2, f"Expected 2 Phase 3 calls, got {phase3.await_count}"
    phase4.assert_awaited_once()


# ── test_pipeline_quality_gate_double_fail ───────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_quality_gate_double_fail(monkeypatch, mock_sheets):
    """Double Phase 3 failure → Error with score breakdown; Phase 4 not called."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500

    phase1, phase2, phase3, phase4 = _patch_pipeline_deps(
        monkeypatch,
        phase1_result=research,
        phase2_results=[article, article],
        phase3_results=[_quality_fail(), _quality_fail()],
    )

    row = make_row()
    result = await orch._run_pipeline(row, sheets=mock_sheets)

    assert result.status == "Error"
    assert result.error != ""
    phase4.assert_not_awaited()
    mock_sheets.update_status.assert_any_call(1, "Error")
    mock_sheets.update_error.assert_called_once()


# ── test_pipeline_retry_includes_feedback ────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_retry_includes_feedback(monkeypatch, mock_sheets):
    """Feedback from Phase 3 failure is passed to the Phase 2 retry call."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500
    expected_feedback = "low content score"

    phase1, phase2, phase3, phase4 = _patch_pipeline_deps(
        monkeypatch,
        phase1_result=research,
        phase2_results=[article, article],
        phase3_results=[_quality_fail(feedback=expected_feedback), _quality_fail()],
    )

    row = make_row()
    await orch._run_pipeline(row, sheets=mock_sheets)

    # Second call to phase2 must include the feedback keyword argument
    assert phase2.await_count == 2
    _, retry_kwargs = phase2.await_args_list[1]
    assert retry_kwargs.get("feedback") == expected_feedback or (
        # Also handle positional: run_phase2(client, row, research, feedback)
        len(phase2.await_args_list[1].args) >= 4
        and phase2.await_args_list[1].args[3] == expected_feedback
    ), f"Feedback not found in second Phase 2 call: {phase2.await_args_list[1]}"


# ── test_pipeline_phase1_failure ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_phase1_failure(monkeypatch, mock_sheets):
    """Phase 1 exception → pipeline returns Error without calling Phase 2/3/4."""
    import app.pipeline.orchestrator as orch

    phase1_mock = AsyncMock(side_effect=ValueError("research failed"))
    monkeypatch.setattr("app.pipeline.phase1_research.run_phase1", phase1_mock)
    monkeypatch.setattr(orch, "_gemini_client", MagicMock())

    phase2_mock = AsyncMock()
    phase3_mock = AsyncMock()
    phase4_mock = AsyncMock()
    monkeypatch.setattr("app.pipeline.phase2_writing.run_phase2", phase2_mock)
    monkeypatch.setattr("app.pipeline.phase3_quality.run_phase3", phase3_mock)
    monkeypatch.setattr("app.pipeline.phase4_metadata.run_phase4", phase4_mock)

    row = make_row()
    # _run_pipeline raises; the exception bubbles to process_single_row
    with pytest.raises(ValueError, match="research failed"):
        await orch._run_pipeline(row, sheets=mock_sheets)

    phase2_mock.assert_not_awaited()
    phase3_mock.assert_not_awaited()
    phase4_mock.assert_not_awaited()


# ── test_pipeline_timing_logged ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_timing_logged(monkeypatch, mock_sheets, mock_docs_service, caplog):
    """Logs include per-phase duration fields and total pipeline duration."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500

    _patch_pipeline_deps(
        monkeypatch,
        phase1_result=research,
        phase2_results=article,
        phase3_results=_quality_pass(),
        docs_svc=mock_docs_service,
    )

    row = make_row()
    with caplog.at_level(logging.INFO, logger="app.pipeline.orchestrator"):
        await orch._run_pipeline(row, sheets=mock_sheets)

    messages = [r.message for r in caplog.records]
    # Total pipeline completion must appear
    assert any("Pipeline completed" in m for m in messages), (
        f"Expected 'Pipeline completed' in logs. Got: {messages}"
    )
    # Per-phase duration logs must appear
    assert any("Phase 1/4 complete" in m for m in messages)
    assert any("Phase 2/4 complete" in m for m in messages)
    assert any("Phase 3/4 complete" in m for m in messages)
    assert any("Phase 4/4 complete" in m for m in messages)


# ── test_pipeline_error_message_format ───────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_error_message_format(monkeypatch, mock_sheets):
    """Double quality gate failure produces the exact score-breakdown format."""
    import app.pipeline.orchestrator as orch

    research = {"strategy": "s", "outline": [], "keyword_map": {}}
    article = "word " * 2500
    scores = {"content": 10, "seo": 15, "eeat": 8, "technical": 9, "ai_citation": 8}
    total = sum(scores.values())  # 50
    fail_result = {"passed": False, "total": total, "scores": scores, "feedback": "needs work"}

    _, phase2, phase3, phase4 = _patch_pipeline_deps(
        monkeypatch,
        phase1_result={"strategy": "s", "outline": [], "keyword_map": {}},
        phase2_results=[article, article],
        phase3_results=[fail_result, fail_result],
    )

    row = make_row()
    result = await orch._run_pipeline(row, sheets=mock_sheets)

    assert result.status == "Error"
    assert f"Content {scores['content']}/30" in result.error
    assert f"SEO {scores['seo']}/25" in result.error
    assert f"E-E-A-T {scores['eeat']}/15" in result.error
    assert f"Technical {scores['technical']}/15" in result.error
    assert f"AI Citation {scores['ai_citation']}/15" in result.error
    assert f"Total: {total}/100" in result.error
    phase4.assert_not_awaited()
