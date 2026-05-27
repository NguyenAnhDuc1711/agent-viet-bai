"""
Tests for Phase 3 quality gate dual-threshold logic.

Covers boundary cases for the dual-threshold pass/fail:
  - total >= 70 AND each category >= 50% of its max => pass
  - total < 70 => fail
  - any category < 50% of its max => fail (even if total >= 70)
  - exact boundary values (70 total, 50% per-category)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.pipeline.phase3_quality import _check_dual_threshold, CATEGORY_MAX, CATEGORY_MIN


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")


# ---------------------------------------------------------------------------
# Unit tests for _check_dual_threshold
# ---------------------------------------------------------------------------


def test_dual_threshold_pass_all_above():
    """Total >= 70 and all categories >= 50% of max => True."""
    scores = {"content": 20, "seo": 18, "eeat": 10, "technical": 12, "ai_citation": 12}
    total = sum(scores.values())  # 72
    assert total >= 70
    assert _check_dual_threshold(scores, total) is True


def test_dual_threshold_fail_total_below_70():
    """Total < 70 => False regardless of per-category scores."""
    scores = {"content": 15, "seo": 13, "eeat": 8, "technical": 8, "ai_citation": 8}
    total = sum(scores.values())  # 52
    assert total < 70
    assert _check_dual_threshold(scores, total) is False


def test_dual_threshold_fail_category_below_50pct():
    """Total >= 70 but one category < 50% of max => False."""
    # content max = 30, so 50% = 15.  Score 14 should fail.
    scores = {"content": 14, "seo": 20, "eeat": 12, "technical": 12, "ai_citation": 12}
    total = sum(scores.values())  # 70
    assert total >= 70
    assert _check_dual_threshold(scores, total) is False


def test_boundary_total_exactly_70_pass():
    """Total exactly 70 with all categories >= 50% => True."""
    # Build scores: content=15 (50%), seo=13 (52%), eeat=8 (53%), technical=8 (53%), ai_citation=8 (53%)
    # But 15+13+8+8+8 = 52, not 70. Need higher values.
    # content=20, seo=18, eeat=12, technical=10, ai_citation=10 = 70
    scores = {"content": 20, "seo": 18, "eeat": 12, "technical": 10, "ai_citation": 10}
    total = sum(scores.values())  # 70
    assert total == 70
    # All >= 50% of max: content 20/30=67%, seo 18/25=72%, eeat 12/15=80%, technical 10/15=67%, ai 10/15=67%
    assert _check_dual_threshold(scores, total) is True


def test_boundary_total_exactly_69_fail():
    """Total exactly 69 => False."""
    scores = {"content": 19, "seo": 18, "eeat": 12, "technical": 10, "ai_citation": 10}
    total = sum(scores.values())  # 69
    assert total == 69
    assert _check_dual_threshold(scores, total) is False


def test_boundary_category_exactly_50pct_pass():
    """Category exactly at 50% of max with total >= 70 => True."""
    # content max=30, 50%=15.0. Score exactly 15 should pass.
    # seo max=25, 50%=12.5. Score exactly 12.5 should pass.
    scores = {"content": 15, "seo": 15, "eeat": 15, "technical": 15, "ai_citation": 15}
    total = sum(scores.values())  # 75
    assert total >= 70
    # content: 15/30=50%, seo: 15/25=60%, eeat: 15/15=100%, etc.
    assert _check_dual_threshold(scores, total) is True


def test_boundary_category_just_below_50pct_fail():
    """Category just below 50% of max with total >= 70 => False."""
    # seo max=25, 50%=12.5.  Score 12 is below 12.5.
    scores = {"content": 20, "seo": 12, "eeat": 15, "technical": 15, "ai_citation": 15}
    total = sum(scores.values())  # 77
    assert total >= 70
    assert _check_dual_threshold(scores, total) is False


def test_category_min_values_are_correct():
    """Verify CATEGORY_MIN is 50% of CATEGORY_MAX for all categories."""
    for cat, max_val in CATEGORY_MAX.items():
        assert CATEGORY_MIN[cat] == max_val * 0.5, f"{cat}: expected {max_val * 0.5}, got {CATEGORY_MIN[cat]}"


# ---------------------------------------------------------------------------
# Integration test: run_phase3 applies dual threshold override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase3_overrides_llm_passed_flag():
    """run_phase3 recalculates 'passed' even if LLM returns passed=True incorrectly."""
    # LLM says passed=True but content score (10) is below 50% of 30 (15)
    llm_response = {
        "scores": {"content": 10, "seo": 20, "eeat": 15, "technical": 15, "ai_citation": 15},
        "total": 75,
        "passed": True,  # Incorrect — should be overridden to False
        "feedback": "",
    }
    mock_client = AsyncMock()
    mock_client.generate_json = AsyncMock(return_value=llm_response)

    with patch("app.pipeline.phase3_quality.PROMPT_PATH") as mock_path:
        mock_path.read_text.return_value = "Prompt {article} {keyword} {research_output}"
        from app.pipeline.phase3_quality import run_phase3

        result = await run_phase3(mock_client, "article text", "keyword", {"strategy": {}})

    assert result["passed"] is False, "Should override LLM's incorrect passed=True"
