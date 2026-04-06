"""
Global application state management.

Centralizes all mutable global state into a single class for better
maintainability and testability.
"""

import threading
from typing import Any, Dict, List, Optional

from .request_context import RequestContext
import asyncio


class AppState:
    """
    Centralized application state container.

    This replaces scattered global variables with a single, well-organized
    state object that can be imported and accessed throughout the application.
    """

    def __init__(self):
        # Screenshot IDs are global so chips remain unique across tabs.
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
        from ..infrastructure.config import DEFAULT_MODEL

        self.selected_model: str = DEFAULT_MODEL

        # Chat history for multi-turn conversations
        self.chat_history: List[Dict[str, Any]] = []

        # Current conversation ID for database persistence
        self.conversation_id: Optional[str] = None

        # Service references for cleanup
        self.screenshot_service: Optional[Any] = None
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


# Global singleton instance
app_state = AppState()
