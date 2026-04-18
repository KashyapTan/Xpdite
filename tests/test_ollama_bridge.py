import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcp_servers.client import ollama_bridge as bridge_module


class _FakeAsyncContext:
    def __init__(self, enter_result=None, *, enter_error: Exception | None = None):
        self.enter_result = enter_result
        self.enter_error = enter_error
        self.exit_calls = 0

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.enter_result

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1


class _FailingExitContext(_FakeAsyncContext):
    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        raise RuntimeError("close failed")


class _FakeTool:
    def __init__(self, name: str, description: str, input_schema: dict):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


class _FallbackContent:
    def __str__(self) -> str:
        return "fallback"


class _FakeMessage:
    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: list | None = None,
        dump: dict | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self._dump = dump or {"role": "assistant", "content": content}

    def model_dump(self) -> dict:
        return self._dump


class _FakeResponse:
    def __init__(self, message: _FakeMessage):
        self.message = message


@pytest.fixture()
def bridge() -> bridge_module.McpOllamaBridge:
    return bridge_module.McpOllamaBridge(model="test-model")


@pytest.mark.asyncio
async def test_connect_server_registers_tools(monkeypatch, bridge):
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    _FakeTool(
                        "add",
                        "Adds numbers",
                        {
                            "type": "object",
                            "properties": {"a": {"type": "number"}},
                            "required": ["a"],
                        },
                    ),
                    _FakeTool("echo", "", None),
                ]
            )
        ),
    )
    session_ctx = _FakeAsyncContext(session)
    stdio_ctx = _FakeAsyncContext(("reader", "writer"))

    monkeypatch.setattr(bridge_module, "stdio_client", lambda _params: stdio_ctx)
    monkeypatch.setattr(
        bridge_module, "ClientSession", lambda _read, _write: session_ctx
    )

    await bridge.connect_server("demo", "python", ["server.py"], env={"A": "B"})

    assert bridge._connections["demo"]["session"] is session
    assert bridge._tool_registry["add"]["server_name"] == "demo"
    assert bridge._ollama_tools == [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Adds numbers",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}},
                    "required": ["a"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


@pytest.mark.asyncio
async def test_connect_server_cleans_up_half_open_contexts_on_failure(
    monkeypatch, bridge
):
    session = SimpleNamespace(
        initialize=AsyncMock(side_effect=RuntimeError("handshake failed"))
    )
    session_ctx = _FakeAsyncContext(session)
    stdio_ctx = _FakeAsyncContext(("reader", "writer"))

    monkeypatch.setattr(bridge_module, "stdio_client", lambda _params: stdio_ctx)
    monkeypatch.setattr(
        bridge_module, "ClientSession", lambda _read, _write: session_ctx
    )

    with pytest.raises(RuntimeError, match="handshake failed"):
        await bridge.connect_server("demo", "python", ["server.py"])

    assert session_ctx.exit_calls == 1
    assert stdio_ctx.exit_calls == 1
    assert bridge._connections == {}
    assert bridge._tool_registry == {}


@pytest.mark.asyncio
async def test_call_mcp_tool_joins_text_blocks(bridge):
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(text="alpha"), _FallbackContent()]
            )
        )
    )
    bridge._tool_registry["echo"] = {"session": session, "server_name": "demo"}

    result = await bridge._call_mcp_tool("echo", {"value": 1})

    assert result == "alpha\nfallback"


@pytest.mark.asyncio
async def test_call_mcp_tool_returns_unknown_tool_error(bridge):
    result = await bridge._call_mcp_tool("missing", {})
    assert result == "Error: Unknown tool 'missing'"


@pytest.mark.asyncio
async def test_chat_records_one_assistant_tool_call_entry_per_model_response(
    monkeypatch, bridge
):
    tool_calls = [
        SimpleNamespace(function=SimpleNamespace(name="add", arguments={"a": 1, "b": 2})),
        SimpleNamespace(
            function=SimpleNamespace(name="multiply", arguments={"a": 3, "b": 4})
        ),
    ]
    responses = iter(
        [
            _FakeResponse(
                _FakeMessage(
                    tool_calls=tool_calls,
                    dump={
                        "role": "assistant",
                        "content": "",
                        "tool_calls": ["add", "multiply"],
                    },
                )
            ),
            _FakeResponse(_FakeMessage(content="done")),
        ]
    )

    monkeypatch.setattr(bridge_module, "chat", lambda **_kwargs: next(responses))
    bridge._ollama_tools = [{"type": "function"}]
    bridge._call_mcp_tool = AsyncMock(side_effect=["3", "12"])

    result = await bridge.chat("Compute things")

    assert result == "done"
    assert [entry["role"] for entry in bridge._chat_history] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "assistant",
    ]
    assert bridge._chat_history[1]["tool_calls"] == ["add", "multiply"]


def test_clear_history_resets_conversation(bridge):
    bridge._chat_history = [{"role": "user", "content": "hello"}]

    bridge.clear_history()

    assert bridge._chat_history == []


@pytest.mark.asyncio
async def test_cleanup_attempts_stdio_shutdown_even_when_session_shutdown_fails(bridge):
    bridge._connections = {
        "broken": {
            "session": object(),
            "session_ctx": _FailingExitContext(),
            "stdio_ctx": _FakeAsyncContext(),
        },
        "healthy": {
            "session": object(),
            "session_ctx": _FakeAsyncContext(),
            "stdio_ctx": _FakeAsyncContext(),
        },
    }
    bridge._tool_registry = {"echo": {"session": object(), "server_name": "broken"}}
    bridge._ollama_tools = [{"type": "function"}]

    broken_stdio = bridge._connections["broken"]["stdio_ctx"]
    healthy_session = bridge._connections["healthy"]["session_ctx"]

    await bridge.cleanup()

    assert broken_stdio.exit_calls == 1
    assert healthy_session.exit_calls == 1
    assert bridge._connections == {}
    assert bridge._tool_registry == {}
    assert bridge._ollama_tools == []


def test_load_server_config_reads_servers_json():
    config = bridge_module.load_server_config()

    assert "servers" in config
    assert config["servers"]["filesystem"]["enabled"] is True
    assert json.dumps(config)  # smoke-check serializability
