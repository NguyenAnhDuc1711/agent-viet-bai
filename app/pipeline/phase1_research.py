"""
Phase 1: Research & Strategy.

Transforms keyword data into a structured research output containing
strategy, outline, keyword map, and visual plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_logger
from app.models import RowData

if TYPE_CHECKING:
    from app.pipeline.gemini_client import GeminiClient

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/phase1_research.md")


async def run_phase1(client: GeminiClient, row: RowData) -> dict:
    """Execute Phase 1: Research & Strategy.

    Args:
        client: Initialized GeminiClient.
        row: Row data with keyword, sub_keyword, and optional outline.

    Returns:
        Dict with keys: strategy, outline, keyword_map, visual_plan.

    Raises:
        ValueError: If required keys are missing from the response.
    """
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{keyword}", row.keyword)
    prompt = prompt.replace("{sub_keyword}", row.sub_keyword)
    prompt = prompt.replace("{outline}", row.outline)

    system_instruction = (
        "You are an expert SEO content strategist. "
        "Analyze the keyword and produce a comprehensive research output."
    )

    result = await client.generate_json(
        prompt=prompt,
        system_instruction=system_instruction,
        labels={"phase": "research"},
    )

    # Validate required keys
    required_keys = {"strategy", "outline", "keyword_map"}
    missing = required_keys - set(result.keys())
    if missing:
        raise ValueError(f"Phase 1 response missing required keys: {missing}")

    # If user provided an outline, verify all user headings are preserved
    if row.outline and row.outline.strip():
        _validate_user_outline_preserved(row.outline, result.get("outline", []))

    logger.info(
        "Phase 1 completed",
        extra={"phase": "research"},
    )

    return result


def _validate_user_outline_preserved(user_outline: str, output_outline: list) -> None:
    """Verify that all user-provided headings appear in the output outline.

    Args:
        user_outline: Raw outline text from user (newline-separated headings).
        output_outline: List of outline items from Phase 1 output.

    Raises:
        ValueError: If any user heading is missing from the output.
    """
    # Extract user headings (lines starting with # or ##, stripped of markdown)
    user_headings = []
    for line in user_outline.strip().split("\n"):
        line = line.strip()
        if line:
            # Strip markdown heading markers
            cleaned = line.lstrip("#").strip()
            if cleaned:
                user_headings.append(cleaned.lower())

    if not user_headings:
        return

    # Flatten output outline to searchable text
    outline_text = _flatten_outline(output_outline).lower()

    missing = [h for h in user_headings if h not in outline_text]
    if missing:
        logger.warning(
            "User headings not preserved in Phase 1 output: %s", missing
        )
        raise ValueError(
            f"Phase 1 output missing user-provided headings: {missing}"
        )


def _flatten_outline(outline: list) -> str:
    """Recursively flatten an outline list into a single searchable string."""
    parts = []
    for item in outline:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.extend(str(v) for v in item.values())
        elif isinstance(item, list):
            parts.append(_flatten_outline(item))
    return " ".join(parts)
