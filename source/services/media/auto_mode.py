"""
Auto Mode (Instant Answer) service.

Auto Mode repurposes the existing screenshot hotkey. When the Settings → General
toggle is on, pressing the hotkey runs a hands-off pipeline instead of a region
capture:

    hotkey → full-screen capture → auto-submit the user's saved prompt →
    stream the answer into a new tab — never stealing OS focus.

This module owns the thin backend half of that pipeline: the hotkey listener
runs on a background thread, so these hooks bridge the press onto the uvicorn
event loop and broadcast a single ``auto_mode_trigger`` message. The frontend
does the rest (new tab, submit, show-inactive), reusing the normal
enqueue → stream → persist flow — so streaming, cancellation, token accounting
and history persistence all behave identically to a manual chat turn.

The bundled mini-mode toggle hotkey (``Control+,`` / ``Alt+,``) is broadcast the
same way via ``toggle_mini_mode``.
"""

import asyncio
import logging

from ...core.state import app_state
from ...core.connection import broadcast_message
from ...infrastructure.config import (
    AUTO_MODE_PROMPT_KEY,
    AUTO_MODE_PINNED_MODEL_KEY,
    AUTO_MODE_KEEP_CONTEXT_KEY,
    AUTO_MODE_FLASH_KEY,
    DEFAULT_AUTO_MODE_PROMPT,
)

logger = logging.getLogger(__name__)


def _resolve_auto_mode_payload() -> dict:
    """Build the ``auto_mode_trigger`` payload from persisted settings.

    Runs on the event loop (fast, in-memory SQLite reads). Resolves the model
    to the pinned Auto Mode model when one is configured, otherwise the model
    the user currently has selected.
    """
    from ...infrastructure.database import db

    prompt = (db.get_setting(AUTO_MODE_PROMPT_KEY) or "").strip()
    if not prompt:
        prompt = DEFAULT_AUTO_MODE_PROMPT

    # Use the pinned model only if it is still an enabled model. A model that
    # was pinned and later disabled/removed would otherwise make every trigger
    # fail silently (hands-off, shown inactive — the user might never notice).
    pinned_model = (db.get_setting(AUTO_MODE_PINNED_MODEL_KEY) or "").strip()
    if pinned_model and pinned_model in db.get_enabled_models():
        model = pinned_model
    else:
        model = app_state.selected_model

    keep_context = db.get_setting(AUTO_MODE_KEEP_CONTEXT_KEY) == "true"
    flash = db.get_setting(AUTO_MODE_FLASH_KEY) == "true"

    return {
        "prompt": prompt,
        "model": model,
        "keep_context": keep_context,
        "flash": flash,
    }


class AutoModeHandler:
    """Coroutines invoked (on the event loop) when a global hotkey fires."""

    @staticmethod
    async def on_auto_mode_trigger() -> None:
        """Broadcast an ``auto_mode_trigger`` so the frontend runs the pipeline.

        Broadcast globally (no ``tab_id`` context) — the frontend decides which
        tab the answer goes into (a brand-new tab, or the current one when
        keep-context is enabled).
        """
        if not app_state.auto_mode_enabled:
            # The listener already checks this at trigger time, but guard again
            # in case the flag flipped between press and scheduling.
            logger.debug("Auto Mode trigger ignored - disabled")
            return

        payload = _resolve_auto_mode_payload()
        logger.info(
            "Auto Mode trigger → model=%s keep_context=%s",
            payload["model"],
            payload["keep_context"],
        )
        await broadcast_message("auto_mode_trigger", payload)

    @staticmethod
    async def on_mini_toggle() -> None:
        """Broadcast a ``toggle_mini_mode`` request to the frontend."""
        await broadcast_message("toggle_mini_mode", {})


def _log_task_result(task: "asyncio.Task") -> None:
    """Surface exceptions from the fire-and-forget hotkey coroutine.

    Without this the exception would only reach asyncio's default handler with
    no Auto-Mode context, so a failed trigger would be silent.
    """
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("Auto Mode hotkey coroutine failed: %s", exc, exc_info=exc)


def _schedule_on_server_loop(coro_factory) -> None:
    """Schedule a coroutine on the uvicorn loop from a background thread."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        logger.warning("Server loop not ready yet; dropping hotkey event.")
        return

    def schedule():
        task = asyncio.create_task(coro_factory())
        task.add_done_callback(_log_task_result)

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        logger.error("Failed to schedule hotkey event: %s", e)


def process_auto_mode() -> None:
    """Hook for the screenshot service thread when Auto Mode fires."""
    _schedule_on_server_loop(AutoModeHandler.on_auto_mode_trigger)


def process_mini_toggle() -> None:
    """Hook for the screenshot service thread when the mini hotkey fires."""
    _schedule_on_server_loop(AutoModeHandler.on_mini_toggle)
