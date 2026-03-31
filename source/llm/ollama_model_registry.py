"""Ollama model capability hints for LiteLLM.

LiteLLM can fall back to JSON-mode tool calling for Ollama models when
function-calling support is unknown. For known-capable model families, we
register a lightweight per-model capability hint so LiteLLM prefers native
tool calling.
"""

from __future__ import annotations

import logging
import os

import litellm

logger = logging.getLogger(__name__)

_DEFAULT_NATIVE_FUNCTION_CALLING_PREFIXES = (
    "llama3.1",
    "llama3.2",
    "qwen2.5",
    "qwen3",
)
_REGISTERED_MODELS: set[str] = set()


def _native_function_calling_prefixes() -> tuple[str, ...]:
    raw = os.getenv("XPDITE_OLLAMA_NATIVE_FC_PREFIXES", "").strip()
    if not raw:
        return _DEFAULT_NATIVE_FUNCTION_CALLING_PREFIXES
    parsed = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return parsed or _DEFAULT_NATIVE_FUNCTION_CALLING_PREFIXES


def _bare_ollama_model(litellm_model: str) -> str:
    if not litellm_model.startswith("ollama_chat/"):
        return ""
    return litellm_model.partition("/")[2].strip().lower()


def should_hint_native_function_calling(litellm_model: str) -> bool:
    bare_model = _bare_ollama_model(litellm_model)
    if not bare_model:
        return False
    return any(
        bare_model.startswith(prefix) for prefix in _native_function_calling_prefixes()
    )


def register_ollama_native_function_calling_hint(litellm_model: str) -> bool:
    """Register ``supports_function_calling`` hint for known Ollama model families.

    Returns ``True`` only when a new hint was registered in this process.
    """
    if litellm_model in _REGISTERED_MODELS:
        return False
    if not should_hint_native_function_calling(litellm_model):
        return False

    register_model = getattr(litellm, "register_model", None)
    if register_model is None:
        return False

    try:
        register_model(
            model_cost={
                litellm_model: {
                    "supports_function_calling": True,
                }
            }
        )
    except Exception as exc:
        logger.debug(
            "Failed to register Ollama function-calling hint for %s (%s)",
            litellm_model,
            type(exc).__name__,
        )
        return False

    _REGISTERED_MODELS.add(litellm_model)
    logger.debug("Registered Ollama function-calling hint for %s", litellm_model)
    return True
