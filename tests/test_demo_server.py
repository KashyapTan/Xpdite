import sys
from pathlib import Path

import pytest

import mcp_servers.test_demo as demo_script
from mcp_servers.servers.demo import server as demo_server


def test_add_returns_sum_as_string():
    assert demo_server.add(2, 3) == "5"


def test_divide_formats_fraction_to_50_decimal_places():
    result = demo_server.divide(1, 4)
    assert result == "0.25000000000000000000000000000000000000000000000000"


def test_divide_handles_zero_without_raising():
    assert demo_server.divide(10, 0) == "Error: Cannot divide by zero."


@pytest.mark.asyncio
async def test_demo_main_uses_env_override_for_model(monkeypatch):
    captured: dict[str, object] = {"questions": []}

    class _FakeBridge:
        def __init__(self, model: str):
            captured["model"] = model

        async def connect_server(self, **kwargs):
            captured["connect_kwargs"] = kwargs

        async def chat(self, question: str) -> str:
            captured["questions"].append(question)
            return "answer"

        async def cleanup(self):
            captured["cleaned"] = True

    monkeypatch.setenv("OLLAMA_MCP_DEMO_MODEL", "llama3.1")
    monkeypatch.setattr(
        "mcp_servers.client.ollama_bridge.McpOllamaBridge",
        _FakeBridge,
    )

    await demo_script.main()

    connect_kwargs = captured["connect_kwargs"]
    assert captured["model"] == "llama3.1"
    assert connect_kwargs["server_name"] == "demo"
    assert connect_kwargs["command"] == sys.executable
    assert Path(connect_kwargs["args"][0]).name == "server.py"
    assert captured["questions"] == [
        "What is 42 + 58?",
        "Now add 100 to that result.",
    ]
    assert captured["cleaned"] is True
