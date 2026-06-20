"""Configuration and JSON policy loading.

Centralizes application settings and the "policy-as-data" loaders used across
the platform. All rules, weights, and runbooks live in JSON files under
``backend/rules/`` (created in task 1.4); this module provides cached access to
them plus general environment-driven settings.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("clover.config")

# Resolve key directories relative to this file (backend/core/config.py).
BACKEND_DIR = Path(__file__).resolve().parent.parent
RULES_DIR = BACKEND_DIR / "rules"
MOCK_DATA_DIR = BACKEND_DIR / "mock_data"
ML_MODELS_DIR = BACKEND_DIR / "ml" / "models"


class Settings:
    """Runtime settings sourced from environment variables with defaults."""

    def __init__(self) -> None:
        self.app_name: str = "Clover Cloud Intelligence Platform"
        self.app_version: str = "0.1.0"
        # Default SQLite DB lives alongside the backend package.
        self.database_path: str = os.getenv(
            "CLOVER_DB_PATH", str(BACKEND_DIR / "clover.db")
        )
        # CORS origins (comma separated). Defaults to the Vite dev servers.
        self.cors_origins: list[str] = self._parse_origins(
            os.getenv(
                "CLOVER_CORS_ORIGINS",
                "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
            )
        )
        self.log_level: str = os.getenv("CLOVER_LOG_LEVEL", "INFO").upper()

    @staticmethod
    def _parse_origins(raw: str) -> list[str]:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


def load_json_config(path: Path | str) -> Any:
    """Load and parse a JSON config file.

    Raises:
        FileNotFoundError: if the file does not exist.
        json.JSONDecodeError: if the file contains invalid JSON.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=None)
def load_policy(name: str) -> Any:
    """Load a named JSON policy file from ``backend/rules/``.

    ``name`` may be given with or without the ``.json`` suffix, e.g.
    ``load_policy("scoring_weights")`` or ``load_policy("scoring_weights.json")``.
    Results are cached; call :func:`clear_policy_cache` after editing files.
    """
    filename = name if name.endswith(".json") else f"{name}.json"
    policy_path = RULES_DIR / filename
    logger.debug("Loading policy %s", policy_path)
    return load_json_config(policy_path)


def clear_policy_cache() -> None:
    """Clear the cached policy files (useful in tests or after hot edits)."""
    load_policy.cache_clear()
