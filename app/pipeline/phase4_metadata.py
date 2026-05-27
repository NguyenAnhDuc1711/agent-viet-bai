"""
Phase 4: Metadata Extraction.

Generates SEO metadata (title, description, h1, url_slug) from a
quality-approved article.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_logger

if TYPE_CHECKING:
    from app.pipeline.gemini_client import GeminiClient

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/phase4_metadata.md")

KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


async def run_phase4(
    client: GeminiClient,
    article: str,
    keyword: str,
) -> dict:
    """Execute Phase 4: Metadata Extraction.

    Args:
        client: Initialized GeminiClient.
        article: Quality-approved markdown article.
        keyword: Main keyword.

    Returns:
        Dict with title, description, h1, url_slug.

    Raises:
        ValueError: If metadata does not meet constraints.
    """
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{article}", article)
    prompt = prompt.replace("{keyword}", keyword)

    system_instruction = (
        "You are an expert SEO metadata specialist. "
        "Extract optimized metadata from the article."
    )

    result = await client.generate_json(
        prompt=prompt,
        system_instruction=system_instruction,
        labels={"phase": "metadata"},
    )

    _validate_metadata(result)

    logger.info(
        "Phase 4 completed",
        extra={"phase": "metadata"},
    )

    return result


def _validate_metadata(metadata: dict) -> None:
    """Validate metadata meets SEO constraints.

    Raises:
        ValueError: If any constraint is violated.
    """
    required_keys = {"title", "description", "h1", "url_slug"}
    missing = required_keys - set(metadata.keys())
    if missing:
        raise ValueError(f"Metadata missing required keys: {missing}")

    title = metadata["title"]
    if not (50 <= len(title) <= 60):
        raise ValueError(
            f"Title length {len(title)} not in range [50, 60]: '{title}'"
        )

    description = metadata["description"]
    if not (150 <= len(description) <= 160):
        raise ValueError(
            f"Description length {len(description)} not in range [150, 160]: '{description}'"
        )

    slug = metadata["url_slug"]
    if not KEBAB_CASE_PATTERN.match(slug):
        raise ValueError(f"Slug is not kebab-case: '{slug}'")
