"""Tests for source/mcp_integration/core/handlers.py."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


_HANDLERS_MODULE_CACHE = None


def _load_handlers_module(monkeypatch):
    """Load handlers.py under an alias to bypass circular import stubs."""
    global _HANDLERS_MODULE_CACHE
    if _HANDLERS_MODULE_CACHE is not None:
        return _HANDLERS_MODULE_CACHE

    root = pathlib.Path(__file__).resolve().parents[1]

    services_pkg = types.ModuleType("source.services")
    services_pkg.__path__ = [str(root / "source" / "services")]
    monkeypatch.setitem(sys.modules, "source.services", services_pkg)

    module_name = "source.mcp_integration.core.handlers_cov"
    module_path = root / "source" / "mcp_integration" / "core" / "handlers.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    _HANDLERS_MODULE_CACHE = module
    return module


@pytest.fixture()
def handlers_module(monkeypatch):
    return _load_handlers_module(monkeypatch)


class TestRetrieveRelevantTools:
    def test_returns_empty_when_manager_has_no_tools(self, handlers_module):
        with patch.object(handlers_module.mcp_manager, "has_tools", return_value=False):
            assert handlers_module.retrieve_relevant_tools("summarize this") == []

    def test_reads_db_settings_and_calls_retriever(self, handlers_module):
        all_tools = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "search_web_pages"}},
        ]
        filtered = [all_tools[0]]

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module.mcp_manager, "get_ollama_tools", return_value=all_tools
            ),
            patch.object(
                handlers_module.retriever, "retrieve_tools", return_value=filtered
            ) as mock_retrieve,
            patch(
                "source.infrastructure.database.db.get_setting",
                side_effect=["{bad json", "7"],
            ),
        ):
            result = handlers_module.retrieve_relevant_tools("find config")

        assert result == filtered
        mock_retrieve.assert_called_once_with(
            query="find config",
            all_tools=all_tools,
            always_on=[],
            top_k=7,
        )

    def test_invalid_top_k_falls_back_to_default(self, handlers_module):
        all_tools = [{"function": {"name": "read_file"}}]
        filtered = all_tools

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module.mcp_manager, "get_ollama_tools", return_value=all_tools
            ),
            patch.object(
                handlers_module.retriever, "retrieve_tools", return_value=filtered
            ) as mock_retrieve,
            patch(
                "source.infrastructure.database.db.get_setting",
                side_effect=[None, "not-an-int"],
            ),
        ):
            result = handlers_module.retrieve_relevant_tools("find config")

        assert result == filtered
        assert mock_retrieve.call_args.kwargs["top_k"] == 5


class TestTruncateResult:
    def test_truncates_large_result_with_suffix(self, handlers_module):
        with patch.object(handlers_module, "MAX_TOOL_RESULT_LENGTH", 10):
            result = handlers_module._truncate_result("abcdefghijklmnopqrstuvwxyz")

        assert result.startswith("abcdefghij")
        assert result.endswith("... [Output truncated due to length]")

    def test_keeps_small_result_unchanged(self, handlers_module):
        assert handlers_module._truncate_result("ok") == "ok"


class TestStreamToolFollowUp:
    @pytest.mark.asyncio
    async def test_streams_text_collects_tool_calls_and_token_stats(
        self, handlers_module
    ):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name="read_file", arguments='{"path":"README.md"}')
        )

        async def _fake_stream():
            yield SimpleNamespace(
                message=SimpleNamespace(
                    content="hello",
                    thinking="Let me think...",
                    tool_calls=None,
                ),
                done=False,
            )
            yield SimpleNamespace(
                message=SimpleNamespace(content=" world", tool_calls=[tool_call]),
                done=True,
                prompt_eval_count=4,
                eval_count=9,
            )

        fake_client = SimpleNamespace(chat=AsyncMock(return_value=_fake_stream()))

        with (
            patch.object(
                handlers_module, "broadcast_message", new=AsyncMock()
            ) as mock_bcast,
            patch.object(
                handlers_module, "is_current_request_cancelled", return_value=False
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
        ):
            (
                text,
                tool_calls,
                stats,
                thinking,
            ) = await handlers_module._stream_tool_follow_up(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"function": {"name": "read_file"}}],
                client=fake_client,
            )

        assert text == "hello world"
        assert thinking == "Let me think..."
        assert tool_calls == [
            {
                "name": "read_file",
                "args": {"path": "README.md"},
                "arg_error": None,
                "raw_args": '{"path":"README.md"}',
            }
        ]
        assert stats == {"prompt_eval_count": 4, "eval_count": 9}
        mock_bcast.assert_any_await("thinking_chunk", "Let me think...")
        mock_bcast.assert_any_await("thinking_complete", "")
        mock_bcast.assert_any_await("response_chunk", "hello")
        mock_bcast.assert_any_await("response_chunk", " world")

    @pytest.mark.asyncio
    async def test_stream_follow_up_error_broadcasts_error_message(
        self, handlers_module
    ):
        fake_client = SimpleNamespace(
            chat=AsyncMock(side_effect=RuntimeError("network"))
        )

        with (
            patch.object(
                handlers_module, "broadcast_message", new=AsyncMock()
            ) as mock_bcast,
            patch.object(
                handlers_module, "is_current_request_cancelled", return_value=False
            ),
        ):
            (
                text,
                tool_calls,
                stats,
                thinking,
            ) = await handlers_module._stream_tool_follow_up(
                messages=[],
                tools=[],
                client=fake_client,
            )

        assert text == ""
        assert thinking == ""
        assert tool_calls == []
        assert stats == {"prompt_eval_count": 0, "eval_count": 0}
        assert mock_bcast.await_count == 1
        assert mock_bcast.await_args.args[0] == "error"
        assert "Tool follow-up streaming error" in mock_bcast.await_args.args[1]


class TestHandleMcpToolCalls:
    @pytest.mark.asyncio
    async def test_returns_early_when_no_tools_registered(self, handlers_module):
        messages = [{"role": "user", "content": "hello"}]

        with patch.object(handlers_module.mcp_manager, "has_tools", return_value=False):
            (
                updated_messages,
                calls,
                precomputed,
            ) = await handlers_module.handle_mcp_tool_calls(
                messages,
                image_paths=[],
                client=SimpleNamespace(chat=AsyncMock()),
            )

        assert updated_messages == messages
        assert calls == []
        assert precomputed is None

    @pytest.mark.asyncio
    async def test_returns_none_when_detection_finds_no_tool_calls(
        self, handlers_module
    ):
        detection = SimpleNamespace(
            message=SimpleNamespace(content="plain response", tool_calls=[])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "read_file"}}],
            ),
            patch.object(
                handlers_module, "is_current_request_cancelled", return_value=False
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
        ):
            (
                updated_messages,
                calls,
                precomputed,
            ) = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "hello"}],
                image_paths=[],
                client=fake_client,
            )

        assert calls == []
        assert precomputed is None
        assert updated_messages == [{"role": "user", "content": "hello"}]

    @pytest.mark.asyncio
    async def test_executes_tool_loop_and_returns_precomputed_response(
        self, handlers_module
    ):
        bad_tool = SimpleNamespace(
            function=SimpleNamespace(name="bad_tool", arguments="{bad json")
        )
        good_tool = SimpleNamespace(
            function=SimpleNamespace(name="good_tool", arguments='{"value": 5}')
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(
                content="Need to run tools",
                thinking="Reason through tools",
                tool_calls=[bad_tool, good_tool],
            )
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        server_lookup = {"bad_tool": "filesystem", "good_tool": "filesystem"}

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "good_tool"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 20,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "Final answer",
                        [],
                        {"prompt_eval_count": 2, "eval_count": 3},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                side_effect=lambda name: server_lookup[name],
            ),
            patch.object(
                handlers_module.mcp_manager,
                "call_tool",
                new=AsyncMock(return_value="tool-output"),
            ) as mock_call_tool,
            patch.object(handlers_module, "is_terminal_tool", return_value=False),
            patch.object(handlers_module, "is_video_watcher_tool", return_value=False),
            patch.object(
                handlers_module, "broadcast_message", new=AsyncMock()
            ) as mock_bcast,
        ):
            (
                updated_messages,
                calls,
                precomputed,
            ) = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "do things"}],
                image_paths=[],
                client=fake_client,
            )

        assert precomputed is not None
        assert precomputed["already_streamed"] is True
        assert "Need to run tools" in precomputed["content"]
        assert "Final answer" in precomputed["content"]
        assert {
            "type": "thinking",
            "content": "Reason through tools",
        } in precomputed["interleaved_blocks"]
        assert precomputed["token_stats"] == {"prompt_eval_count": 2, "eval_count": 3}

        assert len(calls) == 2
        assert calls[0]["name"] == "bad_tool"
        assert "invalid arguments" in calls[0]["result"]
        assert calls[1] == {
            "name": "good_tool",
            "args": {"value": 5},
            "result": "tool-output",
            "server": "filesystem",
        }

        mock_call_tool.assert_awaited_once_with("good_tool", {"value": 5})
        assert any(msg.get("role") == "assistant" for msg in updated_messages)
        assert any(msg.get("role") == "tool" for msg in updated_messages)
        mock_bcast.assert_any_await("response_complete", "")
        token_call = [
            c for c in mock_bcast.await_args_list if c.args[0] == "token_usage"
        ]
        assert len(token_call) == 1
        assert json.loads(token_call[0].args[1]) == {
            "prompt_eval_count": 2,
            "eval_count": 3,
        }

    @pytest.mark.asyncio
    async def test_spawn_agent_calls_are_executed_in_parallel_batch(
        self, handlers_module, monkeypatch
    ):
        spawn_tc = SimpleNamespace(
            function=SimpleNamespace(
                name="spawn_agent",
                arguments='{"instruction":"summarize", "model_tier":"fast", "agent_name":"Worker"}',
            )
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(content="Delegating", tool_calls=[spawn_tc])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        sub_agent_module = types.ModuleType("source.services.skills_runtime.sub_agent")
        sub_agent_module.execute_sub_agents_parallel = AsyncMock(
            return_value=["parallel-result"]
        )
        monkeypatch.setitem(
            sys.modules, "source.services.skills_runtime.sub_agent", sub_agent_module
        )

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "spawn_agent"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 10,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                return_value="sub_agent",
            ),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "",
                        [],
                        {"prompt_eval_count": 0, "eval_count": 0},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "call_tool",
                new=AsyncMock(),
            ) as mock_call_tool,
            patch.object(handlers_module, "broadcast_message", new=AsyncMock()),
        ):
            _, calls, precomputed = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "delegate"}],
                image_paths=[],
                client=fake_client,
            )

        assert precomputed is not None
        assert len(calls) == 1
        assert calls[0]["name"] == "spawn_agent"
        assert calls[0]["result"] == "parallel-result"
        mock_call_tool.assert_not_awaited()
        sub_agent_module.execute_sub_agents_parallel.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_tools_are_intercepted(self, handlers_module):
        memory_tool = SimpleNamespace(
            function=SimpleNamespace(
                name="memread",
                arguments='{"path":"procedural/sqlite_fix.md"}',
            )
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(content="Checking memory", tool_calls=[memory_tool])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "memread"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 10,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "",
                        [],
                        {"prompt_eval_count": 0, "eval_count": 0},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                return_value="memory",
            ),
            patch.object(handlers_module, "is_terminal_tool", return_value=False),
            patch.object(handlers_module, "is_video_watcher_tool", return_value=False),
            patch.object(handlers_module, "is_memory_tool", return_value=True),
            patch.object(
                handlers_module,
                "execute_memory_tool",
                new=AsyncMock(return_value="raw memory"),
            ) as mock_execute,
            patch.object(
                handlers_module.mcp_manager,
                "call_tool",
                new=AsyncMock(),
            ) as mock_call_tool,
            patch.object(handlers_module, "broadcast_message", new=AsyncMock()),
        ):
            _, calls, precomputed = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "use memory"}],
                image_paths=[],
                client=fake_client,
            )

        assert precomputed is not None
        assert calls[0]["name"] == "memread"
        assert calls[0]["result"] == "raw memory"
        mock_execute.assert_awaited_once_with(
            "memread",
            {"path": "procedural/sqlite_fix.md"},
            "memory",
        )
        mock_call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_memcommit_args_are_redacted_in_broadcasts_and_persistence(
        self, handlers_module
    ):
        memory_tool = SimpleNamespace(
            function=SimpleNamespace(
                name="memcommit",
                arguments=(
                    '{"path":"profile/user_profile.md","title":"Profile","category":"profile",'
                    '"importance":1,"tags":["profile"],"abstract":"Sensitive summary",'
                    '"body":"Sensitive body"}'
                ),
            )
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(content="Saving memory", tool_calls=[memory_tool])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "memcommit"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 10,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "",
                        [],
                        {"prompt_eval_count": 0, "eval_count": 0},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                return_value="memory",
            ),
            patch.object(handlers_module, "is_terminal_tool", return_value=False),
            patch.object(handlers_module, "is_video_watcher_tool", return_value=False),
            patch.object(handlers_module, "is_memory_tool", return_value=True),
            patch.object(
                handlers_module,
                "execute_memory_tool",
                new=AsyncMock(
                    return_value="Created memory at 'profile/user_profile.md'."
                ),
            ),
            patch.object(
                handlers_module, "broadcast_message", new=AsyncMock()
            ) as mock_bcast,
        ):
            _, calls, _ = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "save memory"}],
                image_paths=[],
                client=fake_client,
            )

        assert calls[0]["args"] == {
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
            for call in mock_bcast.await_args_list
            if call.args[0] == "tool_call"
        ]
        assert any(
            payload["args"].get("body") == "[REDACTED]"
            and payload["args"].get("abstract") == "[REDACTED]"
            for payload in tool_call_payloads
        )

    @pytest.mark.asyncio
    async def test_memory_tool_failures_are_contained(self, handlers_module):
        memory_tool = SimpleNamespace(
            function=SimpleNamespace(
                name="memread",
                arguments='{"path":"procedural/sqlite_fix.md"}',
            )
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(content="Checking memory", tool_calls=[memory_tool])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "memread"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 10,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "",
                        [],
                        {"prompt_eval_count": 0, "eval_count": 0},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                return_value="memory",
            ),
            patch.object(handlers_module, "is_terminal_tool", return_value=False),
            patch.object(handlers_module, "is_video_watcher_tool", return_value=False),
            patch.object(handlers_module, "is_memory_tool", return_value=True),
            patch.object(
                handlers_module,
                "execute_memory_tool",
                new=AsyncMock(side_effect=OSError("disk failure")),
            ),
            patch.object(handlers_module, "broadcast_message", new=AsyncMock()),
        ):
            _, calls, _ = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "use memory"}],
                image_paths=[],
                client=fake_client,
            )

        assert calls[0]["name"] == "memread"
        assert calls[0]["result"] == (
            "System error: tool execution failed. See server logs for details."
        )

    @pytest.mark.asyncio
    async def test_dict_tool_result_is_serialized_as_json(self, handlers_module):
        tool = SimpleNamespace(
            function=SimpleNamespace(name="read_file", arguments='{"path":"app.py"}')
        )
        detection = SimpleNamespace(
            message=SimpleNamespace(content="Need file", tool_calls=[tool])
        )
        fake_client = SimpleNamespace(chat=AsyncMock(return_value=detection))

        dict_result = {
            "content": "abcd",
            "total_chars": 10,
            "offset": 0,
            "chars_returned": 4,
            "has_more": True,
            "next_offset": 4,
            "chunk_summary": "Showing characters 0-4 of 10 (40%)",
        }

        with (
            patch.object(handlers_module.mcp_manager, "has_tools", return_value=True),
            patch.object(
                handlers_module,
                "retrieve_relevant_tools",
                return_value=[{"function": {"name": "read_file"}}],
            ),
            patch.object(
                handlers_module,
                "is_current_request_cancelled",
                side_effect=[False] * 10,
            ),
            patch.object(handlers_module, "get_current_model", return_value="qwen3:8b"),
            patch.object(
                handlers_module,
                "_stream_tool_follow_up",
                new=AsyncMock(
                    return_value=(
                        "",
                        [],
                        {"prompt_eval_count": 0, "eval_count": 0},
                        "",
                    )
                ),
            ),
            patch.object(
                handlers_module.mcp_manager,
                "get_tool_server_name",
                return_value="filesystem",
            ),
            patch.object(handlers_module, "is_terminal_tool", return_value=False),
            patch.object(handlers_module, "is_video_watcher_tool", return_value=False),
            patch.object(handlers_module, "is_memory_tool", return_value=False),
            patch.object(
                handlers_module.mcp_manager,
                "call_tool",
                new=AsyncMock(return_value=dict_result),
            ),
            patch.object(handlers_module, "broadcast_message", new=AsyncMock()),
        ):
            _, calls, _ = await handlers_module.handle_mcp_tool_calls(
                [{"role": "user", "content": "read file"}],
                image_paths=[],
                client=fake_client,
            )

        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        parsed = json.loads(calls[0]["result"])
        assert parsed["content"] == "abcd"
        assert parsed["has_more"] is True
        assert parsed["next_offset"] == 4
