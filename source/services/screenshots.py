"""
Screenshot handling service.

Manages screenshot capture, storage, and lifecycle.
"""
import os
import asyncio
from typing import Optional

from ..core.state import app_state
from ..core.connection import broadcast_message
from ..config import SCREENSHOT_FOLDER, CaptureMode


class ScreenshotHandler:
    """Handles screenshot capture and management."""
    
    @staticmethod
    async def capture_fullscreen() -> Optional[str]:
        """
        Capture a fullscreen screenshot.
        
        Returns the screenshot ID if successful, None otherwise.
        """
        try:
            # Import here to avoid circular imports
            from ..ss import take_fullscreen_screenshot, create_thumbnail
            
            # Notify about screenshot capture start
            await broadcast_message("screenshot_start", "Taking fullscreen screenshot...")
            
            # Give the UI time to hide
            await asyncio.sleep(0.4)
            
            # Take the screenshot
            image_path = take_fullscreen_screenshot(SCREENSHOT_FOLDER)
            
            if image_path and os.path.exists(image_path):
                return await ScreenshotHandler.add_screenshot(image_path)
            return None
        except Exception as e:
            print(f"Error taking fullscreen screenshot: {e}")
            return None
    
    @staticmethod
    async def add_screenshot(image_path: str) -> str:
        """
        Add a screenshot to the context.
        
        Args:
            image_path: Path to the image file
            
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
        ss_id = app_state.add_screenshot(ss_data)
        
        # Notify clients
        await broadcast_message("screenshot_added", {
            "id": ss_id,
            "name": name,
            "thumbnail": thumbnail
        })
        
        print(f"Screenshot added: {ss_id}")
        return ss_id
    
    @staticmethod
    async def remove_screenshot(screenshot_id: str) -> bool:
        """
        Remove a specific screenshot from context.
        
        Returns True if found and removed.
        """
        for ss in app_state.screenshot_list:
            if ss["id"] == screenshot_id:
                # Delete the file
                if os.path.exists(ss["path"]):
                    try:
                        os.remove(ss["path"])
                    except Exception as e:
                        print(f"Error deleting screenshot file: {e}")
                
                # Remove from state
                app_state.remove_screenshot(screenshot_id)
                print(f"Screenshot removed: {screenshot_id}")
                
                # Notify clients
                await broadcast_message("screenshot_removed", {"id": screenshot_id})
                return True
        
        print(f"Screenshot not found: {screenshot_id}")
        return False
    
    @staticmethod
    async def clear_screenshots():
        """Clear all screenshots from context."""
        for ss in app_state.screenshot_list:
            if os.path.exists(ss["path"]):
                try:
                    os.remove(ss["path"])
                except Exception as e:
                    print(f"Error deleting screenshot: {e}")
        
        app_state.screenshot_list.clear()
        await broadcast_message("screenshots_cleared", "")
    
    @staticmethod
    async def on_screenshot_start():
        """Called when screenshot capture starts via hotkey."""
        # Only process in precision mode
        if app_state.capture_mode != CaptureMode.PRECISION:
            print(f"Hotkey capture ignored - not in precision mode")
            return
        
        print("Screenshot capture starting - hiding window")
        await broadcast_message("screenshot_start", "Screenshot capture starting")
    
    @staticmethod
    async def on_screenshot_captured(image_path: str):
        """Called when a screenshot is captured via hotkey."""
        # Only process in precision mode
        if app_state.capture_mode != CaptureMode.PRECISION:
            print(f"Hotkey capture ignored - not in precision mode")
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    print(f"Error deleting unused screenshot: {e}")
            return
        
        ss_id = await ScreenshotHandler.add_screenshot(image_path)
        
        # Send legacy message for backwards compatibility
        await broadcast_message("screenshot_ready", "Screenshot captured. Enter your query and press Enter.")


def process_screenshot_start():
    """Hook for screenshot service thread when capture starts."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        print("Server loop not ready yet.")
        return None

    def schedule():
        asyncio.create_task(ScreenshotHandler.on_screenshot_start())

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        print(f"Failed to schedule screenshot start: {e}")
    return None


def process_screenshot(image_path: str):
    """Hook for screenshot service thread when screenshot is taken."""
    server_loop = app_state.server_loop_holder.get("loop")
    if server_loop is None:
        print("Server loop not ready yet.")
        return None

    def schedule():
        asyncio.create_task(ScreenshotHandler.on_screenshot_captured(image_path))

    try:
        server_loop.call_soon_threadsafe(schedule)
    except Exception as e:
        print(f"Failed to schedule screenshot handling: {e}")
    return None
