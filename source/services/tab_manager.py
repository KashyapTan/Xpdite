"""
Tab manager — owns per-tab state and queue lifecycle.

Each browser tab maps to a ``TabSession`` that holds its own chat history,
conversation ID, screenshot list, and a ``ConversationQueue`` for sequential
query processing.  The ``TabManager`` singleton is the entry point for all
tab operations.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..core.request_context import RequestContext
from .query_queue import ConversationQueue, QueuedQuery

logger = logging.getLogger(__name__)

MAX_TABS = 10


@dataclass
class TabState:
    """Per-tab mutable state — replaces global AppState fields for tab-scoped data."""

    tab_id: str

    # Conversation state
    chat_history: List[Dict[str, Any]] = field(default_factory=list)
    conversation_id: Optional[str] = None

    # Screenshot state (per-tab)
    screenshot_list: List[Dict[str, Any]] = field(default_factory=list)

    # Request lifecycle
    current_request: Optional[RequestContext] = None
    is_streaming: bool = False
    stop_streaming: bool = False
    _request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reset_conversation(self) -> None:
        """Reset state for a new conversation."""
        self.chat_history = []
        self.conversation_id = None
        self.screenshot_list = []

    def get_image_paths(self) -> List[str]:
        """Get list of valid image paths from current screenshots."""
        return [
            os.path.abspath(ss["path"])
            for ss in self.screenshot_list
            if os.path.exists(ss.get("path", ""))
        ]


@dataclass
class TabSession:
    """Groups a TabState with its ConversationQueue."""

    tab_id: str
    state: TabState
    queue: ConversationQueue


class TabManager:
    """Singleton that owns all tab sessions.

    Provides create / close / get operations and ensures the default tab
    always exists on startup.
    """

    def __init__(
        self,
        *,
        process_fn: Callable[[QueuedQuery], Coroutine[Any, Any, Optional[str]]],
        broadcast_fn: Callable[[str, str, Any], Coroutine[Any, Any, None]],
    ) -> None:
        self._tabs: Dict[str, TabSession] = {}
        self._process_fn = process_fn
        self._broadcast_fn = broadcast_fn

    # ── Tab lifecycle ─────────────────────────────────────────────

    def create_tab(self, tab_id: str) -> TabSession:
        """Create a new tab session. Raises if max tabs reached."""
        if tab_id in self._tabs:
            return self._tabs[tab_id]

        if len(self._tabs) >= MAX_TABS:
            raise ValueError(f"Maximum tab limit ({MAX_TABS}) reached")

        state = TabState(tab_id=tab_id)
        queue = ConversationQueue(
            tab_id,
            process_fn=self._process_fn,
            broadcast_fn=self._broadcast_fn,
        )
        session = TabSession(tab_id=tab_id, state=state, queue=queue)
        self._tabs[tab_id] = session
        logger.info("Created tab session: %s (total: %d)", tab_id, len(self._tabs))
        return session

    async def close_tab(self, tab_id: str) -> None:
        """Close a tab: drain its queue, remove from registry."""
        session = self._tabs.get(tab_id)
        if session is None:
            return

        # Drain the queue before removing from registry so in-flight
        # work can still look up the session during teardown.
        await session.queue.drain()

        # Import here to avoid circular import at module level
        from .ollama_global_queue import ollama_global_queue

        await ollama_global_queue.remove_tab(tab_id)

        # Now safe to remove
        self._tabs.pop(tab_id, None)
        logger.info("Closed tab session: %s (remaining: %d)", tab_id, len(self._tabs))

    async def close_all(self) -> None:
        """Close all tabs — called on app shutdown."""
        tab_ids = list(self._tabs.keys())
        for tab_id in tab_ids:
            await self.close_tab(tab_id)

    def ensure_default_tab(self) -> TabSession:
        """Create the default tab if it doesn't exist."""
        return self.create_tab("default")

    # ── Accessors ─────────────────────────────────────────────────

    def get_session(self, tab_id: str) -> Optional[TabSession]:
        return self._tabs.get(tab_id)

    def get_state(self, tab_id: str) -> Optional[TabState]:
        session = self._tabs.get(tab_id)
        return session.state if session else None

    def get_queue(self, tab_id: str) -> Optional[ConversationQueue]:
        session = self._tabs.get(tab_id)
        return session.queue if session else None

    def get_or_create(self, tab_id: str) -> TabSession:
        """Get an existing session or auto-create it."""
        if tab_id not in self._tabs:
            return self.create_tab(tab_id)
        return self._tabs[tab_id]

    def get_all_tab_ids(self) -> List[str]:
        return list(self._tabs.keys())

    @property
    def tab_count(self) -> int:
        return len(self._tabs)
