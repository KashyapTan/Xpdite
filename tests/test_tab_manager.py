"""Tests for source/services/chat/tab_manager.py — TabState and TabManager."""

from unittest.mock import AsyncMock

import pytest

from source.services.chat.tab_manager import TabManager, TabState, MAX_TABS


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def process_fn():
    return AsyncMock(return_value="conv-123")


@pytest.fixture()
def broadcast_fn():
    return AsyncMock()


@pytest.fixture()
def manager(process_fn, broadcast_fn):
    return TabManager(process_fn=process_fn, broadcast_fn=broadcast_fn)


# ── TabState ──────────────────────────────────────────────────────

class TestTabState:
    def test_initial_state(self):
        state = TabState(tab_id="t1")
        assert state.tab_id == "t1"
        assert state.chat_history == []
        assert state.conversation_id is None
        assert state.screenshot_list == []
        assert state.is_streaming is False
        assert state.stop_streaming is False

    def test_reset_conversation(self):
        state = TabState(tab_id="t1")
        state.chat_history = [{"role": "user", "content": "hi"}]
        state.conversation_id = "conv-1"
        state.screenshot_list = [{"id": "s1", "path": "/tmp/s.png"}]

        state.reset_conversation()

        assert state.chat_history == []
        assert state.conversation_id is None
        assert state.screenshot_list == []

    def test_get_image_paths_filters_invalid(self, tmp_path):
        """Only paths that exist on disk are returned."""
        real = tmp_path / "real.png"
        real.write_bytes(b"\x89PNG")

        state = TabState(tab_id="t1")
        state.screenshot_list = [
            {"id": "s1", "path": str(real)},
            {"id": "s2", "path": "/nonexistent/fake.png"},
        ]

        paths = state.get_image_paths()
        assert len(paths) == 1
        assert paths[0].endswith("real.png")


# ── TabManager ────────────────────────────────────────────────────

class TestTabManager:
    def test_create_tab(self, manager):
        session = manager.create_tab("tab-1")
        assert session.tab_id == "tab-1"
        assert session.state.tab_id == "tab-1"
        assert manager.tab_count == 1

    def test_create_tab_idempotent(self, manager):
        """Creating the same tab twice returns the existing session."""
        s1 = manager.create_tab("tab-1")
        s2 = manager.create_tab("tab-1")
        assert s1 is s2
        assert manager.tab_count == 1

    def test_max_tabs_enforced(self, manager):
        for i in range(MAX_TABS):
            manager.create_tab(f"tab-{i}")

        with pytest.raises(ValueError, match="Maximum tab limit"):
            manager.create_tab("overflow")

    @pytest.mark.asyncio
    async def test_close_tab(self, manager):
        manager.create_tab("tab-1")
        assert manager.tab_count == 1

        await manager.close_tab("tab-1")
        assert manager.tab_count == 0
        assert manager.get_session("tab-1") is None

    @pytest.mark.asyncio
    async def test_close_tab_nonexistent(self, manager):
        """Closing a tab that doesn't exist is a no-op."""
        await manager.close_tab("ghost")
        assert manager.tab_count == 0

    @pytest.mark.asyncio
    async def test_close_all(self, manager):
        manager.create_tab("a")
        manager.create_tab("b")
        manager.create_tab("c")
        assert manager.tab_count == 3

        await manager.close_all()
        assert manager.tab_count == 0

    def test_ensure_default_tab(self, manager):
        session = manager.ensure_default_tab()
        assert session.tab_id == "default"
        assert manager.tab_count == 1

        # Calling again should return the same session
        same = manager.ensure_default_tab()
        assert same is session

    def test_get_session(self, manager):
        manager.create_tab("tab-1")
        assert manager.get_session("tab-1") is not None
        assert manager.get_session("nope") is None

    def test_get_state(self, manager):
        manager.create_tab("tab-1")
        state = manager.get_state("tab-1")
        assert state is not None
        assert state.tab_id == "tab-1"
        assert manager.get_state("nope") is None

    def test_get_queue(self, manager):
        manager.create_tab("tab-1")
        queue = manager.get_queue("tab-1")
        assert queue is not None
        assert queue.tab_id == "tab-1"
        assert manager.get_queue("nope") is None

    def test_get_or_create(self, manager):
        """get_or_create should auto-create if missing."""
        session = manager.get_or_create("new-tab")
        assert session.tab_id == "new-tab"
        assert manager.tab_count == 1

        # Subsequent call returns same session
        same = manager.get_or_create("new-tab")
        assert same is session

    def test_get_all_tab_ids(self, manager):
        manager.create_tab("a")
        manager.create_tab("b")
        ids = manager.get_all_tab_ids()
        assert set(ids) == {"a", "b"}
