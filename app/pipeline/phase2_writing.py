"""
Phase 2: Content Writing.

Produces a complete markdown article from Phase 1 research output,
following SKILL.md writing rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_logger
from app.models import RowData

if TYPE_CHECKING:
    from app.pipeline.gemini_client import GeminiClient

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/phase2_writing.md")
MIN_WORD_COUNT = 2000


async def run_phase2(
    client: GeminiClient,
    row: RowData,
    research: dict,
    feedback: str = "",
) -> str:
    """Execute Phase 2: Content Writing.

    Args:
        client: Initialized GeminiClient.
        row: Row data with keyword info.
        research: Phase 1 research output dict.
        feedback: Quality gate feedback for retry (empty on first attempt).

    Returns:
        Complete markdown article string.

    Raises:
        ValueError: If article is below minimum word count.
    """
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{keyword}", row.keyword)
    prompt = prompt.replace("{research_output}", json.dumps(research, indent=2))
    prompt = prompt.replace("{feedback}", feedback)

    system_instruction = (
        "You are an expert blog content writer. "
        "Write a complete, publication-ready markdown article."
    )

    article = await client.generate(
        prompt=prompt,
        system_instruction=system_instruction,
        json_mode=False,
        labels={"phase": "writing"},
    )

    # Validate word count
    word_count = len(article.split())
    if word_count < MIN_WORD_COUNT:
        raise ValueError(
            f"Article word count {word_count} is below minimum {MIN_WORD_COUNT}"
        )

    logger.info(
        "Phase 2 completed: %d words",
        word_count,
        extra={"phase": "writing"},
    )

    return article
