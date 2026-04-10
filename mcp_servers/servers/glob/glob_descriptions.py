from mcp_servers.servers.description_format import build_tool_description
from mcp_servers.servers.filesystem.sandbox import DEFAULT_BASE_PATH


BASE_PATH = DEFAULT_BASE_PATH


GLOB_FILES_DESCRIPTION = build_tool_description(
    purpose="Find files and directories that match a glob pattern inside the dedicated glob sandbox server.",
    use_when=(
        "You need structured file discovery and should use this instead of "
        "run_command with find, ls, dir, or shell glob expansion workflows."
    ),
    inputs=(
        "pattern = relative glob such as **/*.py or src/**/*.{ts,tsx}; "
        f"path = optional directory inside {BASE_PATH} to search from "
        "(defaults to the current directory); "
        "base_path = legacy alias for path; "
        "include_hidden = optional boolean for dotfiles and hidden directories; "
        "exclude = optional comma/space separated relative glob list to omit; "
        "head_limit = optional pagination size (default 100, 0 means unlimited up to the scan cap); "
        "offset = optional pagination offset."
    ),
    returns=(
        "A JSON string with matches (relative paths), total, available_matches, truncated, and optional pagination metadata. "
        "Results are ordered by most recently modified first."
    ),
    notes=(
        "Version-control metadata directories such as .git are skipped automatically. "
        "Results are collected up to an internal scan cap of 1000 matches and paged after sorting. "
        "If truncated is true, narrow the pattern, path, or exclude list and retry."
    ),
)
