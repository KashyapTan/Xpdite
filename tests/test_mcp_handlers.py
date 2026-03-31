"""Tests for source/mcp_integration/handlers.py."""

from unittest.mock import MagicMock, patch

import source.mcp_integration.handlers as handlers


class TestRetrieveRelevantTools:
    def test_returns_empty_when_manager_has_no_tools(self):
        with patch.object(handlers.mcp_manager, "has_tools", return_value=False):
            assert handlers.retrieve_relevant_tools("summarize this") == []

    def test_reads_settings_and_calls_retriever_with_openai_tool_schema(self):
        all_tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "search_web_pages"}},
        ]
        filtered = [all_tools[0]]
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = ['["read_file"]', "7"]

        with (
            patch.object(handlers.mcp_manager, "has_tools", return_value=True),
            patch.object(handlers.mcp_manager, "get_tools", return_value=all_tools),
            patch.object(
                handlers.retriever, "retrieve_tools", return_value=filtered
            ) as mock_retrieve,
            patch("source.database.db", db_mock),
        ):
            result = handlers.retrieve_relevant_tools("find config")

        assert result == filtered
        mock_retrieve.assert_called_once_with(
            query="find config",
            all_tools=all_tools,
            always_on=["read_file"],
            top_k=7,
        )

    def test_invalid_always_on_json_falls_back_to_empty_and_default_top_k(self):
        all_tools = [{"type": "function", "function": {"name": "read_file"}}]
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = ["{bad json", None]

        with (
            patch.object(handlers.mcp_manager, "has_tools", return_value=True),
            patch.object(handlers.mcp_manager, "get_tools", return_value=all_tools),
            patch.object(handlers.retriever, "retrieve_tools", return_value=all_tools) as mock_retrieve,
            patch("source.database.db", db_mock),
        ):
            result = handlers.retrieve_relevant_tools("find config")

        assert result == all_tools
        mock_retrieve.assert_called_once_with(
            query="find config",
            all_tools=all_tools,
            always_on=[],
            top_k=5,
        )
