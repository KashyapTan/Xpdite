"""Tests for source/llm/cloud_provider.py.

Covers:
- _build_messages: chat history → OpenAI-format conversion
- Helper functions: _format_image, _guess_media_type, _truncate_tool_result, etc.
- _stream_litellm: streaming loop, tool-call accumulation, cancellation, errors
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from source.config import OLLAMA_CTX_SIZE


# ---------------------------------------------------------------------------
# Helpers to build mock LiteLLM streaming chunks
# ---------------------------------------------------------------------------


def _text_chunk(content: str | None, finish_reason=None):
    """A chunk carrying regular text content."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _thinking_chunk(content: str):
    """A chunk carrying reasoning/thinking content."""
    delta = SimpleNamespace(content=None, tool_calls=None, reasoning_content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice], usage=None)


def _tool_call_chunk(
    index: int, tc_id=None, name=None, arguments=None, finish_reason=None
):
    """A chunk carrying a tool call delta."""
    func = SimpleNamespace(
        name=name,
        arguments=arguments,
    )
    tc_delta = SimpleNamespace(index=index, id=tc_id, function=func)
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta])
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _usage_chunk(prompt_tokens: int, completion_tokens: int):
    """A usage-only final chunk (no choices)."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return SimpleNamespace(choices=[], usage=usage)


def _text_chunk_with_usage(content, finish_reason, prompt_tokens, completion_tokens):
    """A final chunk carrying both choices and usage (Anthropic/Gemini pattern)."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _empty_chunk():
    """A chunk with no choices and no usage (e.g. keep-alive)."""
    return SimpleNamespace(choices=[], usage=None)


async def _make_async_iter(chunks):
    """Convert a list of chunks into an async iterator."""
    for chunk in chunks:
        yield chunk


class TestBuildMessages:
    """Unit tests for the unified message builder."""

    @staticmethod
    def _build(chat_history, user_query="hello", image_paths=None, system_prompt=""):
        from source.llm.cloud_provider import _build_messages

        return _build_messages(
            chat_history, user_query, image_paths or [], system_prompt
        )

    def test_plain_user_assistant_roundtrip(self):
        history = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        messages = self._build(history, "next question")

        # No system prompt → 2 history + 1 current query
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is 2+2?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "4"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "next question"

    def test_system_prompt_injected_first(self):
        history = [
            {"role": "user", "content": "hi"},
        ]
        messages = self._build(history, "hello", system_prompt="You are helpful.")

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hi"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "hello"

    def test_tool_role_messages_are_skipped(self):
        history = [
            {"role": "user", "content": "Do something"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "Done"},
        ]
        messages = self._build(history, "next")

        # tool message should be skipped → user + assistant + current
        assert len(messages) == 3
        roles = [m["role"] for m in messages]
        assert "tool" not in roles

    def test_user_with_images_in_history(self, tmp_path):
        # Create a fake image file
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        history = [
            {"role": "user", "content": "Look at this", "images": [str(img)]},
        ]
        messages = self._build(history, "what next")

        # History message should be multipart
        assert len(messages) == 2
        assert isinstance(messages[0]["content"], list)
        # Should have image_url + text parts
        parts = messages[0]["content"]
        types_found = [p["type"] for p in parts]
        assert "image_url" in types_found
        assert "text" in types_found

    def test_current_query_with_images(self, tmp_path):
        img = tmp_path / "screen.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)

        messages = self._build([], "describe this", image_paths=[str(img)])

        assert len(messages) == 1
        assert isinstance(messages[0]["content"], list)
        parts = messages[0]["content"]
        types_found = [p["type"] for p in parts]
        assert "image_url" in types_found
        assert "text" in types_found
        # Text should be last
        assert parts[-1]["type"] == "text"
        assert parts[-1]["text"] == "describe this"

    def test_nonexistent_image_paths_ignored(self):
        messages = self._build([], "hello", image_paths=["/nonexistent/image.png"])
        # Should fall back to plain text since image doesn't exist
        assert len(messages) == 1
        assert messages[0]["content"] == "hello"

    def test_empty_history(self):
        messages = self._build([], "just this")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "just this"

    def test_empty_system_prompt_not_added(self):
        messages = self._build([], "hello", system_prompt="")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


