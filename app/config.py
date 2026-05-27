"""
Configuration module for Blog Writer Agent.

Loads secrets from .env via pydantic-settings and app settings from config.yaml.
Configures structured JSON logging.
"""

import logging
import logging.config
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and config.yaml."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        protected_namespaces=("settings_",),
    )

    # --- Secrets from .env ---
    API_KEY: str
    GOOGLE_SERVICE_ACCOUNT_PATH: str
    VERTEX_AI_PROJECT: str
    VERTEX_AI_LOCATION: str

    # --- App settings (loaded from config.yaml, with defaults) ---
    concurrency_limit: int = 3
    task_timeout_seconds: int = 600
    model_name: str = "gemini-1.5-pro"
    labels: dict[str, str] = {
        "service_account": "blog-writer-agent",
        "agent_name": "blog-writer-agent",
        "department": "content",
    }
    drive_folder_id: str = ""
    doc_share_permission: str = "writer"
    sheet_id: str = ""

    @field_validator("API_KEY", mode="before")
    @classmethod
    def api_key_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("API_KEY must not be empty")
        return v


def _load_yaml_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Load config.yaml if it exists, returning an empty dict otherwise."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class JsonFormatter(logging.Formatter):
    """Format log records as JSON strings with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import datetime

        log_entry = {
            "timestamp": datetime.datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Include optional structured fields if set on the record
        for field in ("row_number", "phase", "duration"):
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def _configure_logging() -> None:
    """Configure structured JSON logging using the built-in logging module."""
    # Use direct class reference to avoid circular import issues with dictConfig string lookup
    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Already configured (e.g. during test reloads)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a structured logger for the given module name."""
    return logging.getLogger(name)


def _build_settings() -> Settings:
    """Load YAML config first, then build and validate Settings."""
    yaml_config = _load_yaml_config()

    # Override environment with YAML values (env/.env take precedence for secrets)
    for key, value in yaml_config.items():
        env_key = key.upper()
        if env_key not in os.environ:
            # Set as env var so pydantic-settings picks it up for non-secret fields
            if isinstance(value, dict):
                import json
                os.environ.setdefault(env_key, json.dumps(value))
            else:
                os.environ.setdefault(env_key, str(value))

    return Settings()


# Configure logging at import time
_configure_logging()

# Global settings instance — validates on construction; raises on missing required fields
settings = _build_settings()
