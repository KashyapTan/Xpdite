"""Tests for source/core/connection.py — ConnectionManager."""

import json

import pytest

from source.core.connection import (
    ConnectionManager,
    get_current_tab_id,
    reset_current_tab_id,
    set_current_tab_id,
    wrap_with_tab_ctx,
)


class _FakeWebSocket:
    """Minimal fake WebSocket for testing."""

    def __init__(self, *, fail_on_send=False):
        self.accepted = False
        self.sent: list[str] = []
        self._fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        if self._fail_on_send:
            raise RuntimeError("connection closed")
        self.sent.append(message)


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_adds(self):
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        await mgr.connect(ws)
        assert ws.accepted is True
        assert ws in mgr.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_removes(self):
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_missing_is_noop(self):
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        mgr.disconnect(ws)  # should not raise
        assert mgr.active_connections == []

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast("hello")
        assert ws1.sent == ["hello"]
        assert ws2.sent == ["hello"]

    @pytest.mark.asyncio
    async def test_broadcast_removes_failed_connections(self):
        mgr = ConnectionManager()
        good = _FakeWebSocket()
        bad = _FakeWebSocket(fail_on_send=True)
        await mgr.connect(good)
        await mgr.connect(bad)
        await mgr.broadcast("test")
        assert good.sent == ["test"]
        assert bad not in mgr.active_connections
        assert good in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_json_formats_correctly(self):
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        await mgr.connect(ws)
        await mgr.broadcast_json("my_type", {"key": "value"})
        assert len(ws.sent) == 1
        parsed = json.loads(ws.sent[0])
        assert parsed["type"] == "my_type"
        assert parsed["content"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self):
        mgr = ConnectionManager()
        await mgr.broadcast("no-one listening")  # should not raise


class TestWrapWithTabCtx:
    @pytest.mark.asyncio
    async def test_sets_tab_id_during_execution(self):
        """Wrapped coroutine should see the correct tab_id."""
        captured = []

        async def capture():
            captured.append(get_current_tab_id())

        wrapped = wrap_with_tab_ctx("tab-42", capture())
        await wrapped
        assert captured == ["tab-42"]

    @pytest.mark.asyncio
    async def test_restores_previous_tab_id(self):
        """After wrapped coroutine completes, the outer tab_id is restored."""
        tok = set_current_tab_id("outer")
        try:
            async def inner():
                assert get_current_tab_id() == "inner"

            await wrap_with_tab_ctx("inner", inner())
            assert get_current_tab_id() == "outer"
        finally:
            reset_current_tab_id(tok)

    @pytest.mark.asyncio
    async def test_none_tab_id_returns_coro_unchanged(self):
        """When tab_id is None, the original coroutine is returned (no wrapper)."""
        async def noop():
            pass

        coro = noop()
        result = wrap_with_tab_ctx(None, coro)
        assert result is coro
        await result  # avoid RuntimeWarning

    @pytest.mark.asyncio
    async def test_restores_on_exception(self):
        """Tab ID is restored even if the inner coroutine raises."""
        tok = set_current_tab_id("before")
        try:
            async def failing():
                raise ValueError("boom")

            with pytest.raises(ValueError, match="boom"):
                await wrap_with_tab_ctx("error-tab", failing())
            assert get_current_tab_id() == "before"
        finally:
            reset_current_tab_id(tok)
