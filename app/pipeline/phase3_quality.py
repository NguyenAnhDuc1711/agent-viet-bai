"""
Phase 3: Quality Gate.

Scores an article across 5 categories and applies dual-threshold
pass/fail logic (total >= 70 AND each category >= 50% of its max).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_logger

if TYPE_CHECKING:
    from app.pipeline.gemini_client import GeminiClient

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/phase3_quality.md")

# Category maximums and their 50% thresholds
CATEGORY_MAX = {
    "content": 30,
    "seo": 25,
    "eeat": 15,
    "technical": 15,
    "ai_citation": 15,
}

CATEGORY_MIN = {k: v * 0.5 for k, v in CATEGORY_MAX.items()}

TOTAL_THRESHOLD = 70


async def run_phase3(
    client: GeminiClient,
    article: str,
    keyword: str,
    research: dict,
) -> dict:
    """Execute Phase 3: Quality Gate.

    Args:
        client: Initialized GeminiClient.
        article: Markdown article from Phase 2.
        keyword: Main keyword for evaluation context.
        research: Phase 1 research output for reference.

    Returns:
        Dict with scores, total, feedback, and passed fields.

    Raises:
        ValueError: If scores are invalid or out of range.
    """
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{article}", article)
    prompt = prompt.replace("{keyword}", keyword)
    prompt = prompt.replace("{research_output}", json.dumps(research, indent=2))

    system_instruction = (
        "You are an expert content quality assessor. "
        "Score the article across all quality categories."
    )

    result = await client.generate_json(
        prompt=prompt,
        system_instruction=system_instruction,
        labels={"phase": "quality_gate"},
    )

    # Validate and normalize scores
    scores = result.get("scores", {})
    _validate_scores(scores)

    total = sum(scores.values())
    passed = _check_dual_threshold(scores, total)

    result["scores"] = scores
    result["total"] = total
    result["passed"] = passed

    logger.info(
        "Phase 3 completed: total=%d, passed=%s",
        total,
        passed,
        extra={"phase": "quality_gate"},
    )

    return result


def _validate_scores(scores: dict) -> None:
    """Validate that all required score categories are present and in range.

    Raises:
        ValueError: If a category is missing or a score is out of range.
    """
    for category, max_val in CATEGORY_MAX.items():
        if category not in scores:
            raise ValueError(f"Missing score category: {category}")
        score = scores[category]
        if not isinstance(score, (int, float)):
            raise ValueError(f"Score for {category} is not numeric: {score}")
        if score < 0 or score > max_val:
            raise ValueError(
                f"Score for {category} ({score}) out of range [0, {max_val}]"
            )


def _check_dual_threshold(scores: dict, total: float) -> bool:
    """Apply dual-threshold pass/fail logic.

    Checks BOTH:
    - total >= 70
    - each category >= 50% of its max

    Returns:
        True if both conditions are met.
    """
    if total < TOTAL_THRESHOLD:
        return False

    for category, min_val in CATEGORY_MIN.items():
        if scores.get(category, 0) < min_val:
            return False

    return True
