from typing import Any

from mcp_servers.servers.video_watcher.video_watcher_descriptions import (
    WATCH_YOUTUBE_VIDEO_DESCRIPTION,
)


def _build_tool_definition(
    name: str, description: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description.strip(),
        "parameters": parameters,
    }


VIDEO_WATCHER_INLINE_TOOLS: list[dict[str, Any]] = [
    _build_tool_definition(
        "watch_youtube_video",
        WATCH_YOUTUBE_VIDEO_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "YouTube URL to watch",
                },
                "include_timestamps": {
                    "type": "boolean",
                    "description": "Prefix transcript lines with [MM:SS]",
                    "default": False,
                },
            },
            "required": ["url"],
        },
    ),
]

