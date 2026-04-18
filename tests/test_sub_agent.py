"""Tests for source/services/skills_runtime/sub_agent.py — tier resolution, tool filtering, local detection."""

from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# We need to import after conftest stubs the circular import
from source.services.skills_runtime.sub_agent import (
    _resolve_tier_model,
    _is_local_ollama,
    _uses_ollama_client,
    _get_sub_agent_tools,
    _EXCLUDED_TOOLS,
    _tool_progress_description,
    _truncate_safely,
    _run_cloud_sub_agent,
    _run_ollama_sub_agent,
    execute_sub_agent,
    execute_sub_agents_parallel,
)


# ---------------------------------------------------------------------------
# _uses_ollama_client  (routing: which provider to call)
# ---------------------------------------------------------------------------


class TestUsesOllamaClient:
    def test_plain_ollama_model(self):
        assert _uses_ollama_client("qwen3:8b") is True

    def test_ollama_cloud_model(self):
        assert _uses_ollama_client("qwen3.5:397b-cloud") is True

    def test_anthropic_model(self):
        assert _uses_ollama_client("anthropic/claude-sonnet-4-20250514") is False

    def test_openai_model(self):
        assert _uses_ollama_client("openai/gpt-4o") is False

    def test_gemini_model(self):
        assert _uses_ollama_client("gemini/gemini-2.5-flash") is False

    def test_openrouter_model(self):
        assert _uses_ollama_client("openrouter/anthropic/claude-3-5-sonnet") is False

    def test_unknown_provider_uses_ollama(self):
        assert _uses_ollama_client("custom/some-model") is True


# ---------------------------------------------------------------------------
# _is_local_ollama  (parallelism: local GPU = sequential)
# ---------------------------------------------------------------------------


class TestIsLocalOllama:
    def test_plain_ollama_model_is_local(self):
        assert _is_local_ollama("qwen3:8b") is True

    def test_ollama_cloud_model_is_not_local(self):
        # -cloud suffix means cloud-hosted Ollama — safe to parallelise
        assert _is_local_ollama("qwen3.5:397b-cloud") is False

    def test_anthropic_model_is_not_local(self):
        assert _is_local_ollama("anthropic/claude-sonnet-4-20250514") is False

    def test_openai_model_is_not_local(self):
        assert _is_local_ollama("openai/gpt-4o") is False

    def test_gemini_model_is_not_local(self):
        assert _is_local_ollama("gemini/gemini-2.5-flash") is False

    def test_unknown_provider_slash_model_is_local(self):
        # provider not in known cloud set → treated as Ollama-like, no -cloud suffix
        assert _is_local_ollama("custom/some-model") is True

    def test_ollama_cloud_colon_tag_is_not_local(self):
        assert _is_local_ollama("qwen3-coder-next:cloud") is False

    def test_ollama_cloud_colon_tag_case_insensitive(self):
        assert _is_local_ollama("qwen3-coder-next:CLOUD") is False

    def test_no_slash_no_cloud_is_local(self):
        assert _is_local_ollama("llama3.2") is True

