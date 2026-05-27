"""
Async task queue and batch processing orchestrator.

Provides bounded concurrency via asyncio.Semaphore and per-task timeout
via asyncio.wait_for. Each row is processed independently — a failure in one
row does not affect others.
"""

import asyncio
import time

from app.config import get_logger, settings
from app.models import PipelineResult, RowData

logger = get_logger(__name__)

# Module-level semaphore — concurrency is fixed at import/startup time
_semaphore = asyncio.Semaphore(settings.concurrency_limit)


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore (testable hook)."""
    return _semaphore


async def _run_pipeline(row: RowData) -> PipelineResult:
    """Placeholder pipeline execution.

    T4 / T5 will replace this with the actual pipeline phases
    (keyword research, outline generation, content writing, etc.).
    """
    # Simulate minimal async work so the coroutine is genuinely async
    await asyncio.sleep(0)
    return PipelineResult(
        row_number=row.row_number,
        status="success",
        title=f"Placeholder title for {row.keyword}",
    )


async def process_single_row(row: RowData) -> PipelineResult:
    """Process one row with semaphore-bounded concurrency and a per-task timeout.

    Guarantees:
    - The semaphore is always released (async with context manager).
    - TimeoutError and any other exception are caught and converted to an
      Error PipelineResult — never re-raised.
    """
    semaphore = _get_semaphore()
    start = time.monotonic()

    async with semaphore:
        logger.info(
            "Row processing started",
            extra={"row_number": row.row_number, "phase": "orchestrator"},
        )
        try:
            result = await asyncio.wait_for(
                _run_pipeline(row),
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
