"""
Screenshot handling service.

Manages screenshot capture, storage, and lifecycle.

All screenshot operations are tab-aware: screenshots are stored in the
active tab's ``TabState.screenshot_list`` rather than the global
``app_state.screenshot_list``.  When no tab context is available (e.g.
during startup), the global list is used as a fallback.
"""
import os
import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from ..core.state import app_state
from ..core.connection import broadcast_message
from ..config import SCREENSHOT_FOLDER, CaptureMode

if TYPE_CHECKING:
    from .tab_manager import TabState

logger = logging.getLogger(__name__)


class ScreenshotHandler:
    """Handles screenshot capture and management."""

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _get_active_tab_state() -> Optional["TabState"]:
        """Look up the active tab's ``TabState`` from the tab manager.

        Checks the ``_current_tab_id`` contextvar first (set by
        ``wrap_with_tab_ctx`` for hotkey captures), then falls back to
        ``app_state.active_tab_id``.

        Returns ``None`` when the tab manager is not yet initialised or
        the active tab ID does not map to a session.
        """
        try:
            from .tab_manager_instance import tab_manager
            from ..core.connection import get_current_tab_id

            if tab_manager is None:
                return None

            # Prefer the contextvar (set for scheduled hotkey coroutines)
            ctx_tab = get_current_tab_id()
            if ctx_tab is not None:
                state = tab_manager.get_state(ctx_tab)
                if state is not None:
                    return state

            # Fall back to the globally-tracked active tab
            return tab_manager.get_state(app_state.active_tab_id)
        except Exception as e:
            logger.debug("Could not resolve active tab state: %s", e)
        return None

    @staticmethod
    def _resolve_tab_state(tab_state: Optional["TabState"] = None) -> Optional["TabState"]:
        """Return the explicitly provided *tab_state*, or look up the active tab."""
        if tab_state is not None:
            return tab_state
        return ScreenshotHandler._get_active_tab_state()

    # ── Public API ────────────────────────────────────────────────

    @staticmethod
    async def capture_fullscreen(tab_state: Optional["TabState"] = None) -> Optional[str]:
        """
        Capture a fullscreen screenshot.
        
        Returns the screenshot ID if successful, None otherwise.
        """
        from ..core.thread_pool import run_in_thread

        try:
            # Import here to avoid circular imports
            from ..ss import take_fullscreen_screenshot
            
            # Notify about screenshot capture start
            await broadcast_message("screenshot_start", "Taking fullscreen screenshot...")
            
            # Give the UI time to hide
            await asyncio.sleep(0.4)
            
            # Take the screenshot in a thread to avoid blocking the event loop
            image_path = await run_in_thread(take_fullscreen_screenshot, SCREENSHOT_FOLDER)
            
            if image_path and os.path.exists(image_path):
                return await ScreenshotHandler.add_screenshot(image_path, tab_state=tab_state)
            return None
        except Exception as e:
            logger.error("Error taking fullscreen screenshot: %s", e)
            return None
    
    @staticmethod
    async def add_screenshot(image_path: str, tab_state: Optional["TabState"] = None) -> str:
        """
        Add a screenshot to the context.
        
        Args:
            image_path: Path to the image file
            tab_state: Per-tab state to add the screenshot to.
                       Falls back to the active tab, then global state.
            
        Returns:
            The screenshot ID
        """
        from ..ss import create_thumbnail
        
        # Convert to absolute path
        abs_path = os.path.abspath(image_path)
        thumbnail = create_thumbnail(abs_path)
        name = os.path.basename(abs_path)
        
        # Add to state
        ss_data = {
            "path": abs_path,
            "name": name,
            "thumbnail": thumbnail
        }

        target = ScreenshotHandler._resolve_tab_state(tab_state)
        if target is not None:
            ss_id = target.add_screenshot(ss_data)
        else:
            ss_id = app_state.add_screenshot(ss_data)
        
        # Notify clients
        await broadcast_message("screenshot_added", {
            "id": ss_id,
            "name": name,
            "thumbnail": thumbnail
        })
        
        logger.info("Screenshot added: %s (tab=%s)", ss_id, target.tab_id if target else "global")
        return ss_id
    
    @staticmethod
    async def remove_screenshot(screenshot_id: str, tab_state: Optional["TabState"] = None) -> bool:
        """
        Remove a specific screenshot from context.
        
        Returns True if found and removed.
        """
        target = ScreenshotHandler._resolve_tab_state(tab_state)
        search_list = target.screenshot_list if target is not None else app_state.screenshot_list

        for ss in search_list:
            if ss["id"] == screenshot_id:
                # Delete the file
                if os.path.exists(ss["path"]):
                    try:
                        os.remove(ss["path"])
                    except Exception as e:
                        logger.error("Error deleting screenshot file: %s", e)
                
                # Remove from state
                if target is not None:
                    target.remove_screenshot(screenshot_id)
                else:
                    app_state.remove_screenshot(screenshot_id)
                logger.info("Screenshot removed: %s", screenshot_id)
                
                # Notify clients
                await broadcast_message("screenshot_removed", {"id": screenshot_id})
                return True
        
        logger.warning("Screenshot not found: %s", screenshot_id)
        return False
    
    @staticmethod
    async def clear_screenshots(tab_state: Optional["TabState"] = None):
        """Clear all screenshots from context."""
        target = ScreenshotHandler._resolve_tab_state(tab_state)
        search_list = target.screenshot_list if target is not None else app_state.screenshot_list

        for ss in search_list:
            if os.path.exists(ss["path"]):
                try:
                    os.remove(ss["path"])
                except Exception as e:
                    logger.error("Error deleting screenshot: %s", e)
        
        search_list.clear()
        await broadcast_message("screenshots_cleared", "")
    
    @staticmethod
    async def on_screenshot_start():
        """Called when screenshot capture starts via hotkey."""
        # Only process in precision mode
        if app_state.capture_mode != CaptureMode.PRECISION:
            logger.debug("Hotkey capture ignored - not in precision mode")
            return
        
        logger.debug("Screenshot capture starting - hiding window")
        await broadcast_message("screenshot_start", "Screenshot capture starting")
    
    @staticmethod
    async def on_screenshot_captured(image_path: str):
        """Called when a screenshot is captured via hotkey."""
        # Only process in precision mode
        if app_state.capture_mode != CaptureMode.PRECISION:
            logger.debug("Hotkey capture ignored - not in precision mode")
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    logger.error("Error deleting unused screenshot: %s", e)
            return
        
        # tab_state is resolved inside add_screenshot via active_tab_id
        await ScreenshotHandler.add_screenshot(image_path)
        
        # Send legacy message for backwards compatibility
        await broadcast_message("screenshot_ready", "Screenshot captured. Enter your query and press Enter.")


def process_screenshot_start():
    """Hook for screenshot service thread when capture starts."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        logger.warning("Server loop not ready yet.")
        return None

    # Capture the active tab_id now (on the calling thread) so that
    # the coroutine scheduled on the event loop broadcasts to the
    # correct tab even if the user switches tabs before it runs.
    active_tab = app_state.active_tab_id

    def schedule():
        from ..core.connection import wrap_with_tab_ctx
        coro = wrap_with_tab_ctx(active_tab, ScreenshotHandler.on_screenshot_start())
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
    active_tab = app_state.active_tab_id

    def schedule():
        from ..core.connection import wrap_with_tab_ctx
        coro = wrap_with_tab_ctx(active_tab, ScreenshotHandler.on_screenshot_captured(image_path))
        asyncio.create_task(coro)

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        logger.error("Failed to schedule screenshot handling: %s", e)
    return None
