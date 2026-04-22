"""Tests for MCP manager embedding refresh behaviour."""

import asyncio
import sys
import types
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import source.mcp_integration.core.manager as manager_module


def _install_fake_mcp(
    monkeypatch,
    *,
    tools=None,
    stdio_enter_exception: Exception | None = None,
    initialize_exception: Exception | None = None,
):
    captured: dict[str, object] = {}
    tools = list(tools or [])

    class DummyClientSession:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            if initialize_exception is not None:
                raise initialize_exception
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=tools)

    class DummyStdioClient:
        def __init__(self, params):
            captured["params"] = params

        async def __aenter__(self):
            if stdio_enter_exception is not None:
                raise stdio_enter_exception
            return object(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_mcp = types.ModuleType("mcp")
    fake_mcp.ClientSession = DummyClientSession
    fake_mcp.StdioServerParameters = lambda command, args, env=None: SimpleNamespace(
        command=command,
        args=args,
        env=env,
    )
    fake_mcp_client = types.ModuleType("mcp.client")
    fake_mcp_client.__path__ = []
    fake_mcp_stdio = types.ModuleType("mcp.client.stdio")
    fake_mcp_stdio.stdio_client = lambda params: DummyStdioClient(params)
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", fake_mcp_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_mcp_stdio)
    return captured


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
            patch(
                "source.services.marketplace.service.get_marketplace_service",
                return_value=SimpleNamespace(
                    reconnect_enabled_mcp_installs_async=AsyncMock()
                ),
            ),
        ):
            await manager_module.init_mcp_servers()

        # 4 built-in servers on non-Windows, plus windows_mcp on Windows.
        expected_server_count = 5 if sys.platform == "win32" else 4
        assert connect_server.await_count == expected_server_count
        # 6 inline tool registrations: terminal, sub_agent, video_watcher,
        # skills, memory, scheduler
        assert register_inline_tools.call_count == 6
        assert embed_tools.call_count >= 1
        assert embed_tools.call_args_list[-1].args == ([],)
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
    async def test_connect_server_cleans_up_when_tool_discovery_fails(
        self,
        reset_mcp_manager_state,
        monkeypatch,
    ):
        manager = reset_mcp_manager_state

        class DummyClientSession:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def initialize(self):
                return None

            async def list_tools(self):
                raise RuntimeError("tool discovery failed")

        class DummyStdioClient:
            async def __aenter__(self):
                return object(), object()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_mcp = types.ModuleType("mcp")
        fake_mcp.ClientSession = DummyClientSession
        fake_mcp.StdioServerParameters = lambda command, args, env=None: SimpleNamespace(
            command=command,
            args=args,
            env=env,
        )
        fake_mcp_client = types.ModuleType("mcp.client")
        fake_mcp_client.__path__ = []
        fake_mcp_stdio = types.ModuleType("mcp.client.stdio")
        fake_mcp_stdio.stdio_client = lambda _params: DummyStdioClient()
        monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
        monkeypatch.setitem(sys.modules, "mcp.client", fake_mcp_client)
        monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_mcp_stdio)

        with patch.object(manager_module.retriever, "embed_tools") as embed_tools:
            with pytest.raises(RuntimeError, match="tool discovery failed"):
                await manager.connect_server("demo", "python", ["server.py"])

        assert manager.is_server_connected("demo") is False
        assert manager._tool_registry == {}
        assert manager._ollama_tools == []
        assert manager._raw_tools == []
        embed_tools.assert_called_once_with([])

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


