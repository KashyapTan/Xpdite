"""
Global Ollama serialization queue.

Ollama can only serve one request at a time (single GPU).  This singleton
ensures that all tabs using Ollama models are serialized globally, while
cloud-provider tabs run independently in parallel.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class _OllamaEntry:
    """Internal wrapper for a queued Ollama request."""

    tab_id: str
    process_fn: Callable[[], Coroutine[Any, Any, None]]
    done_event: asyncio.Event
    exception_holder: List[Optional[BaseException]]


class OllamaGlobalQueue:
    """Serializes Ollama requests across all tabs.

    Cloud tabs bypass this entirely and run in parallel via their
    tab-local ``ConversationQueue``.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[_OllamaEntry] = asyncio.Queue()
        self._active_tab_id: Optional[str] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._broadcast_fn: Optional[
            Callable[[str, Any], Coroutine[Any, Any, None]]
        ] = None

    def set_broadcast_fn(
        self,
        fn: Callable[[str, Any], Coroutine[Any, Any, None]],
    ) -> None:
        """Inject the global broadcast function (avoids circular imports)."""
        self._broadcast_fn = fn

    # ── Public API ────────────────────────────────────────────────

    async def run(
        self,
        tab_id: str,
        process_fn: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """Enqueue an Ollama request and wait for it to complete.

        The caller suspends here until the global queue reaches this entry
        and ``process_fn`` finishes.  Returns whatever ``process_fn`` returns.
        """
        done_event = asyncio.Event()
        exception_holder: List[Optional[BaseException]] = [None]
        result_holder: List[Any] = [None]

        async def _wrapper() -> None:
            try:
                result_holder[0] = await process_fn()
            except Exception as exc:
                exception_holder[0] = exc
                raise
            finally:
                done_event.set()

        entry = _OllamaEntry(
            tab_id=tab_id,
            process_fn=_wrapper,
            done_event=done_event,
            exception_holder=exception_holder,
        )
        await self._queue.put(entry)

        # Spawn consumer if not running
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consumer(), name="ollama-global-consumer"
            )

        await self._broadcast_status()

        # Wait for our entry to be processed
        await done_event.wait()

        if exception_holder[0] is not None:
            raise exception_holder[0]

        return result_holder[0]

    async def remove_tab(self, tab_id: str) -> None:
        """Remove all pending entries for a tab (called on tab close).

        Unblocks any ``run()`` callers waiting on removed entries by setting
        their ``done_event`` and storing a ``CancelledError`` so they raise
        cleanly instead of hanging forever.

        Does NOT cancel the currently active entry — that is handled by
        ``ConversationQueue.drain()``.
        """
        temp: List[_OllamaEntry] = []

        while not self._queue.empty():
            try:
                entry = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if entry.tab_id == tab_id:
                # Unblock the caller so it doesn't hang
                entry.exception_holder[0] = asyncio.CancelledError(
                    f"Tab {tab_id} was closed"
                )
                entry.done_event.set()
            else:
                temp.append(entry)

        for entry in temp:
            await self._queue.put(entry)

        await self._broadcast_status()

    # ── Status ────────────────────────────────────────────────────

    @property
    def active_tab_id(self) -> Optional[str]:
        return self._active_tab_id

    @property
    def queued_tab_ids(self) -> List[str]:
        return [e.tab_id for e in list(self._queue._queue)]  # type: ignore[attr-defined]

    # ── Internal ──────────────────────────────────────────────────

    async def _consumer(self) -> None:
        """Process Ollama requests one at a time, globally."""
        try:
            while True:
                try:
                    entry = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                self._active_tab_id = entry.tab_id
                await self._broadcast_status()

                try:
                    await entry.process_fn()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Ollama global queue: error processing tab %s",
                        entry.tab_id,
                    )
                finally:
                    self._queue.task_done()
                    self._active_tab_id = None
                    await self._broadcast_status()
        except asyncio.CancelledError:
            pass
        finally:
            self._consumer_task = None

    async def _broadcast_status(self) -> None:
        """Send Ollama queue status to all clients."""
        if self._broadcast_fn is None:
            return
        await self._broadcast_fn(
            "ollama_queue_status",
            {
                "active_tab_id": self._active_tab_id,
                "queued_tab_ids": self.queued_tab_ids,
            },
        )


# Module-level singleton
ollama_global_queue = OllamaGlobalQueue()
