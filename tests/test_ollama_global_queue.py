"""Tests for source/services/ollama_global_queue.py — OllamaGlobalQueue."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from source.services.ollama_global_queue import OllamaGlobalQueue


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def gq():
    """Fresh OllamaGlobalQueue (no module-level singleton reuse)."""
    return OllamaGlobalQueue()


@pytest.fixture()
def broadcast_fn():
    return AsyncMock()


# ── Basic run ─────────────────────────────────────────────────────

class TestRun:
    @pytest.mark.asyncio
    async def test_run_executes_process_fn(self, gq):
        executed = []

        async def _fn():
            executed.append(True)

        await gq.run("tab-1", _fn)
        assert len(executed) == 1

    @pytest.mark.asyncio
    async def test_run_propagates_exception(self, gq):
        async def _fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await gq.run("tab-1", _fail)

    @pytest.mark.asyncio
    async def test_sequential_execution(self, gq):
        """Two concurrent runs should execute sequentially."""
        order = []

        async def _first():
            order.append("first-start")
            await asyncio.sleep(0.02)
            order.append("first-end")

        async def _second():
            order.append("second-start")
            order.append("second-end")

        # Run both concurrently — second should wait for first
        await asyncio.gather(
            gq.run("tab-1", _first),
            gq.run("tab-2", _second),
        )

        assert order == ["first-start", "first-end", "second-start", "second-end"]


# ── Status properties ────────────────────────────────────────────

class TestStatus:
    @pytest.mark.asyncio
    async def test_active_tab_id_during_run(self, gq):
        captured_active = []

        async def _capture():
            captured_active.append(gq.active_tab_id)

        await gq.run("tab-A", _capture)
        assert captured_active == ["tab-A"]
        # After processing, active should be None
        assert gq.active_tab_id is None

    @pytest.mark.asyncio
    async def test_queued_tab_ids(self, gq):
        blocker = asyncio.Event()

        async def _block():
            await blocker.wait()

        async def _noop():
            pass

        # Start one blocking, queue another
        t1 = asyncio.create_task(gq.run("tab-1", _block))
        await asyncio.sleep(0.02)  # Let consumer start processing tab-1
        t2 = asyncio.create_task(gq.run("tab-2", _noop))
        await asyncio.sleep(0.02)

        assert gq.active_tab_id == "tab-1"
        assert "tab-2" in gq.queued_tab_ids

        blocker.set()
        await asyncio.gather(t1, t2)


# ── Remove tab ────────────────────────────────────────────────────

class TestRemoveTab:
    @pytest.mark.asyncio
    async def test_remove_queued_entries(self, gq):
        blocker = asyncio.Event()

        async def _block():
            await blocker.wait()

        async def _noop():
            pass

        t1 = asyncio.create_task(gq.run("tab-1", _block))
        await asyncio.sleep(0.02)

        # Queue tab-2 entries
        t2 = asyncio.create_task(gq.run("tab-2", _noop))
        await asyncio.sleep(0.02)

        await gq.remove_tab("tab-2")
        assert "tab-2" not in gq.queued_tab_ids

        blocker.set()
        await t1
        # t2 should complete with CancelledError (not hang forever)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(t2, timeout=1.0)

    @pytest.mark.asyncio
    async def test_remove_tab_unblocks_caller(self, gq):
        """After remove_tab, the caller of run() must NOT hang forever."""
        blocker = asyncio.Event()

        async def _block():
            await blocker.wait()

        async def _noop():
            pass

        t1 = asyncio.create_task(gq.run("tab-1", _block))
        await asyncio.sleep(0.02)

        t2 = asyncio.create_task(gq.run("tab-2", _noop))
        await asyncio.sleep(0.02)

        await gq.remove_tab("tab-2")

        # t2 must complete promptly (not hang)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(t2, timeout=1.0)

        blocker.set()
        await t1


# ── Broadcast ─────────────────────────────────────────────────────

class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_fn_called(self, gq, broadcast_fn):
        gq.set_broadcast_fn(broadcast_fn)

        async def _noop():
            pass

        await gq.run("tab-1", _noop)

        assert broadcast_fn.call_count >= 1
        # First call should be ollama_queue_status
        first_call = broadcast_fn.call_args_list[0]
        assert first_call.args[0] == "ollama_queue_status"

    @pytest.mark.asyncio
    async def test_no_broadcast_without_fn(self, gq):
        """Should not error if no broadcast_fn is set."""
        async def _noop():
            pass

        # Should complete without error even though no broadcast_fn
        await gq.run("tab-1", _noop)