class TestManagerAdditionalCoverage:
    @pytest.mark.asyncio
    async def test_connect_server_returns_when_mcp_import_is_unavailable(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        original_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"mcp", "mcp.client.stdio"}:
                raise ImportError("mcp missing")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            await manager.connect_server("demo", "python", ["server.py"])

        assert manager._connections == {}
        assert manager._tool_registry == {}
        assert manager.get_ollama_tools() is None

    @pytest.mark.asyncio
    async def test_connect_server_registers_prefixed_tools_and_extends_pythonpath(
        self,
        reset_mcp_manager_state,
        monkeypatch,
    ):
        manager = reset_mcp_manager_state
        captured = _install_fake_mcp(
            monkeypatch,
            tools=[
                SimpleNamespace(
                    name="beta",
                    description="Beta tool",
                    inputSchema=None,
                ),
                SimpleNamespace(
                    name="Alpha",
                    description="Alpha tool",
                    inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
                ),
            ],
        )

        with patch(
            "source.core.thread_pool.run_in_thread",
            new=AsyncMock(side_effect=lambda fn: fn()),
        ):
            await manager.connect_server(
                "demo",
                "python",
                ["server.py"],
                env={"PYTHONPATH": "C:\\custom"},
                tool_name_prefix="mcp__demo__",
                display_name="Demo Display",
            )

        try:
            assert manager.is_server_connected("demo") is True
            env = captured["params"].env
            assert env["PYTHONPATH"].startswith(
                f"{manager_module.RUNTIME_ROOT}{manager_module.os.pathsep}"
            )
            assert env["PYTHONPATH"].endswith("C:\\custom")
            assert set(manager._tool_registry) == {"mcp__demo__beta", "mcp__demo__Alpha"}
            assert manager._tool_registry["mcp__demo__Alpha"]["server_display_name"] == "Demo Display"
            assert manager._tool_registry["mcp__demo__Alpha"]["session_tool_name"] == "Alpha"
            assert manager._tool_registry["mcp__demo__beta"]["display_tool_name"] == "beta"
            assert manager.get_ollama_tools() is not None
            assert manager.has_tools() is True
            assert manager.get_tool_server_name("mcp__demo__beta") == "demo"
            assert manager.get_tool_server_name("missing") == "unknown"
            assert manager.tool_uses_mcp_session("mcp__demo__beta") is True
            assert manager.tool_uses_mcp_session("missing") is False
            assert manager.get_tools()[0]["function"]["name"] == "mcp__demo__beta"

            assert manager.get_server_tools() == [
                {
                    "server": "demo",
                    "display_name": "Demo Display",
                    "tools": [
                        {"id": "mcp__demo__Alpha", "name": "Alpha"},
                        {"id": "mcp__demo__beta", "name": "beta"},
                    ],
                }
            ]
        finally:
            await manager.disconnect_server("demo")

    @pytest.mark.asyncio
    async def test_connect_server_raises_when_stdio_lifecycle_fails_before_connect(
        self,
        reset_mcp_manager_state,
        monkeypatch,
    ):
        manager = reset_mcp_manager_state
        _install_fake_mcp(
            monkeypatch,
            stdio_enter_exception=RuntimeError("startup failed"),
        )

        with pytest.raises(RuntimeError, match="startup failed"):
            await manager.connect_server("demo", "python", ["server.py"])

        assert manager.is_server_connected("demo") is False
        assert manager._tool_registry == {}

    @pytest.mark.asyncio
    async def test_call_tool_returns_image_payload_when_json_text_contains_image_type(
        self,
    ):
        manager = manager_module.McpToolManager()
        session = SimpleNamespace(
            call_tool=AsyncMock(
                return_value=SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            text='{"type":"image","mime_type":"image/png","data":"abc"}'
                        )
                    ]
                )
            )
        )
        manager._tool_registry["image_tool"] = {
            "session": session,
            "server_name": "filesystem",
        }

        result = await manager.call_tool("image_tool", {"path": "x"})

        assert result == {"type": "image", "mime_type": "image/png", "data": "abc"}

    @pytest.mark.asyncio
    async def test_call_tool_keeps_text_when_json_decode_fails(self):
        manager = manager_module.McpToolManager()
        session = SimpleNamespace(
            call_tool=AsyncMock(
                return_value=SimpleNamespace(content=[SimpleNamespace(text="{not-json}")])
            )
        )
        manager._tool_registry["broken_json_tool"] = {
            "session": session,
            "server_name": "filesystem",
        }

        result = await manager.call_tool("broken_json_tool", {"path": "x"})

        assert result == "{not-json}"

    def test_get_server_tools_groups_and_sorts_by_display_name_and_tool_name(self):
        manager = manager_module.McpToolManager()
        manager._tool_registry = {
            "beta_id": {
                "server_name": "zebra",
                "server_display_name": "Zebra Server",
                "display_tool_name": "beta",
                "session": object(),
            },
            "alpha_id": {
                "server_name": "zebra",
                "server_display_name": "Zebra Server",
                "display_tool_name": "Alpha",
                "session": object(),
            },
            "gamma_id": {
                "server_name": "aardvark",
                "server_display_name": "Aardvark Server",
                "display_tool_name": "gamma",
                "session": object(),
            },
        }

        assert manager.get_server_tools() == [
            {
                "server": "aardvark",
                "display_name": "Aardvark Server",
                "tools": [{"id": "gamma_id", "name": "gamma"}],
            },
            {
                "server": "zebra",
                "display_name": "Zebra Server",
                "tools": [
                    {"id": "alpha_id", "name": "Alpha"},
                    {"id": "beta_id", "name": "beta"},
                ],
            },
        ]

    @pytest.mark.asyncio
    async def test_disconnect_server_timeout_cancels_task_and_removes_tools(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        task = asyncio.create_task(asyncio.sleep(3600))
        manager._connections = {
            "demo": {
                "shutdown_event": asyncio.Event(),
                "task": task,
            }
        }
        manager._tool_registry = {"demo_tool": {"server_name": "demo", "session": object()}}
        manager._ollama_tools = [{"function": {"name": "demo_tool", "description": "Demo"}}]
        manager._raw_tools = [{"name": "demo_tool", "description": "Demo", "input_schema": {}}]

        async def _timeout_wait_for(awaitable, timeout):
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        with (
            patch.object(manager_module.asyncio, "wait_for", new=_timeout_wait_for),
            patch.object(manager, "refresh_tool_embeddings") as refresh_tool_embeddings,
        ):
            await manager.disconnect_server("demo")

        assert task.cancelled() is True
        assert manager._connections == {}
        assert manager._tool_registry == {}
        assert manager._ollama_tools == []
        assert manager._raw_tools == []
        refresh_tool_embeddings.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_disconnect_server_logs_shutdown_error_and_still_cleans_state(
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
            {"function": {"name": "demo_tool", "description": "Demo"}},
            {"function": {"name": "keep_tool", "description": "Keep"}},
        ]
        manager._raw_tools = [
            {"name": "demo_tool", "description": "Demo", "input_schema": {}},
            {"name": "keep_tool", "description": "Keep", "input_schema": {}},
        ]

        async def _failing_wait_for(*_args, **_kwargs):
            raise RuntimeError("close failed")

        with (
            patch.object(manager_module.asyncio, "wait_for", new=_failing_wait_for),
            patch.object(manager, "refresh_tool_embeddings") as refresh_tool_embeddings,
        ):
            await manager.disconnect_server("demo")

        assert "demo" not in manager._connections
        assert list(manager._tool_registry) == ["keep_tool"]
        assert [tool["function"]["name"] for tool in manager._ollama_tools] == ["keep_tool"]
        assert [tool["name"] for tool in manager._raw_tools] == ["keep_tool"]
        refresh_tool_embeddings.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_connect_google_servers_skips_when_token_file_is_missing(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        with (
            patch("source.mcp_integration.core.manager.os.path.exists", return_value=False),
            patch.object(manager, "connect_server", new_callable=AsyncMock) as connect_server,
            patch.object(manager, "refresh_tool_embeddings") as refresh_tool_embeddings,
        ):
            await manager.connect_google_servers()

        connect_server.assert_not_awaited()
        refresh_tool_embeddings.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_google_servers_only_connects_missing_servers(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        async def _passthrough_wait_for(coro, timeout):
            return await coro

        with (
            patch("source.mcp_integration.core.manager.os.path.exists", return_value=True),
            patch.object(manager, "is_server_connected", side_effect=[True, False]),
            patch.object(manager, "connect_server", new_callable=AsyncMock) as connect_server,
            patch.object(manager, "refresh_tool_embeddings") as refresh_tool_embeddings,
            patch.object(manager_module.asyncio, "wait_for", new=_passthrough_wait_for),
        ):
            await manager.connect_google_servers()

        connect_server.assert_awaited_once()
        assert connect_server.await_args.args[0] == "calendar"
        refresh_tool_embeddings.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_disconnect_google_servers_and_cleanup_only_disconnect_connected_servers(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        manager._initialized = True
        manager._connections = {"gmail": object(), "keep": object()}

        async def _disconnect_server(name):
            manager._connections.pop(name, None)
            if name == "keep":
                raise RuntimeError("boom")

        with patch.object(manager, "disconnect_server", new=AsyncMock(side_effect=_disconnect_server)) as disconnect_server:
            await manager.disconnect_google_servers()

        disconnect_server.assert_awaited_once_with("gmail")

        manager._connections = {"gmail": object(), "keep": object()}
        manager._initialized = True
        with patch.object(manager, "disconnect_server", new=AsyncMock(side_effect=_disconnect_server)):
            await manager.cleanup()

        assert manager._initialized is False
        assert "keep" not in manager._connections

    @pytest.mark.asyncio
    async def test_init_mcp_servers_handles_connector_and_marketplace_failures(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state

        terminal_mod = types.ModuleType("mcp_servers.servers.terminal.inline_tools")
        terminal_mod.TERMINAL_INLINE_TOOLS = []
        sub_agent_mod = types.ModuleType("mcp_servers.servers.sub_agent.inline_tools")
        sub_agent_mod.SUB_AGENT_INLINE_TOOLS = []
        video_mod = types.ModuleType("mcp_servers.servers.video_watcher.inline_tools")
        video_mod.VIDEO_WATCHER_INLINE_TOOLS = []
        skills_mod = types.ModuleType("mcp_servers.servers.skills.inline_tools")
        skills_mod.SKILLS_INLINE_TOOLS = []
        memory_mod = types.ModuleType("mcp_servers.servers.memory.inline_tools")
        memory_mod.MEMORY_INLINE_TOOLS = []
        scheduler_mod = types.ModuleType("mcp_servers.servers.scheduler.inline_tools")
        scheduler_mod.SCHEDULER_INLINE_TOOLS = []

        with (
            patch.object(manager, "connect_server", new_callable=AsyncMock),
            patch.object(manager, "register_inline_tools") as register_inline_tools,
            patch.object(manager, "refresh_tool_embeddings") as refresh_tool_embeddings,
            patch(
                "source.services.integrations.external_connectors.init_external_connectors",
                new=AsyncMock(side_effect=RuntimeError("external boom")),
            ),
            patch(
                "source.services.marketplace.service.get_marketplace_service",
                return_value=SimpleNamespace(
                    reconnect_enabled_mcp_installs_async=AsyncMock(
                        side_effect=RuntimeError("marketplace boom")
                    )
                ),
            ),
            patch.dict(
                sys.modules,
                {
                    "mcp_servers.servers.terminal.inline_tools": terminal_mod,
                    "mcp_servers.servers.sub_agent.inline_tools": sub_agent_mod,
                    "mcp_servers.servers.video_watcher.inline_tools": video_mod,
                    "mcp_servers.servers.skills.inline_tools": skills_mod,
                    "mcp_servers.servers.memory.inline_tools": memory_mod,
                    "mcp_servers.servers.scheduler.inline_tools": scheduler_mod,
                },
                clear=False,
            ),
        ):
            await manager_module.init_mcp_servers()

        assert register_inline_tools.call_count == 6
        refresh_tool_embeddings.assert_called_once_with()
        assert manager._initialized is True

    @pytest.mark.asyncio
    async def test_init_mcp_servers_returns_early_when_already_initialized(
        self, reset_mcp_manager_state
    ):
        manager = reset_mcp_manager_state
        manager._initialized = True

        with patch.object(manager, "connect_server", new_callable=AsyncMock) as connect_server:
            await manager_module.init_mcp_servers()

        connect_server.assert_not_awaited()
