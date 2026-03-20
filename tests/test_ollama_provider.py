"""Tests for source/llm/ollama_provider.py edge cases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _tool_call(name: str, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


@pytest.mark.asyncio
async def test_empty_stream_and_empty_fallback_returns_stable_message():
    """Empty stream/fallback should not emit hard error text anymore."""
    async def _empty_stream():
        if False:
            yield None

    fallback = SimpleNamespace(message=SimpleNamespace(content="", thinking=""))

    client = AsyncMock()
    client.chat = AsyncMock(side_effect=[_empty_stream(), fallback])
    client._client = SimpleNamespace(aclose=AsyncMock())

    with patch("source.llm.ollama_provider.OllamaAsyncClient", return_value=client), \
         patch("source.llm.ollama_provider.mcp_manager.has_tools", return_value=False), \
         patch("source.llm.ollama_provider.broadcast_message", new_callable=AsyncMock), \
         patch("source.llm.ollama_provider.get_current_model", return_value="qwen3:8b"), \
         patch("source.llm.ollama_provider.get_current_request", return_value=None), \
         patch("source.llm.ollama_provider.is_current_request_cancelled", return_value=False), \
         patch("source.llm.ollama_provider.app_state") as mock_state:
        mock_state.selected_model = "qwen3:8b"
        mock_state.current_request = None
        from source.llm.ollama_provider import stream_ollama_chat

        text, _, _, _ = await stream_ollama_chat("hi", [], [], "")

    assert text == "[Model returned no content after tool loop]"


def test_extract_token_handles_tool_arg_string_shape():
    """Tool-call rendering path should tolerate string arguments."""
    from source.llm.ollama_provider import _extract_token

    chunk = {
        "message": {
            "content": "hello",
            "tool_calls": [{"function": {"name": "spawn_agent", "arguments": "{bad"}}],
        }
    }
    content, thinking = _extract_token(chunk)
    assert content == "hello"
    assert thinking is None

