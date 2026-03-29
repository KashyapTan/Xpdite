"""LLM package exports.

These imports are intentionally lazy so importing a narrow submodule like
``source.llm.router`` does not also load LiteLLM and every provider adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["stream_ollama_chat", "stream_cloud_chat", "route_chat", "key_manager"]

if TYPE_CHECKING:
    from .cloud_provider import stream_cloud_chat
    from .key_manager import key_manager
    from .ollama_provider import stream_ollama_chat
    from .router import route_chat


def __getattr__(name: str) -> Any:
    if name == "stream_ollama_chat":
        from .ollama_provider import stream_ollama_chat

        return stream_ollama_chat
    if name == "stream_cloud_chat":
        from .cloud_provider import stream_cloud_chat

        return stream_cloud_chat
    if name == "route_chat":
        from .router import route_chat

        return route_chat
    if name == "key_manager":
        from .key_manager import key_manager

        return key_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
