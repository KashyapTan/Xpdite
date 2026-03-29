"""
Global application state management.

Centralizes all mutable global state into a single class for better
maintainability and testability.
"""

import os
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .request_context import RequestContext
import asyncio

if TYPE_CHECKING:
    from ..ss import ScreenshotService

# Compatibility placeholder for tests and patch sites. The actual screenshot
# implementation is imported lazily elsewhere during runtime startup.
ScreenshotService = Any


class AppState:
    """
    Centralized application state container.

    This replaces scattered global variables with a single, well-organized
    state object that can be imported and accessed throughout the application.
    """

    def __init__(self):
        # Screenshot state
        # Each entry: {"id": str, "path": str, "name": str, "thumbnail": str}
        self.screenshot_list: List[Dict[str, Any]] = []
        self.screenshot_counter: int = 0

        # Request lifecycle — the canonical way to manage streaming state.
        self.current_request: Optional[RequestContext] = None
        self.__request_lock: Optional[asyncio.Lock] = None

        # Legacy streaming flags
        self.is_streaming: bool = False
        self.stop_streaming: bool = False
        self.__stream_lock: Optional[asyncio.Lock] = None

        # Capture mode: 'fullscreen' | 'precision' | 'none'
        self.capture_mode: str = "fullscreen"

        # Active tab — updated from every incoming WS message so that
        # background-thread screenshot captures route to the correct tab.
        self.active_tab_id: str = "default"

        # Currently selected model (updated when user picks from dropdown)
        # deferred: avoid circular import with config.py
        from ..config import DEFAULT_MODEL

        self.selected_model: str = DEFAULT_MODEL

        # Chat history for multi-turn conversations
        self.chat_history: List[Dict[str, Any]] = []

        # Current conversation ID for database persistence
        self.conversation_id: Optional[str] = None

        # Service references for cleanup
        self.screenshot_service: Optional["ScreenshotService"] = None
        self.transcription_service: Optional[Any] = None
        self.server_thread: Optional[threading.Thread] = None
        self.service_thread: Optional[threading.Thread] = None

        # Event loop holder for cross-thread scheduling
        self.server_loop_holder: Dict[str, Any] = {}

    @property
    def _request_lock(self) -> asyncio.Lock:
        """Lazily create request lock (avoids issues on Python < 3.10)."""
        if self.__request_lock is None:
            self.__request_lock = asyncio.Lock()
        return self.__request_lock

    @property
    def stream_lock(self) -> asyncio.Lock:
        """Lazily create stream lock (avoids issues on Python < 3.10)."""
        if self.__stream_lock is None:
            self.__stream_lock = asyncio.Lock()
        return self.__stream_lock

    def reset_conversation(self):
        """Reset state for a new conversation."""
        self.chat_history = []
        self.conversation_id = None
        self.screenshot_list = []

    def add_screenshot(self, screenshot_data: Dict[str, Any]) -> str:
        """Add a screenshot and return its ID."""
        self.screenshot_counter += 1
        ss_id = f"ss_{self.screenshot_counter}"
        screenshot_data["id"] = ss_id
        self.screenshot_list.append(screenshot_data)
        return ss_id

    def remove_screenshot(self, screenshot_id: str) -> bool:
        """Remove a screenshot by ID. Returns True if found and removed."""
        original_len = len(self.screenshot_list)
        self.screenshot_list = [
            ss for ss in self.screenshot_list if ss["id"] != screenshot_id
        ]
        return len(self.screenshot_list) < original_len

    def get_image_paths(self) -> List[str]:
        """Get list of valid image paths from current screenshots."""
        return [
            os.path.abspath(ss["path"])
            for ss in self.screenshot_list
            if os.path.exists(ss["path"])
        ]


# Global singleton instance
app_state = AppState()
