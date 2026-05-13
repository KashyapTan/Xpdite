"""Shared token usage and prompt-cache helpers for LLM providers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Mapping, Optional

TokenStats = Dict[str, int]

_BASE_USAGE_KEYS = ("prompt_eval_count", "eval_count")
_CACHE_USAGE_KEYS = ("cached_tokens", "cache_write_tokens")
_ALL_USAGE_KEYS = (*_BASE_USAGE_KEYS, *_CACHE_USAGE_KEYS)


def empty_token_stats(*, include_cache_fields: bool = False) -> TokenStats:
    """Return an empty token usage dict.

    Cache fields are optional so legacy no-cache providers keep the previous
    compact payload shape, while providers that report cache usage can preserve
    explicit zero values.
    """
    stats: TokenStats = {"prompt_eval_count": 0, "eval_count": 0}
    if include_cache_fields:
        stats.update({"cached_tokens": 0, "cache_write_tokens": 0})
    return stats


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _has_field(obj: Any, key: str) -> bool:
    if isinstance(obj, Mapping):
        return key in obj
    return hasattr(obj, key)


def _nested_field(obj: Any, key: str, nested_key: str) -> tuple[bool, Any]:
    nested = _get_field(obj, key)
    if nested is None or not _has_field(nested, nested_key):
        return False, None
    return True, _get_field(nested, nested_key)


def merge_token_stats(*stats_items: Optional[Mapping[str, Any]]) -> TokenStats:
    """Sum token usage dicts while preserving reported cache fields."""
    merged = empty_token_stats()
    for stats in stats_items:
        if not stats:
            continue
        for key in _ALL_USAGE_KEYS:
            if key not in stats:
                continue
            if key not in merged:
                merged[key] = 0
            merged[key] += _coerce_int(stats.get(key))
    return merged


def add_token_stats(target: TokenStats, stats: Optional[Mapping[str, Any]]) -> None:
    """Add ``stats`` into ``target`` in-place."""
    if not stats:
        return
    for key in _ALL_USAGE_KEYS:
        if key not in stats:
            continue
        if key not in target:
            target[key] = 0
        target[key] += _coerce_int(stats.get(key))


def has_token_usage(stats: Mapping[str, Any]) -> bool:
    """Return whether any token usage value is non-zero."""
    return any(_coerce_int(stats.get(key)) for key in _ALL_USAGE_KEYS)


def usage_from_ollama_response(response: Any) -> TokenStats:
    """Extract Ollama prompt/eval counters from dict or SDK response objects."""
    return {
        "prompt_eval_count": _coerce_int(_get_field(response, "prompt_eval_count", 0)),
        "eval_count": _coerce_int(_get_field(response, "eval_count", 0)),
    }


def usage_from_litellm_chat_usage(usage: Any) -> TokenStats:
    """Normalize LiteLLM chat-completion usage into Xpdite token stats."""
    prompt_tokens = _coerce_int(_get_field(usage, "prompt_tokens", 0))
    completion_tokens = _coerce_int(_get_field(usage, "completion_tokens", 0))

    stats = {
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }

    cached_reported, cached_value = _nested_field(
        usage, "prompt_tokens_details", "cached_tokens"
    )
    cache_read_reported = _has_field(usage, "cache_read_input_tokens")
    cache_write_reported = _has_field(usage, "cache_creation_input_tokens")

    cache_read_tokens = _coerce_int(
        _get_field(usage, "cache_read_input_tokens", cached_value if cached_reported else 0)
    )
    cache_write_tokens = _coerce_int(
        _get_field(usage, "cache_creation_input_tokens", 0)
    )

    if cached_reported or cache_read_reported:
        stats["cached_tokens"] = cache_read_tokens
    if cache_write_reported:
        stats["cache_write_tokens"] = cache_write_tokens

    gemini_cached_reported = _has_field(usage, "cached_content_token_count")
    if gemini_cached_reported and "cached_tokens" not in stats:
        stats["cached_tokens"] = _coerce_int(
            _get_field(usage, "cached_content_token_count", 0)
        )

    return stats


def usage_from_litellm_responses_usage(usage: Any) -> TokenStats:
    """Normalize LiteLLM Responses API usage into Xpdite token stats."""
    input_tokens = _coerce_int(_get_field(usage, "input_tokens", 0))
    output_tokens = _coerce_int(_get_field(usage, "output_tokens", 0))
    stats = {
        "prompt_eval_count": input_tokens,
        "eval_count": output_tokens,
    }

    cached_reported, cached_value = _nested_field(
        usage, "input_tokens_details", "cached_tokens"
    )
    if cached_reported:
        stats["cached_tokens"] = _coerce_int(cached_value)

    cache_write_reported = _has_field(usage, "cache_creation_input_tokens")
    if cache_write_reported:
        stats["cache_write_tokens"] = _coerce_int(
            _get_field(usage, "cache_creation_input_tokens", 0)
        )

    return stats


def add_sub_agent_token_totals(target: TokenStats, stats: Mapping[str, Any]) -> None:
    """Add normalized Xpdite stats into a sub-agent prompt/completion total."""
    target["prompt_tokens"] = _coerce_int(target.get("prompt_tokens")) + _coerce_int(
        stats.get("prompt_eval_count")
    )
    target["completion_tokens"] = _coerce_int(
        target.get("completion_tokens")
    ) + _coerce_int(stats.get("eval_count"))
    if "cached_tokens" in stats:
        target["cached_tokens"] = _coerce_int(target.get("cached_tokens")) + _coerce_int(
            stats.get("cached_tokens")
        )
    if "cache_write_tokens" in stats:
        target["cache_write_tokens"] = _coerce_int(
            target.get("cache_write_tokens")
        ) + _coerce_int(stats.get("cache_write_tokens"))


def build_prompt_cache_key(
    provider: str,
    model: str,
    *,
    system_prompt: str = "",
    tools: Optional[Iterable[Mapping[str, Any]]] = None,
) -> str:
    """Build a stable, content-safe prompt-cache affinity key.

    The key never includes raw prompt/tool text. It hashes the cacheable prefix
    ingredients so repeated requests with the same stable prompt shape route
    consistently while keeping user content out of request metadata.
    """
    fingerprint = {
        "provider": provider,
        "model": model,
        "system_prompt_sha256": hashlib.sha256(
            system_prompt.encode("utf-8", errors="replace")
        ).hexdigest(),
        "tools_sha256": "",
    }
    if tools:
        tools_payload = json.dumps(list(tools), sort_keys=True, default=str)
        fingerprint["tools_sha256"] = hashlib.sha256(
            tools_payload.encode("utf-8", errors="replace")
        ).hexdigest()
    payload = json.dumps(fingerprint, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    safe_model = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in model
    )[:80]
    return f"xpdite-{provider}-{safe_model}-{digest}"[:250]


def supports_openai_prompt_cache_key(provider: str) -> bool:
    """Whether this provider path should receive OpenAI prompt_cache_key."""
    return provider in {"openai", "openai-codex"}


def supports_anthropic_cache_control(provider: str, model: str) -> bool:
    """Whether to request ephemeral Anthropic-style prompt caching."""
    model_key = model.lower()
    if provider == "anthropic":
        return True
    if provider == "openrouter":
        return "claude" in model_key or "anthropic" in model_key
    return False
