"""Tests for source/services/chat/tab_manager_instance.py."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from source.core import connection
from source.core.state import app_state
from source.services.chat.conversations import ConversationService
from source.services.chat.ollama_global_queue import ollama_global_queue
from source.services.chat.query_queue import QueuedQuery
from source.services.chat import tab_manager_instance
from source.services.chat.tab_manager_instance import init_tab_manager


@pytest.fixture(autouse=True)
def reset_tab_manager_singleton():
    """Keep the tab_manager singleton isolated across tests."""
    saved_singleton = tab_manager_instance.tab_manager
    tab_manager_instance.tab_manager = None
    yield
    tab_manager_instance.tab_manager = None
    tab_manager_instance.tab_manager = saved_singleton


class TestInitTabManager:
    def test_returns_existing_singleton_without_reinitializing(self):
        existing_singleton = object()
        tab_manager_instance.tab_manager = existing_singleton

        result = init_tab_manager()

        assert result is existing_singleton

    def test_initializes_default_tab(self):
        manager = init_tab_manager()

        default_session = manager.get_session("default")
        assert default_session is not None
        assert default_session.state.tab_id == "default"
        assert ollama_global_queue._broadcast_fn is connection.broadcast_message


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
        submit_kwargs = submit_query_mock.await_args_list[0].kwargs  # type: ignore[union-attr]
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
    async def test_ollama_cloud_model_submits_directly_without_global_queue(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-ollama-cloud")
        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        query = QueuedQuery(
            tab_id="tab-ollama-cloud",
            content="hello ollama cloud",
            model="qwen3.5:397b-cloud",
            capture_mode="none",
        )

        conversation_id = await manager._process_fn(query)

        assert conversation_id == "conv-ollama-cloud"
        ollama_run_mock.assert_not_awaited()
        submit_query_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ollama_cloud_colon_tag_submits_directly_without_global_queue(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-ollama-cloud-colon")
        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        query = QueuedQuery(
            tab_id="tab-ollama-cloud-colon",
            content="hello ollama cloud colon",
            model="qwen3-coder-next:cloud",
            capture_mode="none",
        )

        conversation_id = await manager._process_fn(query)

        assert conversation_id == "conv-ollama-cloud-colon"
        ollama_run_mock.assert_not_awaited()
        submit_query_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ollama_cloud_models_can_run_in_parallel(self, monkeypatch):
        manager = init_tab_manager()
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_submit_query(**kwargs):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)

            await asyncio.sleep(0.05)

            async with lock:
                in_flight -= 1

            return f"conv-{kwargs['tab_state'].tab_id}"

        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", fake_submit_query)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        query_a = QueuedQuery(
            tab_id="tab-cloud-a",
            content="hello cloud A",
            model="qwen3.5:397b-cloud",
            capture_mode="none",
        )
        query_b = QueuedQuery(
            tab_id="tab-cloud-b",
            content="hello cloud B",
            model="qwen3-coder-next:cloud",
            capture_mode="none",
        )

        results = await asyncio.gather(
            manager._process_fn(query_a),
            manager._process_fn(query_b),
        )

        assert set(results) == {"conv-tab-cloud-a", "conv-tab-cloud-b"}
        assert max_in_flight == 2
        ollama_run_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_model_uses_selected_model_and_routes_local_through_queue(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-selected-local")

        async def fake_ollama_run(_tab_id, fn):
            return await fn()

        ollama_run_mock = AsyncMock(side_effect=fake_ollama_run)
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        saved_model = app_state.selected_model
        app_state.selected_model = "qwen3-vl:8b"
        try:
            query = QueuedQuery(
                tab_id="tab-selected-local",
                content="hello selected local",
                model="",
                capture_mode="none",
            )

            conversation_id = await manager._process_fn(query)

            assert conversation_id == "conv-selected-local"
            ollama_run_mock.assert_awaited_once()
            submit_query_mock.assert_awaited_once()
        finally:
            app_state.selected_model = saved_model

    @pytest.mark.asyncio
    async def test_empty_model_uses_selected_model_and_bypasses_queue_for_cloud(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-selected-cloud")
        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        saved_model = app_state.selected_model
        app_state.selected_model = "qwen3.5:397b-cloud"
        try:
            query = QueuedQuery(
                tab_id="tab-selected-cloud",
                content="hello selected cloud",
                model="",
                capture_mode="none",
            )

            conversation_id = await manager._process_fn(query)

            assert conversation_id == "conv-selected-cloud"
            ollama_run_mock.assert_not_awaited()
            submit_query_mock.assert_awaited_once()
        finally:
            app_state.selected_model = saved_model

    @pytest.mark.asyncio
    async def test_empty_model_uses_selected_model_cloud_colon_tag_bypasses_queue(
        self, monkeypatch
    ):
        manager = init_tab_manager()
        submit_query_mock = AsyncMock(return_value="conv-selected-cloud-colon")
        ollama_run_mock = AsyncMock(return_value="should-not-be-used")
        monkeypatch.setattr(ConversationService, "submit_query", submit_query_mock)
        monkeypatch.setattr(ollama_global_queue, "run", ollama_run_mock)

        saved_model = app_state.selected_model
        app_state.selected_model = "qwen3-coder-next:cloud"
        try:
            query = QueuedQuery(
                tab_id="tab-selected-cloud-colon",
                content="hello selected cloud colon",
                model="",
                capture_mode="none",
            )

            conversation_id = await manager._process_fn(query)

            assert conversation_id == "conv-selected-cloud-colon"
            ollama_run_mock.assert_not_awaited()
            submit_query_mock.assert_awaited_once()
        finally:
            app_state.selected_model = saved_model

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
