"""Ollama model capability hints for LiteLLM.

Hints are only registered when launch-time metadata already indicates native
function-calling support for that exact model.
"""

from __future__ import annotations

import logging
from typing import Any

import litellm
import requests

from .provider_resolution import DEFAULT_OLLAMA_API_BASE

logger = logging.getLogger(__name__)

_REGISTERED_MODELS: set[str] = set()
_METADATA_TOOL_SUPPORT_CACHE: dict[str, bool] = {}


def _bare_ollama_model(litellm_model: str) -> str:
    if not litellm_model.startswith("ollama_chat/"):
        return ""
    return litellm_model.partition("/")[2].strip().lower()


def _supports_tools_from_launch_metadata(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False

    capabilities = metadata.get("capabilities")
    if isinstance(capabilities, list):
        lowered = {str(item).strip().lower() for item in capabilities}
        if "tools" in lowered or "tool" in lowered:
            return True

    return any(
        metadata.get(key) is True
        for key in (
            "supports_function_calling",
            "supports_tools",
            "tool_calling",
        )
    )


def _fetch_launch_metadata(bare_model: str) -> dict[str, Any] | None:
    cached = _METADATA_TOOL_SUPPORT_CACHE.get(bare_model)
    if cached is not None:
        return {"supports_tools": cached}

    try:
        response = requests.post(
            f"{DEFAULT_OLLAMA_API_BASE}/api/show",
            json={"model": bare_model},
            timeout=2,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        _METADATA_TOOL_SUPPORT_CACHE[bare_model] = False
        return None

    supported = _supports_tools_from_launch_metadata(payload)
    _METADATA_TOOL_SUPPORT_CACHE[bare_model] = supported
    return payload


def should_hint_native_function_calling(
    litellm_model: str,
    model_info: dict[str, Any] | None = None,
) -> bool:
    bare_model = _bare_ollama_model(litellm_model)
    if not bare_model:
        return False

    if model_info and model_info.get("supports_function_calling") is True:
        return True

    metadata = _fetch_launch_metadata(bare_model)
    return _supports_tools_from_launch_metadata(metadata)


def register_ollama_native_function_calling_hint(
    litellm_model: str,
    model_info: dict[str, Any] | None = None,
) -> bool:
    """Register ``supports_function_calling`` hint when metadata confirms support.

    Returns ``True`` only when a new hint was registered in this process.
    """
    if litellm_model in _REGISTERED_MODELS:
        return False
    if not should_hint_native_function_calling(litellm_model, model_info):
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
