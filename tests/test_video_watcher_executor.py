from unittest.mock import AsyncMock, patch

import pytest

from source.services.media.video_watcher import VideoWatcherError
from source.mcp_integration.executors.video_watcher_executor import (
    VIDEO_WATCHER_TOOLS,
    execute_video_watcher_tool,
    is_video_watcher_tool,
)


class TestIsVideoWatcherTool:
    def test_known_tool_on_video_watcher_server(self):
        for tool in VIDEO_WATCHER_TOOLS:
            assert is_video_watcher_tool(tool, "video_watcher") is True

    def test_unknown_tool_or_wrong_server(self):
        assert is_video_watcher_tool("unknown_tool", "video_watcher") is False
        assert is_video_watcher_tool("watch_youtube_video", "terminal") is False


class TestExecuteVideoWatcherTool:
    @pytest.mark.asyncio
    async def test_missing_url_returns_error(self):
        result = await execute_video_watcher_tool(
            "watch_youtube_video", {}, "video_watcher"
        )
        assert result == "Error: url is required"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = await execute_video_watcher_tool(
            "unknown_tool", {"url": "https://youtu.be/abc"}, "video_watcher"
        )
        assert "Unknown video watcher tool" in result

    @pytest.mark.asyncio
    async def test_watch_youtube_video_success_passes_include_timestamps(self):
        with patch(
            "source.mcp_integration.executors.video_watcher_executor.video_watcher_service.watch_youtube_video",
            new=AsyncMock(return_value="ok"),
        ) as mock_watch:
            result = await execute_video_watcher_tool(
                "watch_youtube_video",
                {"url": "https://youtu.be/abc", "include_timestamps": True},
                "video_watcher",
            )

        assert result == "ok"
        mock_watch.assert_awaited_once_with(
            url="https://youtu.be/abc", include_timestamps=True
        )

    @pytest.mark.asyncio
    async def test_watch_youtube_video_wraps_service_errors(self):
        with patch(
            "source.mcp_integration.executors.video_watcher_executor.video_watcher_service.watch_youtube_video",
            new=AsyncMock(side_effect=VideoWatcherError("boom")),
        ):
            result = await execute_video_watcher_tool(
                "watch_youtube_video",
                {"url": "https://youtu.be/abc"},
                "video_watcher",
            )

        assert result.startswith("Error:")