class TestExecuteSubAgentsParallel:
    async def test_empty_call_batch_returns_empty_list(self):
        assert await execute_sub_agents_parallel([]) == []

    async def test_cloud_tagged_ollama_models_run_in_parallel(self):
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_execute_sub_agent(instruction: str, model_tier: str, agent_name: str):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.03)
            async with lock:
                in_flight -= 1
            return f"ok:{agent_name}:{model_tier}:{instruction}"

        with patch("source.services.skills_runtime.sub_agent._resolve_tier_model") as mock_resolve, patch(
            "source.services.skills_runtime.sub_agent.execute_sub_agent",
            side_effect=fake_execute_sub_agent,
        ):
            mock_resolve.side_effect = lambda tier: {
                "fast": "qwen3-coder-next:cloud",
                "smart": "gpt-oss:20b-cloud",
            }[tier]

            calls = [
                {"instruction": "task one", "model_tier": "fast", "agent_name": "A"},
                {"instruction": "task two", "model_tier": "smart", "agent_name": "B"},
            ]

            results = await execute_sub_agents_parallel(calls)

        assert max_in_flight == 2
        assert len(results) == 2
        assert results[0].startswith("ok:A")
        assert results[1].startswith("ok:B")

    async def test_local_ollama_forces_sequential_execution(self):
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_execute_sub_agent(instruction: str, model_tier: str, agent_name: str):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.03)
            async with lock:
                in_flight -= 1
            return f"ok:{agent_name}:{model_tier}:{instruction}"

        with patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="llama3.2"), patch(
            "source.services.skills_runtime.sub_agent.execute_sub_agent",
            side_effect=fake_execute_sub_agent,
        ):
            calls = [
                {"instruction": "task one", "model_tier": "fast", "agent_name": "A"},
                {"instruction": "task two", "model_tier": "fast", "agent_name": "B"},
            ]

            results = await execute_sub_agents_parallel(calls)

        assert max_in_flight == 1
        assert len(results) == 2

    async def test_invalid_model_tier_normalizes_before_locality_decision(self):
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_execute_sub_agent(instruction: str, model_tier: str, agent_name: str):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.03)
            async with lock:
                in_flight -= 1
            return f"ok:{agent_name}:{model_tier}:{instruction}"

        with patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="llama3.2"), patch(
            "source.services.skills_runtime.sub_agent.execute_sub_agent",
            side_effect=fake_execute_sub_agent,
        ):
            calls = [
                {"instruction": "task one", "model_tier": "unknown", "agent_name": "A"},
                {"instruction": "task two", "model_tier": "unknown", "agent_name": "B"},
            ]

            results = await execute_sub_agents_parallel(calls)

        assert max_in_flight == 1
        assert len(results) == 2

    async def test_parallel_batch_converts_execute_exceptions_to_error_strings(self):
        async def fake_execute_sub_agent(instruction: str, model_tier: str, agent_name: str):
            if agent_name == "B":
                raise RuntimeError("boom")
            return f"ok:{agent_name}:{model_tier}:{instruction}"

        with patch(
            "source.services.skills_runtime.sub_agent._resolve_tier_model",
            return_value="qwen3-coder-next:cloud",
        ), patch(
            "source.services.skills_runtime.sub_agent.execute_sub_agent",
            side_effect=fake_execute_sub_agent,
        ):
            results = await execute_sub_agents_parallel(
                [
                    {"instruction": "task one", "model_tier": "fast", "agent_name": "A"},
                    {"instruction": "task two", "model_tier": "smart", "agent_name": "B"},
                ]
            )

        assert results == [
            "ok:A:fast:task one",
            "Error: Sub-agent 'B' failed: RuntimeError",
        ]


# ---------------------------------------------------------------------------
# _resolve_tier_model
# ---------------------------------------------------------------------------


class TestResolveTierModel:
    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value="anthropic/claude-sonnet-4-20250514")
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_self_tier_returns_current_model(self, mock_db, mock_model):
        result = _resolve_tier_model("self")
        assert result == "anthropic/claude-sonnet-4-20250514"
        # self tier should never check DB
        mock_db.get_setting.assert_not_called()

    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_fast_tier_with_no_override_returns_current(self, mock_db, mock_model):
        mock_db.get_setting.return_value = None
        result = _resolve_tier_model("fast")
        assert result == "openai/gpt-4o"

    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_fast_tier_with_override_returns_override(self, mock_db, mock_model):
        mock_db.get_setting.return_value = "gemini/gemini-2.5-flash"
        result = _resolve_tier_model("fast")
        assert result == "gemini/gemini-2.5-flash"

    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_smart_tier_with_empty_override_returns_current(self, mock_db, mock_model):
        mock_db.get_setting.return_value = "  "
        result = _resolve_tier_model("smart")
        assert result == "openai/gpt-4o"

    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value=None)
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_uses_override_when_no_context_var(self, mock_db, mock_model):
        mock_db.get_setting.return_value = "llama3.2"
        result = _resolve_tier_model("fast")
        assert result == "llama3.2"

    @patch("source.services.skills_runtime.sub_agent.get_current_model", return_value=None)
    @patch("source.services.skills_runtime.sub_agent.db")
    def test_raises_when_no_context_model_and_no_override(self, mock_db, mock_model):
        mock_db.get_setting.return_value = None
        with pytest.raises(ValueError, match="No model available"):
            _resolve_tier_model("fast")


class TestHelpers:
    def test_tool_progress_description_formats_known_tools(self):
        assert _tool_progress_description("read_website", {"url": "https://example.com/x"}) == "Reading example.com..."
        assert _tool_progress_description("search_web_pages", {"query": "find docs"}) == 'Searching: "find docs"'
        assert _tool_progress_description("unknown_tool", {}) == "Using unknown_tool..."

    def test_truncate_safely_preserves_word_boundaries(self):
        text = "word " * 100
        truncated = _truncate_safely(text, 60)

        assert len(truncated) <= 75
        assert truncated.endswith("... [truncated]")


