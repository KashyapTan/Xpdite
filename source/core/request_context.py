"""
Request lifecycle context.

Encapsulates the state of a single LLM request (one user query -> tool loop
-> streaming response cycle).  Replaces the scattered stream_lock +
is_streaming + stop_streaming triple in AppState with a single, self-contained
object that every subsystem can check for cancellation.

Usage:
    ctx = RequestContext()
    app_state.current_request = ctx
    ...
    # Anywhere in the codebase:
    if ctx.cancelled:
        break
    ...
    # When the user clicks Stop:
    ctx.cancel()
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List


class RequestContext:
    """Tracks the lifecycle of one LLM request.

    Attributes:
        cancelled: True once cancel() has been called.

    The object is created at the start of submit_query and stored on
    app_state.current_request.  Every subsystem (tool loop, streaming,
    terminal approval, PTY execution) checks ``ctx.cancelled`` instead
    of the old ``app_state.stop_streaming`` flag.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._cancel_callbacks: List[Callable[[], None]] = []
        # asyncio.Event() requires a running event loop on Python < 3.10.
        # RequestContext is always created inside async handlers, so this is safe.
        self._done_event = asyncio.Event()
        self.forced_skills: List[Dict[str, Any]] = []  # Skills from slash commands

    # ── Read-only state ────────────────────────────────────────────

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_done(self) -> bool:
        return self._done_event.is_set()

    # ── Actions ────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Cancel this request.  Fires all registered callbacks."""
        if self._cancelled:
            return
        self._cancelled = True
        for cb in self._cancel_callbacks:
            try:
                cb()
            except Exception as e:
                print(f"[RequestContext] Cancel callback failed: {e}")

    def mark_done(self) -> None:
        """Mark the request as completed (success or failure)."""
        self._done_event.set()
        self._cancel_callbacks.clear()

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a cleanup callback that fires on cancel().

        If the context is already cancelled, the callback fires immediately.
        """
        if self._cancelled:
            try:
                callback()
            except Exception:
                pass
            return
        self._cancel_callbacks.append(callback)
