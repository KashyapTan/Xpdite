"""
Application lifecycle management.

Handles startup, shutdown, signal handling, and resource cleanup.
"""

import sys
import os
import glob
import asyncio
import signal
import atexit
import logging

logger = logging.getLogger(__name__)


_cleanup_done = False


def cleanup_resources():
    """Clean up all resources when shutting down."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    # Use absolute imports inside the function to avoid circular import issues
    import sys

    # Support both package mode and direct execution
    if "source.core.state" in sys.modules:
        from source.core.state import app_state
        from source.mcp_integration.core.manager import mcp_manager
        from source.infrastructure.config import SCREENSHOT_FOLDER
    else:
        try:
            from .state import app_state
            from ..mcp_integration.core.manager import mcp_manager
            from ..infrastructure.config import SCREENSHOT_FOLDER
        except ImportError:
            logger.warning("Could not import cleanup dependencies")
            return

    logger.info("Cleaning up resources...")

    # Clean up MCP servers
    try:
        loop = app_state.server_loop_holder.get("loop")
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(mcp_manager.cleanup(), loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
        logger.info("MCP servers cleaned up")
    except Exception as e:
        logger.error("Error cleaning up MCP: %s", e)

    # Stop screenshot service
    if app_state.screenshot_service:
        try:
            app_state.screenshot_service.stop_listener()
            logger.info("Screenshot service stopped")
        except Exception as e:
            logger.error("Error stopping screenshot service: %s", e)

    # Clean up temporary screenshot folder
    try:
        if os.path.exists("screenshots") and os.path.abspath(
            "screenshots"
        ) != os.path.abspath(SCREENSHOT_FOLDER):
            _clear_folder("screenshots")
            logger.info("Temp screenshots folder cleaned")
    except Exception as e:
        logger.error("Error cleaning screenshots folder: %s", e)

    # Clean up extracted document images (all of them on shutdown)
    try:
        from ..services.media.file_extractor import FileExtractor

        removed = FileExtractor.cleanup_extracted_images(max_age_hours=0)
        if removed > 0:
            logger.info("Cleaned up %d extracted document images", removed)
    except Exception as e:
        logger.error("Error cleaning extracted images: %s", e)

    # Shut down the thread pool so worker threads don't block exit
    try:
        from .thread_pool import shutdown_thread_pool

        shutdown_thread_pool()
        logger.info("Thread pool shut down")
    except Exception as e:
        logger.error("Error shutting down thread pool: %s", e)

    # Drain all tab queues
    try:
        from source.services.chat.tab_manager_instance import tab_manager

        if tab_manager is not None:
            loop = None
            try:
                if "source.core.state" in sys.modules:
                    from source.core.state import app_state

                    loop = app_state.server_loop_holder.get("loop")
            except Exception:
                pass
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(tab_manager.close_all(), loop)
                try:
                    fut.result(timeout=5)
                except Exception:
                    pass
            logger.info("Tab manager closed all tabs")
    except Exception as e:
        logger.error("Error closing tab manager: %s", e)

    # Stop the scheduler service
    try:
        from source.services.scheduling.scheduler import scheduler_service

        loop = app_state.server_loop_holder.get("loop")
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(scheduler_service.stop(), loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
        logger.info("Scheduler service stopped")
    except Exception as e:
        logger.error("Error stopping scheduler service: %s", e)

    logger.info("Cleanup completed")


def _clear_folder(folder_path: str):
    """Remove all files (not subdirectories) from a folder."""
    if os.path.exists(folder_path):
        for file_path in glob.glob(os.path.join(folder_path, "*")):
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    logger.warning("Could not remove %s: %s", file_path, e)


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("Received signal %s, shutting down...", signum)
    cleanup_resources()
    sys.exit(0)


def register_signal_handlers():
    """Register signal handlers for graceful shutdown."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_resources)
