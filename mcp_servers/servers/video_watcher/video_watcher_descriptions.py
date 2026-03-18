from mcp_servers.servers.description_format import build_tool_description


WATCH_YOUTUBE_VIDEO_DESCRIPTION = build_tool_description(
    purpose=(
        "Fetch and understand a YouTube video by returning metadata and a full transcript."
    ),
    use_when=(
        "The user provides a YouTube URL or asks questions about a specific video. "
        "Use this tool before summarizing or reasoning about video content."
    ),
    inputs=(
        "url (required YouTube video URL) and include_timestamps (optional, defaults "
        "to false, prefixes transcript lines with [MM:SS])."
    ),
    returns=(
        "A structured text block containing title, channel, duration, URL, truncated "
        "description, and transcript text suitable for direct LLM reasoning."
    ),
    notes=(
        "Captions are fetched first (fast path). If captions are unavailable, this "
        "tool may request explicit user approval before downloading audio and running "
        "Whisper transcription."
    ),
)

