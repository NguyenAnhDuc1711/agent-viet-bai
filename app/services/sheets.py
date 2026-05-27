"""
Google Sheets Service for Blog Writer Agent.

Provides read/write access to the Google Sheet used for tracking blog pipeline
processing status, output metadata, and error messages.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_logger
from app.models import RowData, PipelineResult

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Column mapping constants (1-based, A=1 … P=16)
# ---------------------------------------------------------------------------

COL_KEYWORD = 1
COL_SUB_KEYWORD = 2
COL_OUTLINE = 3
COL_STATUS = 4
COL_TITLE = 5
COL_DESCRIPTION = 6
COL_H1 = 7
COL_URL_SLUG = 8
COL_DOCS = 9
COL_WORD_COUNT = 10
COL_WRITING_DATE = 11
COL_PUBLISHED_DATE = 12
COL_PUBLISHER = 13
COL_ERROR = 14
COL_STARTED_AT = 15
COL_FINISHED_AT = 16

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

_STALE_ERROR_MESSAGE = "Stale - processing interrupted; retry required"


class SheetsService:
    """Thin wrapper around gspread for sheet read/write operations."""

    def __init__(self, settings: "Settings") -> None:
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_PATH,
            scopes=_SCOPES,
        )
        client = gspread.authorize(creds)
        self._worksheet = client.open_by_key(settings.sheet_id).sheet1

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_rows_by_status(self, status: str) -> list[RowData]:
        """Return all rows where the Status column (D) matches *status*."""
        all_values = self._worksheet.get_all_values()
        results: list[RowData] = []
        for idx, row in enumerate(all_values):
            # Row index in the sheet is 1-based; row 1 is the header
            sheet_row = idx + 1
            if sheet_row == 1:
                continue  # skip header
            # Pad row to at least COL_STATUS columns
            while len(row) < COL_STATUS:
                row.append("")
            if row[COL_STATUS - 1] == status:
                results.append(
                    RowData(
                        row_number=sheet_row,
                        keyword=row[COL_KEYWORD - 1],
                        sub_keyword=row[COL_SUB_KEYWORD - 1] if len(row) >= COL_SUB_KEYWORD else "",
                        outline=row[COL_OUTLINE - 1] if len(row) >= COL_OUTLINE else "",
                    )
                )
        return results

    def check_idempotency(self, row_number: int) -> bool:
        """Return True if the row should be skipped (already Processing or Done)."""
        cell_value = self._worksheet.cell(row_number, COL_STATUS).value or ""
        return cell_value in ("Processing", "Done")

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def update_status(self, row_number: int, status: str) -> None:
        """Update the Status column for *row_number*.

        Side effects:
        - Sets ``started_at`` (col O) when status is ``"Processing"``.
        - Sets ``finished_at`` (col P) when status is ``"Done"`` or ``"Error"``.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        self._worksheet.update_cell(row_number, COL_STATUS, status)

        if status == "Processing":
            self._worksheet.update_cell(row_number, COL_STARTED_AT, now_iso)
        elif status in ("Done", "Error"):
            self._worksheet.update_cell(row_number, COL_FINISHED_AT, now_iso)

    def update_output_columns(self, row_number: int, result: PipelineResult) -> None:
        """Batch-update output columns E-K in a single API call.

        Columns: title(E), description(F), h1(G), url_slug(H), docs(I),
                 word_count(J), writing_date(K).
        """
        writing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._worksheet.update(
            f"E{row_number}:K{row_number}",
            [[
                result.title,
                result.description,
                result.h1,
                result.url_slug,
                result.doc_url,
                result.word_count,
                writing_date,
            ]],
        )

    def update_error(self, row_number: int, message: str) -> None:
        """Write *message* to the Error column (N) for *row_number*."""
        self._worksheet.update_cell(row_number, COL_ERROR, message)

    # ------------------------------------------------------------------
    # Stale row detection
    # ------------------------------------------------------------------

    def detect_stale_rows(self, timeout_minutes: int = 30) -> list[int]:
        """Return row numbers where status is 'Processing' and started_at is older than *timeout_minutes*."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        all_values = self._worksheet.get_all_values()
        stale: list[int] = []

        for idx, row in enumerate(all_values):
            sheet_row = idx + 1
            if sheet_row == 1:
                continue  # skip header
            while len(row) < COL_STARTED_AT:
                row.append("")
            status = row[COL_STATUS - 1]
            if status != "Processing":
                continue
            started_at_raw = row[COL_STARTED_AT - 1]
            if not started_at_raw:
                # No timestamp — treat as stale
                stale.append(sheet_row)
                continue
            try:
                started_at = datetime.fromisoformat(started_at_raw)
                # Ensure timezone-aware for comparison
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                if started_at < cutoff:
                    stale.append(sheet_row)
            except ValueError:
                logger.warning(
                    "Could not parse started_at for row %d: %r",
                    sheet_row,
                    started_at_raw,
                )
        return stale

    def mark_stale_rows(self) -> None:
        """Detect stale Processing rows and mark them as Error."""
        stale_rows = self.detect_stale_rows()
        for row_number in stale_rows:
            logger.warning(
                "Marking stale row as Error",
                extra={"row_number": row_number},
            )
            self.update_status(row_number, "Error")
            self.update_error(row_number, _STALE_ERROR_MESSAGE)
