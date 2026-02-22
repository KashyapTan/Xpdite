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
    if 'source.core.state' in sys.modules:
        from source.core.state import app_state
        from source.mcp_integration.manager import mcp_manager
        from source.config import SCREENSHOT_FOLDER
    else:
        try:
            from .state import app_state
            from ..mcp_integration.manager import mcp_manager
            from ..config import SCREENSHOT_FOLDER
        except ImportError:
            print("Warning: Could not import cleanup dependencies")
            return
    
    print("Cleaning up resources...")
    
    # Clean up MCP servers
    try:
        loop = app_state.server_loop_holder.get("loop")
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(mcp_manager.cleanup(), loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
        print("MCP servers cleaned up")
    except Exception as e:
        print(f"Error cleaning up MCP: {e}")
    
    # Stop screenshot service
    if app_state.screenshot_service:
        try:
            app_state.screenshot_service.stop_listener()
            print("Screenshot service stopped")
        except Exception as e:
            print(f"Error stopping screenshot service: {e}")
    
    # Clean up temporary screenshot folder
    try:
        if os.path.exists("screenshots") and os.path.abspath("screenshots") != os.path.abspath(SCREENSHOT_FOLDER):
            _clear_folder("screenshots")
            print("Temp screenshots folder cleaned")
    except Exception as e:
        print(f"Error cleaning screenshots folder: {e}")
    
    # Shut down the thread pool so worker threads don't block exit
    try:
        from .thread_pool import shutdown_thread_pool
        shutdown_thread_pool()
        print("Thread pool shut down")
    except Exception as e:
        print(f"Error shutting down thread pool: {e}")

    print("Cleanup completed")


def _clear_folder(folder_path: str):
    """Remove all files (not subdirectories) from a folder."""
    if os.path.exists(folder_path):
        for file_path in glob.glob(os.path.join(folder_path, "*")):
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    print(f"Warning: Could not remove {file_path}: {e}")


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print(f"Received signal {signum}, shutting down...")
    cleanup_resources()
    sys.exit(0)


def register_signal_handlers():
    """Register signal handlers for graceful shutdown."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_resources)
