"""
Async task queue and batch processing orchestrator.

Provides bounded concurrency via asyncio.Semaphore and per-task timeout
via asyncio.wait_for. Each row is processed independently — a failure in one
row does not affect others.
"""

import asyncio
import time
from typing import Optional

from app.config import get_logger, settings
from app.models import PipelineResult, RowData

logger = get_logger(__name__)

# Module-level semaphore — concurrency is fixed at import/startup time
_semaphore = asyncio.Semaphore(settings.concurrency_limit)

# NFR-1: warn if pipeline takes longer than this (seconds)
_PIPELINE_WARN_SECONDS = 300


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore (testable hook)."""
    return _semaphore


# ---------------------------------------------------------------------------
# Lazy module-level service instances
# ---------------------------------------------------------------------------

_gemini_client = None
_sheets_service = None


def _get_gemini_client():
    """Return the shared GeminiClient, initializing on first call."""
    global _gemini_client
    if _gemini_client is None:
        from app.pipeline.gemini_client import GeminiClient
        _gemini_client = GeminiClient()
    return _gemini_client


def _get_sheets_service():
    """Return the shared SheetsService, initializing on first call."""
    global _sheets_service
    if _sheets_service is None:
        from app.services.sheets import SheetsService
        _sheets_service = SheetsService(settings)
    return _sheets_service


def _get_docs_service():
    """Create a fresh GoogleDocsService (stateless, cheap to construct)."""
    from app.services.google_docs import GoogleDocsService
    return GoogleDocsService(settings)


# ---------------------------------------------------------------------------
# Core pipeline execution
# ---------------------------------------------------------------------------


async def _run_pipeline(row: RowData, sheets=None) -> PipelineResult:
    """Execute the full Phase 1 → 2 → 3 → (retry?) → 4 → Doc pipeline.

    Args:
        row: Row data for the article to generate.
        sheets: SheetsService instance for status updates (optional; if None,
                status updates are skipped — useful in tests).

    Returns:
        PipelineResult with populated fields on success or error details on
        failure.
    """
    from app.pipeline.phase1_research import run_phase1
    from app.pipeline.phase2_writing import run_phase2
    from app.pipeline.phase3_quality import run_phase3
    from app.pipeline.phase4_metadata import run_phase4

    client = _get_gemini_client()
    pipeline_start = time.monotonic()

    def _elapsed() -> float:
        return round(time.monotonic() - pipeline_start, 3)

    # ------------------------------------------------------------------
    # Phase 1: Research & Strategy
    # ------------------------------------------------------------------
    if sheets:
        sheets.update_status(row.row_number, "Processing")

    phase_start = time.monotonic()
    logger.info(
        "Phase 1/4 starting for row %d",
        row.row_number,
        extra={"row_number": row.row_number, "phase": "research"},
    )

    research = await run_phase1(client, row)

    phase_duration = round(time.monotonic() - phase_start, 3)
    logger.info(
        "Phase 1/4 complete for row %d (%.3fs)",
        row.row_number,
        phase_duration,
        extra={
            "row_number": row.row_number,
            "phase": "research",
            "duration": phase_duration,
        },
    )

    # ------------------------------------------------------------------
    # Phase 2: Content Writing (first attempt)
    # ------------------------------------------------------------------
    phase_start = time.monotonic()
    logger.info(
        "Phase 2/4 starting for row %d",
        row.row_number,
        extra={"row_number": row.row_number, "phase": "writing"},
    )

    article = await run_phase2(client, row, research)

    phase_duration = round(time.monotonic() - phase_start, 3)
    logger.info(
        "Phase 2/4 complete for row %d (%.3fs)",
        row.row_number,
        phase_duration,
        extra={
            "row_number": row.row_number,
            "phase": "writing",
            "duration": phase_duration,
        },
    )

    # ------------------------------------------------------------------
    # Phase 3: Quality Gate (first attempt)
    # ------------------------------------------------------------------
    phase_start = time.monotonic()
    logger.info(
        "Phase 3/4 starting for row %d",
        row.row_number,
        extra={"row_number": row.row_number, "phase": "quality_gate"},
    )

    quality = await run_phase3(client, article, row.keyword, research)

    phase_duration = round(time.monotonic() - phase_start, 3)
    logger.info(
        "Phase 3/4 complete for row %d: score=%d, passed=%s (%.3fs)",
        row.row_number,
        quality.get("total", 0),
        quality.get("passed", False),
        phase_duration,
        extra={
            "row_number": row.row_number,
            "phase": "quality_gate",
            "duration": phase_duration,
        },
    )

    # ------------------------------------------------------------------
    # Quality gate retry logic (AD-12)
    # ------------------------------------------------------------------
    if not quality.get("passed", False):
        total_score = quality.get("total", 0)
        feedback = quality.get("feedback", "")
        logger.warning(
            "Quality gate failed (score %d/100), retrying Phase 2 with feedback for row %d",
            total_score,
            row.row_number,
            extra={"row_number": row.row_number, "phase": "quality_gate"},
        )

        # Phase 2 retry with feedback
        phase_start = time.monotonic()
        article = await run_phase2(client, row, research, feedback=feedback)
        phase_duration = round(time.monotonic() - phase_start, 3)
        logger.info(
            "Phase 2/4 retry complete for row %d (%.3fs)",
            row.row_number,
            phase_duration,
            extra={
                "row_number": row.row_number,
                "phase": "writing_retry",
                "duration": phase_duration,
            },
        )

        # Phase 3 retry
        phase_start = time.monotonic()
        quality = await run_phase3(client, article, row.keyword, research)
        phase_duration = round(time.monotonic() - phase_start, 3)
        logger.info(
            "Phase 3/4 retry complete for row %d: score=%d, passed=%s (%.3fs)",
            row.row_number,
            quality.get("total", 0),
            quality.get("passed", False),
            phase_duration,
            extra={
                "row_number": row.row_number,
                "phase": "quality_gate_retry",
                "duration": phase_duration,
            },
        )

        if not quality.get("passed", False):
            # Double failure — build score breakdown error message
            scores = quality.get("scores", {})
            error_message = (
                "Quality gate failed after retry. "
                f"Scores: Content {scores.get('content', 0)}/30, "
                f"SEO {scores.get('seo', 0)}/25, "
                f"E-E-A-T {scores.get('eeat', 0)}/15, "
                f"Technical {scores.get('technical', 0)}/15, "
                f"AI Citation {scores.get('ai_citation', 0)}/15. "
                f"Total: {quality.get('total', 0)}/100"
            )
            logger.error(
                "Quality gate double failure for row %d: %s",
                row.row_number,
                error_message,
                extra={"row_number": row.row_number, "phase": "quality_gate"},
            )

            total_duration = _elapsed()
            logger.info(
                "Pipeline completed for row %d in %.3fs (Error)",
                row.row_number,
                total_duration,
                extra={
                    "row_number": row.row_number,
                    "phase": "orchestrator",
                    "duration": total_duration,
                },
            )

            if sheets:
                sheets.update_status(row.row_number, "Error")
                sheets.update_error(row.row_number, error_message)

            return PipelineResult(
                row_number=row.row_number,
                status="Error",
                error=error_message,
            )

    # ------------------------------------------------------------------
    # Phase 4: Metadata Extraction
    # ------------------------------------------------------------------
    phase_start = time.monotonic()
    logger.info(
        "Phase 4/4 starting for row %d",
        row.row_number,
        extra={"row_number": row.row_number, "phase": "metadata"},
    )

    metadata = await run_phase4(client, article, row.keyword)

    phase_duration = round(time.monotonic() - phase_start, 3)
    logger.info(
        "Phase 4/4 complete for row %d (%.3fs)",
        row.row_number,
        phase_duration,
        extra={
            "row_number": row.row_number,
            "phase": "metadata",
            "duration": phase_duration,
        },
    )

    # ------------------------------------------------------------------
    # Create Google Doc
    # ------------------------------------------------------------------
    doc_url = ""
    try:
        docs_service = _get_docs_service()
        title = metadata.get("title", row.keyword)
        doc_url = await docs_service.create_formatted_doc(title, article)
        logger.info(
            "Google Doc created for row %d: %s",
            row.row_number,
            doc_url,
            extra={"row_number": row.row_number, "phase": "docs"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Google Doc creation failed for row %d: %s",
            row.row_number,
            exc,
            extra={"row_number": row.row_number, "phase": "docs"},
        )

    # ------------------------------------------------------------------
    # Build final result
    # ------------------------------------------------------------------
    word_count = len(article.split())
    result = PipelineResult(
        row_number=row.row_number,
        status="Done",
        title=metadata.get("title", ""),
        description=metadata.get("description", ""),
        h1=metadata.get("h1", ""),
        url_slug=metadata.get("url_slug", ""),
        doc_url=doc_url,
        word_count=word_count,
    )

    total_duration = _elapsed()
    if total_duration > _PIPELINE_WARN_SECONDS:
        logger.warning(
            "Pipeline for row %d exceeded NFR-1 limit: %.3fs > %ds",
            row.row_number,
            total_duration,
            _PIPELINE_WARN_SECONDS,
            extra={"row_number": row.row_number, "phase": "orchestrator", "duration": total_duration},
        )

    logger.info(
        "Pipeline completed for row %d in %.3fs",
        row.row_number,
        total_duration,
        extra={
            "row_number": row.row_number,
            "phase": "orchestrator",
            "duration": total_duration,
        },
    )

    # Update sheet with results
    if sheets:
        sheets.update_output_columns(row.row_number, result)
        sheets.update_status(row.row_number, "Done")

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def process_single_row(row: RowData) -> PipelineResult:
    """Process one row with semaphore-bounded concurrency and a per-task timeout.

    Guarantees:
    - The semaphore is always released (async with context manager).
    - TimeoutError and any other exception are caught and converted to an
      Error PipelineResult — never re-raised.
    """
    semaphore = _get_semaphore()
    start = time.monotonic()

    # Lazily obtain sheets service; failures here are non-fatal
    try:
        sheets = _get_sheets_service()
    except Exception:  # noqa: BLE001
        sheets = None

    async with semaphore:
        logger.info(
            "Row processing started",
            extra={"row_number": row.row_number, "phase": "orchestrator"},
        )
        try:
            result = await asyncio.wait_for(
                _run_pipeline(row, sheets),
                timeout=settings.task_timeout_seconds,
            )
            duration = time.monotonic() - start
            logger.info(
                "Row processing finished",
                extra={
                    "row_number": row.row_number,
                    "phase": "orchestrator",
                    "duration": round(duration, 3),
                },
            )
            return result

        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            msg = f"Pipeline timeout after {settings.task_timeout_seconds}s"
            logger.error(
                "Row timed out",
                extra={
                    "row_number": row.row_number,
                    "phase": "orchestrator",
                    "duration": round(duration, 3),
                },
            )
            if sheets:
                try:
                    sheets.update_status(row.row_number, "Error")
                    sheets.update_error(row.row_number, msg)
                except Exception:  # noqa: BLE001
                    pass
            return PipelineResult(
                row_number=row.row_number,
                status="error",
                error=msg,
            )

        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            logger.error(
                "Row processing error: %s",
                exc,
                extra={
                    "row_number": row.row_number,
                    "phase": "orchestrator",
                    "duration": round(duration, 3),
                },
            )
            if sheets:
                try:
                    sheets.update_status(row.row_number, "Error")
                    sheets.update_error(row.row_number, str(exc))
                except Exception:  # noqa: BLE001
                    pass
            return PipelineResult(
                row_number=row.row_number,
                status="error",
                error=str(exc),
            )


async def process_rows(rows: list[RowData]) -> list[PipelineResult]:
    """Process a batch of rows concurrently, returning one result per row.

    Creates one asyncio.Task per row. The semaphore inside process_single_row
    ensures at most settings.concurrency_limit rows run simultaneously.
    Each task handles its own exceptions — gather never sees an unhandled error.
    """
    batch_start = time.monotonic()
    logger.info(
        "Batch processing started",
        extra={"row_number": len(rows), "phase": "orchestrator"},
    )

    tasks = [asyncio.create_task(process_single_row(row)) for row in rows]
    results: list[PipelineResult] = await asyncio.gather(*tasks)

    succeeded = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status != "success")
    duration = time.monotonic() - batch_start

    logger.info(
        "Batch processing complete: %d succeeded, %d failed",
        succeeded,
        failed,
        extra={
            "row_number": len(rows),
            "phase": "orchestrator",
            "duration": round(duration, 3),
        },
    )

    return results
