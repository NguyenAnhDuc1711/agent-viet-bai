"""
Tests for Gemini client and pipeline phases 1-4.

All tests mock the Vertex AI SDK to avoid real API calls.
Covers acceptance criteria from Task #010.
"""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import RowData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/tmp/sa.json")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "us-central1")


@pytest.fixture
def sample_row():
    return RowData(
        row_number=1,
        keyword="best running shoes",
        sub_keyword="marathon shoes, trail running",
        outline="",
    )


@pytest.fixture
def sample_row_with_outline():
    return RowData(
        row_number=1,
        keyword="best running shoes",
        sub_keyword="marathon shoes",
        outline="## Top picks for runners\n## How to choose the right shoe\n## Budget-friendly options",
    )


@pytest.fixture
def phase1_output():
    return {
        "strategy": {
            "search_intent": "informational",
            "user_goal": "Find the best running shoes",
            "information_gaps": ["durability comparison", "price analysis"],
            "target_word_count": 2500,
            "data_points": ["80% of runners need neutral shoes"],
        },
        "outline": [
            {
                "level": "h2",
                "heading": "Top picks for runners",
                "keyword_target": "best running shoes",
                "image_planned": True,
                "subsections": [],
            },
            {
                "level": "h2",
                "heading": "How to choose the right shoe",
                "keyword_target": "marathon shoes",
                "image_planned": True,
                "subsections": [],
            },
            {
                "level": "h2",
                "heading": "Budget-friendly options",
                "keyword_target": "trail running",
                "image_planned": True,
                "subsections": [],
            },
        ],
        "keyword_map": {
            "main_keyword": "best running shoes",
            "placement": {"title": True, "sapo": True, "h2_headings": []},
            "sub_keywords": {},
        },
        "visual_plan": [],
    }


def _make_long_article(word_count=2500):
    return " ".join(["word"] * word_count)


def _make_gemini_client_mock():
    """Create a GeminiClient instance with mocked internals."""
    with patch("app.pipeline.gemini_client.vertexai"), \
         patch("app.pipeline.gemini_client.settings") as mock_s:
        mock_s.VERTEX_AI_PROJECT = "test"
        mock_s.VERTEX_AI_LOCATION = "us-central1"
        mock_s.model_name = "gemini-1.5-pro"
        mock_s.labels = {
            "service_account": "blog-writer-agent",
            "agent_name": "blog-writer-agent",
            "department": "content",
        }

        from app.pipeline.gemini_client import GeminiClient

        client = GeminiClient.__new__(GeminiClient)
        client.model_name = "gemini-1.5-pro"
        client.default_labels = dict(mock_s.labels)

        model_instance = MagicMock()
        client.model = model_instance
        return client, model_instance


# ---------------------------------------------------------------------------
# GeminiClient Tests
# ---------------------------------------------------------------------------


class TestGeminiClient:

    @pytest.mark.asyncio
    async def test_labels_include_config_defaults(self):
        """FR-9: Labels include service_account, agent_name, department."""
        client, model = _make_gemini_client_mock()
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        model.generate_content.return_value = mock_response

        with patch("app.pipeline.gemini_client.GenerativeModel", return_value=model):
            result = await client.generate("test", labels={"phase": "research"})

        call_kwargs = model.generate_content.call_args
        labels = call_kwargs.kwargs["labels"]
        assert labels["service_account"] == "blog-writer-agent"
        assert labels["agent_name"] == "blog-writer-agent"
        assert labels["department"] == "content"
        assert labels["phase"] == "research"
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        """Retry on ServiceUnavailable, succeed on third attempt."""
        from google.api_core import exceptions as gexc

        client, model = _make_gemini_client_mock()
        mock_response = MagicMock()
        mock_response.text = "Success"
        model.generate_content.side_effect = [
            gexc.ServiceUnavailable("unavailable"),
            gexc.ServiceUnavailable("unavailable"),
            mock_response,
        ]

        with patch("app.pipeline.gemini_client.GenerativeModel", return_value=model):
            result = await client.generate("test")

        assert result == "Success"
        assert model.generate_content.call_count == 3

    @pytest.mark.asyncio
    async def test_json_mode_sets_response_mime_type(self):
        """JSON mode includes response_mime_type='application/json' in config."""
        client, model = _make_gemini_client_mock()
        mock_response = MagicMock()
        mock_response.text = '{"key": "value"}'
        model.generate_content.return_value = mock_response

        with patch("app.pipeline.gemini_client.GenerativeModel", return_value=model):
            result = await client.generate_json("test")

        call_kwargs = model.generate_content.call_args
        gen_config = call_kwargs.kwargs["generation_config"]
        assert gen_config._raw_generation_config.response_mime_type == "application/json"
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_json_validation_retry(self):
        """FR-9: Retries once with JSON-fix instruction on malformed JSON."""
        client, model = _make_gemini_client_mock()
        bad_resp = MagicMock()
        bad_resp.text = "not valid json {{"
        good_resp = MagicMock()
        good_resp.text = '{"valid": true}'
        model.generate_content.side_effect = [bad_resp, good_resp]

        with patch("app.pipeline.gemini_client.GenerativeModel", return_value=model):
            result = await client.generate_json("test prompt")

        assert result == {"valid": True}
        assert model.generate_content.call_count == 2
        second_call_prompt = model.generate_content.call_args_list[1].args[0]
        assert "Return ONLY valid JSON" in second_call_prompt


