"""
Screenshot handling service.

Manages screenshot capture, storage, and lifecycle.

All screenshot operations are tab-aware: screenshots are always stored in
the resolved tab's ``TabState.screenshot_list``.
"""

import os
import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from ...core.state import app_state
from ...core.connection import broadcast_message, broadcast_to_tab
from ...infrastructure.config import SCREENSHOT_FOLDER, CaptureMode
from ...core.thread_pool import run_in_thread

if TYPE_CHECKING:
    from ..chat.tab_manager import TabState

logger = logging.getLogger(__name__)


class ScreenshotHandler:
    """Handles screenshot capture and management."""

    @staticmethod
    def _delete_screenshot_file(path: str) -> None:
        """Delete a screenshot file if it exists."""
        if os.path.exists(path):
            os.remove(path)

    @staticmethod
    def _delete_many_screenshot_files(paths: list[str]) -> None:
        """Delete multiple screenshot files, logging and continuing on errors."""
        for path in paths:
            try:
                ScreenshotHandler._delete_screenshot_file(path)
            except Exception as e:
                logger.error("Error deleting screenshot: %s", e)

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _get_active_tab_state() -> "TabState":
        """Look up the active tab's ``TabState`` from the tab manager.

        Checks the ``_current_tab_id`` contextvar first (set by
        ``wrap_with_tab_ctx`` for hotkey captures), then falls back to
        ``app_state.active_tab_id``.

        If the resolved tab no longer exists, falls back to ``default`` and
        updates ``app_state.active_tab_id``.
        """
        from ..chat.tab_manager_instance import tab_manager
        from ...core.connection import get_current_tab_id

        if tab_manager is None:
            raise RuntimeError("Tab manager is not initialized")

        # Prefer the contextvar (set for scheduled hotkey coroutines)
        ctx_tab = get_current_tab_id()
        if ctx_tab is not None:
            state = tab_manager.get_state(ctx_tab)
            if state is not None:
                return state
            logger.warning(
                "Context tab '%s' is missing; falling back to active tab",
                ctx_tab,
            )

        # Fall back to the globally-tracked active tab.
        active_tab_id = app_state.active_tab_id or "default"
        state = tab_manager.get_state(active_tab_id)
        if state is not None:
            return state

        # Ensure screenshot operations still have a valid tab target.
        default_session = tab_manager.get_or_create("default")
        app_state.active_tab_id = default_session.tab_id
        logger.warning(
            "Active tab '%s' is missing; routing screenshot to '%s'",
            active_tab_id,
            default_session.tab_id,
        )
        return default_session.state

    @staticmethod
    def _resolve_tab_state(tab_state: Optional["TabState"] = None) -> "TabState":
        """Return the explicitly provided *tab_state*, or look up the active tab."""
        if tab_state is not None:
            return tab_state
        return ScreenshotHandler._get_active_tab_state()

    # ── Public API ────────────────────────────────────────────────

    @staticmethod
    async def capture_fullscreen(
        tab_state: Optional["TabState"] = None,
    ) -> Optional[str]:
        """
        Capture a fullscreen screenshot.

        Returns the screenshot ID if successful, None otherwise.
        """
        try:
            # Import here to avoid circular imports
            from ...infrastructure.screenshot_runtime import take_fullscreen_screenshot

            # Notify about screenshot capture start
            await broadcast_message(
                "screenshot_start", "Taking fullscreen screenshot..."
            )

            # Give the UI time to hide
            await asyncio.sleep(0.4)

            # Take the screenshot in a thread to avoid blocking the event loop
            image_path = await run_in_thread(
                take_fullscreen_screenshot, SCREENSHOT_FOLDER
            )

            if image_path and os.path.exists(image_path):
                return await ScreenshotHandler.add_screenshot(
                    image_path, tab_state=tab_state
                )
            return None
        except Exception as e:
            logger.error("Error taking fullscreen screenshot: %s", e)
            return None

    @staticmethod
    async def add_screenshot(
        image_path: str, tab_state: Optional["TabState"] = None
    ) -> str:
        """
        Add a screenshot to the context.

        Args:
            image_path: Path to the image file
            tab_state: Per-tab state to add the screenshot to.
                       Falls back to the currently active tab state.

        Returns:
            The screenshot ID
        """
        from ...infrastructure.screenshot_runtime import create_thumbnail

        # Convert to absolute path
        abs_path = os.path.abspath(image_path)
        thumbnail = await run_in_thread(create_thumbnail, abs_path)
        name = os.path.basename(abs_path)

        # Add to state
        ss_data = {"path": abs_path, "name": name, "thumbnail": thumbnail}

        target = ScreenshotHandler._resolve_tab_state(tab_state)
        ss_id = target.add_screenshot(ss_data)

        # Notify clients
        await broadcast_to_tab(
            target.tab_id,
            "screenshot_added",
            {
                "id": ss_id,
                "name": name,
                "thumbnail": thumbnail,
            },
        )

        logger.info("Screenshot added: %s (tab=%s)", ss_id, target.tab_id)
        return ss_id

    @staticmethod
    async def remove_screenshot(
        screenshot_id: str, tab_state: Optional["TabState"] = None
    ) -> bool:
        """
        Remove a specific screenshot from context.

        Returns True if found and removed.
        """
        target = ScreenshotHandler._resolve_tab_state(tab_state)
        search_list = target.screenshot_list

        for ss in list(search_list):
            if ss["id"] == screenshot_id:
                # Delete the file
                try:
                    await run_in_thread(
                        ScreenshotHandler._delete_screenshot_file,
                        ss["path"],
                    )
                except Exception as e:
                    logger.error("Error deleting screenshot file: %s", e)

                # Remove from state
                target.remove_screenshot(screenshot_id)
                logger.info("Screenshot removed: %s", screenshot_id)

                # Notify clients
                await broadcast_to_tab(
                    target.tab_id,
                    "screenshot_removed",
                    {"id": screenshot_id},
                )
                return True

        logger.warning(
            "Screenshot not found: %s (tab=%s)", screenshot_id, target.tab_id
        )
        return False

    @staticmethod
    async def clear_screenshots(tab_state: Optional["TabState"] = None):
        """Clear all screenshots from context."""
        target = ScreenshotHandler._resolve_tab_state(tab_state)
        search_list = target.screenshot_list

        paths_to_delete = [str(ss.get("path", "")) for ss in list(search_list)]
        if paths_to_delete:
            await run_in_thread(
                ScreenshotHandler._delete_many_screenshot_files,
                paths_to_delete,
            )

        search_list.clear()
        await broadcast_to_tab(target.tab_id, "screenshots_cleared", "")

    @staticmethod
    async def on_screenshot_start(force: bool = False):
        """Called when screenshot capture starts via hotkey."""
        # Only process in precision mode
        if not force and app_state.capture_mode != CaptureMode.PRECISION:
            logger.debug("Hotkey capture ignored - not in precision mode")
            return

        target_tab_id = app_state.active_tab_id or "default"
        try:
            target_tab_id = ScreenshotHandler._resolve_tab_state().tab_id
        except Exception as e:
            logger.debug("Could not resolve tab for screenshot start: %s", e)

        logger.debug(
            "Screenshot capture starting - hiding window (tab=%s)", target_tab_id
        )
        await broadcast_to_tab(
            target_tab_id,
            "screenshot_start",
            "Screenshot capture starting",
        )

    @staticmethod
    async def on_screenshot_captured(image_path: str, force: bool = False):
        """Called when a screenshot is captured via hotkey."""
        # Only process in precision mode
        if not force and app_state.capture_mode != CaptureMode.PRECISION:
            logger.debug("Hotkey capture ignored - not in precision mode")
            try:
                await run_in_thread(
                    ScreenshotHandler._delete_screenshot_file, image_path
                )
            except Exception as e:
                logger.error("Error deleting unused screenshot: %s", e)
            return

        target_tab_id = app_state.active_tab_id or "default"
        target_tab_state = None
        try:
            target_tab_state = ScreenshotHandler._resolve_tab_state()
            target_tab_id = target_tab_state.tab_id
        except Exception as e:
            logger.debug("Could not resolve tab for captured screenshot: %s", e)

        try:
            await ScreenshotHandler.add_screenshot(
                image_path, tab_state=target_tab_state
            )
        except Exception as e:
            logger.error("Failed to attach captured screenshot: %s", e)
            try:
                await run_in_thread(
                    ScreenshotHandler._delete_screenshot_file, image_path
                )
            except Exception as cleanup_error:
                logger.error(
                    "Failed to cleanup unattached screenshot file: %s", cleanup_error
                )
            return

        # Send legacy message for backwards compatibility
        await broadcast_to_tab(
            target_tab_id,
            "screenshot_ready",
            "Screenshot captured. Enter your query and press Enter.",
        )

    @staticmethod
    async def on_screenshot_cancelled(force: bool = False):
        """Called when the hotkey-driven region capture is cancelled."""
        if not force and app_state.capture_mode != CaptureMode.PRECISION:
            logger.debug("Screenshot cancel ignored - not in precision mode")
            return

        target_tab_id = app_state.active_tab_id or "default"
        try:
            target_tab_id = ScreenshotHandler._resolve_tab_state().tab_id
        except Exception as e:
            logger.debug("Could not resolve tab for cancelled screenshot: %s", e)

        await broadcast_to_tab(
            target_tab_id,
            "screenshot_cancelled",
            "Screenshot cancelled.",
        )


