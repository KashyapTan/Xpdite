from mcp_servers.servers.sub_agent.inline_tools import SUB_AGENT_INLINE_TOOLS
from mcp_servers.servers.terminal.inline_tools import TERMINAL_INLINE_TOOLS
from mcp_servers.servers.video_watcher.inline_tools import VIDEO_WATCHER_INLINE_TOOLS


def test_terminal_inline_tools_match_expected_names_and_required_fields():
    expected_names = [
        "get_environment",
        "run_command",
        "find_files",
        "request_session_mode",
        "end_session_mode",
        "send_input",
        "read_output",
        "kill_process",
    ]

    assert [tool["name"] for tool in TERMINAL_INLINE_TOOLS] == expected_names

    run_command = next(
        tool for tool in TERMINAL_INLINE_TOOLS if tool["name"] == "run_command"
    )
    assert run_command["parameters"]["required"] == ["command"]
    assert run_command["parameters"]["properties"]["background"]["default"] is False
    assert run_command["parameters"]["properties"]["shell"]["enum"] == [
        "auto",
        "cmd",
        "powershell",
        "bash",
        "sh",
    ]


def test_sub_agent_inline_tool_schema_matches_expected_shape():
    assert [tool["name"] for tool in SUB_AGENT_INLINE_TOOLS] == ["spawn_agent"]

    spawn_agent = SUB_AGENT_INLINE_TOOLS[0]
    assert spawn_agent["parameters"]["required"] == ["instruction"]
    assert spawn_agent["parameters"]["properties"]["model_tier"]["enum"] == [
        "fast",
        "smart",
        "self",
    ]


def test_video_watcher_inline_tool_schema_matches_expected_shape():
    assert [tool["name"] for tool in VIDEO_WATCHER_INLINE_TOOLS] == [
        "watch_youtube_video"
    ]
    watch_tool = VIDEO_WATCHER_INLINE_TOOLS[0]
    assert watch_tool["parameters"]["required"] == ["url"]
    assert (
        watch_tool["parameters"]["properties"]["include_timestamps"]["default"] is False
    )


def test_all_inline_tools_include_core_fields():
    for tool in (
        TERMINAL_INLINE_TOOLS + SUB_AGENT_INLINE_TOOLS + VIDEO_WATCHER_INLINE_TOOLS
    ):
        assert set(tool) == {"name", "description", "parameters"}
        assert tool["description"]
        assert tool["parameters"]["type"] == "object"
        assert "properties" in tool["parameters"]
