"""Tests for MCP manager embedding refresh behaviour."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import source.mcp_integration.manager as manager_module


@pytest.fixture()
def reset_mcp_manager_state():
    """Reset the singleton manager around tests that inspect init flow."""
    manager = manager_module.mcp_manager
    original_state = {
        "tool_registry": manager._tool_registry,
        "connections": manager._connections,
        "ollama_tools": manager._ollama_tools,
        "raw_tools": manager._raw_tools,
        "initialized": manager._initialized,
    }

    manager._tool_registry = {}
    manager._connections = {}
    manager._ollama_tools = []
    manager._raw_tools = []
    manager._initialized = False

    try:
        yield manager
    finally:
        manager._tool_registry = original_state["tool_registry"]
        manager._connections = original_state["connections"]
        manager._ollama_tools = original_state["ollama_tools"]
        manager._raw_tools = original_state["raw_tools"]
        manager._initialized = original_state["initialized"]


class TestInitMcpServers:
    @pytest.mark.asyncio
    async def test_final_startup_refresh_does_not_prune_cached_tools(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        with patch.object(manager, "connect_server", new_callable=AsyncMock) as connect_server, patch.object(
            manager, "register_inline_tools"
        ) as register_inline_tools, patch.object(
            manager_module.retriever, "embed_tools"
        ) as embed_tools:
            await manager_module.init_mcp_servers()

        assert connect_server.await_count == 2
        assert register_inline_tools.call_count == 3
        embed_tools.assert_called_once_with([])
        assert manager._initialized is True


class TestConnectGoogleServers:
    @pytest.mark.asyncio
    async def test_google_reconnect_refresh_does_not_prune_cached_tools(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        with patch("source.mcp_integration.manager.os.path.exists", return_value=True), patch.object(
            manager,
            "is_server_connected",
            side_effect=[False, False],
        ), patch.object(
            manager, "connect_server", new_callable=AsyncMock
        ) as connect_server, patch.object(
            manager_module.retriever, "embed_tools"
        ) as embed_tools:
            await manager.connect_google_servers()

        assert connect_server.await_count == 2
        embed_tools.assert_called_once_with([])


class TestManagerLifecycleRefresh:
    @pytest.mark.asyncio
    async def test_disconnect_server_refreshes_remaining_tools_without_pruning_cache(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task

        manager._connections = {
            "demo": {
                "shutdown_event": asyncio.Event(),
                "task": done_task,
            }
        }
        manager._tool_registry = {
            "demo_tool": {"server_name": "demo", "session": object()},
            "keep_tool": {"server_name": "keep", "session": object()},
        }
        manager._ollama_tools = [
            {"function": {"name": "demo_tool", "description": "Demo tool"}},
            {"function": {"name": "keep_tool", "description": "Keep tool"}},
        ]
        manager._raw_tools = [
            {"name": "demo_tool", "description": "Demo tool", "input_schema": {}},
            {"name": "keep_tool", "description": "Keep tool", "input_schema": {}},
        ]

        with patch.object(manager_module.retriever, "embed_tools") as embed_tools:
            await manager.disconnect_server("demo")

        assert "demo" not in manager._connections
        assert "demo_tool" not in manager._tool_registry
        assert [tool["function"]["name"] for tool in manager._ollama_tools] == ["keep_tool"]
        assert [tool["name"] for tool in manager._raw_tools] == ["keep_tool"]
        embed_tools.assert_called_once_with(manager._ollama_tools)

    def test_register_inline_tools_refreshes_active_tool_set_without_pruning_cache(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        manager._ollama_tools = [
            {"function": {"name": "existing_tool", "description": "Existing tool"}},
        ]
        manager._raw_tools = [
            {"name": "existing_tool", "description": "Existing tool", "input_schema": {}},
        ]

        inline_tools = [
            {
                "name": "new_inline_tool",
                "description": "New inline tool",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        with patch.object(manager_module.retriever, "embed_tools") as embed_tools:
            manager.register_inline_tools("inline", inline_tools, skip_embed=False)

        assert "new_inline_tool" in manager._tool_registry
        assert [tool["function"]["name"] for tool in manager._ollama_tools] == [
            "existing_tool",
            "new_inline_tool",
        ]
        embed_tools.assert_called_once_with(manager._ollama_tools)
