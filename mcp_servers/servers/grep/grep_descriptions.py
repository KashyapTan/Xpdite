from mcp_servers.servers.description_format import build_tool_description
from mcp_servers.servers.filesystem.sandbox import DEFAULT_BASE_PATH


BASE_PATH = DEFAULT_BASE_PATH


GREP_FILES_DESCRIPTION = build_tool_description(
    purpose="Search text files for a literal string or regex pattern inside the dedicated grep sandbox server.",
    use_when=(
        "You need structured content search and should use this instead of "
        "run_command with grep, rg, ag, Select-String, or similar terminal search commands."
    ),
    inputs=(
        "pattern = string or regex to search for; "
        f"path = optional file or directory inside {BASE_PATH} to search from "
        "(defaults to the current directory); "
        "file_glob = optional relative glob filter such as **/*.py; "
        "glob = optional alias for file_glob; "
        "type = optional file-type alias such as py, ts, js, md, json, powershell, or shell; "
        "is_regex, case_sensitive, include_hidden, and multiline = optional booleans; "
        "context_lines or context = optional integers up to 10 for content mode; "
        "output_mode = optional content, files_with_matches, or count (defaults to files_with_matches); "
        "head_limit = optional pagination size; offset = optional pagination offset; "
        "max_results = optional legacy content-mode cap."
    ),
    returns=(
        "A JSON string with structured search results. "
        "content mode returns matches with context lines; files_with_matches mode returns matching file paths; "
        "count mode returns per-file match counts. All modes include traversal stats and truncation metadata."
    ),
    notes=(
        "Binary files, files larger than 1 MB, and version-control metadata directories such as .git are skipped automatically when appropriate. "
        "Long output lines are truncated to keep tool output readable. "
        "If truncated is true, narrow the path, file_glob, type, or pattern, or continue with offset/head_limit pagination."
    ),
)