# ---------------------------------------------------------------------------
# _get_sub_agent_tools — tool filtering
# ---------------------------------------------------------------------------


class TestGetSubAgentTools:
    @patch("source.mcp_integration.core.manager.mcp_manager")
    def test_returns_none_when_no_tools(self, mock_manager):
        mock_manager.has_tools.return_value = False
        assert _get_sub_agent_tools("read the file") is None

    @patch("source.mcp_integration.core.handlers.retrieve_relevant_tools")
    @patch("source.mcp_integration.core.manager.mcp_manager")
    def test_excludes_terminal_and_spawn_agent(self, mock_manager, mock_retrieve):
        mock_manager.has_tools.return_value = True
        mock_retrieve.return_value = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "run_command"}},
            {"function": {"name": "spawn_agent"}},
            {"function": {"name": "search_web_pages"}},
        ]
        result = _get_sub_agent_tools("test instruction")
        assert result is not None
        names = [t["function"]["name"] for t in result]
        assert "read_file" in names
        assert "search_web_pages" in names
        assert "run_command" not in names
        assert "spawn_agent" not in names

    @patch("source.mcp_integration.core.handlers.retrieve_relevant_tools")
    @patch("source.mcp_integration.core.manager.mcp_manager")
    def test_returns_none_when_all_filtered(self, mock_manager, mock_retrieve):
        mock_manager.has_tools.return_value = True
        mock_retrieve.return_value = [
            {"function": {"name": "run_command"}},
            {"function": {"name": "spawn_agent"}},
        ]
        assert _get_sub_agent_tools("test") is None


# ---------------------------------------------------------------------------
# _EXCLUDED_TOOLS constant
# ---------------------------------------------------------------------------


class TestExcludedTools:
    def test_contains_all_terminal_tools(self):
        terminal_tools = {
            "run_command", "request_session_mode", "end_session_mode",
            "send_input", "read_output", "kill_process",
            "get_environment",
        }
        assert terminal_tools.issubset(_EXCLUDED_TOOLS)

    def test_contains_spawn_agent(self):
        assert "spawn_agent" in _EXCLUDED_TOOLS


# ---------------------------------------------------------------------------
# _run_cloud_sub_agent — direct cloud call behavior
# ---------------------------------------------------------------------------


def _make_streaming_chunks(content: str, tool_calls=None, prompt_tokens=0, completion_tokens=0):
    """Create a list of streaming chunks that mimic LiteLLM's streaming response.

    Returns an async generator that yields streaming chunks.
    """
    async def generator():
        # First chunk: content delta
        if content:
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=content, tool_calls=None),
                    finish_reason=None
                )],
                usage=None
            )

        # Tool calls chunks (if any)
        if tool_calls:
            for i, tc in enumerate(tool_calls):
                yield SimpleNamespace(
                    choices=[SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[SimpleNamespace(
                                index=i,
                                id=tc.id,
                                function=SimpleNamespace(
                                    name=tc.function.name,
                                    arguments=tc.function.arguments
                                )
                            )]
                        ),
                        finish_reason=None
                    )],
                    usage=None
                )

        # Final chunk with usage and finish_reason
        yield SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=None),
                finish_reason="stop" if not tool_calls else "tool_calls"
            )],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        )

    return generator()


def _make_ollama_stream(
    *,
    content: str = "",
    thinking: str = "",
    tool_calls=None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    as_dict: bool = True,
):
    async def generator():
        message = {}
        if content:
            message["content"] = content
        if thinking:
            message["thinking"] = thinking
        if tool_calls is not None:
            message["tool_calls"] = tool_calls

        if as_dict:
            yield {
                "message": message,
                "done": True,
                "prompt_eval_count": prompt_tokens,
                "eval_count": completion_tokens,
            }
        else:
            yield SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    thinking=thinking,
                    tool_calls=tool_calls,
                ),
                done=True,
                prompt_eval_count=prompt_tokens,
                eval_count=completion_tokens,
            )

    return generator()