class TestHelpers:
    """Tests for helper functions."""

    def test_guess_media_type(self):
        from source.llm.cloud_provider import _guess_media_type

        assert _guess_media_type("photo.jpg") == "image/jpeg"
        assert _guess_media_type("photo.jpeg") == "image/jpeg"
        assert _guess_media_type("photo.png") == "image/png"
        assert _guess_media_type("photo.gif") == "image/gif"
        assert _guess_media_type("photo.webp") == "image/webp"
        assert _guess_media_type("photo.bmp") == "image/png"  # fallback

    def test_truncate_tool_result_short(self):
        from source.llm.cloud_provider import _truncate_tool_result

        assert _truncate_tool_result("short") == "short"

    def test_truncate_tool_result_long(self):
        from source.llm.cloud_provider import _truncate_tool_result

        long_text = "x" * 200_000
        result = _truncate_tool_result(long_text)
        assert len(result) < len(long_text)
        assert result.endswith("[Output truncated due to length]")

    def test_format_image(self):
        from source.llm.cloud_provider import _format_image

        result = _format_image("abc123", "image/png")
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_sanitize_tool_args_redacts_sensitive_keys(self):
        from source.mcp_integration.tool_args import sanitize_tool_args

        result = sanitize_tool_args(
            "read_file",
            "filesystem",
            {
                "path": "notes.txt",
                "api_key": "secret-value",
                "nested": {"token": "abc123", "safe": "ok"},
            },
        )

        assert result == {
            "path": "notes.txt",
            "api_key": "[REDACTED]",
            "nested": {"token": "[REDACTED]", "safe": "ok"},
        }

    def test_sanitize_tool_args_redacts_memcommit_content(self):
        from source.mcp_integration.tool_args import sanitize_tool_args

        result = sanitize_tool_args(
            "memcommit",
            "memory",
            {
                "path": "profile/user_profile.md",
                "title": "Personal profile",
                "category": "profile",
                "importance": 1.0,
                "tags": ["profile"],
                "abstract": "Sensitive summary",
                "body": "Sensitive body",
            },
        )

        assert result == {
            "path": "profile/user_profile.md",
            "title": "[REDACTED]",
            "category": "profile",
            "importance": 1.0,
            "tags": ["profile"],
            "abstract": "[REDACTED]",
            "body": "[REDACTED]",
        }

    def test_get_reasoning_params_supported(self):
        """Models that support reasoning should get reasoning_effort."""
        from source.llm.cloud_provider import _get_reasoning_params

        # Mock litellm.get_model_info to return supports_reasoning=True
        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            return_value={"supports_reasoning": True},
        ):
            params = _get_reasoning_params("anthropic/claude-sonnet-4-20250514")
        assert params == {"reasoning_effort": "high"}

    def test_get_reasoning_params_not_supported(self):
        """Models that don't support reasoning should get empty dict."""
        from source.llm.cloud_provider import _get_reasoning_params

        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            return_value={"supports_reasoning": False},
        ):
            params = _get_reasoning_params("openai/gpt-4o")
        assert params == {}

    def test_get_reasoning_params_unknown_model(self):
        """Unknown models (not in litellm registry) should get empty dict."""
        from source.llm.cloud_provider import _get_reasoning_params

        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            side_effect=Exception("Model not found"),
        ):
            params = _get_reasoning_params("custom/my-model")
        assert params == {}

    def test_get_reasoning_params_missing_field(self):
        """Model info without supports_reasoning field defaults to no reasoning."""
        from source.llm.cloud_provider import _get_reasoning_params

        with patch("source.llm.cloud_provider.litellm.get_model_info", return_value={}):
            params = _get_reasoning_params("openai/gpt-4o-mini")
        assert params == {}

    def test_get_max_tokens_supported(self):
        """Models with known max output tokens should return their limit."""
        from source.llm.cloud_provider import _get_max_tokens

        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            return_value={"max_output_tokens": 64000},
        ):
            result = _get_max_tokens("anthropic/claude-sonnet-4-20250514")
        assert result == 64000

    def test_get_max_tokens_unknown_model(self):
        """Unknown models should return None for max_tokens."""
        from source.llm.cloud_provider import _get_max_tokens

        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            side_effect=Exception("Not found"),
        ):
            result = _get_max_tokens("custom/my-model")
        assert result is None

    def test_get_max_tokens_missing_field(self):
        """Model info without max_output_tokens should return None."""
        from source.llm.cloud_provider import _get_max_tokens

        with patch(
            "source.llm.cloud_provider.litellm.get_model_info",
            return_value={"supports_reasoning": False},
        ):
            result = _get_max_tokens("openai/gpt-4o")
        assert result is None


# ---------------------------------------------------------------------------
# Streaming integration tests (_stream_litellm via stream_cloud_chat)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _mock_broadcast():
    """Patch broadcast_message and return the mock."""
    with patch(
        "source.llm.cloud_provider.broadcast_message", new_callable=AsyncMock
    ) as m:
        yield m


@pytest.fixture()
def _mock_cancelled():
    """Patch is_current_request_cancelled to always return False."""
    with patch(
        "source.llm.cloud_provider.is_current_request_cancelled", return_value=False
    ) as m:
        yield m


@pytest.fixture(autouse=True)
def _mock_model_info():
    """Prevent litellm.get_model_info from hitting the real registry in tests.

    Defaults to supports_reasoning=False so streaming tests behave like
    non-reasoning models.  Individual tests can override by mocking again.
    """
    with patch(
        "source.llm.cloud_provider.litellm.get_model_info",
        return_value={"supports_reasoning": False},
    ):
        yield


@pytest.fixture()
def _mock_mcp():
    """Patch the mcp_manager used inside _stream_litellm.

    mcp_manager is imported inline (from ..mcp_integration.manager import mcp_manager),
    so we patch it at the source module where it lives.
    """
    mock_mgr = MagicMock()
    mock_mgr.get_tools.return_value = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_cmd",
                "description": "Run a command",
                "parameters": {},
            },
        },
    ]
    mock_mgr.get_tool_server_name.return_value = "test-server"
    mock_mgr.call_tool = AsyncMock(return_value="tool output")
    with (
        patch("source.mcp_integration.manager.mcp_manager", mock_mgr),
        patch(
            "source.mcp_integration.terminal_executor.is_terminal_tool",
            return_value=False,
        ),
    ):
        yield mock_mgr


def _patch_acompletion(*streams):
    """Return a patch context manager that yields each stream in sequence."""
    mock = AsyncMock()
    mock.side_effect = [_make_async_iter(s) for s in streams]
    return patch("source.llm.cloud_provider.litellm.acompletion", mock)


