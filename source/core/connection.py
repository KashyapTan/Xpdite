"""
WebSocket connection management.

Handles tracking of active WebSocket connections and message broadcasting.

Tab routing:
    ``_current_tab_id`` is an asyncio-aware context variable that is set
    at the start of each tab-scoped operation.  ``broadcast_message()``
    reads it automatically and stamps ``tab_id`` on every outgoing message
    so the frontend can route it to the correct tab — even for broadcasts
    originating deep in the LLM / MCP call chain.

Mobile relay:
    When a tab is mobile-originated, broadcast events are relayed to the
    Channel Bridge for delivery to the user's messaging platform. The relay
    callback is registered via ``set_mobile_relay_callback()``.
"""

import contextvars
import logging
from typing import Callable, Coroutine, List, Dict, Any, Optional, Awaitable
from fastapi import WebSocket
import json

logger = logging.getLogger(__name__)

# ── Tab routing context variable ──────────────────────────────────
# Set via ``set_current_tab_id()`` before processing a tab-scoped request.
# ``broadcast_message()`` reads it to stamp ``tab_id`` on outgoing messages.
_current_tab_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_tab_id", default=None
)

# ── Mobile relay callback ──────────────────────────────────────────
# Called for every broadcast when set. The callback receives:
#   (message_type, content, tab_id) and should relay to Channel Bridge
#   if the tab is mobile-originated.
MobileRelayCallback = Callable[[str, Any, Optional[str]], Awaitable[None]]
_mobile_relay_callback: Optional[MobileRelayCallback] = None

# ── Tab routing context variable ──────────────────────────────────
# Set via ``set_current_tab_id()`` before processing a tab-scoped request.
# ``broadcast_message()`` reads it to stamp ``tab_id`` on outgoing messages.
_current_tab_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_tab_id", default=None
)


def set_current_tab_id(tab_id: Optional[str]) -> contextvars.Token[Optional[str]]:
    """Set the tab_id for the current async context. Returns a reset token."""
    return _current_tab_id.set(tab_id)


def reset_current_tab_id(token: contextvars.Token[Optional[str]]) -> None:
    """Restore the previous tab_id for the current async context."""
    _current_tab_id.reset(token)


def get_current_tab_id() -> Optional[str]:
    """Get the tab_id for the current async context."""
    return _current_tab_id.get()


def set_mobile_relay_callback(callback: Optional[MobileRelayCallback]) -> None:
    """Set the callback for relaying broadcasts to mobile platforms.

    The callback is called for EVERY broadcast. It should check if the
    tab_id corresponds to a mobile-originated tab and relay accordingly.
    """
    global _mobile_relay_callback
    _mobile_relay_callback = callback


def get_mobile_relay_callback() -> Optional[MobileRelayCallback]:
    """Get the current mobile relay callback."""
    return _mobile_relay_callback


def wrap_with_tab_ctx(tab_id: Optional[str], coro: Coroutine) -> Coroutine:
    """Wrap a coroutine so ``_current_tab_id`` is set during its execution.

    Background threads that schedule coroutines on the event loop via
    ``call_soon_threadsafe(create_task, ...)`` or ``run_coroutine_threadsafe``
    lose the contextvar.  Wrapping the coroutine with this helper preserves
    it, ensuring ``broadcast_message`` stamps the correct ``tab_id``.

    If *tab_id* is ``None`` the coroutine is returned unchanged (no overhead).
    """
    if tab_id is None:
        return coro

    async def _ctx_coro():
        tok = set_current_tab_id(tab_id)
        try:
            await coro
        finally:
            reset_current_tab_id(tok)

    return _ctx_coro()


class ConnectionManager:
    """
    Manages WebSocket connections for real-time communication.

    Handles:
    - Connection tracking
    - Safe message broadcasting
    - Automatic disconnection cleanup
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from tracked connections."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        """
        Broadcast a message to all connected clients.

        Automatically removes disconnected clients.
        """
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_json(
        self, message_type: str, content: Any, *, tab_id: Optional[str] = None
    ) -> None:
        """Broadcast a JSON message with type and content fields.

        ``content`` can be any JSON-serialisable value (str, dict, list, etc.).
        It is embedded directly in the outer dict — no double-encoding.

        If *tab_id* is provided (or set via the ``_current_tab_id`` context
        variable), it is stamped onto the outgoing message so the frontend
        can route it to the correct tab.

        If a mobile relay callback is registered, it is called to potentially
        relay the message to mobile platforms.
        """
        resolved_tab = tab_id or _current_tab_id.get()
        payload: Dict[str, Any] = {"type": message_type, "content": content}
        if resolved_tab is not None:
            payload["tab_id"] = resolved_tab
        message = json.dumps(payload)

        # Mobile relay hook - enqueue in order before broadcasting.
        # The registered callback should stay lightweight (e.g. queueing work)
        # so websocket delivery is not delayed by platform HTTP calls.
        if _mobile_relay_callback is not None:
            await self._safe_mobile_relay(message_type, content, resolved_tab)

        await self.broadcast(message)

    async def _safe_mobile_relay(
        self, message_type: str, content: Any, tab_id: Optional[str]
    ) -> None:
        """Safely call the mobile relay callback, catching any errors."""
        if _mobile_relay_callback is None:
            return
        try:
            await _mobile_relay_callback(message_type, content, tab_id)
        except Exception as e:
            # Log but don't fail - mobile relay errors shouldn't affect main app
            logger.warning(f"Mobile relay error: {e}")


# Global connection manager instance
manager = ConnectionManager()


async def broadcast_message(message_type: str, content: Any) -> None:
    """Helper function to broadcast messages.

    Automatically stamps ``tab_id`` from the current async context if set.
    """
    await manager.broadcast_json(message_type, content)


async def broadcast_to_tab(tab_id: str, message_type: str, content: Any) -> None:
    """Broadcast a message explicitly scoped to a specific tab."""
    await manager.broadcast_json(message_type, content, tab_id=tab_id)
