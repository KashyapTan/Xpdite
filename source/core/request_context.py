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
import contextvars
import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# ── ContextVar: per-task current request ──────────────────────────
_current_request_ctx: contextvars.ContextVar[Optional[RequestContext]] = contextvars.ContextVar(
    "current_request_ctx", default=None
)

# ── ContextVar: per-task current model ────────────────────────────
_current_model_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_model_ctx", default=None
)


def set_current_request(ctx: Optional[RequestContext]) -> contextvars.Token:
    """Set the current RequestContext for this async task."""
    return _current_request_ctx.set(ctx)


def get_current_request() -> Optional[RequestContext]:
    """Get the current RequestContext for this async task."""
    return _current_request_ctx.get()


def is_current_request_cancelled() -> bool:
    """Check if the current request is cancelled.

    Safe to call from any async context.  Returns False if no request
    is active.  This replaces all ``app_state.stop_streaming`` checks
    in the LLM / tool layers.
    """
    ctx = _current_request_ctx.get()
    return ctx is not None and ctx.cancelled


def set_current_model(model: Optional[str]) -> contextvars.Token:
    """Set the model for this async task (per-request, not global)."""
    return _current_model_ctx.set(model)


def get_current_model() -> Optional[str]:
    """Get the model for this async task.  Returns None if not set."""
    return _current_model_ctx.get()


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
        self.forced_skills: list = []  # List[Skill] at runtime

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
                logger.debug("Cancel callback failed: %s", e)

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
