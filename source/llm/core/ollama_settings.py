"""Persisted Ollama runtime settings."""

from __future__ import annotations

import logging
from typing import Any

from ...infrastructure.config import OLLAMA_CTX_SIZE

logger = logging.getLogger(__name__)

OLLAMA_LOCAL_CONTEXT_SIZE_SETTING = "ollama_local_context_size"
OLLAMA_LOCAL_CONTEXT_SIZE_MIN = 512
OLLAMA_LOCAL_CONTEXT_SIZE_MAX = 1_048_576


def normalize_ollama_context_size(value: Any) -> int | None:
    """Return a valid Ollama context size or ``None``."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    if (
        parsed < OLLAMA_LOCAL_CONTEXT_SIZE_MIN
        or parsed > OLLAMA_LOCAL_CONTEXT_SIZE_MAX
    ):
        return None
    return parsed


def get_local_ollama_context_size() -> int:
    """Return the configured ``num_ctx`` for local Ollama models."""
    try:
        from ...infrastructure.database import db

        stored = db.get_setting(OLLAMA_LOCAL_CONTEXT_SIZE_SETTING)
    except Exception as exc:
        logger.debug("Could not read Ollama context setting: %s", exc)
        return OLLAMA_CTX_SIZE

    configured = normalize_ollama_context_size(stored)
    return configured if configured is not None else OLLAMA_CTX_SIZE


def get_local_ollama_options() -> dict[str, int]:
    """Return Ollama chat options for local model calls."""
    return {"num_ctx": get_local_ollama_context_size()}


def get_ollama_settings_payload() -> dict[str, int | bool]:
    """Return the public settings payload for the Ollama settings tab."""
    try:
        from ...infrastructure.database import db

        stored = db.get_setting(OLLAMA_LOCAL_CONTEXT_SIZE_SETTING)
    except Exception as exc:
        logger.debug("Could not read Ollama settings payload: %s", exc)
        stored = None

    configured = normalize_ollama_context_size(stored)
    return {
        "local_context_size": configured if configured is not None else OLLAMA_CTX_SIZE,
        "default_local_context_size": OLLAMA_CTX_SIZE,
        "min_local_context_size": OLLAMA_LOCAL_CONTEXT_SIZE_MIN,
        "max_local_context_size": OLLAMA_LOCAL_CONTEXT_SIZE_MAX,
        "is_custom": configured is not None,
    }


def set_local_ollama_context_size(value: int | None) -> dict[str, int | bool]:
    """Persist or reset the local Ollama context size."""
    try:
        from ...infrastructure.database import db

        if value is None:
            db.delete_setting(OLLAMA_LOCAL_CONTEXT_SIZE_SETTING)
            return get_ollama_settings_payload()

        normalized = normalize_ollama_context_size(value)
        if normalized is None:
            raise ValueError(
                "Local Ollama context size must be between "
                f"{OLLAMA_LOCAL_CONTEXT_SIZE_MIN} and {OLLAMA_LOCAL_CONTEXT_SIZE_MAX}"
            )

        db.set_setting(OLLAMA_LOCAL_CONTEXT_SIZE_SETTING, str(normalized))
        return get_ollama_settings_payload()
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Could not save Ollama context setting: %s", exc)
        raise
