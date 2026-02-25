"""
WebSocket connection management.

Handles tracking of active WebSocket connections and message broadcasting.

Tab routing:
    ``_current_tab_id`` is an asyncio-aware context variable that is set
    at the start of each tab-scoped operation.  ``broadcast_message()``
    reads it automatically and stamps ``tab_id`` on every outgoing message
    so the frontend can route it to the correct tab — even for broadcasts
    originating deep in the LLM / MCP call chain.
"""
import contextvars
from typing import Coroutine, List, Dict, Any, Optional
from fastapi import WebSocket
import json

# ── Tab routing context variable ──────────────────────────────────
# Set via ``set_current_tab_id()`` before processing a tab-scoped request.
# ``broadcast_message()`` reads it to stamp ``tab_id`` on outgoing messages.
_current_tab_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_tab_id", default=None
)


def set_current_tab_id(tab_id: Optional[str]) -> contextvars.Token[Optional[str]]:
    """Set the tab_id for the current async context. Returns a reset token."""
    return _current_tab_id.set(tab_id)


def get_current_tab_id() -> Optional[str]:
    """Get the tab_id for the current async context."""
    return _current_tab_id.get()


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
            _current_tab_id.reset(tok)

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
    
    async def broadcast_json(self, message_type: str, content: Any, *, tab_id: Optional[str] = None) -> None:
        """Broadcast a JSON message with type and content fields.

        ``content`` can be any JSON-serialisable value (str, dict, list, etc.).
        It is embedded directly in the outer dict — no double-encoding.

        If *tab_id* is provided (or set via the ``_current_tab_id`` context
        variable), it is stamped onto the outgoing message so the frontend
        can route it to the correct tab.
        """
        resolved_tab = tab_id or _current_tab_id.get()
        payload: Dict[str, Any] = {"type": message_type, "content": content}
        if resolved_tab is not None:
            payload["tab_id"] = resolved_tab
        message = json.dumps(payload)
        await self.broadcast(message)


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