# ---------------------------------------------------------------------------
# Phase 1 Tests
# ---------------------------------------------------------------------------


class TestPhase1:

    @pytest.mark.asyncio
    async def test_output_structure(self, sample_row, phase1_output):
        """FR-3: Output contains strategy, outline, keyword_map keys."""
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=phase1_output)

        with patch("app.pipeline.phase1_research.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {keyword} {sub_keyword} {outline}"
            from app.pipeline.phase1_research import run_phase1

            result = await run_phase1(mock_client, sample_row)

        assert "strategy" in result
        assert "outline" in result
        assert "keyword_map" in result

    @pytest.mark.asyncio
    async def test_preserves_user_outline(self, sample_row_with_outline, phase1_output):
        """FR-3: All user-provided headings preserved in output."""
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=phase1_output)

        with patch("app.pipeline.phase1_research.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {keyword} {sub_keyword} {outline}"
            from app.pipeline.phase1_research import run_phase1

            result = await run_phase1(mock_client, sample_row_with_outline)

        outline_text = json.dumps(result["outline"]).lower()
        assert "top picks for runners" in outline_text
        assert "how to choose the right shoe" in outline_text
        assert "budget-friendly options" in outline_text

    @pytest.mark.asyncio
    async def test_missing_keys_raises(self, sample_row):
        """Raises ValueError when response lacks required keys."""
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value={"strategy": {}})

        with patch("app.pipeline.phase1_research.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {keyword} {sub_keyword} {outline}"
            from app.pipeline.phase1_research import run_phase1

            with pytest.raises(ValueError, match="missing required keys"):
                await run_phase1(mock_client, sample_row)


# ---------------------------------------------------------------------------
# Phase 2 Tests
# ---------------------------------------------------------------------------


class TestPhase2:

    @pytest.mark.asyncio
    async def test_word_count_pass(self, sample_row, phase1_output):
        """FR-4: Article with >= 2000 words passes."""
        article = _make_long_article(2500)
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=article)

        with patch("app.pipeline.phase2_writing.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {keyword} {research_output} {feedback}"
            from app.pipeline.phase2_writing import run_phase2

            result = await run_phase2(mock_client, sample_row, phase1_output)

        assert len(result.split()) >= 2000

    @pytest.mark.asyncio
    async def test_below_word_count_raises(self, sample_row, phase1_output):
        """FR-4: Article with < 2000 words raises ValueError."""
        article = _make_long_article(500)
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=article)

        with patch("app.pipeline.phase2_writing.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {keyword} {research_output} {feedback}"
            from app.pipeline.phase2_writing import run_phase2

            with pytest.raises(ValueError, match="below minimum"):
                await run_phase2(mock_client, sample_row, phase1_output)


# ---------------------------------------------------------------------------
# Phase 3 Tests
# ---------------------------------------------------------------------------


class TestPhase3:

    @pytest.mark.asyncio
    async def test_dual_threshold_pass(self, phase1_output):
        """FR-5: Total >= 70 and all categories >= 50% max => passed=True."""
        scores = {
            "scores": {"content": 25, "seo": 20, "eeat": 12, "technical": 12, "ai_citation": 12},
            "total": 81,
            "passed": True,
            "feedback": "",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=scores)

        with patch("app.pipeline.phase3_quality.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword} {research_output}"
            from app.pipeline.phase3_quality import run_phase3

            result = await run_phase3(mock_client, "article", "keyword", phase1_output)

        assert result["passed"] is True
        assert result["total"] == 81

    @pytest.mark.asyncio
    async def test_dual_threshold_fail_total(self, phase1_output):
        """FR-5: Total < 70 => passed=False."""
        scores = {
            "scores": {"content": 15, "seo": 12.5, "eeat": 8, "technical": 8, "ai_citation": 8},
            "total": 51.5,
            "passed": False,
            "feedback": "Total below threshold",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=scores)

        with patch("app.pipeline.phase3_quality.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword} {research_output}"
            from app.pipeline.phase3_quality import run_phase3

            result = await run_phase3(mock_client, "article", "keyword", phase1_output)

        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_dual_threshold_fail_category(self, phase1_output):
        """FR-5: Total >= 70 but content < 50% of 30 => passed=False."""
        scores = {
            "scores": {"content": 10, "seo": 20, "eeat": 15, "technical": 15, "ai_citation": 15},
            "total": 75,
            "passed": True,  # Will be overridden
            "feedback": "",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=scores)

        with patch("app.pipeline.phase3_quality.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword} {research_output}"
            from app.pipeline.phase3_quality import run_phase3

            result = await run_phase3(mock_client, "article", "keyword", phase1_output)

        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Phase 4 Tests
# ---------------------------------------------------------------------------


class TestPhase4:

    @pytest.mark.asyncio
    async def test_title_length_accepted(self):
        """FR-6: Title 52 chars is accepted."""
        metadata = {
            "title": "Best Running Shoes for Marathon Training Guide Here",  # 52 chars
            "description": (
                "Discover the best running shoes for marathon training with our expert reviews, detailed "
                "comparisons, and top picks to help you find your perfect pair."
            ),  # 153 chars
            "h1": "Best Running Shoes for Marathon Training",
            "url_slug": "best-running-shoes",
        }
        assert 50 <= len(metadata["title"]) <= 60
        assert 150 <= len(metadata["description"]) <= 160

        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=metadata)

        with patch("app.pipeline.phase4_metadata.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword}"
            from app.pipeline.phase4_metadata import run_phase4

            result = await run_phase4(mock_client, "article", "best running shoes")

        assert result["title"] == metadata["title"]

    @pytest.mark.asyncio
    async def test_slug_format(self):
        """FR-6: Kebab-case slug is accepted."""
        metadata = {
            "title": "Best Running Shoes for Marathon Training Guide Here",
            "description": (
                "Discover the best running shoes for marathon training with our expert reviews, detailed "
                "comparisons, and top picks to help you find your perfect pair."
            ),
            "h1": "Best Running Shoes for Marathon Training",
            "url_slug": "best-running-shoes",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=metadata)

        with patch("app.pipeline.phase4_metadata.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword}"
            from app.pipeline.phase4_metadata import run_phase4

            result = await run_phase4(mock_client, "article", "best running shoes")

        assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", result["url_slug"])

    @pytest.mark.asyncio
    async def test_invalid_title_length_raises(self):
        """FR-6: Title outside 50-60 chars raises ValueError."""
        metadata = {
            "title": "Short",
            "description": "x" * 155,
            "h1": "Heading",
            "url_slug": "short",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=metadata)

        with patch("app.pipeline.phase4_metadata.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword}"
            from app.pipeline.phase4_metadata import run_phase4

            with pytest.raises(ValueError, match="Title length"):
                await run_phase4(mock_client, "article", "keyword")

    @pytest.mark.asyncio
    async def test_invalid_slug_raises(self):
        """FR-6: Non-kebab-case slug raises ValueError."""
        metadata = {
            "title": "Best Running Shoes for Marathon Training Guide Here",
            "description": (
                "Discover the best running shoes for marathon training with our expert reviews, detailed "
                "comparisons, and top picks to help you find your perfect pair."
            ),
            "h1": "Heading",
            "url_slug": "Best Running Shoes",
        }
        mock_client = AsyncMock()
        mock_client.generate_json = AsyncMock(return_value=metadata)

        with patch("app.pipeline.phase4_metadata.PROMPT_PATH") as mock_path:
            mock_path.read_text.return_value = "Prompt {article} {keyword}"
            from app.pipeline.phase4_metadata import run_phase4

            with pytest.raises(ValueError, match="not kebab-case"):
                await run_phase4(mock_client, "article", "keyword")