def process_screenshot_start():
    """Hook for screenshot service thread when capture starts."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        logger.warning("Server loop not ready yet.")
        return None

    # Capture the active tab_id now (on the calling thread) so that
    # the coroutine scheduled on the event loop broadcasts to the
    # correct tab even if the user switches tabs before it runs.
    active_tab = app_state.active_tab_id or "default"

    def schedule():
        from ...core.connection import wrap_with_tab_ctx

        coro = wrap_with_tab_ctx(
            active_tab, ScreenshotHandler.on_screenshot_start(force=True)
        )
        asyncio.create_task(coro)

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        logger.error("Failed to schedule screenshot start: %s", e)
    return None


def process_screenshot(image_path: str):
    """Hook for screenshot service thread when screenshot is taken."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        logger.warning("Server loop not ready yet.")
        return None

    # Capture the active tab_id now (on the calling thread).
    active_tab = app_state.active_tab_id or "default"

    def schedule():
        from ...core.connection import wrap_with_tab_ctx

        coro = wrap_with_tab_ctx(
            active_tab,
            ScreenshotHandler.on_screenshot_captured(image_path, force=True),
        )
        asyncio.create_task(coro)

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        logger.error("Failed to schedule screenshot handling: %s", e)
    return None


def process_screenshot_cancelled():
    """Hook for screenshot service thread when region capture is cancelled."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        logger.warning("Server loop not ready yet.")
        return None

    active_tab = app_state.active_tab_id or "default"

    def schedule():
        from ...core.connection import wrap_with_tab_ctx

        coro = wrap_with_tab_ctx(
            active_tab, ScreenshotHandler.on_screenshot_cancelled(force=True)
        )
        asyncio.create_task(coro)

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        logger.error("Failed to schedule screenshot cancel handling: %s", e)
    return None
