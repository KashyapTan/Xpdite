import os
from pathlib import Path

from mcp_servers.servers.description_format import build_tool_description

# --- Configuration (dynamic — works on any machine / OS) ---
USERNAME = os.getenv("USERNAME") or os.getenv("USER") or Path.home().name
BASE_PATH = os.path.abspath(str(Path.home()))


LIST_DIRECTORY_DESCRIPTION = build_tool_description(
    purpose="List the contents of a directory inside the filesystem sandbox.",
    use_when=(
        "You need to discover real paths, inspect folder structure, or verify a "
        "directory before using any other filesystem tool."
    ),
    inputs=(
        f"path = an absolute, relative, or home-relative directory path inside "
        f"{BASE_PATH}."
    ),
    returns="A list of up to 50 file or folder names sorted by most recently modified first, or a one-item error list.",
    notes=(
        "Call this first before read_file, write_file, create_folder, "
        f"move_file, or rename_file to verify real paths. Access is restricted "
        f"to {BASE_PATH} for user {USERNAME}."
    ),
)

READ_FILE_DESCRIPTION = build_tool_description(
    purpose="Read the content of a file inside the filesystem sandbox, supporting text, documents, and images with pagination for large files.",
    use_when=(
        "You need to inspect a text file, extract content from documents (PDF, DOCX, PPTX, XLSX, etc.), "
        "or view an image file."
    ),
    inputs=(
        f"path = the exact absolute, relative, or home-relative file path inside {BASE_PATH}; "
        "offset = optional character position to start reading from (default 0); "
        "max_chars = optional maximum characters to return (default 8000, max 100000)."
    ),
    returns=(
        "A JSON envelope with: content (the text slice), total_chars (full document size), offset, "
        "chars_returned, has_more (boolean), next_offset (for continuation), chunk_summary. "
        "On the first call (offset=0), also includes file_info with format, page_count, title, author, "
        "extracted_images (paths/dimensions for all embedded images), and warnings. "
        "For images (PNG, JPG, etc.): returns base64-encoded image data directly (no pagination). "
        "Returns an error string for unsupported formats (.doc, .ppt)."
    ),
    notes=(
        "For large files, check has_more - if true, call again with the provided next_offset to continue reading. "
        "Stop reading once you have found what you need. "
        "Embedded images appear as inline markers [IMAGE: absolute_path (WxH) - call read_file to view] in the text flow. "
        "Call read_file on an extracted image path to view it. "
        "Images cannot be paginated - passing offset > 0 for an image file returns an error."
    ),
)

WRITE_FILE_DESCRIPTION = build_tool_description(
    purpose="Create a file or replace an existing file's full contents.",
    use_when=(
        "You need to create a new text file or fully rewrite an existing file "
        "after checking its current state."
    ),
    inputs=(
        f"path = target absolute, relative, or home-relative file path inside "
        f"{BASE_PATH}; content = raw file text to write."
    ),
    returns="A success string with the number of characters written, or an error string.",
    notes=(
        "Call list_directory first, and call read_file before overwriting an "
        "existing file. WARNING: this fully overwrites existing files. Do not "
        "include markdown fences in content."
    ),
)

CREATE_FOLDER_DESCRIPTION = build_tool_description(
    purpose="Create a new folder inside an existing parent directory.",
    use_when=(
        "You need to set up a directory before writing files or organizing "
        "existing content."
    ),
    inputs=(
        f"path = the parent directory inside {BASE_PATH}; folder_name = the new "
        "folder name only."
    ),
    returns="A success string or an error string.",
    notes="Call list_directory first to verify the parent directory. Do not include the new folder name inside path.",
)

MOVE_FILE_DESCRIPTION = build_tool_description(
    purpose="Move a file or directory into a different destination folder.",
    use_when=(
        "You want to relocate an existing file or folder without changing its name."
    ),
    inputs=(
        f"source_path = existing file or folder inside {BASE_PATH}; "
        f"destination_folder = existing target directory inside {BASE_PATH}."
    ),
    returns="A success string or an error string.",
    notes="Call list_directory on both source and destination first. Use rename_file for same-folder renames.",
)

RENAME_FILE_DESCRIPTION = build_tool_description(
    purpose="Rename a file or directory without moving it to another folder.",
    use_when=(
        "You want to fix a filename, change a naming convention, or update an "
        "extension in place."
    ),
    inputs=(
        f"source_path = existing file or folder inside {BASE_PATH}; "
        "new_name = filename or folder name only, not a path."
    ),
    returns="A success string or an error string.",
    notes="Call list_directory first to confirm the source and check for name conflicts. Use move_file to change directories.",
)

GLOB_FILES_DESCRIPTION = build_tool_description(
    purpose="Find files and directories that match a glob pattern inside the filesystem sandbox.",
    use_when=(
        "You need structured file discovery and should use this instead of "
        "run_command with find, ls, dir, or shell glob expansion workflows."
    ),
    inputs=(
        "pattern = relative glob such as **/*.py or src/**/*.ts; "
        f"base_path = optional directory inside {BASE_PATH} to search from "
        "(defaults to the current directory); include_hidden = optional boolean "
        "for dotfiles and hidden directories."
    ),
    returns=(
        "A JSON string with matches (relative paths), total, truncated, and optional applied_limit metadata. "
        "Results are ordered by most recently modified first."
    ),
    notes=(
        "Results are capped at 500 matches. Version-control metadata directories such as .git are skipped automatically. "
        "If truncated is true, narrow the pattern or base_path and try again. This tool is sandboxed to "
        f"{BASE_PATH} for user {USERNAME}."
    ),
)

GREP_FILES_DESCRIPTION = build_tool_description(
    purpose="Search text files for a literal string or regex pattern inside the filesystem sandbox.",
    use_when=(
        "You need structured content search and should use this instead of "
        "run_command with grep, rg, ag, or similar terminal search commands."
    ),
    inputs=(
        "pattern = string or regex to search for; path = optional directory "
        f"inside {BASE_PATH} to search from (defaults to the current "
        "directory); file_glob = optional relative glob filter such as "
        "**/*.py; is_regex and case_sensitive = optional booleans; "
        "context_lines = optional integer up to 10; max_results = optional "
        "legacy content-mode cap; include_hidden = optional boolean; "
        "output_mode = optional content, files_with_matches, or count; "
        "head_limit = optional pagination size (0 means unlimited); "
        "offset = optional pagination offset."
    ),
    returns=(
        "A JSON string with structured search results. "
        "content mode returns matches with context lines; files_with_matches mode returns matching file paths; "
        "count mode returns per-file match counts. All modes include traversal stats, truncation metadata, pattern, and is_regex."
    ),
    notes=(
        "Binary files, files larger than 1 MB, and version-control metadata directories such as .git are skipped automatically and counted in the "
        "response when applicable. If truncated is true, narrow the path, file_glob, or pattern "
        "before retrying, or continue with offset/head_limit pagination."
    ),
)
