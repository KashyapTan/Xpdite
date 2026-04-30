"""Model context-window resolution helpers.

The chat UI should not guess context limits.  Cloud models use LiteLLM's
registry metadata; Ollama models use local ``/api/show`` metadata plus the
configured ``num_ctx`` this app sends with generation requests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import litellm
from ollama import AsyncClient as OllamaAsyncClient

from ...infrastructure.config import OLLAMA_CTX_SIZE

logger = logging.getLogger(__name__)

_NUM_CTX_RE = re.compile(r"(?:^|\s)num_ctx\s+(\d+)(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class ModelContextWindow:
    """Resolved model context-window metadata."""

    model: str
    context_window: Optional[int]
    source: str


def _positive_int(value: Any) -> Optional[int]:
    """Return ``value`` as a positive int when possible."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _strip_ollama_prefix(model_name: str) -> str:
    normalized = model_name.strip()
    if normalized.lower().startswith("ollama/"):
        return normalized.partition("/")[2].strip()
    return normalized


def _extract_ollama_native_context(model_info: Mapping[str, Any] | None) -> Optional[int]:
    """Extract the native context length from Ollama ``model_info`` metadata."""
    if not model_info:
        return None

    values: list[int] = []
    for key, value in model_info.items():
        if not str(key).endswith(".context_length"):
            continue
        parsed = _positive_int(value)
        if parsed is not None:
            values.append(parsed)

    return max(values) if values else None


def _extract_ollama_num_ctx(parameters: str | None) -> Optional[int]:
    """Extract ``num_ctx`` from Ollama's serialized parameter text."""
    if not parameters:
        return None
    match = _NUM_CTX_RE.search(parameters)
    if not match:
        return None
    return _positive_int(match.group(1))


def _effective_ollama_context_window(
    *,
    native_context: Optional[int],
    model_num_ctx: Optional[int],
    configured_num_ctx: int = OLLAMA_CTX_SIZE,
) -> tuple[Optional[int], str]:
    """Return the context window Xpdite will actually request from Ollama."""
    configured = _positive_int(configured_num_ctx)
    if configured is not None:
        if native_context is not None:
            return min(configured, native_context), "ollama_show+configured_num_ctx"
        return configured, "configured_num_ctx"

    if model_num_ctx is not None:
        if native_context is not None:
            return min(model_num_ctx, native_context), "ollama_show+model_num_ctx"
        return model_num_ctx, "ollama_model_num_ctx"

    if native_context is not None:
        return native_context, "ollama_show"

    return None, "unknown"


def _effective_ollama_cloud_context_window(
    *,
    native_context: Optional[int],
    model_num_ctx: Optional[int],
) -> tuple[Optional[int], str]:
    """Return the maximum context advertised for an Ollama cloud model."""
    if native_context is not None:
        return native_context, "ollama_cloud_show"

    if model_num_ctx is not None:
        return model_num_ctx, "ollama_cloud_model_num_ctx"

    return None, "unknown"


async def _resolve_ollama_context_window(model_name: str) -> ModelContextWindow:
    """Resolve the effective context window for an Ollama model."""
    from .router import is_ollama_cloud_model

    normalized_model = _strip_ollama_prefix(model_name)
    if not normalized_model:
        return ModelContextWindow(model=model_name, context_window=None, source="unknown")

    is_cloud_model = is_ollama_cloud_model(normalized_model)

    try:
        response = await OllamaAsyncClient().show(normalized_model)
    except Exception as exc:
        logger.debug(
            "Could not resolve Ollama context window for %s: %s",
            normalized_model,
            exc,
        )
        if is_cloud_model:
            window, source = _effective_ollama_cloud_context_window(
                native_context=None,
                model_num_ctx=None,
            )
        else:
            window, source = _effective_ollama_context_window(
                native_context=None,
                model_num_ctx=None,
            )
        return ModelContextWindow(
            model=normalized_model,
            context_window=window,
            source=source,
        )

    model_info = getattr(response, "modelinfo", None)
    if model_info is None and isinstance(response, dict):
        model_info = response.get("model_info") or response.get("modelinfo")
    native_context = _extract_ollama_native_context(model_info)

    parameters = getattr(response, "parameters", None)
    if parameters is None and isinstance(response, dict):
        parameters = response.get("parameters")
    model_num_ctx = _extract_ollama_num_ctx(parameters)

    if is_cloud_model:
        window, source = _effective_ollama_cloud_context_window(
            native_context=native_context,
            model_num_ctx=model_num_ctx,
        )
    else:
        window, source = _effective_ollama_context_window(
            native_context=native_context,
            model_num_ctx=model_num_ctx,
        )
    return ModelContextWindow(
        model=normalized_model,
        context_window=window,
        source=source,
    )


def _litellm_provider_for(provider: str) -> str:
    if provider == "openai-codex":
        return "chatgpt"
    return provider


def _litellm_context_from_info(model_info: Mapping[str, Any]) -> Optional[int]:
    return _positive_int(model_info.get("max_input_tokens")) or _positive_int(
        model_info.get("max_tokens")
    )


def _resolve_openai_codex_context_window(model_name: str) -> ModelContextWindow:
    """Resolve ChatGPT subscription model context from the Codex model list."""
    try:
        from ...services.integrations.openai_codex import openai_codex

        models = openai_codex.list_models()
        normalized = model_name.strip()
        for raw_model in models:
            raw_id = str(raw_model.get("model") or raw_model.get("id") or "").strip()
            if raw_id == normalized:
                return ModelContextWindow(
                    model=f"openai-codex/{normalized}",
                    context_window=_positive_int(raw_model.get("contextWindow")),
                    source="openai_codex_model_list",
                )
    except Exception as exc:
        logger.debug("Could not resolve OpenAI Codex context window: %s", exc)

    return ModelContextWindow(
        model=f"openai-codex/{model_name}",
        context_window=None,
        source="unknown",
    )


def _resolve_cloud_context_window(provider: str, model_name: str) -> ModelContextWindow:
    """Resolve a cloud model context window from LiteLLM metadata."""
    litellm_provider = _litellm_provider_for(provider)
    litellm_model = f"{litellm_provider}/{model_name}"
    try:
        model_info = litellm.get_model_info(litellm_model)
        return ModelContextWindow(
            model=f"{provider}/{model_name}",
            context_window=_litellm_context_from_info(model_info),
            source="litellm_model_info",
        )
    except Exception as exc:
        logger.debug(
            "Could not resolve LiteLLM context window for %s: %s",
            litellm_model,
            exc,
        )
        return ModelContextWindow(
            model=f"{provider}/{model_name}",
            context_window=None,
            source="unknown",
        )


async def resolve_model_context_window(model_name: str) -> ModelContextWindow:
    """Resolve context-window metadata for a user-facing model identifier."""
    from .router import parse_provider

    provider, model = parse_provider(model_name)
    if provider == "ollama":
        return await _resolve_ollama_context_window(model)

    if provider == "openai-codex":
        return _resolve_openai_codex_context_window(model)

    return _resolve_cloud_context_window(provider, model)
