"""Tests for LLM router — parse_provider and route_chat dispatch."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from source.llm.router import is_local_ollama_model, parse_provider
import source.mcp_integration.manager as mcp_manager_module


# ------------------------------------------------------------------
# parse_provider
# ------------------------------------------------------------------


class TestParseProvider:
    def test_anthropic_prefix(self):
        provider, model = parse_provider("anthropic/claude-sonnet-4-20250514")
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-20250514"

    def test_openai_prefix(self):
        provider, model = parse_provider("openai/gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_gemini_prefix(self):
        provider, model = parse_provider("gemini/gemini-2.5-pro")
        assert provider == "gemini"
        assert model == "gemini-2.5-pro"

    def test_openrouter_prefix(self):
        provider, model = parse_provider("openrouter/anthropic/claude-3-5-sonnet")
        assert provider == "openrouter"
        assert model == "anthropic/claude-3-5-sonnet"

    def test_ollama_fallback_no_prefix(self):
        provider, model = parse_provider("qwen3-vl:8b-instruct")
        assert provider == "ollama"
        assert model == "qwen3-vl:8b-instruct"

    def test_unknown_prefix_falls_to_ollama(self):
        provider, model = parse_provider("mistral/mistral-7b")
        assert provider == "ollama"
        # model should be the full original string since "mistral" is not a known provider
        assert model == "mistral/mistral-7b"

    def test_model_with_slashes(self):
        # E.g. "openai/ft:gpt-4o:my-org:custom"
        provider, model = parse_provider("openai/ft:gpt-4o:my-org:custom")
        assert provider == "openai"
        assert model == "ft:gpt-4o:my-org:custom"


class TestIsLocalOllamaModel:
    def test_local_ollama_model_is_local(self):
        assert is_local_ollama_model("qwen3-vl:8b-instruct") is True

    def test_cloud_ollama_model_is_not_local(self):
        assert is_local_ollama_model("qwen3.5:397b-cloud") is False

    def test_cloud_ollama_model_with_explicit_prefix_is_not_local(self):
        assert is_local_ollama_model("ollama/qwen3.5:397b-cloud") is False

    def test_cloud_ollama_colon_tag_with_explicit_prefix_is_not_local(self):
        assert is_local_ollama_model("ollama/qwen3-coder-next:cloud") is False

    def test_cloud_ollama_suffix_check_is_case_insensitive(self):
        assert is_local_ollama_model("qwen3.5:397b-CLOUD") is False

    def test_cloud_ollama_colon_tag_is_not_local(self):
        assert is_local_ollama_model("qwen3-coder-next:cloud") is False

    def test_cloud_ollama_colon_tag_is_case_insensitive(self):
        assert is_local_ollama_model("qwen3-coder-next:CLOUD") is False

    def test_openai_model_is_not_local_ollama(self):
        assert is_local_ollama_model("openai/gpt-4o") is False

    def test_whitespace_around_provider_model_is_not_local_ollama(self):
        assert is_local_ollama_model("  openai/gpt-4o  ") is False


# ------------------------------------------------------------------
# route_chat — ensure correct provider dispatch
# ------------------------------------------------------------------


# All lazy imports in route_chat need to be patched at their source module.
_ROUTE_PATCHES = {
    "source.database.db": MagicMock(
        get_setting=MagicMock(return_value=None),
    ),
    "source.llm.prompt.build_system_prompt": MagicMock(return_value="system"),
    "source.mcp_integration.skill_injector.get_skills_to_inject": MagicMock(
        return_value=[]
    ),
    "source.mcp_integration.skill_injector.build_skills_prompt_block": MagicMock(
        return_value=""
    ),
    "source.core.state.app_state": MagicMock(
        stop_streaming=False, current_request=None
    ),
}


class TestRouteChat:
    @pytest.mark.asyncio
    async def test_route_chat_calls_ollama_for_local_model(self):
        """Ollama models should be dispatched to stream_ollama_chat."""
        mock_stream = AsyncMock(
            return_value=("reply", {"prompt_eval_count": 1, "eval_count": 2}, [], None)
        )

        patches = {**_ROUTE_PATCHES}
        patches["source.llm.ollama_provider.stream_ollama_chat"] = mock_stream

        with patch.dict("sys.modules", {}):
            ctx = {k: patch(k, v) for k, v in patches.items()}
            for p in ctx.values():
                p.start()
            try:
                from source.llm.router import route_chat

                result = await route_chat("llama3:8b", "Hello", [], [])
                mock_stream.assert_awaited_once()
                assert result[0] == "reply"
            finally:
                for p in ctx.values():
                    p.stop()

    @pytest.mark.asyncio
    async def test_route_chat_reuses_prefiltered_tools_for_ollama(self):
        """Ollama path should reuse already retrieved tools from the router."""
        mock_stream = AsyncMock(
            return_value=("reply", {"prompt_eval_count": 1, "eval_count": 2}, [], None)
        )
        retrieved_tools = [{"function": {"name": "read_file"}}]

        mock_mcp = MagicMock()
        mock_mcp.has_tools.return_value = True

        patches = {**_ROUTE_PATCHES}
        patches["source.llm.ollama_provider.stream_ollama_chat"] = mock_stream
        patches["source.mcp_integration.handlers.retrieve_relevant_tools"] = MagicMock(
            return_value=retrieved_tools
        )

        ctx = {k: patch(k, v) for k, v in patches.items()}
        for p in ctx.values():
            p.start()
        try:
            with patch.object(mcp_manager_module, "mcp_manager", mock_mcp):
                from source.llm.router import route_chat

                await route_chat("llama3:8b", "Hello", [], [])

                mock_stream.assert_awaited_once()
                call = mock_stream.await_args
                assert call is not None
                assert call.kwargs.get("prefiltered_tools") == retrieved_tools
        finally:
            for p in ctx.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_route_chat_calls_cloud_for_anthropic(self):
        """Anthropic-prefixed models should be dispatched to stream_cloud_chat."""
        mock_stream = AsyncMock(
            return_value=(
                "cloud reply",
                {"prompt_eval_count": 10, "eval_count": 20},
                [],
                None,
            )
        )
        mock_km = MagicMock()
        mock_km.get_api_key.return_value = "sk-test-key"

        mock_mcp = MagicMock()
        mock_mcp.has_tools.return_value = False

        patches = {**_ROUTE_PATCHES}
        patches["source.llm.cloud_provider.stream_cloud_chat"] = mock_stream
        patches["source.llm.key_manager.key_manager"] = mock_km

        ctx = {k: patch(k, v) for k, v in patches.items()}
        for p in ctx.values():
            p.start()
        try:
            with patch.object(mcp_manager_module, "mcp_manager", mock_mcp):
                from source.llm.router import route_chat

                result = await route_chat(
                    "anthropic/claude-sonnet-4-20250514", "Hello", [], []
                )
                mock_stream.assert_awaited_once()
                assert result[0] == "cloud reply"
        finally:
            for p in ctx.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_route_chat_errors_on_missing_api_key(self):
        """Cloud provider without API key should return error."""
        mock_km = MagicMock()
        mock_km.get_api_key.return_value = None

        mock_mcp = MagicMock()
        mock_mcp.has_tools.return_value = False

        mock_broadcast = AsyncMock()

        patches = {**_ROUTE_PATCHES}
        patches["source.llm.key_manager.key_manager"] = mock_km
        patches["source.core.connection.broadcast_message"] = mock_broadcast

        ctx = {k: patch(k, v) for k, v in patches.items()}
        for p in ctx.values():
            p.start()
        try:
            with patch.object(mcp_manager_module, "mcp_manager", mock_mcp):
                from source.llm.router import route_chat

                result = await route_chat("openai/gpt-4o", "Hi", [], [])
                # Should return an error message
                assert "Error" in result[0] or "error" in result[0].lower()
                # Should have broadcast an error
                mock_broadcast.assert_awaited_once()
        finally:
            for p in ctx.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_route_chat_builds_profile_injection_when_enabled(self):
        mock_stream = AsyncMock(
            return_value=("reply", {"prompt_eval_count": 1, "eval_count": 2}, [], None)
        )
        mock_build_prompt = MagicMock(return_value="system with profile")
        mock_db = MagicMock()
        mock_db.get_setting.side_effect = lambda key: {
            "system_prompt_template": None,
            "memory_profile_auto_inject": "true",
        }.get(key)

        patches = {**_ROUTE_PATCHES}
        patches["source.database.db"] = mock_db
        patches["source.llm.ollama_provider.stream_ollama_chat"] = mock_stream
        patches["source.llm.prompt.build_system_prompt"] = mock_build_prompt
        patches["source.llm.prompt.build_memory_prompt_block"] = MagicMock(
            return_value="\nMEMORY BLOCK\n"
        )
        patches["source.llm.prompt.build_user_profile_block"] = MagicMock(
            return_value="\n## User Profile\n\nProfile body\n"
        )
        patches["source.core.thread_pool.run_in_thread"] = AsyncMock(
            return_value={"body": "Profile body"}
        )
        patches["source.config.MEMORY_PROFILE_FILE"] = MagicMock(
            exists=MagicMock(return_value=True)
        )
        mock_mcp = MagicMock(has_tools=MagicMock(return_value=False))

        ctx = {k: patch(k, v) for k, v in patches.items()}
        for p in ctx.values():
            p.start()
        try:
            with patch.object(mcp_manager_module, "mcp_manager", mock_mcp):
                from source.llm.router import route_chat

                result = await route_chat("llama3:8b", "Hello", [], [])
                assert result[0] == "reply"
                mock_build_prompt.assert_called_once_with(
                    skills_block="",
                    memory_block="\nMEMORY BLOCK\n",
                    user_profile_block="\n## User Profile\n\nProfile body\n",
                    template=None,
                )
        finally:
            for p in ctx.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_route_chat_skips_profile_injection_when_disabled(self):
        mock_stream = AsyncMock(
            return_value=("reply", {"prompt_eval_count": 1, "eval_count": 2}, [], None)
        )
        mock_build_prompt = MagicMock(return_value="system without profile")
        mock_db = MagicMock()
        mock_db.get_setting.side_effect = lambda key: {
            "system_prompt_template": None,
            "memory_profile_auto_inject": "false",
        }.get(key)

        patches = {**_ROUTE_PATCHES}
        patches["source.database.db"] = mock_db
        patches["source.llm.ollama_provider.stream_ollama_chat"] = mock_stream
        patches["source.llm.prompt.build_system_prompt"] = mock_build_prompt
        patches["source.llm.prompt.build_memory_prompt_block"] = MagicMock(
            return_value="\nMEMORY BLOCK\n"
        )
        patches["source.llm.prompt.build_user_profile_block"] = MagicMock(
            return_value="\n## User Profile\n\nProfile body\n"
        )
        patches["source.core.thread_pool.run_in_thread"] = AsyncMock(
            return_value={"body": "Profile body"}
        )
        patches["source.config.MEMORY_PROFILE_FILE"] = MagicMock(
            exists=MagicMock(return_value=True)
        )
        mock_mcp = MagicMock(has_tools=MagicMock(return_value=False))

        ctx = {k: patch(k, v) for k, v in patches.items()}
        for p in ctx.values():
            p.start()
        try:
            with patch.object(mcp_manager_module, "mcp_manager", mock_mcp):
                from source.llm.router import route_chat

                result = await route_chat("llama3:8b", "Hello", [], [])
                assert result[0] == "reply"
                mock_build_prompt.assert_called_once_with(
                    skills_block="",
                    memory_block="\nMEMORY BLOCK\n",
                    user_profile_block="",
                    template=None,
                )
                patches["source.core.thread_pool.run_in_thread"].assert_not_awaited()
        finally:
            for p in ctx.values():
                p.stop()
