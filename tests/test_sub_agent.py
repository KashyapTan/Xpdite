"""Tests for source/services/sub_agent.py — tier resolution, tool filtering, local detection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


# We need to import after conftest stubs the circular import
from source.services.sub_agent import (
    _resolve_tier_model,
    _is_local_ollama,
    _uses_ollama_client,
    _get_sub_agent_tools,
    _EXCLUDED_TOOLS,
    _run_cloud_sub_agent,
    execute_sub_agent,
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

    def test_no_slash_no_cloud_is_local(self):
        assert _is_local_ollama("llama3.2") is True


# ---------------------------------------------------------------------------
# _resolve_tier_model
# ---------------------------------------------------------------------------


class TestResolveTierModel:
    @patch("source.services.sub_agent.get_current_model", return_value="anthropic/claude-sonnet-4-20250514")
    @patch("source.services.sub_agent.db")
    def test_self_tier_returns_current_model(self, mock_db, mock_model):
        result = _resolve_tier_model("self")
        assert result == "anthropic/claude-sonnet-4-20250514"
        # self tier should never check DB
        mock_db.get_setting.assert_not_called()

    @patch("source.services.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.sub_agent.db")
    def test_fast_tier_with_no_override_returns_current(self, mock_db, mock_model):
        mock_db.get_setting.return_value = None
        result = _resolve_tier_model("fast")
        assert result == "openai/gpt-4o"

    @patch("source.services.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.sub_agent.db")
    def test_fast_tier_with_override_returns_override(self, mock_db, mock_model):
        mock_db.get_setting.return_value = "gemini/gemini-2.5-flash"
        result = _resolve_tier_model("fast")
        assert result == "gemini/gemini-2.5-flash"

    @patch("source.services.sub_agent.get_current_model", return_value="openai/gpt-4o")
    @patch("source.services.sub_agent.db")
    def test_smart_tier_with_empty_override_returns_current(self, mock_db, mock_model):
        mock_db.get_setting.return_value = "  "
        result = _resolve_tier_model("smart")
        assert result == "openai/gpt-4o"

    @patch("source.services.sub_agent.get_current_model", return_value=None)
    @patch("source.services.sub_agent.db")
    def test_fallback_to_app_state_when_no_context_var(self, mock_db, mock_model):
        mock_db.get_setting.return_value = None
        with patch("source.core.state.app_state") as mock_app:
            mock_app.selected_model = "llama3.2"
            result = _resolve_tier_model("fast")
            assert result == "llama3.2"


# ---------------------------------------------------------------------------
# _get_sub_agent_tools — tool filtering
# ---------------------------------------------------------------------------


class TestGetSubAgentTools:
    @patch("source.mcp_integration.manager.mcp_manager")
    def test_returns_none_when_no_tools(self, mock_manager):
        mock_manager.has_tools.return_value = False
        assert _get_sub_agent_tools("read the file") is None

    @patch("source.mcp_integration.handlers.retrieve_relevant_tools")
    @patch("source.mcp_integration.manager.mcp_manager")
    def test_excludes_terminal_and_spawn_agent(self, mock_manager, mock_retrieve):
        mock_manager.has_tools.return_value = True
        mock_retrieve.return_value = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "run_command"}},
            {"function": {"name": "spawn_agent"}},
            {"function": {"name": "search_web_pages"}},
        ]
        result = _get_sub_agent_tools("test instruction")
        names = [t["function"]["name"] for t in result]
        assert "read_file" in names
        assert "search_web_pages" in names
        assert "run_command" not in names
        assert "spawn_agent" not in names

    @patch("source.mcp_integration.handlers.retrieve_relevant_tools")
    @patch("source.mcp_integration.manager.mcp_manager")
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
            "get_environment", "find_files",
        }
        assert terminal_tools.issubset(_EXCLUDED_TOOLS)

    def test_contains_spawn_agent(self):
        assert "spawn_agent" in _EXCLUDED_TOOLS


# ---------------------------------------------------------------------------
# _run_cloud_sub_agent — direct cloud call behavior
# ---------------------------------------------------------------------------


class TestRunCloudSubAgent:
    @patch("source.services.sub_agent.is_current_request_cancelled", return_value=False)
    @patch("source.services.sub_agent.litellm.get_model_info", return_value={})
    @patch("source.services.sub_agent.litellm.acompletion", new_callable=AsyncMock)
    @patch("source.llm.key_manager.key_manager.get_api_key", return_value="or-test-key")
    async def test_openrouter_passes_api_key_directly(
        self, _mock_key, mock_acompletion, _mock_model_info, _mock_cancelled
    ):
        mock_acompletion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
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


# ---------------------------------------------------------------------------
# execute_sub_agent — integration-level with mocked LLM
# ---------------------------------------------------------------------------


class TestExecuteSubAgent:
    @patch("source.services.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.sub_agent._resolve_tier_model", return_value="anthropic/claude-sonnet-4-20250514")
    @patch("source.services.sub_agent._run_cloud_sub_agent", new_callable=AsyncMock)
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
        # Should have broadcast calling + complete
        assert mock_broadcast.call_count == 2

    @patch("source.services.sub_agent.broadcast_message", new_callable=AsyncMock)
    @patch("source.services.sub_agent._get_sub_agent_tools", return_value=None)
    @patch("source.services.sub_agent._resolve_tier_model", return_value="llama3.2")
    @patch("source.services.sub_agent._run_ollama_sub_agent", new_callable=AsyncMock)
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
