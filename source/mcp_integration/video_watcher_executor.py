"""Inline execution entrypoint for video watcher MCP tools."""

from ..services.video_watcher import VideoWatcherError, video_watcher_service


VIDEO_WATCHER_TOOLS = {
    "watch_youtube_video",
}


def is_video_watcher_tool(fn_name: str, server_name: str) -> bool:
    """Check if a tool call should be handled inline by the video watcher service."""
    return server_name == "video_watcher" and fn_name in VIDEO_WATCHER_TOOLS


async def execute_video_watcher_tool(
    fn_name: str,
    fn_args: dict,
    server_name: str,
) -> str:
    """Execute a video watcher inline tool."""
    if fn_name == "watch_youtube_video":
        url = str(fn_args.get("url") or "").strip()
        include_timestamps = bool(fn_args.get("include_timestamps", False))
        if not url:
            return "Error: url is required"
        try:
            return await video_watcher_service.watch_youtube_video(
                url=url,
                include_timestamps=include_timestamps,
            )
        except VideoWatcherError as exc:
            return f"Error: {exc}"

    return f"Unknown video watcher tool: {fn_name}"

