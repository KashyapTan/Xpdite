"""Tests for source/llm/providers/ollama_provider.py edge cases."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _tool_call(name: str, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def _dict_stream(*chunks):
    async def generator():
        for chunk in chunks:
            yield chunk

    return generator()


def test_events_include_visible_artifact_detects_artifact_output():
    from source.llm.providers.ollama_provider import _events_include_visible_artifact

    assert _events_include_visible_artifact([{"type": "artifact_chunk"}]) is True
    assert _events_include_visible_artifact([{"type": "text"}]) is False


def test_build_messages_filters_missing_images(tmp_path):
    from source.llm.providers.ollama_provider import _build_messages

    existing = tmp_path / "existing.png"
    existing.write_bytes(b"img")
    missing = tmp_path / "missing.png"

    messages = _build_messages(
        [
            {
                "role": "assistant",
                "content": "previous",
                "images": [str(existing), str(missing)],
            }
        ],
        "current",
        [str(missing), str(existing)],
    )

    assert messages == [
        {"role": "assistant", "content": "previous", "images": [str(existing)]},
        {"role": "user", "content": "current", "images": [str(existing)]},
    ]


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

    with patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client), \
         patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=False), \
         patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock), \
         patch("source.llm.providers.ollama_provider.get_current_request", return_value=None), \
         patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=False):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, _, _, _ = await stream_ollama_chat("qwen3:8b", "hi", [], [], "")

    assert text == "[Model returned no content after tool loop]"


def test_extract_token_handles_tool_arg_string_shape():
    """Tool-call rendering path should tolerate string arguments."""
    from source.llm.providers.ollama_provider import _extract_token

    chunk = {
        "message": {
            "content": "hello",
            "tool_calls": [{"function": {"name": "spawn_agent", "arguments": "{bad"}}],
        }
    }
    content, thinking = _extract_token(chunk)
    assert content == "hello"
    assert thinking is None


def test_extract_token_supports_dict_and_object_fallback_shapes():
    from source.llm.providers.ollama_provider import _extract_token

    assert _extract_token({"response": "fallback text"}) == ("fallback text", None)
    assert _extract_token(SimpleNamespace(token="object token")) == ("object token", None)


@pytest.mark.asyncio
async def test_broadcast_tool_final_response_emits_thinking_content_and_tokens():
    from source.llm.providers.ollama_provider import _broadcast_tool_final_response

    with (
        patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock) as mock_broadcast,
        patch(
            "source.llm.providers.ollama_provider.emit_artifact_stream_events",
            new_callable=AsyncMock,
            return_value="final content",
        ),
    ):
        content, stats, tool_calls, blocks = await _broadcast_tool_final_response(
            {
                "thinking": "reasoning",
                "content": "answer",
                "token_stats": {"prompt_eval_count": 2, "eval_count": 3},
            },
            [{"id": "tool-call"}],
        )

    assert content == "final content"
    assert stats == {"prompt_eval_count": 2, "eval_count": 3}
    assert tool_calls == [{"id": "tool-call"}]
    assert blocks == [{"type": "thinking", "content": "reasoning"}]
    assert [call.args for call in mock_broadcast.await_args_list] == [
        ("thinking_chunk", "reasoning"),
        ("thinking_complete", ""),
        ("response_complete", ""),
        ("token_usage", '{"prompt_eval_count": 2, "eval_count": 3}'),
    ]


@pytest.mark.asyncio
async def test_stream_uses_explicit_model_name_without_global_fallback():
    async def _stream():
        yield SimpleNamespace(
            message=SimpleNamespace(content="hello"),
            done=True,
            prompt_eval_count=2,
            eval_count=1,
        )

    client = AsyncMock()
    client.chat = AsyncMock(return_value=_stream())
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch(
            "source.llm.providers.ollama_provider.OllamaAsyncClient",
            return_value=client,
        ),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=False),
        patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock),
        patch("source.llm.providers.ollama_provider.get_current_request", return_value=None),
        patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=False),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, _, _ = await stream_ollama_chat(
            "explicit-model",
            "hello",
            [],
            [],
            "",
        )

    assert text == "hello"
    assert stats == {"prompt_eval_count": 2, "eval_count": 1}
    assert client.chat.await_args_list[0].kwargs["model"] == "explicit-model"


@pytest.mark.asyncio
async def test_stream_collects_token_usage_from_dict_chunks_and_renders_tool_calls():
    stream_chunk = {
        "message": {
            "content": "hello",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": '{"path": "/tmp/demo.txt"}'}}
            ],
        },
        "done": True,
        "prompt_eval_count": 4,
        "eval_count": 2,
    }

    client = AsyncMock()
    client.chat = AsyncMock(return_value=_dict_stream(stream_chunk))
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=False),
        patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock) as mock_broadcast,
        patch(
            "source.llm.providers.ollama_provider.emit_artifact_stream_events",
            new_callable=AsyncMock,
            side_effect=lambda events, _blocks: "".join(event["content"] for event in events if event["type"] == "text"),
        ),
        patch("source.llm.providers.ollama_provider.get_current_request", return_value=None),
        patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=False),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, tool_calls, blocks = await stream_ollama_chat(
            "explicit-model",
            "hello",
            [],
            [],
            "",
        )

    assert text == "hello\n\n[Model requested tool: read_file({'path': '/tmp/demo.txt'})]"
    assert stats == {"prompt_eval_count": 4, "eval_count": 2}
    assert tool_calls == []
    assert blocks is None
    assert ("token_usage", '{"prompt_eval_count": 4, "eval_count": 2}') in [
        call.args for call in mock_broadcast.await_args_list
    ]


@pytest.mark.asyncio
async def test_empty_stream_fallback_supports_dict_response_shape():
    client = AsyncMock()
    client.chat = AsyncMock(
        side_effect=[
            _dict_stream(),
            {"message": {"content": "fallback answer", "thinking": "fallback reasoning"}},
        ]
    )
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=False),
        patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock) as mock_broadcast,
        patch("source.llm.providers.ollama_provider.get_current_request", return_value=None),
        patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=False),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, _, blocks = await stream_ollama_chat(
            "qwen3:8b",
            "hi",
            [],
            [],
            "",
        )

    assert text == "fallback answer"
    assert stats == {"prompt_eval_count": 0, "eval_count": 0}
    assert blocks is not None
    assert {"type": "thinking", "content": "fallback reasoning"} in blocks
    assert any(block.get("type") == "text" for block in blocks)
    assert ("thinking_chunk", "fallback reasoning") in [call.args for call in mock_broadcast.await_args_list]
    assert ("thinking_complete", "") in [call.args for call in mock_broadcast.await_args_list]


@pytest.mark.asyncio
async def test_mcp_phase_cancelled_exception_returns_empty_result():
    client = AsyncMock()
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=True),
        patch(
            "source.llm.providers.ollama_provider.handle_mcp_tool_calls",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cancelled"),
        ),
        patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=True),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, tool_calls, blocks = await stream_ollama_chat(
            "explicit-model",
            "hello",
            [],
            [],
            "",
        )

    assert text == ""
    assert stats == {"prompt_eval_count": 0, "eval_count": 0}
    assert tool_calls == []
    assert blocks is None


@pytest.mark.asyncio
async def test_cancel_callback_closes_client_transport_when_invoked():
    class FakeRequestContext:
        def __init__(self):
            self.callback = None

        def on_cancel(self, callback):
            self.callback = callback

    async def _stream():
        yield SimpleNamespace(
            message=SimpleNamespace(content="hello"),
            done=True,
            prompt_eval_count=1,
            eval_count=1,
        )

    ctx = FakeRequestContext()
    client = AsyncMock()
    client.chat = AsyncMock(return_value=_stream())
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=False),
        patch("source.llm.providers.ollama_provider.broadcast_message", new_callable=AsyncMock),
        patch("source.llm.providers.ollama_provider.get_current_request", return_value=ctx),
        patch("source.llm.providers.ollama_provider.is_current_request_cancelled", return_value=False),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        await stream_ollama_chat("explicit-model", "hello", [], [], "")
        assert ctx.callback is not None
        ctx.callback()
        await asyncio.sleep(0)

    client._client.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_stream_returns_precomputed_already_streamed_response():
    client = AsyncMock()
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=True),
        patch(
            "source.llm.providers.ollama_provider.handle_mcp_tool_calls",
            new_callable=AsyncMock,
            return_value=(
                [{"role": "user", "content": "hello"}],
                [{"id": "tool-call"}],
                {
                    "already_streamed": True,
                    "content": "pre-streamed",
                    "token_stats": {"prompt_eval_count": 7, "eval_count": 5},
                    "interleaved_blocks": [{"type": "text", "content": "pre-streamed"}],
                },
            ),
        ),
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, tool_calls, blocks = await stream_ollama_chat(
            "explicit-model",
            "hello",
            [],
            [],
            "",
        )

    assert text == "pre-streamed"
    assert stats == {"prompt_eval_count": 7, "eval_count": 5}
    assert tool_calls == [{"id": "tool-call"}]
    assert blocks == [{"type": "text", "content": "pre-streamed"}]
    client.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_legacy_precomputed_path_uses_broadcast_helper():
    client = AsyncMock()
    client._client = SimpleNamespace(aclose=AsyncMock())

    with (
        patch("source.llm.providers.ollama_provider.OllamaAsyncClient", return_value=client),
        patch("source.llm.providers.ollama_provider.mcp_manager.has_tools", return_value=True),
        patch(
            "source.llm.providers.ollama_provider.handle_mcp_tool_calls",
            new_callable=AsyncMock,
            return_value=(
                [{"role": "user", "content": "hello"}],
                [{"id": "tool-call"}],
                {"content": "legacy"},
            ),
        ),
        patch(
            "source.llm.providers.ollama_provider._broadcast_tool_final_response",
            new_callable=AsyncMock,
            return_value=(
                "legacy-final",
                {"prompt_eval_count": 1, "eval_count": 1},
                [{"id": "tool-call"}],
                [{"type": "text", "content": "legacy-final"}],
            ),
        ) as mock_broadcast_helper,
    ):
        from source.llm.providers.ollama_provider import stream_ollama_chat

        text, stats, tool_calls, blocks = await stream_ollama_chat(
            "explicit-model",
            "hello",
            [],
            [],
            "",
        )

    assert text == "legacy-final"
    assert stats == {"prompt_eval_count": 1, "eval_count": 1}
    assert tool_calls == [{"id": "tool-call"}]
    assert blocks == [{"type": "text", "content": "legacy-final"}]
    mock_broadcast_helper.assert_awaited_once()
    client.chat.assert_not_awaited()

