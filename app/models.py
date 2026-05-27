"""
Pydantic models for Blog Writer Agent.

Defines request/response types used across all pipeline stages.
"""

from pydantic import BaseModel, field_validator


class RowData(BaseModel):
    """Represents a single row from the Google Sheet."""

    row_number: int
    keyword: str
    sub_keyword: str = ""
    outline: str = ""


class WebhookPayload(BaseModel):
    """Payload received by the POST /webhook endpoint."""

    rows: list[RowData]

    @field_validator("rows", mode="before")
    @classmethod
    def rows_must_not_be_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("rows must contain at least one item")
        return v


class PipelineResult(BaseModel):
    """Result of processing a single row through the pipeline."""

    row_number: int
    status: str  # "success" | "error" | "skipped"
    title: str = ""
    description: str = ""
    h1: str = ""
    url_slug: str = ""
    doc_url: str = ""
    word_count: int = 0
    error: str = ""
