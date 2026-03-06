"""
Per-tab async message queue.

Each tab gets its own ConversationQueue backed by an asyncio.Queue.
Items are processed sequentially within a tab. Ollama models are
additionally serialized across all tabs via the OllamaGlobalQueue.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional

if TYPE_CHECKING:
    from ..core.request_context import RequestContext

logger = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 5


class QueueFullError(Exception):
    """Raised when a tab's queue has reached its capacity."""


@dataclass
class QueuedQuery:
    """A single queued user message waiting to be processed."""

    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tab_id: str = ""
    content: str = ""
    model: str = ""
    capture_mode: str = "none"
    images: List[str] = field(default_factory=list)
    conversation_id: Optional[str] = None
    forced_skills: list = field(default_factory=list)  # List[Skill] at runtime
    llm_query: Optional[str] = None
    action: str = "submit"
    target_message_id: Optional[str] = None


class ConversationQueue:
    """Async queue that processes user queries sequentially for one tab.

    - Backed by ``asyncio.Queue(maxsize=MAX_QUEUE_SIZE)``
    - Consumer task is lazily spawned on first ``enqueue`` and exits
      when the queue drains (re-spawned on next ``enqueue``).
    - ``resolved_conversation_id`` is set after the first query creates
      a conversation; subsequent items inherit it automatically.
    """

    def __init__(
        self,
        tab_id: str,
        *,
        process_fn: Callable[[QueuedQuery], Coroutine[Any, Any, Optional[str]]],
        broadcast_fn: Callable[[str, str, Any], Coroutine[Any, Any, None]],
    ) -> None:
        self.tab_id = tab_id
        self._queue: asyncio.Queue[QueuedQuery] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._active_ctx: Optional[RequestContext] = None
        self.resolved_conversation_id: Optional[str] = None

        # Injected dependencies
        self._process_fn = process_fn
        self._broadcast_fn = broadcast_fn

    # ── Public API ────────────────────────────────────────────────

    async def enqueue(self, query: QueuedQuery) -> int:
        """Add a query to the queue.

        Returns the 1-based position in the queue.
        Raises ``QueueFullError`` if the queue is at capacity.
        """
        if self._queue.full():
            raise QueueFullError(
                f"Tab {self.tab_id} queue is full ({MAX_QUEUE_SIZE} items)"
            )

        # Inherit conversation_id if we already have one for this tab
        if self.resolved_conversation_id and not query.conversation_id:
            query.conversation_id = self.resolved_conversation_id

        self._queue.put_nowait(query)
        position = self._queue.qsize()

        # Notify frontend
        await self._broadcast_fn(
            self.tab_id,
            "query_queued",
            {"item_id": query.item_id, "position": position},
        )
        await self._broadcast_queue_state()

        # Spawn consumer if not running
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consumer(), name=f"queue-consumer-{self.tab_id}"
            )

        return position

    async def cancel_item(self, item_id: str) -> bool:
        """Cancel a queued (not yet running) item.

        Returns True if the item was found and removed.
        Returns False if the item is currently running or not found.
        """
        temp: List[QueuedQuery] = []
        found = False

        # Drain → filter → refill
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item.item_id == item_id:
                found = True
            else:
                temp.append(item)

        for item in temp:
            self._queue.put_nowait(item)

        if found:
            await self._broadcast_queue_state()

        return found

    async def drain(self) -> None:
        """Cancel everything: running item + all queued items.

        Called on tab close or app shutdown.
        """
        # Cancel consumer task
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        # Cancel active request
        if self._active_ctx is not None:
            self._active_ctx.cancel()
            self._active_ctx = None

        # Clear remaining items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def stop_current(self) -> None:
        """Stop only the currently running request. Queue continues."""
        if self._active_ctx is not None:
            self._active_ctx.cancel()

    def reset_conversation(self) -> None:
        """Reset resolved_conversation_id (e.g. on clear_context)."""
        self.resolved_conversation_id = None

    @property
    def is_processing(self) -> bool:
        return self._active_ctx is not None and not self._active_ctx.is_done

    @property
    def queued_items(self) -> List[Dict[str, Any]]:
        """Snapshot of items waiting in the queue (not the active one)."""
        items = list(self._queue._queue)  # type: ignore[attr-defined]
        return [
            {
                "item_id": item.item_id,
                "preview": item.content[:80],
                "position": i + 1,
            }
            for i, item in enumerate(items)
        ]

    # ── Internal ──────────────────────────────────────────────────

    async def _consumer(self) -> None:
        """Process items sequentially until the queue is empty."""
        try:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                try:
                    await self._process_item(item)
                except asyncio.CancelledError:
                    # Drain was called — save interrupted state and exit
                    logger.info(
                        "Queue consumer for tab %s cancelled during processing",
                        self.tab_id,
                    )
                    raise
                except Exception:
                    logger.exception(
                        "Error processing queued item %s on tab %s",
                        item.item_id,
                        self.tab_id,
                    )
                    # Broadcast error to the tab, but continue processing
                    await self._broadcast_fn(
                        self.tab_id,
                        "error",
                        f"Queued message failed: {item.content[:80]}...",
                    )
                finally:
                    self._queue.task_done()
                    await self._broadcast_queue_state()
        except asyncio.CancelledError:
            pass
        finally:
            self._consumer_task = None

    async def _process_item(self, item: QueuedQuery) -> None:
        """Process a single queued query."""
        conversation_id = await self._process_fn(item)

        # Track the conversation_id for this tab
        if conversation_id and not self.resolved_conversation_id:
            self.resolved_conversation_id = conversation_id

    def set_active_ctx(self, ctx: RequestContext) -> None:
        """Called by the processing function to register the active context."""
        self._active_ctx = ctx

    def clear_active_ctx(self) -> None:
        """Called by the processing function when done."""
        self._active_ctx = None

    async def _broadcast_queue_state(self) -> None:
        """Send current queue state to the frontend."""
        await self._broadcast_fn(
            self.tab_id,
            "queue_updated",
            {"tab_id": self.tab_id, "items": self.queued_items},
        )
