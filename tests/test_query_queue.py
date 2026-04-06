"""Tests for source/services/chat/query_queue.py — ConversationQueue."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from source.services.chat.query_queue import (
    ConversationQueue,
    QueuedQuery,
    QueueFullError,
    MAX_QUEUE_SIZE,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def process_fn():
    """Mock process function that returns a conversation id."""
    fn = AsyncMock(return_value="conv-123")
    return fn


@pytest.fixture()
def broadcast_fn():
    """Mock broadcast function."""
    return AsyncMock()


@pytest.fixture()
def queue(process_fn, broadcast_fn):
    return ConversationQueue(
        "tab-1",
        process_fn=process_fn,
        broadcast_fn=broadcast_fn,
    )


def _make_query(**kwargs) -> QueuedQuery:
    defaults = {"tab_id": "tab-1", "content": "hello", "model": "test-model"}
    defaults.update(kwargs)
    return QueuedQuery(**defaults)  # type: ignore[arg-type]


# ── Enqueue / Consumer ────────────────────────────────────────────

class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_returns_position(self, queue):
        pos = await queue.enqueue(_make_query())
        assert pos == 1

    @pytest.mark.asyncio
    async def test_enqueue_broadcasts_queued_and_state(self, queue, broadcast_fn):
        q = _make_query()
        await queue.enqueue(q)
        # Should have been called for query_queued and queue_updated
        types = [call.args[1] for call in broadcast_fn.call_args_list]
        assert "query_queued" in types
        assert "queue_updated" in types

    @pytest.mark.asyncio
    async def test_first_enqueued_item_is_hidden_from_queue_state(self, queue, broadcast_fn):
        await queue.enqueue(_make_query())

        queue_update_calls = [
            call for call in broadcast_fn.call_args_list if call.args[1] == "queue_updated"
        ]
        assert len(queue_update_calls) == 1
        assert queue_update_calls[0].args[2]["items"] == []

    @pytest.mark.asyncio
    async def test_consumer_processes_item(self, queue, process_fn):
        await queue.enqueue(_make_query())
        # Give the consumer task time to run
        await asyncio.sleep(0.05)
        process_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consumer_exits_when_empty(self, queue, process_fn):
        await queue.enqueue(_make_query())
        await asyncio.sleep(0.05)
        # Consumer should have finished and cleaned up
        assert queue._consumer_task is None

    @pytest.mark.asyncio
    async def test_consumer_processes_multiple_items_sequentially(self, queue, process_fn):
        order = []

        async def _track(item):
            order.append(item.item_id)
            return "conv-123"

        process_fn.side_effect = _track

        q1 = _make_query(content="first")
        q2 = _make_query(content="second")
        await queue.enqueue(q1)
        await queue.enqueue(q2)
        await asyncio.sleep(0.1)

        assert len(order) == 2
        assert order[0] == q1.item_id
        assert order[1] == q2.item_id

    @pytest.mark.asyncio
    async def test_queue_state_updates_when_next_item_becomes_active(self, broadcast_fn):
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()

        async def _track(item):
            if item.content == "first":
                first_started.set()
                await release_first.wait()
            else:
                second_started.set()
                await release_second.wait()
            return "conv-123"

        q = ConversationQueue(
            "tab-seq",
            process_fn=_track,
            broadcast_fn=broadcast_fn,
        )

        try:
            q1 = _make_query(content="first")
            q2 = _make_query(content="second")

            await q.enqueue(q1)
            await first_started.wait()
            await q.enqueue(q2)

            queue_update_calls = [
                call for call in broadcast_fn.call_args_list if call.args[1] == "queue_updated"
            ]
            assert queue_update_calls[-1].args[2]["items"][0]["item_id"] == q2.item_id

            release_first.set()
            await second_started.wait()

            queue_update_calls = [
                call for call in broadcast_fn.call_args_list if call.args[1] == "queue_updated"
            ]
            assert queue_update_calls[-1].args[2]["items"] == []

            release_second.set()
            await asyncio.sleep(0.02)
        finally:
            await q.drain()

    @pytest.mark.asyncio
    async def test_resolved_conversation_id_inherited(self, queue, process_fn):
        """Second enqueue should inherit the conversation_id from the first."""
        process_fn.return_value = "conv-abc"

        q1 = _make_query(content="first")
        await queue.enqueue(q1)
        await asyncio.sleep(0.05)

        # After processing, resolved_conversation_id should be set
        assert queue.resolved_conversation_id == "conv-abc"

        q2 = _make_query(content="second")
        await queue.enqueue(q2)
        await asyncio.sleep(0.05)

        # q2 should have inherited the conversation_id
        last_call_item = process_fn.call_args_list[-1].args[0]
        assert last_call_item.conversation_id == "conv-abc"


# ── Queue Full ────────────────────────────────────────────────────

class TestQueueFull:
    @pytest.mark.asyncio
    async def test_raises_when_full(self, broadcast_fn):
        # Use a slow process_fn so items stay queued
        never_finish = asyncio.Event()

        async def _slow(item):
            await never_finish.wait()
            return None

        q = ConversationQueue(
            "tab-full",
            process_fn=_slow,
            broadcast_fn=broadcast_fn,
        )

        try:
            # First enqueue starts the consumer which immediately dequeues item 0
            # for processing. That frees one slot in the asyncio.Queue, so we can
            # enqueue MAX_QUEUE_SIZE more items (1 processing + 5 queued = 6 total).
            await q.enqueue(_make_query(content="msg-0"))
            await asyncio.sleep(0.02)  # Let consumer pick up msg-0

            # Now fill the queue to capacity
            for i in range(1, MAX_QUEUE_SIZE + 1):
                await q.enqueue(_make_query(content=f"msg-{i}"))

            # Next one should fail
            with pytest.raises(QueueFullError):
                await q.enqueue(_make_query(content="overflow"))
        finally:
            await q.drain()


# ── Cancel Item ───────────────────────────────────────────────────

class TestCancelItem:
    @pytest.mark.asyncio
    async def test_cancel_queued_item(self, broadcast_fn):
        """Cancel a waiting item (not the one being processed)."""
        blocker = asyncio.Event()

        async def _block(item):
            await blocker.wait()
            return None

        q = ConversationQueue(
            "tab-cancel",
            process_fn=_block,
            broadcast_fn=broadcast_fn,
        )

        try:
            q1 = _make_query(content="blocking")
            q2 = _make_query(content="to-cancel")

            await q.enqueue(q1)
            await q.enqueue(q2)
            await asyncio.sleep(0.02)

            # q1 should be processing; q2 should be queued
            removed = await q.cancel_item(q2.item_id)
            assert removed is True
            assert len(q.queued_items) == 0
        finally:
            await q.drain()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, queue):
        result = await queue.cancel_item("does-not-exist")
        assert result is False


# ── Drain ─────────────────────────────────────────────────────────

class TestDrain:
    @pytest.mark.asyncio
    async def test_drain_clears_queue(self, broadcast_fn):
        blocker = asyncio.Event()

        async def _block(item):
            await blocker.wait()
            return None

        q = ConversationQueue(
            "tab-drain",
            process_fn=_block,
            broadcast_fn=broadcast_fn,
        )

        await q.enqueue(_make_query(content="blocking"))
        await q.enqueue(_make_query(content="queued"))
        await asyncio.sleep(0.02)

        await q.drain()

        assert q._consumer_task is None
        assert q._queue.empty()


# ── Stop Current ──────────────────────────────────────────────────

class TestStopCurrent:
    @pytest.mark.asyncio
    async def test_stop_current_cancels_active_ctx(self, queue):
        """stop_current should cancel the active RequestContext."""
        from unittest.mock import MagicMock

        mock_ctx = MagicMock()
        queue._active_ctx = mock_ctx

        await queue.stop_current()
        mock_ctx.cancel.assert_called_once()


# ── Reset Conversation ────────────────────────────────────────────

class TestResetConversation:
    def test_reset_clears_resolved_id(self, queue):
        queue.resolved_conversation_id = "conv-xyz"
        queue.reset_conversation()
        assert queue.resolved_conversation_id is None


# ── Error Handling ────────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_consumer_continues_after_error(self, broadcast_fn):
        """If a process_fn raises, the consumer broadcasts error and continues."""
        call_order = []

        async def _fail_then_succeed(item):
            if item.content == "fail":
                call_order.append("fail")
                raise RuntimeError("Simulated failure")
            call_order.append("success")
            return "conv-ok"

        q = ConversationQueue(
            "tab-err",
            process_fn=_fail_then_succeed,
            broadcast_fn=broadcast_fn,
        )

        await q.enqueue(_make_query(content="fail"))
        await q.enqueue(_make_query(content="succeed"))
        await asyncio.sleep(0.1)

        assert call_order == ["fail", "success"]
        # The error should have been broadcast
        error_calls = [
            c for c in broadcast_fn.call_args_list
            if c.args[1] == "error"
        ]
        assert len(error_calls) >= 1


# ── Queued Items Snapshot ─────────────────────────────────────────

class TestQueuedItems:
    @pytest.mark.asyncio
    async def test_queued_items_snapshot(self, broadcast_fn):
        blocker = asyncio.Event()

        async def _block(item):
            await blocker.wait()
            return None

        q = ConversationQueue(
            "tab-snap",
            process_fn=_block,
            broadcast_fn=broadcast_fn,
        )

        try:
            q1 = _make_query(content="blocking")
            q2 = _make_query(content="second item here")

            await q.enqueue(q1)
            await q.enqueue(q2)
            await asyncio.sleep(0.02)

            items = q.queued_items
            # Only q2 should appear (q1 is being processed)
            assert len(items) == 1
            assert items[0]["item_id"] == q2.item_id
            assert items[0]["preview"] == "second item here"
            assert items[0]["position"] == 1
        finally:
            await q.drain()
