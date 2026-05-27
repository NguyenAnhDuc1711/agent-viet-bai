"""
Google Docs & Drive Service for Blog Writer Agent.

Creates formatted Google Docs from markdown content, places them in a
configured Drive folder, and sets sharing permissions.  Combines what
was originally planned as separate ``docs.py`` and ``drive.py`` modules
(per plan-review DRY-1).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.config import get_logger
from app.services.markdown_parser import parse_markdown

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


class GoogleDocsService:
    """Create and format Google Docs via the Docs and Drive APIs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_PATH,
            scopes=_SCOPES,
        )
        self._drive = build("drive", "v3", credentials=creds)
        self._docs = build("docs", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_formatted_doc(
        self,
        title: str,
        markdown_content: str,
    ) -> str:
        """Create a Google Doc with formatted content and return its URL.

        Parameters
        ----------
        title:
            Document title (appears in Drive and at the top of the Doc).
        markdown_content:
            Markdown-formatted article body.

        Returns
        -------
        str
            Full Google Docs URL for the created document.
        """
        # Step 1 — create blank Doc in Drive folder
        doc_id = await self._create_blank_doc(title)
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        # Step 2 — parse markdown
        plain_text, format_requests = parse_markdown(markdown_content)

        # Step 3 — insert plain text
        try:
            await asyncio.to_thread(
                self._docs.documents()
                .batchUpdate(
                    documentId=doc_id,
                    body={
                        "requests": [
                            {
                                "insertText": {
                                    "location": {"index": 1},
                                    "text": plain_text,
                                }
                            }
                        ]
                    },
                )
                .execute
            )
        except Exception:
            logger.warning(
                "Failed to insert text into doc %s", doc_id, exc_info=True
            )
            return doc_url

        # Step 4 — apply formatting (reverse-order requests)
        if format_requests:
            try:
                await asyncio.to_thread(
                    self._docs.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={"requests": format_requests},
                    )
                    .execute
                )
            except Exception:
                logger.warning(
                    "Formatting partially failed for doc %s",
                    doc_id,
                    exc_info=True,
                )

        # Step 5 — set sharing permission
        try:
            await asyncio.to_thread(
                self._drive.permissions()
                .create(
                    fileId=doc_id,
                    body={
                        "role": self._settings.doc_share_permission,
                        "type": "anyone",
                    },
                )
                .execute
            )
        except Exception:
            logger.warning(
                "Failed to set sharing on doc %s", doc_id, exc_info=True
            )

        return doc_url

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_blank_doc(self, title: str) -> str:
        """Create a blank Google Doc in the configured Drive folder.

        Returns the document ID.
        """
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if self._settings.drive_folder_id:
            file_metadata["parents"] = [self._settings.drive_folder_id]

        result = await asyncio.to_thread(
            self._drive.files()
            .create(body=file_metadata, fields="id")
            .execute
        )
        doc_id: str = result["id"]
        logger.info("Created blank doc %s (%s)", doc_id, title)
        return doc_id
