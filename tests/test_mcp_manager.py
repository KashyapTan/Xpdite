"""Tests for MCP manager embedding refresh behaviour."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import source.mcp_integration.core.manager as manager_module


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

        with (
            patch.object(
                manager, "connect_server", new_callable=AsyncMock
            ) as connect_server,
            patch.object(manager, "register_inline_tools") as register_inline_tools,
            patch.object(manager_module.retriever, "embed_tools") as embed_tools,
            patch(
                "source.services.integrations.external_connectors.init_external_connectors",
                new_callable=AsyncMock,
            ),
        ):
            await manager_module.init_mcp_servers()

        # 5 servers: filesystem, glob, grep, websearch, windows_mcp
        assert connect_server.await_count == 5
        # 6 inline tool registrations: terminal, sub_agent, video_watcher,
        # skills, memory, scheduler
        assert register_inline_tools.call_count == 6
        embed_tools.assert_called_once_with([])
        assert manager._initialized is True


class TestConnectGoogleServers:
    @pytest.mark.asyncio
    async def test_google_reconnect_refresh_does_not_prune_cached_tools(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        with (
            patch(
                "source.mcp_integration.core.manager.os.path.exists", return_value=True
            ),
            patch.object(
                manager,
                "is_server_connected",
                side_effect=[False, False],
            ),
            patch.object(
                manager, "connect_server", new_callable=AsyncMock
            ) as connect_server,
            patch.object(manager_module.retriever, "embed_tools") as embed_tools,
        ):
            await manager.connect_google_servers()

        assert connect_server.await_count == 2
        embed_tools.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_google_connect_timeout_is_handled(self, reset_mcp_manager_state):
        manager = reset_mcp_manager_state

        async def _timeout_wait_for(coro, timeout):
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError

        with (
            patch(
                "source.mcp_integration.core.manager.os.path.exists", return_value=True
            ),
            patch.object(
                manager,
                "is_server_connected",
                side_effect=[False, False],
            ),
            patch.object(
                manager, "connect_server", new_callable=AsyncMock
            ) as connect_server,
            patch.object(manager_module.asyncio, "wait_for", new=_timeout_wait_for),
            patch.object(manager_module.retriever, "embed_tools") as embed_tools,
        ):
            await manager.connect_google_servers()

        # connect coroutines were attempted but timed out via wait_for wrapper
        assert connect_server.await_count == 0
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
        assert [tool["function"]["name"] for tool in manager._ollama_tools] == [
            "keep_tool"
        ]
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
            {
                "name": "existing_tool",
                "description": "Existing tool",
                "input_schema": {},
            },
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


class TestCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool_returns_error(self):
        manager = manager_module.McpToolManager()

        result = await manager.call_tool("missing_tool", {"q": "x"})

        assert result == "Error: Unknown tool 'missing_tool'"

    @pytest.mark.asyncio
    async def test_call_tool_inline_tool_session_none_guard(self):
        manager = manager_module.McpToolManager()
        manager._tool_registry["inline_tool"] = {
            "session": None,
            "server_name": "terminal",
        }

        result = await manager.call_tool("inline_tool", {"cmd": "ls"})

        assert "inline tool" in result
        assert "cannot be called via MCP session" in result
        assert "server 'terminal'" in result

    @pytest.mark.asyncio
    async def test_call_tool_timeout_branch(self):
        manager = manager_module.McpToolManager()

        async def _timeout_wait_for(*_args, **_kwargs):
            raise asyncio.TimeoutError

        session = SimpleNamespace(call_tool=Mock(return_value="ignored-by-timeout"))
        manager._tool_registry["slow_tool"] = {
            "session": session,
            "server_name": "filesystem",
        }

        with patch.object(
            manager_module.asyncio,
            "wait_for",
            new=_timeout_wait_for,
        ):
            result = await manager.call_tool("slow_tool", {"path": "/tmp"})

        assert (
            result
            == "Error: Tool 'slow_tool' (server 'filesystem') timed out after 90s"
        )

    @pytest.mark.asyncio
    async def test_call_tool_timeout_branch_websearch_uses_shorter_timeout(self):
        manager = manager_module.McpToolManager()

        async def _timeout_wait_for(*_args, **_kwargs):
            raise asyncio.TimeoutError

        session = SimpleNamespace(call_tool=Mock(return_value="ignored-by-timeout"))
        manager._tool_registry["read_website"] = {
            "session": session,
            "server_name": "websearch",
        }

        with patch.object(
            manager_module.asyncio,
            "wait_for",
            new=_timeout_wait_for,
        ):
            result = await manager.call_tool(
                "read_website", {"url": "https://example.com"}
            )

        assert (
            result
            == "Error: Tool 'read_website' (server 'websearch') timed out after 25s"
        )

    @pytest.mark.asyncio
    async def test_call_tool_websearch_uses_shorter_wait_and_read_timeouts(self):
        manager = manager_module.McpToolManager()

        captured = {"wait_for_timeout": None}

        async def _capturing_wait_for(coro, timeout):
            captured["wait_for_timeout"] = timeout
            return await coro

        session = SimpleNamespace(
            call_tool=AsyncMock(
                return_value=SimpleNamespace(content=[SimpleNamespace(text="ok")])
            )
        )
        manager._tool_registry["read_website"] = {
            "session": session,
            "server_name": "websearch",
        }

        with patch.object(manager_module.asyncio, "wait_for", new=_capturing_wait_for):
            result = await manager.call_tool(
                "read_website", {"url": "https://example.com"}
            )

        assert result == "ok"
        assert captured["wait_for_timeout"] == 30.0
        session.call_tool.assert_awaited_once_with(
            "read_website",
            arguments={"url": "https://example.com"},
            read_timeout_seconds=timedelta(seconds=25),
        )

    @pytest.mark.asyncio
    async def test_call_tool_transport_error_branch(self):
        manager = manager_module.McpToolManager()

        async def _raise_transport(*_args, **_kwargs):
            raise BrokenPipeError("pipe closed")

        session = SimpleNamespace(call_tool=_raise_transport)
        manager._tool_registry["network_tool"] = {
            "session": session,
            "server_name": "websearch",
        }

        result = await manager.call_tool("network_tool", {"query": "x"})

        assert (
            result
            == "Error: Tool 'network_tool' (server 'websearch') connection lost: BrokenPipeError"
        )

    @pytest.mark.asyncio
    async def test_call_tool_unexpected_error_branch(self):
        manager = manager_module.McpToolManager()

        async def _raise_unexpected(*_args, **_kwargs):
            raise ValueError("bad args")

        session = SimpleNamespace(call_tool=_raise_unexpected)
        manager._tool_registry["fragile_tool"] = {
            "session": session,
            "server_name": "demo",
        }

        result = await manager.call_tool("fragile_tool", {"x": 1})

        assert result == "Error: Tool 'fragile_tool' (server 'demo') failed: ValueError"

    @pytest.mark.asyncio
    async def test_call_tool_assembles_output_from_mixed_content_blocks(self):
        manager = manager_module.McpToolManager()

        class StringableBlock:
            def __str__(self):
                return "[non-text-block]"

        session = SimpleNamespace(
            call_tool=AsyncMock(
                return_value=SimpleNamespace(
                    content=[
                        SimpleNamespace(text="alpha"),
                        StringableBlock(),
                        SimpleNamespace(text="omega"),
                    ]
                )
            )
        )
        manager._tool_registry["mix_tool"] = {
            "session": session,
            "server_name": "filesystem",
        }

        result = await manager.call_tool("mix_tool", {"id": 7})

        assert result == "alpha\n[non-text-block]\nomega"
        session.call_tool.assert_awaited_once_with(
            "mix_tool",
            arguments={"id": 7},
            read_timeout_seconds=timedelta(seconds=90),
        )


class TestGetTools:
    def test_get_tools_strips_additional_properties_without_mutating_source_schema(
        self,
    ):
        manager = manager_module.McpToolManager()
        manager._raw_tools = [
            {
                "name": "schema_tool",
                "description": "schema test",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "nested": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"k": {"type": "string"}},
                        },
                    },
                    "additionalProperties": False,
                },
            }
        ]

        tools = manager.get_tools()

        assert tools is not None
        params = tools[0]["function"]["parameters"]
        assert "additionalProperties" not in params
        assert params["properties"]["nested"]["additionalProperties"] is False
        assert manager._raw_tools[0]["input_schema"]["additionalProperties"] is False
