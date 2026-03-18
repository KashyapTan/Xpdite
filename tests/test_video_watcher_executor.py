from source.mcp_integration.video_watcher_executor import (
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
    async def test_missing_url_returns_error(self):
        result = await execute_video_watcher_tool(
            "watch_youtube_video", {}, "video_watcher"
        )
        assert result == "Error: url is required"

    async def test_unknown_tool_returns_error(self):
        result = await execute_video_watcher_tool(
            "unknown_tool", {"url": "https://youtu.be/abc"}, "video_watcher"
        )
        assert "Unknown video watcher tool" in result

