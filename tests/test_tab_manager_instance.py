"""Tests for source/services/tab_manager_instance.py."""

from unittest.mock import AsyncMock

import pytest

from source.core import connection
from source.core.state import app_state
from source.services.conversations import ConversationService
from source.services.ollama_global_queue import ollama_global_queue
from source.services.query_queue import QueuedQuery
from source.services.tab_manager import TabSession, TabState
from source.services import tab_manager_instance
from source.services.tab_manager_instance import (
    _adopt_global_screenshots,
    init_tab_manager,
)


@pytest.fixture(autouse=True)
def reset_tab_manager_singleton():
    """Keep the tab_manager singleton isolated across tests."""
    saved_singleton = tab_manager_instance.tab_manager
    tab_manager_instance.tab_manager = None
    yield
    tab_manager_instance.tab_manager = None
    tab_manager_instance.tab_manager = saved_singleton


class TestAdoptGlobalScreenshots:
    """Verify legacy global screenshots are absorbed into a tab session."""

    def test_moves_global_screenshots_into_target_session(self):
        session = TabSession(
            tab_id="default", state=TabState(tab_id="default"), queue=object()
        )
        saved_global_screenshots = list(app_state.screenshot_list)

        try:
            app_state.screenshot_list = [
                {
                    "id": "ss_1",
                    "path": "/tmp/a.png",
                    "name": "a.png",
                    "thumbnail": "thumb-a",
                },
                {
                    "id": "ss_2",
                    "path": "/tmp/b.png",
                    "name": "b.png",
                    "thumbnail": "thumb-b",
                },
            ]

            adopted_count = _adopt_global_screenshots(session)

            assert adopted_count == 2
            assert app_state.screenshot_list == []
            assert session.state.screenshot_list == [
                {
                    "id": "ss_1",
                    "path": "/tmp/a.png",
                    "name": "a.png",
                    "thumbnail": "thumb-a",
                },
                {
                    "id": "ss_2",
                    "path": "/tmp/b.png",
                    "name": "b.png",
                    "thumbnail": "thumb-b",
                },
            ]
        finally:
            app_state.screenshot_list = saved_global_screenshots

    def test_noop_when_global_list_is_empty(self):
        session = TabSession(
            tab_id="default", state=TabState(tab_id="default"), queue=object()
        )
        saved_global_screenshots = list(app_state.screenshot_list)

        try:
            app_state.screenshot_list = []

            adopted_count = _adopt_global_screenshots(session)

            assert adopted_count == 0
            assert session.state.screenshot_list == []
        finally:
            app_state.screenshot_list = saved_global_screenshots


class TestInitTabManager:
    def test_returns_existing_singleton_without_reinitializing(self):
        existing_singleton = object()
        tab_manager_instance.tab_manager = existing_singleton

        result = init_tab_manager()

        assert result is existing_singleton

    def test_initializes_default_tab_and_adopts_global_screenshots(self):
        saved_global_screenshots = list(app_state.screenshot_list)

        try:
            app_state.screenshot_list = [
                {
                    "id": "ss_legacy",
                    "path": "/tmp/legacy.png",
                    "name": "legacy.png",
                    "thumbnail": "legacy-thumb",
                }
            ]

            manager = init_tab_manager()

            default_session = manager.get_session("default")
            assert default_session is not None
            assert app_state.screenshot_list == []
            assert default_session.state.screenshot_list == [
                {
                    "id": "ss_legacy",
                    "path": "/tmp/legacy.png",
                    "name": "legacy.png",
                    "thumbnail": "legacy-thumb",
                }
            ]
            assert ollama_global_queue._broadcast_fn is connection.broadcast_message
        finally:
            app_state.screenshot_list = saved_global_screenshots


class TestProcessFnRouting:
    @pytest.mark.asyncio
    async def test_ollama_provider_routes_via_global_queue(self, monkeypatch):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-ollama")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)

        route_capture = {}

        async def fake_run(tab_id, process_fn):
            route_capture["tab_id"] = tab_id
            return await process_fn()

        monkeypatch.setattr(ollama_global_queue, "run", fake_run)

        query = QueuedQuery(
            tab_id="tab-ollama",
            content="hello ollama",
            model="qwen3-vl:8b",
            capture_mode="none",
        )

        conversation_id = await manager._process_fn(query)

        assert conversation_id == "conv-ollama"
        assert route_capture["tab_id"] == "tab-ollama"
        submit_query_mock.assert_awaited_once()
        submit_kwargs = submit_query_mock.await_args.kwargs
        assert submit_kwargs["user_query"] == "hello ollama"
        assert submit_kwargs["tab_state"].tab_id == "tab-ollama"
        assert submit_kwargs["queue"].tab_id == "tab-ollama"

    @pytest.mark.asyncio
    async def test_non_ollama_provider_submits_directly_without_global_queue(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-cloud")
        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        query = QueuedQuery(
            tab_id="tab-cloud",
            content="hello cloud",
            model="openai/gpt-4o",
            capture_mode="none",
        )

        conversation_id = await manager._process_fn(query)

        assert conversation_id == "conv-cloud"
        ollama_run_mock.assert_not_awaited()
        submit_query_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_fn_sets_and_resets_tab_context(self, monkeypatch):
        manager = init_tab_manager()
        observed = {}

        async def fake_submit_query(**kwargs):
            observed["during_submit"] = connection.get_current_tab_id()
            return "conv-context"

        monkeypatch.setattr(ConversationService, "submit_query", fake_submit_query)

        query = QueuedQuery(
            tab_id="tab-context",
            content="check context",
            model="openai/gpt-4o",
            capture_mode="none",
        )

        assert connection.get_current_tab_id() is None
        conversation_id = await manager._process_fn(query)

        assert conversation_id == "conv-context"
        assert observed["during_submit"] == "tab-context"
        assert connection.get_current_tab_id() is None
