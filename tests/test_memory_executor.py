"""Tests for source/mcp_integration/executors/memory_executor.py."""

from unittest.mock import AsyncMock, patch

import pytest

from source.mcp_integration.executors.memory_executor import (
    _format_memory_listing,
    execute_memory_tool,
    is_memory_tool,
)


class TestIsMemoryTool:
    def test_matches_memory_server_tools(self):
        assert is_memory_tool("memlist", "memory") is True
        assert is_memory_tool("memread", "memory") is True
        assert is_memory_tool("memcommit", "memory") is True

    def test_rejects_unknown_tools_or_servers(self):
        assert is_memory_tool("unknown", "memory") is False
        assert is_memory_tool("memlist", "filesystem") is False


class TestFormatMemoryListing:
    def test_empty_listing_with_and_without_folder(self):
        assert _format_memory_listing([], None) == "No memories found."
        assert _format_memory_listing([], "notes") == "No memories found in 'notes'."

    def test_groups_by_folder_and_includes_parse_warning(self):
        formatted = _format_memory_listing(
            [
                {
                    "folder": "notes",
                    "path": "notes/a.md",
                    "abstract": "alpha",
                    "parse_warning": "bad yaml",
                },
                {
                    "folder": ".",
                    "path": "root.md",
                    "abstract": "root",
                },
            ],
            "notes",
        )

        assert "Memory listing for 'notes':" in formatted
        assert "[(root)]" in formatted
        assert "[notes]" in formatted
        assert "- notes/a.md :: alpha [warning: bad yaml]" in formatted
        assert "- root.md :: root" in formatted


class TestExecuteMemoryTool:
    @pytest.mark.asyncio
    async def test_memlist_formats_listing(self):
        memories = [
            {"folder": "notes", "path": "notes/one.md", "abstract": "first"},
        ]
        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            new_callable=AsyncMock,
            return_value=memories,
        ) as mock_run:
            result = await execute_memory_tool("memlist", {"folder": "notes"}, "memory")

        assert "Memory listing for 'notes':" in result
        assert "notes/one.md" in result
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memread_requires_path(self):
        result = await execute_memory_tool("memread", {}, "memory")
        assert result == "Error: path is required"

    @pytest.mark.asyncio
    async def test_memread_missing_file_returns_friendly_error(self):
        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            result = await execute_memory_tool(
                "memread", {"path": "notes/missing.md"}, "memory"
            )

        assert result == "Error: memory 'notes/missing.md' was not found"

    @pytest.mark.asyncio
    async def test_memcommit_rejects_non_list_tags(self):
        result = await execute_memory_tool(
            "memcommit",
            {"path": "notes/a.md", "tags": "not-a-list"},
            "memory",
        )
        assert result == "Error: tags must be an array of strings"

    @pytest.mark.asyncio
    async def test_memcommit_reports_created_memory(self):
        async_run = AsyncMock(
            side_effect=[
                FileNotFoundError(),
                {"path": "notes/a.md"},
            ]
        )
        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            async_run,
        ):
            result = await execute_memory_tool(
                "memcommit",
                {"path": "notes/a.md", "title": "A", "tags": ["x"]},
                "memory",
            )

        assert result == "Created memory at 'notes/a.md'."

    @pytest.mark.asyncio
    async def test_memcommit_reports_updated_memory(self):
        async_run = AsyncMock(
            side_effect=[
                {"raw_text": "existing"},
                {"path": "notes/a.md"},
            ]
        )
        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            async_run,
        ):
            result = await execute_memory_tool(
                "memcommit",
                {"path": "notes/a.md", "title": "A", "tags": []},
                "memory",
            )

        assert result == "Updated memory at 'notes/a.md'."

    @pytest.mark.asyncio
    async def test_value_error_and_oserror_are_sanitized(self):
        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            new_callable=AsyncMock,
            side_effect=ValueError("bad path"),
        ):
            assert (
                await execute_memory_tool("memread", {"path": "x"}, "memory")
                == "Error: bad path"
            )

        with patch(
            "source.mcp_integration.executors.memory_executor.run_in_thread",
            new_callable=AsyncMock,
            side_effect=OSError("disk issue"),
        ):
            assert (
                await execute_memory_tool("memread", {"path": "x"}, "memory")
                == "Error: memory operation failed. See server logs for details."
            )

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_clear_message(self):
        result = await execute_memory_tool("noop", {}, "memory")
        assert result == "Unknown memory tool: noop"