class TestRunCloudSubAgent:
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value=None)
    async def test_returns_error_when_api_key_missing(self, _mock_key):
        result = await _run_cloud_sub_agent(
            model_name="openai/gpt-4o",
            instruction="Say hi",
            tools=None,
        )

        assert result == {
            "response": "Error: No API key for openai",
            "token_stats": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": "No API key for openai",
        }

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="or-test-key")
    async def test_openrouter_passes_api_key_directly(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        mock_acompletion.return_value = _make_streaming_chunks(
            content="ok", prompt_tokens=7, completion_tokens=3
        )

        result = await _run_cloud_sub_agent(
            model_name="openrouter/anthropic/claude-3-5-sonnet",
            instruction="Say hi",
            tools=None,
        )

        assert result["response"] == "ok"
        assert result["error"] is None
        assert result["token_stats"] == {"prompt_tokens": 7, "completion_tokens": 3}

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == "openrouter/anthropic/claude-3-5-sonnet"
        assert call_kwargs["api_key"] == "or-test-key"

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="sk-test")
    async def test_cloud_sub_agent_invalid_tool_args_do_not_crash(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        # Create tool call with invalid JSON arguments
        bad_tool_call = SimpleNamespace(
            id="call1",
            function=SimpleNamespace(name="read_file", arguments="{bad json"),
        )
        mock_acompletion.return_value = _make_streaming_chunks(
            content="",
            tool_calls=[bad_tool_call],
            prompt_tokens=3,
            completion_tokens=2,
        )

        result = await _run_cloud_sub_agent(
            model_name="openai/gpt-4o",
            instruction="Read file",
            tools=[{"type": "function", "function": {"name": "read_file", "description": "", "parameters": {}}}],
        )

        assert result["error"] is None
        assert "response" in result

    @patch("source.services.skills_runtime.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="sk-test")
    async def test_cloud_sub_agent_executes_tool_and_aggregates_tokens(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled, mock_broadcast
    ):
        read_file_call = SimpleNamespace(
            id="call1",
            function=SimpleNamespace(name="read_file", arguments='{"path": "/tmp/demo.txt"}'),
        )
        mock_acompletion.side_effect = [
            _make_streaming_chunks(content="", tool_calls=[read_file_call], prompt_tokens=2, completion_tokens=3),
            _make_streaming_chunks(content="Final answer", prompt_tokens=4, completion_tokens=5),
        ]

        fake_manager = MagicMock()
        fake_manager.get_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "", "parameters": {}}}
        ]
        fake_manager.call_tool = AsyncMock(return_value="tool output")

        with patch("source.mcp_integration.core.manager.mcp_manager", fake_manager):
            result = await _run_cloud_sub_agent(
                model_name="openai/gpt-4o",
                instruction="Read the file",
                tools=[{"function": {"name": "read_file"}}],
                agent_id="agent-1",
                agent_name="TestAgent",
                model_tier="fast",
            )

        assert result == {
            "response": "Final answer",
            "token_stats": {"prompt_tokens": 6, "completion_tokens": 8},
            "error": None,
        }
        fake_manager.call_tool.assert_awaited_once_with("read_file", {"path": "/tmp/demo.txt"})
        stream_types = [call.args[1] for call in mock_broadcast.await_args_list]
        assert any('"stream_type": "tool_call"' in payload for payload in stream_types)
        assert any('"stream_type": "tool_result"' in payload for payload in stream_types)
        assert any('"stream_type": "final"' in payload for payload in stream_types)

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="sk-test")
    async def test_cloud_sub_agent_blocks_excluded_tools_without_calling_manager(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        blocked_call = SimpleNamespace(
            id="call1",
            function=SimpleNamespace(name="run_command", arguments='{"command": "whoami"}'),
        )
        mock_acompletion.side_effect = [
            _make_streaming_chunks(content="", tool_calls=[blocked_call], prompt_tokens=1, completion_tokens=1),
            _make_streaming_chunks(content="Done", prompt_tokens=1, completion_tokens=1),
        ]

        fake_manager = MagicMock()
        fake_manager.get_tools.return_value = [
            {"type": "function", "function": {"name": "run_command", "description": "", "parameters": {}}}
        ]
        fake_manager.call_tool = AsyncMock()

        with patch("source.mcp_integration.core.manager.mcp_manager", fake_manager):
            result = await _run_cloud_sub_agent(
                model_name="openai/gpt-4o",
                instruction="Run a command",
                tools=[{"function": {"name": "run_command"}}],
            )

        assert result["response"] == "Done"
        fake_manager.call_tool.assert_not_called()

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="sk-anthropic")
    async def test_cloud_sub_agent_defaults_anthropic_max_tokens(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        mock_acompletion.return_value = _make_streaming_chunks(content="Anthropic answer")

        result = await _run_cloud_sub_agent(
            model_name="anthropic/claude-sonnet-4-20250514",
            instruction="Say hi",
            tools=None,
        )

        assert result["response"] == "Anthropic answer"
        assert mock_acompletion.await_args.kwargs["max_tokens"] == 16384

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.skills_runtime.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.skills_runtime.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.core.key_manager.key_manager.get_api_key", return_value="sk-test")
    async def test_cloud_sub_agent_returns_error_when_streaming_fails(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        mock_acompletion.side_effect = RuntimeError("stream exploded")

        result = await _run_cloud_sub_agent(
            model_name="openai/gpt-4o",
            instruction="Say hi",
            tools=None,
        )

        assert result == {
            "response": "Sub-agent error: RuntimeError",
            "token_stats": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": "RuntimeError",
        }


class TestRunOllamaSubAgent:
    @patch("source.services.skills_runtime.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    async def test_ollama_sub_agent_strips_provider_prefix_and_streams_response(
        self, _mock_cancelled, mock_broadcast
    ):
        client = AsyncMock()
        client.chat = AsyncMock(
            return_value=_make_ollama_stream(
                content="Local answer",
                thinking="Planning...",
                prompt_tokens=3,
                completion_tokens=2,
                as_dict=True,
            )
        )

        with patch("source.services.skills_runtime.sub_agent.OllamaAsyncClient", create=True):
            pass

        with patch("ollama.AsyncClient", return_value=client):
            result = await _run_ollama_sub_agent(
                model_name="ollama/llama3.2",
                instruction="Say hi",
                tools=None,
                agent_id="agent-1",
                agent_name="LocalAgent",
                model_tier="fast",
            )

        assert result == {
            "response": "Planning...Local answer",
            "token_stats": {"prompt_tokens": 3, "completion_tokens": 2},
            "error": None,
        }
        assert client.chat.await_args.kwargs["model"] == "llama3.2"
        stream_types = [call.args[1] for call in mock_broadcast.await_args_list]
        assert any('"stream_type": "instruction"' in payload for payload in stream_types)
        assert any('"stream_type": "thinking_complete"' in payload for payload in stream_types)
        assert any('"stream_type": "final"' in payload for payload in stream_types)

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    async def test_ollama_sub_agent_handles_invalid_excluded_and_valid_tool_calls(
        self, _mock_cancelled
    ):
        tool_calls = [
            {"function": {"name": "run_command", "arguments": {"command": "whoami"}}},
            {"function": {"name": "read_file", "arguments": "{bad json"}},
            {"function": {"name": "search_web_pages", "arguments": {"query": "docs"}}},
            {"function": {}},
        ]
        client = AsyncMock()
        client.chat = AsyncMock(
            side_effect=[
                _make_ollama_stream(tool_calls=tool_calls, prompt_tokens=2, completion_tokens=1),
                _make_ollama_stream(content="Tool-assisted answer", prompt_tokens=1, completion_tokens=1, as_dict=False),
            ]
        )

        fake_manager = MagicMock()
        fake_manager.call_tool = AsyncMock(return_value="search results")

        with (
            patch("ollama.AsyncClient", return_value=client),
            patch("source.mcp_integration.core.manager.mcp_manager", fake_manager),
        ):
            result = await _run_ollama_sub_agent(
                model_name="llama3.2",
                instruction="Use tools",
                tools=[{"function": {"name": "search_web_pages"}}],
            )

        assert result == {
            "response": "Tool-assisted answer",
            "token_stats": {"prompt_tokens": 3, "completion_tokens": 2},
            "error": None,
        }
        fake_manager.call_tool.assert_awaited_once_with("search_web_pages", {"query": "docs"})

    @patch("source.services.skills_runtime.sub_agent.is_current_request_cancelled", return_value=False)
    async def test_ollama_sub_agent_returns_error_when_client_fails(self, _mock_cancelled):
        client = AsyncMock()
        client.chat = AsyncMock(side_effect=RuntimeError("client exploded"))

        with patch("ollama.AsyncClient", return_value=client):
            result = await _run_ollama_sub_agent(
                model_name="llama3.2",
                instruction="Say hi",
                tools=None,
            )

        assert result == {
            "response": "Sub-agent error: RuntimeError",
            "token_stats": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": "RuntimeError",
        }


# ---------------------------------------------------------------------------
# execute_sub_agent — integration-level with mocked LLM
# ---------------------------------------------------------------------------


class TestExecuteSubAgent:
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model")
    async def test_model_resolution_failure_returns_error_string(self, mock_resolve):
        mock_resolve.side_effect = ValueError("missing model context")

        result = await execute_sub_agent("What is the answer?", "fast", "BrokenAgent")

        assert result == (
            "Error: Failed to resolve sub-agent model tier: ValueError: missing model context"
        )

    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools")
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="openai/gpt-4o")
    async def test_tool_preparation_failure_returns_error_string(
        self, mock_resolve, mock_tools
    ):
        mock_tools.side_effect = RuntimeError("mcp unavailable")

        result = await execute_sub_agent("What is the answer?", "fast", "BrokenAgent")

        assert result == (
            "Error: Failed to prepare sub-agent tools: RuntimeError: mcp unavailable"
        )

    @patch("source.services.skills_runtime.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="anthropic/claude-sonnet-4-20250514")
    @patch("source.services.skills_runtime.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
    async def test_cloud_sub_agent_returns_response(
        self, mock_run, mock_resolve, mock_tools, mock_broadcast
    ):
        mock_run.return_value = {
            "response": "The answer is 42.",
            "token_stats": {"prompt_tokens": 100, "completion_tokens": 50},
            "error": None,
        }
        result = await execute_sub_agent("What is the answer?", "fast", "TestAgent")
        assert result == "The answer is 42."
        # Live transcript updates are streamed separately; execute_sub_agent no longer
        # emits redundant outer tool_call lifecycle broadcasts here.
        assert mock_broadcast.call_count == 0

    @patch("source.services.skills_runtime.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="llama3.2")
    @patch("source.services.skills_runtime.sub_agent._run_ollama_sub_agent", new_callable=AsyncMock)
    async def test_ollama_sub_agent_routes_to_ollama(
        self, mock_run, mock_resolve, mock_tools, mock_broadcast
    ):
        mock_run.return_value = {
            "response": "Local response",
            "token_stats": {"prompt_tokens": 50, "completion_tokens": 25},
            "error": None,
        }
        result = await execute_sub_agent("Do something", "fast", "LocalAgent")
        assert result == "Local response"
        mock_run.assert_called_once()

    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent.run_in_thread", new_callable=AsyncMock)
    async def test_logging_failure_does_not_hide_successful_result(
        self, mock_run_in_thread, mock_run, mock_resolve, mock_tools
    ):
        mock_run.return_value = {
            "response": "The answer is still returned.",
            "token_stats": {"prompt_tokens": 10, "completion_tokens": 5},
            "error": None,
        }
        mock_run_in_thread.side_effect = RuntimeError("thread pool unavailable")

        result = await execute_sub_agent("What is the answer?", "fast", "TestAgent")

        assert result == "The answer is still returned."

    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
    @patch("source.services.skills_runtime.sub_agent.run_in_thread", new_callable=AsyncMock)
    async def test_error_result_includes_partial_response(
        self, mock_run_in_thread, mock_run, mock_resolve, mock_tools
    ):
        mock_run.return_value = {
            "response": "Partial answer",
            "token_stats": {"prompt_tokens": 10, "completion_tokens": 5},
            "error": "ProviderError",
        }
        mock_run_in_thread.return_value = None

        result = await execute_sub_agent("What is the answer?", "fast", "TestAgent")

        assert result == "Error: ProviderError\n\nPartial response:\nPartial answer"

    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
    async def test_timeout_returns_clear_error(self, mock_run, mock_resolve, mock_tools):
        mock_run.side_effect = asyncio.TimeoutError()

        result = await execute_sub_agent("What is the answer?", "fast", "SlowAgent")

        assert "timed out" in result

    @patch("source.services.skills_runtime.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.skills_runtime.sub_agent._resolve_tier_model", return_value="openai/gpt-4o")
    @patch("source.services.skills_runtime.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
    async def test_unexpected_exception_returns_error(self, mock_run, mock_resolve, mock_tools):
        mock_run.side_effect = RuntimeError("boom")

        result = await execute_sub_agent("What is the answer?", "fast", "ExplodingAgent")

        assert result == "Error: Sub-agent 'ExplodingAgent' failed: RuntimeError"

    async def test_parallel_batch_returns_error_strings_when_tier_resolution_fails(self):
        with patch(
            "source.services.skills_runtime.sub_agent._resolve_tier_model",
            side_effect=ValueError("missing model context"),
        ):
            results = await execute_sub_agents_parallel(
                [
                    {"instruction": "task one", "model_tier": "fast", "agent_name": "A"},
                    {"instruction": "task two", "model_tier": "smart", "agent_name": "B"},
                ]
            )

        assert len(results) == 2
        assert all("Failed to resolve sub-agent model tier" in result for result in results)