class TestStreamLitellm:
    """Integration tests for the streaming loop and tool-call handling."""

    @pytest.mark.asyncio
    async def test_simple_text_response(self, _mock_broadcast, _mock_cancelled):
        """Text-only response: returns accumulated text and correct stats."""
        chunks = [
            _text_chunk("Hello "),
            _text_chunk("world!"),
            _usage_chunk(10, 5),
            _text_chunk(None, finish_reason="stop"),
        ]
        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == "Hello world!"
        assert stats["prompt_eval_count"] == 10
        assert stats["eval_count"] == 5
        assert tool_calls == []
        # No tool calls → blocks should be [{"type":"text",...}] or None
        # (implementation appends current_round_text at end)

    @pytest.mark.asyncio
    async def test_ollama_passes_api_base_without_empty_api_key(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        chunks = [
            _text_chunk("Hello Ollama"),
            _usage_chunk(9, 4),
            _text_chunk(None, finish_reason="stop"),
        ]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, _, _ = await stream_cloud_chat(
                provider="ollama",
                model="qwen3:8b",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                api_base="https://ollama.example.com",
                litellm_model_override="ollama_chat/qwen3:8b",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        assert text == "Hello Ollama"
        assert stats == {"prompt_eval_count": 9, "eval_count": 4}
        kwargs = mock_acomp.call_args.kwargs
        assert kwargs["model"] == "ollama_chat/qwen3:8b"
        assert kwargs["api_base"] == "https://ollama.example.com"
        assert kwargs["num_ctx"] == OLLAMA_CTX_SIZE
        assert "api_key" not in kwargs

    @pytest.mark.asyncio
    async def test_ollama_skips_reasoning_effort_even_if_model_registry_supports_it(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        chunks = [
            _text_chunk("No thinking toggle"),
            _text_chunk(None, finish_reason="stop"),
        ]
        with (
            patch(
                "source.llm.cloud_provider.litellm.get_model_info",
                return_value={"supports_reasoning": True},
            ),
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                AsyncMock(return_value=_make_async_iter(chunks)),
            ) as mock_acomp,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="ollama",
                model="qwen3:8b",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                litellm_model_override="ollama_chat/qwen3:8b",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        assert "reasoning_effort" not in mock_acomp.call_args.kwargs

    @pytest.mark.asyncio
    async def test_ollama_skips_max_tokens_even_if_model_registry_has_value(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        """Ollama should never receive max_tokens — Ollama manages its own limits."""
        chunks = [
            _text_chunk("No max_tokens"),
            _text_chunk(None, finish_reason="stop"),
        ]
        with (
            patch(
                "source.llm.cloud_provider.litellm.get_model_info",
                return_value={"max_output_tokens": 262144},
            ),
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                AsyncMock(return_value=_make_async_iter(chunks)),
            ) as mock_acomp,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="ollama",
                model="qwen3.5:cloud",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                litellm_model_override="ollama_chat/qwen3.5:cloud",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        # max_tokens should NOT be in kwargs for Ollama
        assert "max_tokens" not in mock_acomp.call_args.kwargs

    @pytest.mark.asyncio
    async def test_ollama_registers_native_function_calling_hint_before_streaming(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        chunks = [
            _text_chunk("hinted"),
            _text_chunk(None, finish_reason="stop"),
        ]
        with (
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                AsyncMock(return_value=_make_async_iter(chunks)),
            ),
            patch(
                "source.llm.ollama_model_registry.register_ollama_native_function_calling_hint",
                return_value=True,
            ) as register_hint,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="ollama",
                model="qwen3:8b",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                litellm_model_override="ollama_chat/qwen3:8b",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        register_hint.assert_called_once_with("ollama_chat/qwen3:8b")

    @pytest.mark.asyncio
    async def test_non_ollama_does_not_register_function_calling_hint(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        chunks = [
            _text_chunk("ok"),
            _text_chunk(None, finish_reason="stop"),
        ]
        with (
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                AsyncMock(return_value=_make_async_iter(chunks)),
            ),
            patch(
                "source.llm.ollama_model_registry.register_ollama_native_function_calling_hint",
                return_value=True,
            ) as register_hint,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        register_hint.assert_not_called()

    def test_ollama_debug_logging_default_is_disabled(self):
        from source.llm import cloud_provider

        assert cloud_provider.OLLAMA_DEBUG_LOGGING is False

    @pytest.mark.asyncio
    async def test_ollama_debug_logging_does_not_log_exception_message(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        with (
            patch("source.llm.cloud_provider.OLLAMA_DEBUG_LOGGING", True),
            patch("source.llm.cloud_provider.logger.error") as log_error,
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                side_effect=RuntimeError("token=super-secret"),
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="ollama",
                model="qwen3:8b",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                litellm_model_override="ollama_chat/qwen3:8b",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        rendered_logs = "\n".join(
            " ".join(str(arg) for arg in call.args) for call in log_error.call_args_list
        )
        assert "super-secret" not in rendered_logs

    @pytest.mark.asyncio
    async def test_ollama_debug_logging_redacts_api_base_credentials(
        self,
        _mock_broadcast,
        _mock_cancelled,
    ):
        with (
            patch("source.llm.cloud_provider.OLLAMA_DEBUG_LOGGING", True),
            patch("source.llm.cloud_provider.logger.error") as log_error,
            patch(
                "source.llm.cloud_provider.litellm.acompletion",
                side_effect=RuntimeError("boom"),
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="ollama",
                model="qwen3:8b",
                api_key=None,
                user_query="hi",
                image_paths=[],
                chat_history=[],
                api_base="https://user:pass@example.com:11434/v1?token=abc",
                litellm_model_override="ollama_chat/qwen3:8b",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        rendered_logs = "\n".join(
            " ".join(str(arg) for arg in call.args) for call in log_error.call_args_list
        )
        assert "user:pass" not in rendered_logs
        assert "token=abc" not in rendered_logs
        assert "example.com:11434" in rendered_logs

    @pytest.mark.asyncio
    async def test_tool_call_then_text(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """Tool call round followed by text response."""
        # Round 1: model calls read_file tool
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path":'),
            _tool_call_chunk(0, arguments=' "test.py"}', finish_reason="tool_calls"),
            _usage_chunk(20, 10),
        ]
        # Round 2: model responds with text after seeing tool result
        text_stream = [
            _text_chunk("File contents: hello"),
            _text_chunk(None, finish_reason="stop"),
            _usage_chunk(30, 15),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="read file",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "File contents: hello"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "read_file"
        assert tool_calls[0]["args"] == {"path": "test.py"}
        assert tool_calls[0]["result"] == "tool output"
        # Token stats should be summed across both rounds
        assert stats["prompt_eval_count"] == 50
        assert stats["eval_count"] == 25

        # Interleaved blocks should have tool_call and final text
        assert blocks is not None
        block_types = [b["type"] for b in blocks]
        assert "tool_call" in block_types
        assert "text" in block_types

    @pytest.mark.asyncio
    async def test_spawn_agent_result_is_truncated_and_not_double_broadcast(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_spawn", name="spawn_agent"),
            _tool_call_chunk(
                0,
                arguments=(
                    '{"instruction":"do work","model_tier":"fast","agent_name":"Worker"}'
                ),
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Summarized"),
            _text_chunk(None, finish_reason="stop"),
        ]

        huge_result = "x" * 200_000
        _mock_mcp.get_tool_server_name.side_effect = lambda name: (
            "sub_agent" if name == "spawn_agent" else "test-server"
        )

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.services.sub_agent.execute_sub_agents_parallel",
                AsyncMock(return_value=[huge_result]),
            ) as batch_exec,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="delegate",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"spawn_agent"},
            )

        assert text == "Summarized"
        batch_exec.assert_awaited_once()
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "spawn_agent"
        assert len(tool_calls[0]["result"]) < len(huge_result)
        assert tool_calls[0]["result"].endswith("[Output truncated due to length]")

        tool_call_events = [
            call
            for call in _mock_broadcast.call_args_list
            if call.args[0] == "tool_call"
        ]
        assert len(tool_call_events) == 0

    @pytest.mark.asyncio
    async def test_spawn_agent_batch_failure_returns_system_error_result(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_spawn", name="spawn_agent"),
            _tool_call_chunk(
                0,
                arguments='{"instruction":"do work"}',
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Recovered"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.side_effect = lambda name: (
            "sub_agent" if name == "spawn_agent" else "test-server"
        )

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.services.sub_agent.execute_sub_agents_parallel",
                AsyncMock(side_effect=RuntimeError("boom")),
            ) as batch_exec,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="delegate",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"spawn_agent"},
            )

        assert text == "Recovered"
        batch_exec.assert_awaited_once()
        assert len(tool_calls) == 1
        assert (
            tool_calls[0]["result"]
            == "System error: sub-agent execution failed. See server logs for details."
        )

    @pytest.mark.asyncio
    async def test_spawn_agent_batch_with_missing_result_falls_back_per_call(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_a", name="spawn_agent"),
            _tool_call_chunk(
                0,
                arguments='{"instruction":"one"}',
            ),
            _tool_call_chunk(1, tc_id="call_b", name="spawn_agent"),
            _tool_call_chunk(
                1,
                arguments='{"instruction":"two"}',
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Recovered"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.side_effect = lambda name: (
            "sub_agent" if name == "spawn_agent" else "test-server"
        )

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.services.sub_agent.execute_sub_agents_parallel",
                AsyncMock(return_value=["only-one-result"]),
            ) as batch_exec,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="delegate",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"spawn_agent"},
            )

        assert text == "Recovered"
        batch_exec.assert_awaited_once()
        assert len(tool_calls) == 2
        assert tool_calls[0]["result"] == "only-one-result"
        assert (
            tool_calls[1]["result"]
            == "System error: sub-agent execution failed. See server logs for details."
        )

    @pytest.mark.asyncio
    async def test_cancellation_mid_stream(self, _mock_broadcast):
        """Cancellation during streaming should stop early."""
        call_count = 0

        def cancel_after_one():
            nonlocal call_count
            call_count += 1
            return call_count > 1  # cancelled on 2nd check (inside chunk loop)

        with patch(
            "source.llm.cloud_provider.is_current_request_cancelled",
            side_effect=cancel_after_one,
        ):
            chunks = [
                _text_chunk("Hello "),
                _text_chunk("world should not appear"),
                _text_chunk(None, finish_reason="stop"),
            ]
            with _patch_acompletion(chunks):
                from source.llm.cloud_provider import stream_cloud_chat

                text, stats, tool_calls, blocks = await stream_cloud_chat(
                    provider="openai",
                    model="gpt-4o",
                    api_key="sk-test",
                    user_query="hi",
                    image_paths=[],
                    chat_history=[],
                )

        # Should have stopped after partial consumption
        assert len(text) < len("Hello world should not appear")

    @pytest.mark.asyncio
    async def test_cancelled_before_start(self, _mock_broadcast):
        """If cancelled before streaming starts, returns immediately."""
        with patch(
            "source.llm.cloud_provider.is_current_request_cancelled", return_value=True
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == ""
        assert blocks is None

    @pytest.mark.asyncio
    async def test_malformed_tool_call_args(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """Malformed JSON in tool call args reports error back to model for self-correction."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_bad", name="read_file"),
            _tool_call_chunk(0, arguments="not valid json{{{"),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Fixed it"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="do it",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Fixed it"
        assert len(tool_calls) == 1
        # Args should be empty dict since JSON was invalid
        assert tool_calls[0]["args"] == {}
        # Result should contain the JSON error message fed back to the model
        assert "invalid JSON" in tool_calls[0]["result"]
        # Tool should NOT have been actually executed
        _mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_call_with_json_array_args_reports_error(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """Non-object JSON arguments should be rejected without crashing the loop."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_bad_type", name="read_file"),
            _tool_call_chunk(0, arguments='["not","an","object"]'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Recovered"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="do it",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Recovered"
        assert len(tool_calls) == 1
        assert tool_calls[0]["args"] == {}
        assert "JSON object" in tool_calls[0]["result"]
        _mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_call_arguments_handle_cumulative_stream_snapshots(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Cumulative argument snapshots should replace, not double-append."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_mem", name="memlist"),
            _tool_call_chunk(0, arguments='{"folder":"'),
            _tool_call_chunk(
                0,
                arguments='{"folder":"procedural"}',
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Listed"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.return_value = "memory"
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.mcp_integration.memory_executor.is_memory_tool",
                return_value=True,
            ),
            patch(
                "source.mcp_integration.memory_executor.execute_memory_tool",
                new=AsyncMock(return_value="memory listing"),
            ) as mock_execute,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="ollama",
                model="qwen3.5:cloud",
                api_key=None,
                user_query="list memory",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"memlist"},
                litellm_model_override="ollama_chat/qwen3.5:cloud",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        assert text == "Listed"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "memlist"
        assert tool_calls[0]["args"] == {"folder": "procedural"}
        mock_execute.assert_awaited_once_with(
            "memlist",
            {"folder": "procedural"},
            "memory",
        )

    @pytest.mark.asyncio
    async def test_memlist_malformed_args_fallback_to_empty_object(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """memlist should recover from malformed args by calling with {}."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_mem_bad", name="memlist"),
            _tool_call_chunk(
                0,
                arguments='{"folder":"procedural"}{"extra":1}',
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Recovered"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.return_value = "memory"
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.mcp_integration.memory_executor.is_memory_tool",
                return_value=True,
            ),
            patch(
                "source.mcp_integration.memory_executor.execute_memory_tool",
                new=AsyncMock(return_value="memory listing"),
            ) as mock_execute,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="ollama",
                model="glm-5:cloud",
                api_key=None,
                user_query="list memory",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"memlist"},
                litellm_model_override="ollama_chat/glm-5:cloud",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        assert text == "Recovered"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "memlist"
        assert tool_calls[0]["args"] == {}
        assert tool_calls[0]["result"] == "memory listing"
        mock_execute.assert_awaited_once_with("memlist", {}, "memory")

    @pytest.mark.asyncio
    async def test_list_skills_malformed_args_fallback_to_empty_object(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """list_skills should recover from malformed args by calling with {}."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_skills_bad", name="list_skills"),
            _tool_call_chunk(0, arguments='{"x":1}{"y":2}', finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Skills ready"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.return_value = "skills"
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.mcp_integration.skills_executor.execute_skill_tool",
                return_value="Available skills:\n- demo",
            ) as mock_execute,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="ollama",
                model="qwen3.5:cloud",
                api_key=None,
                user_query="what skills",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"list_skills"},
                litellm_model_override="ollama_chat/qwen3.5:cloud",
                provider_kwargs={"num_ctx": OLLAMA_CTX_SIZE},
            )

        assert text == "Skills ready"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "list_skills"
        assert tool_calls[0]["args"] == {}
        assert "Available skills" in tool_calls[0]["result"]
        mock_execute.assert_called_once_with("list_skills", {})

    @pytest.mark.asyncio
    async def test_thinking_tokens_broadcast(self, _mock_broadcast, _mock_cancelled):
        """Thinking tokens should be broadcast and thinking_complete sent once before text."""
        chunks = [
            _thinking_chunk("Let me think..."),
            _thinking_chunk(" about this."),
            _text_chunk("The answer is 42"),
            _text_chunk(None, finish_reason="stop"),
        ]
        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, _, _ = await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-test",
                user_query="think",
                image_paths=[],
                chat_history=[],
            )

        assert text == "The answer is 42"

        # Check broadcast calls
        broadcast_calls = [
            (call.args[0], call.args[1]) for call in _mock_broadcast.call_args_list
        ]

        # Should have thinking chunks
        thinking_chunks = [c for c in broadcast_calls if c[0] == "thinking_chunk"]
        assert len(thinking_chunks) == 2
        assert thinking_chunks[0][1] == "Let me think..."

        # Should have exactly one thinking_complete
        thinking_complete = [c for c in broadcast_calls if c[0] == "thinking_complete"]
        assert len(thinking_complete) == 1

        # thinking_complete should come before first response_chunk
        types_in_order = [c[0] for c in broadcast_calls]
        tc_idx = types_in_order.index("thinking_complete")
        rc_idx = types_in_order.index("response_chunk")
        assert tc_idx < rc_idx

    @pytest.mark.asyncio
    async def test_empty_chunks_ignored(self, _mock_broadcast, _mock_cancelled):
        """Empty/keep-alive chunks should be silently skipped."""
        chunks = [
            _empty_chunk(),
            _text_chunk("OK"),
            _empty_chunk(),
            _text_chunk(None, finish_reason="stop"),
        ]
        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, _, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == "OK"

    @pytest.mark.asyncio
    async def test_api_error_returns_empty(self, _mock_broadcast, _mock_cancelled):
        """An exception from litellm.acompletion should be caught and broadcast as error."""
        with patch(
            "source.llm.cloud_provider.litellm.acompletion",
            side_effect=Exception("API down"),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == ""
        assert blocks is None
        # Should have broadcast an error
        error_calls = [
            c for c in _mock_broadcast.call_args_list if c.args[0] == "error"
        ]
        assert len(error_calls) == 1
        assert (
            error_calls[0].args[1]
            == "LLM service temporarily unavailable. See server logs for details."
        )

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_round(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """Multiple parallel tool calls in a single streaming round."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_a", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "a.py"}'),
            _tool_call_chunk(1, tc_id="call_b", name="run_cmd"),
            _tool_call_chunk(1, arguments='{"cmd": "ls"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Both done"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="do both",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file", "run_cmd"},
            )

        assert text == "Both done"
        assert len(tool_calls) == 2
        names = {tc["name"] for tc in tool_calls}
        assert names == {"read_file", "run_cmd"}

    @pytest.mark.asyncio
    async def test_api_key_passed_directly(self, _mock_broadcast, _mock_cancelled):
        """Verify api_key is passed to litellm.acompletion, not set in os.environ."""
        chunks = [
            _text_chunk("ok", finish_reason="stop"),
        ]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-secret-123",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        # api_key should be in the call kwargs
        call_kwargs = mock_acomp.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-secret-123"

    @pytest.mark.asyncio
    async def test_openrouter_api_key_passed_directly(
        self, _mock_broadcast, _mock_cancelled
    ):
        """OpenRouter should use explicit api_key kwargs like other cloud providers."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="openrouter",
                model="anthropic/claude-3-5-sonnet",
                api_key="or-secret-key",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert call_kwargs["model"] == "openrouter/anthropic/claude-3-5-sonnet"
        assert call_kwargs["api_key"] == "or-secret-key"

    @pytest.mark.asyncio
    async def test_reasoning_params_forwarded(self, _mock_broadcast, _mock_cancelled):
        """reasoning_effort should be passed to acompletion for reasoning models."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.llm.cloud_provider.litellm.get_model_info",
                return_value={"supports_reasoning": True},
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-test",
                user_query="think",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert call_kwargs.get("reasoning_effort") == "high"

    @pytest.mark.asyncio
    async def test_no_reasoning_for_non_reasoning_model(
        self, _mock_broadcast, _mock_cancelled
    ):
        """Non-reasoning models should not get reasoning_effort in kwargs."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert "reasoning_effort" not in call_kwargs

    @pytest.mark.asyncio
    async def test_max_tokens_from_model_info(self, _mock_broadcast, _mock_cancelled):
        """max_tokens should be set dynamically from model info, not hardcoded."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.llm.cloud_provider.litellm.get_model_info",
                return_value={"supports_reasoning": False, "max_output_tokens": 64000},
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert call_kwargs["max_tokens"] == 64000

    @pytest.mark.asyncio
    async def test_no_max_tokens_when_unknown(self, _mock_broadcast, _mock_cancelled):
        """max_tokens should not be set when model's max_output_tokens is unknown."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert "max_tokens" not in call_kwargs

    @pytest.mark.asyncio
    async def test_max_tokens_zero_not_forwarded(
        self, _mock_broadcast, _mock_cancelled
    ):
        """A zero max_output_tokens value should not be forwarded to LiteLLM."""
        chunks = [_text_chunk("ok", finish_reason="stop")]
        mock_acomp = AsyncMock(return_value=_make_async_iter(chunks))
        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.llm.cloud_provider.litellm.get_model_info",
                return_value={"supports_reasoning": False, "max_output_tokens": 0},
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert "max_tokens" not in call_kwargs

    @pytest.mark.asyncio
    async def test_tool_resolution_failure_falls_back_to_no_tools(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Tool schema lookup failures should not crash the request."""
        chunks = [_text_chunk("No tools needed", finish_reason="stop")]
        _mock_mcp.get_tools.side_effect = RuntimeError("registry unavailable")

        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hello",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "No tools needed"
        assert stats["prompt_eval_count"] == 0
        assert stats["eval_count"] == 0
        assert tool_calls == []
        assert blocks is None or all(block["type"] != "tool_call" for block in blocks)

    @pytest.mark.asyncio
    async def test_unauthorized_tool_call_rejected(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """A tool outside the allowed set should be rejected and not executed."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_forbidden", name="run_cmd"),
            _tool_call_chunk(0, arguments='{"cmd": "whoami"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("I cannot call that tool."),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="run something",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "I cannot call that tool."
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "run_cmd"
        assert "not available for this request" in tool_calls[0]["result"]
        _mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_execution_errors_are_sanitized(
        self, _mock_broadcast, _mock_cancelled, _mock_mcp
    ):
        """Tool execution failures should not leak raw exception details."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(
                0, arguments='{"path": "secret.txt", "api_key": "secret-token-value"}'
            ),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Handled"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.call_tool.side_effect = RuntimeError("secret-token-value")
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="read it",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Handled"
        assert len(tool_calls) == 1
        assert tool_calls[0]["args"] == {"path": "secret.txt", "api_key": "[REDACTED]"}
        assert (
            tool_calls[0]["result"]
            == "System error: tool execution failed. See server logs for details."
        )
        assert "secret-token-value" not in tool_calls[0]["result"]
        _mock_mcp.call_tool.assert_awaited_once_with(
            "read_file",
            {"path": "secret.txt", "api_key": "secret-token-value"},
        )

        tool_call_payloads = [
            json.loads(call.args[1])
            for call in _mock_broadcast.call_args_list
            if call.args[0] == "tool_call"
        ]
        assert any(
            payload["args"].get("api_key") == "[REDACTED]"
            for payload in tool_call_payloads
        )

    @pytest.mark.asyncio
    async def test_memory_tool_execution_is_intercepted(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Memory tools should be handled by the inline memory executor."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="memread"),
            _tool_call_chunk(0, arguments='{"path": "procedural/sqlite_fix.md"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Used memory"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.return_value = "memory"
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.mcp_integration.memory_executor.is_memory_tool",
                return_value=True,
            ),
            patch(
                "source.mcp_integration.memory_executor.execute_memory_tool",
                new=AsyncMock(return_value="raw memory"),
            ) as mock_execute,
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="read memory",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"memread"},
            )

        assert text == "Used memory"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "memread"
        assert tool_calls[0]["result"] == "raw memory"
        mock_execute.assert_awaited_once_with(
            "memread",
            {"path": "procedural/sqlite_fix.md"},
            "memory",
        )
        _mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_memcommit_args_are_redacted_in_persisted_tool_calls(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Memory commit args should be redacted before UI/persistence surfaces."""
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="memcommit"),
            _tool_call_chunk(
                0,
                arguments=(
                    '{"path": "profile/user_profile.md", "title": "Profile", '
                    '"category": "profile", "importance": 1, "tags": ["profile"], '
                    '"abstract": "Sensitive summary", "body": "Sensitive body"}'
                ),
                finish_reason="tool_calls",
            ),
        ]
        text_stream = [
            _text_chunk("Committed"),
            _text_chunk(None, finish_reason="stop"),
        ]

        _mock_mcp.get_tool_server_name.return_value = "memory"
        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]

        with (
            patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp),
            patch(
                "source.mcp_integration.memory_executor.is_memory_tool",
                return_value=True,
            ),
            patch(
                "source.mcp_integration.memory_executor.execute_memory_tool",
                new=AsyncMock(
                    return_value="Created memory at 'profile/user_profile.md'."
                ),
            ),
        ):
            from source.llm.cloud_provider import stream_cloud_chat

            _, _, tool_calls, _ = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="commit memory",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"memcommit"},
            )

        assert tool_calls[0]["args"] == {
            "path": "profile/user_profile.md",
            "title": "[REDACTED]",
            "category": "profile",
            "importance": 1,
            "tags": ["profile"],
            "abstract": "[REDACTED]",
            "body": "[REDACTED]",
        }

        tool_call_payloads = [
            json.loads(call.args[1])
            for call in _mock_broadcast.call_args_list
            if call.args[0] == "tool_call"
        ]
        assert any(
            payload["args"].get("body") == "[REDACTED]"
            and payload["args"].get("abstract") == "[REDACTED]"
            for payload in tool_call_payloads
        )

    @pytest.mark.asyncio
    async def test_cancellation_during_tool_execution_stops_loop(
        self,
        _mock_broadcast,
        _mock_mcp,
    ):
        """Cancellation during tool execution should exit both inner and outer loops."""
        cancel_calls = 0

        def cancel_on_tool():
            nonlocal cancel_calls
            cancel_calls += 1
            # Calls 1-5: pre-loop, top-of-while, 3 chunk iterations → False
            # Call 6: inside tool execution for-loop → True (cancels before executing tool)
            return cancel_calls > 5

        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "a.py"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        with patch(
            "source.llm.cloud_provider.is_current_request_cancelled",
            side_effect=cancel_on_tool,
        ):
            mock_acomp = AsyncMock()
            mock_acomp.side_effect = [_make_async_iter(tool_stream)]
            with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
                from source.llm.cloud_provider import stream_cloud_chat

                text, _, tool_calls, _ = await stream_cloud_chat(
                    provider="openai",
                    model="gpt-4o",
                    api_key="sk-test",
                    user_query="do it",
                    image_paths=[],
                    chat_history=[],
                    allowed_tool_names={"read_file"},
                )

        # Should not have made a second acompletion call
        assert mock_acomp.call_count == 1
        # Tool should not have been executed
        _mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancellation_mid_tool_batch_keeps_message_history_consistent(
        self,
        _mock_broadcast,
        _mock_mcp,
    ):
        """Cancellation mid-batch should not append orphaned assistant tool_calls."""
        cancel_calls = 0

        def cancel_after_first_tool():
            nonlocal cancel_calls
            cancel_calls += 1
            return cancel_calls > 6

        tool_stream = [
            _tool_call_chunk(0, tc_id="call_a", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "a.py"}'),
            _tool_call_chunk(1, tc_id="call_b", name="run_cmd"),
            _tool_call_chunk(1, arguments='{"cmd": "dir"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]

        with patch(
            "source.llm.cloud_provider.is_current_request_cancelled",
            side_effect=cancel_after_first_tool,
        ):
            mock_acomp = AsyncMock(return_value=_make_async_iter(tool_stream))
            with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
                from source.llm.cloud_provider import stream_cloud_chat

                await stream_cloud_chat(
                    provider="openai",
                    model="gpt-4o",
                    api_key="sk-test",
                    user_query="do both",
                    image_paths=[],
                    chat_history=[],
                    allowed_tool_names={"read_file", "run_cmd"},
                )

        first_round_messages = mock_acomp.call_args.kwargs["messages"]
        assistant_messages = [
            m for m in first_round_messages if m.get("role") == "assistant"
        ]
        tool_messages = [m for m in first_round_messages if m.get("role") == "tool"]
        assert assistant_messages == []
        assert tool_messages == []

    @pytest.mark.asyncio
    async def test_api_error_preserves_partial_data(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Exception after partial streaming should preserve accumulated data."""
        # Round 1: model streams text + tool call
        tool_stream = [
            _text_chunk("Partial text "),
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "x"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            Exception("Connection reset"),  # Round 2 fails
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        # Partial text and tool calls from round 1 should be preserved
        assert "Partial text" in text
        assert len(tool_calls) >= 1

    @pytest.mark.asyncio
    async def test_fallback_tool_call_id(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Providers that omit tool_call IDs should get synthetic fallback IDs."""
        # Tool call with no ID (tc_id=None)
        tool_stream = [
            _tool_call_chunk(0, name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "x.py"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        text_stream = [
            _text_chunk("Done"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, tool_calls, _ = await stream_cloud_chat(
                provider="gemini",
                model="gemini-2.5-flash",
                api_key="key",
                user_query="do it",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Done"
        assert len(tool_calls) == 1

        # Verify the tool result message in round 2's messages has a synthetic ID
        second_call_messages = mock_acomp.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"].startswith("call_")

    @pytest.mark.asyncio
    async def test_thinking_reset_between_rounds(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Thinking state should reset per-round so round 2 thinking is broadcast."""
        # Round 1: thinking + tool call
        round1_stream = [
            _thinking_chunk("Round 1 thinking"),
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "a.py"}'),
            _tool_call_chunk(0, finish_reason="tool_calls"),
        ]
        # Round 2: thinking + text
        round2_stream = [
            _thinking_chunk("Round 2 thinking"),
            _text_chunk("Final answer"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(round1_stream),
            _make_async_iter(round2_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, _, _, _ = await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-test",
                user_query="think and use tools",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Final answer"

        broadcast_calls = [
            (call.args[0], call.args[1]) for call in _mock_broadcast.call_args_list
        ]

        # Should have thinking chunks from BOTH rounds
        thinking_chunks = [c for c in broadcast_calls if c[0] == "thinking_chunk"]
        thinking_texts = [c[1] for c in thinking_chunks]
        assert "Round 1 thinking" in thinking_texts
        assert "Round 2 thinking" in thinking_texts

        # Should have TWO thinking_complete broadcasts (one per round)
        thinking_completes = [c for c in broadcast_calls if c[0] == "thinking_complete"]
        assert len(thinking_completes) == 2

    @pytest.mark.asyncio
    async def test_token_usage_on_content_chunk(self, _mock_broadcast, _mock_cancelled):
        """Token usage attached to a content chunk (Anthropic/Gemini) is captured."""
        chunks = [
            _text_chunk("Hello "),
            _text_chunk("world!"),
            _text_chunk_with_usage(None, "stop", 15, 8),
        ]
        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == "Hello world!"
        assert stats["prompt_eval_count"] == 15
        assert stats["eval_count"] == 8

    @pytest.mark.asyncio
    async def test_token_usage_summed_across_tool_rounds(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Token usage from multiple acompletion rounds is summed correctly."""
        # Round 1: tool call with usage on final chunk
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "a.py"}'),
            _text_chunk_with_usage(None, "stop", 20, 10),
        ]
        # Round 2: text response with usage on final chunk
        text_stream = [
            _text_chunk("Done"),
            _text_chunk_with_usage(None, "stop", 30, 15),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="gemini",
                model="gemini-2.5-flash",
                api_key="key",
                user_query="read file",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Done"
        assert stats["prompt_eval_count"] == 50  # 20 + 30
        assert stats["eval_count"] == 25  # 10 + 15

    @pytest.mark.asyncio
    async def test_tool_calls_with_non_standard_finish_reason(
        self,
        _mock_broadcast,
        _mock_cancelled,
        _mock_mcp,
    ):
        """Tool calls execute even when finish_reason != 'tool_calls' (Gemini uses 'stop')."""
        # Round 1: model returns tool calls but finish_reason is "stop" (Gemini behavior)
        tool_stream = [
            _tool_call_chunk(0, tc_id="call_1", name="read_file"),
            _tool_call_chunk(0, arguments='{"path": "test.py"}'),
            _text_chunk(
                None, finish_reason="stop"
            ),  # Gemini: "stop" instead of "tool_calls"
        ]
        # Round 2: model responds with text after seeing tool result
        text_stream = [
            _text_chunk("Here are the contents"),
            _text_chunk(None, finish_reason="stop"),
        ]

        mock_acomp = AsyncMock()
        mock_acomp.side_effect = [
            _make_async_iter(tool_stream),
            _make_async_iter(text_stream),
        ]
        with patch("source.llm.cloud_provider.litellm.acompletion", mock_acomp):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="gemini",
                model="gemini-2.5-flash",
                api_key="key",
                user_query="read file",
                image_paths=[],
                chat_history=[],
                allowed_tool_names={"read_file"},
            )

        assert text == "Here are the contents"
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "read_file"
        assert tool_calls[0]["args"] == {"path": "test.py"}
        _mock_mcp.call_tool.assert_called_once()

        # Should have tool_call and text in interleaved blocks
        assert blocks is not None
        block_types = [b["type"] for b in blocks]
        assert "tool_call" in block_types
        assert "text" in block_types

    @pytest.mark.asyncio
    async def test_token_usage_no_double_count(self, _mock_broadcast, _mock_cancelled):
        """Usage on a content chunk AND a usage-only chunk should not double-count."""
        chunks = [
            _text_chunk("Hi"),
            # Final content chunk carries usage (Anthropic style)
            _text_chunk_with_usage(None, "stop", 15, 8),
            # Separate usage-only chunk also carries usage (OpenAI style)
            _usage_chunk(15, 8),
        ]
        with _patch_acompletion(chunks):
            from source.llm.cloud_provider import stream_cloud_chat

            text, stats, tool_calls, blocks = await stream_cloud_chat(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                user_query="hi",
                image_paths=[],
                chat_history=[],
            )

        assert text == "Hi"
        # Should be 15/8, NOT 30/16
        assert stats["prompt_eval_count"] == 15
        assert stats["eval_count"] == 8
