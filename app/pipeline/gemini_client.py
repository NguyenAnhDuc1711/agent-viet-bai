"""
Vertex AI Gemini client wrapper.

Provides centralized access to Gemini with label tracking for billing,
tenacity retry for transient errors, and JSON response validation with
format-specific retry.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import vertexai
from google.api_core import exceptions as google_exceptions
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from vertexai.generative_models import GenerationConfig, GenerativeModel

from app.config import get_logger, settings

logger = get_logger(__name__)

_vertex_initialized = False


def _ensure_vertex_init() -> None:
    """Initialize Vertex AI once (lazy, to support testing)."""
    global _vertex_initialized
    if not _vertex_initialized:
        vertexai.init(
            project=settings.VERTEX_AI_PROJECT,
            location=settings.VERTEX_AI_LOCATION,
        )
        _vertex_initialized = True


class GeminiClient:
    """Centralized Gemini API wrapper with labels, retry, and JSON validation."""

    def __init__(self, model_name: Optional[str] = None):
        _ensure_vertex_init()
        self.model_name = model_name or settings.model_name
        self.model = GenerativeModel(self.model_name)
        self.default_labels = dict(settings.labels)

    def _merge_labels(self, extra_labels: Optional[dict] = None) -> dict:
        """Merge default labels from config with call-specific labels."""
        labels = dict(self.default_labels)
        if extra_labels:
            labels.update(extra_labels)
        return labels

    @retry(
        retry=retry_if_exception_type(
            (
                google_exceptions.ServiceUnavailable,
                google_exceptions.ResourceExhausted,
                google_exceptions.DeadlineExceeded,
            )
        ),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        json_mode: bool = False,
        labels: Optional[dict] = None,
    ) -> str:
        """Generate content from Gemini with retry on transient errors.

        Args:
            prompt: The user prompt.
            system_instruction: System-level instruction for the model.
            json_mode: If True, set response_mime_type to application/json.
            labels: Additional labels to merge with defaults.

        Returns:
            The generated text response.
        """
        merged_labels = self._merge_labels(labels)

        config_kwargs = {
            "temperature": 0.7,
            "max_output_tokens": 8192,
        }
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        generation_config = GenerationConfig(**config_kwargs)

        # Build model with system instruction if provided
        model = self.model
        if system_instruction:
            model = GenerativeModel(
                self.model_name,
                system_instruction=[system_instruction],
            )

        logger.info(
            "Calling Gemini API",
            extra={"phase": merged_labels.get("phase", "unknown")},
        )

        response = model.generate_content(
            prompt,
            generation_config=generation_config,
            labels=merged_labels,
        )

        return response.text

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str = "",
        labels: Optional[dict] = None,
    ) -> dict:
        """Generate and parse JSON response with validation retry.

        Calls generate() with json_mode=True, parses the response as JSON.
        On JSONDecodeError, retries once with a JSON-fix instruction appended.
        Max 2 JSON validation attempts total.

        Args:
            prompt: The user prompt.
            system_instruction: System-level instruction.
            labels: Additional labels.

        Returns:
            Parsed JSON as a dict.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 2 attempts.
        """
        for attempt in range(2):
            current_prompt = prompt
            if attempt > 0:
                current_prompt = (
                    prompt
                    + "\n\nYour previous response was not valid JSON. "
                    "Return ONLY valid JSON with no markdown formatting."
                )
                logger.warning("JSON validation retry (attempt %d)", attempt + 1)

            text = await self.generate(
                prompt=current_prompt,
                system_instruction=system_instruction,
                json_mode=True,
                labels=labels,
            )

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                if attempt == 1:
                    logger.error("JSON parsing failed after 2 attempts")
                    raise

        # Should not reach here, but satisfy type checker
        raise json.JSONDecodeError("Unreachable", "", 0)  # pragma: no cover
