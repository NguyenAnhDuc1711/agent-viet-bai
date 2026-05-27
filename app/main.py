"""
Blog Writer Agent — FastAPI application entry point.

Exposes a single authenticated POST /webhook endpoint.
API key authentication is implemented as a FastAPI dependency (not middleware).
"""

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Header

from app.config import get_logger, settings
from app.models import WebhookPayload

logger = get_logger(__name__)

app = FastAPI(title="Blog Writer Agent")


# ---------------------------------------------------------------------------
# Startup event — stale row detection
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_stale_detection() -> None:
    """On startup, scan for stale Processing rows and mark them as Error.

    Wrapped in try/except so a transient Sheet unavailability does not prevent
    the server from starting.
    """
    try:
        from app.services.sheets import SheetsService

        sheets = SheetsService(settings)
        sheets.mark_stale_rows()
        logger.info("Startup stale detection complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Startup stale detection failed — continuing without it: %s", exc
        )


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


async def verify_api_key(x_api_key: str = Header(default=None)) -> str:
    """
    FastAPI dependency that validates the X-API-Key request header.

    Raises HTTP 401 if the header is absent or does not match the configured key.
    """
    if x_api_key is None:
        logger.warning("Request rejected: missing X-API-Key header")
        raise HTTPException(status_code=401, detail="Missing API key")
    if x_api_key != settings.API_KEY:
        logger.warning("Request rejected: invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@app.post("/webhook")
async def webhook(
    payload: WebhookPayload,
    _api_key: str = Depends(verify_api_key),
) -> dict:
    """
    Accept a batch of rows for blog-writing pipeline processing.

    Returns 200 immediately with the number of rows accepted.
    Background task spawning will be added in T2.
    """
    logger.info(
        "Webhook accepted",
        extra={"row_number": len(payload.rows), "phase": "intake"},
    )

    # TODO (T2): spawn background asyncio tasks for pipeline processing
    # semaphore = asyncio.Semaphore(settings.concurrency_limit)
    # asyncio.create_task(run_pipeline_batch(payload.rows, semaphore))

    return {"status": "accepted", "rows": len(payload.rows)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
