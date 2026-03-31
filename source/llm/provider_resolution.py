"""Shared model/provider resolution helpers.

Centralizes parsing, LiteLLM model selection, Ollama env handling, and
local-vs-remote runtime classification so chat, sub-agents, scheduling,
and meeting analysis stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from ..config import OLLAMA_CTX_SIZE

KNOWN_CLOUD_PROVIDERS = ("anthropic", "openai", "gemini", "openrouter")
LOCAL_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_OLLAMA_API_BASE = "http://localhost:11434"


@dataclass
class ResolvedModelTarget:
    """Normalized model target for unified LiteLLM calls."""

    raw_model_name: str
    provider: str
    model: str
    litellm_model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    provider_kwargs: Dict[str, Any] = field(default_factory=dict)
    is_local_runtime: bool = False


def parse_provider(model_name: str) -> Tuple[str, str]:
    """Parse a model name into (provider, bare_model)."""
    normalized = (model_name or "").strip()
    if normalized.lower().startswith("ollama/"):
        return "ollama", normalized.partition("/")[2]

    if "/" in normalized:
        provider, _, model = normalized.partition("/")
        provider_lower = provider.lower()
        if provider_lower in KNOWN_CLOUD_PROVIDERS:
            return provider_lower, model

    return "ollama", normalized


def normalize_ollama_model_name(model_name: str) -> str:
    """Strip whitespace and an optional explicit ``ollama/`` prefix."""
    normalized = (model_name or "").strip()
    if normalized.lower().startswith("ollama/"):
        return normalized.partition("/")[2].strip()
    return normalized


def is_cloud_tagged_ollama_model(model_name: str) -> bool:
    """Whether an Ollama model name is explicitly tagged as cloud-hosted."""
    normalized = normalize_ollama_model_name(model_name).lower()
    return normalized.endswith(":cloud") or normalized.endswith("-cloud")


def is_local_ollama_api_base(api_base: Optional[str]) -> bool:
    """Whether an Ollama API base points at a local daemon."""
    candidate = (api_base or DEFAULT_OLLAMA_API_BASE).strip()
    if not candidate:
        candidate = DEFAULT_OLLAMA_API_BASE

    parsed = urlparse(candidate if "://" in candidate else f"http://{candidate}")
    hostname = (parsed.hostname or "").lower()
    return hostname in LOCAL_OLLAMA_HOSTS


def get_ollama_api_base() -> str:
    """Resolve the Ollama API base from the environment or local default."""
    return (os.getenv("OLLAMA_API_BASE") or DEFAULT_OLLAMA_API_BASE).strip()


def get_ollama_api_key() -> Optional[str]:
    """Resolve the optional Ollama API key from the environment."""
    api_key = (os.getenv("OLLAMA_API_KEY") or "").strip()
    return api_key or None


def resolve_model_target(model_name: str) -> ResolvedModelTarget:
    """Resolve a model ID into one provider-agnostic LiteLLM target."""
    provider, parsed_model = parse_provider(model_name)

    if provider == "ollama":
        bare_model = normalize_ollama_model_name(parsed_model)
        api_base = get_ollama_api_base()
        return ResolvedModelTarget(
            raw_model_name=(model_name or "").strip(),
            provider="ollama",
            model=bare_model,
            litellm_model=f"ollama_chat/{bare_model}",
            api_key=get_ollama_api_key(),
            api_base=api_base,
            provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            is_local_runtime=(
                bool(bare_model)
                and not is_cloud_tagged_ollama_model(bare_model)
                and is_local_ollama_api_base(api_base)
            ),
        )

    from .key_manager import key_manager

    return ResolvedModelTarget(
        raw_model_name=(model_name or "").strip(),
        provider=provider,
        model=parsed_model,
        litellm_model=f"{provider}/{parsed_model}",
        api_key=key_manager.get_api_key(provider),
        api_base=None,
        provider_kwargs={},
        is_local_runtime=False,
    )


def is_local_ollama_model(model_name: str) -> bool:
    """Whether a model resolves to a true local Ollama runtime."""
    target = resolve_model_target(model_name)
    return target.provider == "ollama" and target.is_local_runtime
