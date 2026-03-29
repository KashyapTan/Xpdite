"""Core package exports.

Keep these lazy so lightweight imports do not eagerly load state, screenshot,
and lifecycle dependencies before they are needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "AppState",
    "app_state",
    "ConnectionManager",
    "manager",
    "broadcast_message",
    "cleanup_resources",
    "signal_handler",
    "RequestContext",
    "run_in_thread",
]

if TYPE_CHECKING:
    from .connection import ConnectionManager, broadcast_message, manager
    from .lifecycle import cleanup_resources, signal_handler
    from .request_context import RequestContext
    from .state import AppState, app_state
    from .thread_pool import run_in_thread


def __getattr__(name: str) -> Any:
    if name in {"AppState", "app_state"}:
        from .state import AppState, app_state

        return {"AppState": AppState, "app_state": app_state}[name]
    if name in {"ConnectionManager", "manager", "broadcast_message"}:
        from .connection import ConnectionManager, broadcast_message, manager

        return {
            "ConnectionManager": ConnectionManager,
            "manager": manager,
            "broadcast_message": broadcast_message,
        }[name]
    if name in {"cleanup_resources", "signal_handler"}:
        from .lifecycle import cleanup_resources, signal_handler

        return {
            "cleanup_resources": cleanup_resources,
            "signal_handler": signal_handler,
        }[name]
    if name == "RequestContext":
        from .request_context import RequestContext

        return RequestContext
    if name == "run_in_thread":
        from .thread_pool import run_in_thread

        return run_in_thread
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
