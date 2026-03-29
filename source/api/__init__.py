"""API package exports.

Lazy exports prevent ``source.api`` from importing the full WebSocket handler
graph when callers only need a specific endpoint module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["websocket_endpoint", "MessageHandler"]

if TYPE_CHECKING:
    from .handlers import MessageHandler
    from .websocket import websocket_endpoint


def __getattr__(name: str) -> Any:
    if name == "websocket_endpoint":
        from .websocket import websocket_endpoint

        return websocket_endpoint
    if name == "MessageHandler":
        from .handlers import MessageHandler

        return MessageHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
