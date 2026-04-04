import glob as globlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import regex as regexlib
from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.filesystem.filesystem_descriptions import (
    BASE_PATH,
    CREATE_FOLDER_DESCRIPTION,
    GLOB_FILES_DESCRIPTION,
    GREP_FILES_DESCRIPTION,
    LIST_DIRECTORY_DESCRIPTION,
    MOVE_FILE_DESCRIPTION,
    READ_FILE_DESCRIPTION,
    RENAME_FILE_DESCRIPTION,
    WRITE_FILE_DESCRIPTION,
)

# File extraction imports (lazy loaded to avoid import overhead if not used)
_file_extractor = None


def _get_file_extractor():
    """Lazy-load the file extractor to avoid import overhead."""
    global _file_extractor
    if _file_extractor is None:
        from source.services.file_extractor import FileExtractor

        _file_extractor = FileExtractor()
    return _file_extractor


# File extension sets for routing
_IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
    }
)

_EXTRACTION_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xlsm",
        ".xls",
        ".odt",
        ".odp",
        ".ods",
        ".rtf",
    }
)

_ARCHIVE_EXTENSIONS = frozenset({".zip"})

_LEGACY_UNSUPPORTED = frozenset({".doc", ".ppt"})

mcp = FastMCP("Filesystem Tools")

_GLOB_RESULTS_CAP = 500
_GREP_DEFAULT_CONTEXT_LINES = 2
_GREP_MAX_CONTEXT_LINES = 10
_GREP_DEFAULT_MAX_RESULTS = 100
_GREP_MAX_RESULTS = 500
_GREP_MAX_FILE_BYTES = 1_000_000
_GREP_MAX_FILES = 10_000
_REGEX_MATCH_TIMEOUT_SECONDS = 0.05
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")


def _get_safe_path(path: str) -> str:
    """
    Resolve a path and ensure it stays within BASE_PATH.

    This prevents path traversal and symlink escapes outside the sandbox root.
    """
    expanded_path = os.path.expanduser(path)
    target_path = os.path.realpath(expanded_path)
    safe_base = os.path.realpath(BASE_PATH)

    try:
        common_root = os.path.commonpath([safe_base, target_path])
    except ValueError as exc:
        raise PermissionError(
            f"Access denied: Path '{path}' resolves outside the allowed directory."
        ) from exc

    if safe_base != common_root:
        raise PermissionError(
            f"Access denied: Path '{path}' resolves outside the allowed directory."
        )

    return target_path


def _json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def _build_error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _to_display_path(relative_path: str | Path) -> str:
    path_obj = relative_path if isinstance(relative_path, Path) else Path(relative_path)
    display_path = path_obj.as_posix()
    return display_path or "."


def _has_hidden_part(relative_path: str | Path) -> bool:
    parts = (
        relative_path.parts
        if isinstance(relative_path, Path)
        else Path(relative_path).parts
    )
    return any(part.startswith(".") for part in parts if part not in ("", ".", ".."))


def _is_within_search_root(candidate_path: str, search_root: str) -> bool:
    resolved_candidate = os.path.realpath(candidate_path)
    resolved_root = os.path.realpath(search_root)
    try:
        return resolved_root == os.path.commonpath([resolved_root, resolved_candidate])
    except ValueError:
        return False


def _validate_relative_glob_pattern(pattern: str, field_name: str) -> str | None:
    normalized = pattern.replace("\\", "/")
    if os.path.isabs(pattern):
        return (
            f"{field_name} must be relative to the search root, not an absolute path."
        )
    if _WINDOWS_DRIVE_PATTERN.match(normalized):
        return f"{field_name} must not be drive-qualified."

    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        return f"{field_name} must not contain parent-directory segments."
    return None


def _glob_payload(
    matches: list[str],
    *,
    truncated: bool,
    error: dict[str, str] | None = None,
    truncation_reason: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "matches": matches,
        "total": len(matches),
        "truncated": truncated,
    }
    if truncation_reason is not None:
        payload["truncation_reason"] = truncation_reason
    if error is not None:
        payload["error"] = error
    return _json_response(payload)


def _grep_payload(
    matches: list[dict[str, Any]],
    *,
    pattern: str,
    is_regex: bool,
    files_searched: int,
    files_traversed: int,
    truncated: bool,
    skipped_binary_files: int,
    skipped_large_files: int,
    skipped_permission_denied_files: int,
    error: dict[str, str] | None = None,
    truncation_reason: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "matches": matches,
        "total_matches": len(matches),
        "files_searched": files_searched,
        "files_traversed": files_traversed,
        "skipped_binary_files": skipped_binary_files,
        "skipped_large_files": skipped_large_files,
        "skipped_permission_denied_files": skipped_permission_denied_files,
        "truncated": truncated,
        "pattern": pattern,
        "is_regex": is_regex,
    }
    if truncation_reason is not None:
        payload["truncation_reason"] = truncation_reason
    if error is not None:
        payload["error"] = error
    return _json_response(payload)


@mcp.tool(description=LIST_DIRECTORY_DESCRIPTION)
def list_directory(path: str) -> list[str]:
    try:
        clean_path = _get_safe_path(path)
        # Use os.scandir for efficiency (avoids repeated stat calls)
        entries_with_mtime: list[tuple[str, float]] = []
        with os.scandir(clean_path) as it:
            for entry in it:
                try:
                    # DirEntry.stat() caches stat info, much faster than os.stat()
                    mtime = entry.stat().st_mtime
                    entries_with_mtime.append((entry.name, mtime))
                except (OSError, PermissionError):
                    # Skip entries we can't stat
                    continue
        # Sort by mtime descending (most recent first)
        entries_with_mtime.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in entries_with_mtime][:50]

    except FileNotFoundError:
        return [f"Error: The directory '{path}' does not exist."]

    except PermissionError as e:
        return [f"Error: {str(e)}"]

    except NotADirectoryError:
        return [
            f"Error: '{path}' is a file, not a directory. Use read_file to view it."
        ]

    except Exception as e:
        return [f"Error: An unexpected error occurred: {str(e)}"]


@mcp.tool(description=READ_FILE_DESCRIPTION)
def read_file(path: str) -> str | dict[str, Any]:
    """
    Read file content with support for multiple formats.

    Returns:
        - str: For text files, extracted document content, or error messages
        - dict: For image files, returns {"type": "image", "media_type": ..., "data": ..., ...}
    """
    try:
        clean_path = _get_safe_path(path)
        ext = Path(clean_path).suffix.lower()

        # Image files - return dict for LLM image content block
        if ext in _IMAGE_EXTENSIONS:
            extractor = _get_file_extractor()
            result = extractor._load_image_file(clean_path)
            if result.data:
                return result.to_dict()
            return f"Error: Failed to load image '{path}'"

        # Legacy unsupported formats - return actionable error
        if ext in _LEGACY_UNSUPPORTED:
            return (
                f"Error: Legacy format '{ext}' is not supported. "
                "Please resave as .docx or .pptx for Word/PowerPoint documents."
            )

        # Document formats requiring extraction
        if ext in _EXTRACTION_EXTENSIONS:
            extractor = _get_file_extractor()
            result = extractor._extract_document(clean_path, ext)
            return extractor.format_result_for_tool(result)

        # Archive files - list contents
        if ext in _ARCHIVE_EXTENSIONS:
            extractor = _get_file_extractor()
            result = extractor._extract_zip(clean_path)
            return extractor.format_result_for_tool(result)

        # Text-native files and unknown formats - read as UTF-8
        with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    except FileNotFoundError:
        return f"Error: The file '{path}' was not found. Please check the path using list_directory."

    except PermissionError as e:
        return f"Error: {str(e)}"

    except IsADirectoryError:
        return f"Error: '{path}' is a directory, not a file. Use list_directory to see its contents."

    except Exception as e:
        return f"Error: An unexpected error occurred reading '{path}': {str(e)}"


@mcp.tool(description=WRITE_FILE_DESCRIPTION)
def write_file(path: str, content: str) -> str:
    try:
        clean_path = _get_safe_path(path)
        parent_dir = os.path.dirname(clean_path)
        if not os.path.exists(parent_dir):
            return f"Error: The directory '{parent_dir}' does not exist. Please use create_folder first."

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Success: Successfully wrote {len(content)} characters to '{path}'."

    except PermissionError as e:
        return f"Error: {str(e)}"

    except IsADirectoryError:
        return f"Error: '{path}' is a directory. You cannot write content to a directory path."

    except OSError as e:
        return f"Error: System error while writing to '{path}': {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=CREATE_FOLDER_DESCRIPTION)
def create_folder(path: str, folder_name: str) -> str:
    try:
        full_path = os.path.join(path, folder_name)
        clean_path = _get_safe_path(full_path)

        if os.path.exists(clean_path):
            return f"Error: The folder '{folder_name}' already exists at '{path}'."

        os.makedirs(clean_path)
        return f"Success: Folder '{folder_name}' created successfully at '{path}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while creating folder '{folder_name}': {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=MOVE_FILE_DESCRIPTION)
def move_file(source_path: str, destination_folder: str) -> str:
    try:
        clean_source = _get_safe_path(source_path)
        clean_dest_folder = _get_safe_path(destination_folder)

        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."

        if not os.path.isdir(clean_dest_folder):
            return f"Error: The destination '{destination_folder}' is not a valid directory."

        filename = os.path.basename(clean_source)
        clean_full_destination = os.path.join(clean_dest_folder, filename)
        clean_full_destination = _get_safe_path(clean_full_destination)

        if os.path.exists(clean_full_destination):
            return f"Error: A file already exists at '{clean_full_destination}'. Move aborted."

        shutil.move(clean_source, clean_full_destination)
        return f"Success: Moved '{filename}' to '{destination_folder}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while moving file: {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=RENAME_FILE_DESCRIPTION)
def rename_file(source_path: str, new_name: str) -> str:
    try:
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return f"Error: 'new_name' must be a filename only, not a path. separators ('{os.sep}') are not allowed."

        clean_source = _get_safe_path(source_path)
        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."

        parent_dir = os.path.dirname(clean_source)
        clean_new_path = os.path.join(parent_dir, new_name)
        clean_new_path = _get_safe_path(clean_new_path)

        if os.path.exists(clean_new_path):
            return f"Error: A file already exists with the name '{new_name}' in this directory. Rename aborted."

        os.rename(clean_source, clean_new_path)
        return f"Success: Renamed '{os.path.basename(source_path)}' to '{new_name}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while renaming file: {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=GLOB_FILES_DESCRIPTION)
def glob_files(
    pattern: str,
    base_path: str = ".",
    include_hidden: bool = False,
) -> str:
    if not pattern.strip():
        return _glob_payload(
            [],
            truncated=False,
            error=_build_error("invalid_pattern", "pattern must not be empty."),
        )

    pattern_error = _validate_relative_glob_pattern(pattern, "pattern")
    if pattern_error is not None:
        return _glob_payload(
            [],
            truncated=False,
            error=_build_error(
                "invalid_pattern",
                pattern_error,
            ),
        )

    try:
        clean_base = _get_safe_path(base_path or ".")
        if not os.path.exists(clean_base):
            return _glob_payload(
                [],
                truncated=False,
                error=_build_error(
                    "path_not_found", f"base_path '{base_path}' does not exist."
                ),
            )
        if not os.path.isdir(clean_base):
            return _glob_payload(
                [],
                truncated=False,
                error=_build_error(
                    "not_a_directory",
                    f"base_path '{base_path}' is not a directory.",
                ),
            )

        matches: list[str] = []
        seen: set[str] = set()
        truncated = False

        for relative_match in globlib.iglob(
            pattern,
            root_dir=clean_base,
            recursive=True,
            include_hidden=include_hidden,
        ):
            if relative_match in ("", "."):
                continue

            relative_path = Path(relative_match)
            if not include_hidden and _has_hidden_part(relative_path):
                continue

            candidate_path = os.path.join(clean_base, relative_match)
            try:
                clean_candidate = _get_safe_path(candidate_path)
            except PermissionError:
                continue

            if not _is_within_search_root(clean_candidate, clean_base):
                continue

            display_path = _to_display_path(relative_path)
            if display_path in seen:
                continue

            seen.add(display_path)
            matches.append(display_path)
            if len(matches) >= _GLOB_RESULTS_CAP:
                truncated = True
                break

        matches.sort()
        return _glob_payload(
            matches,
            truncated=truncated,
            truncation_reason="result_limit" if truncated else None,
        )
    except PermissionError as exc:
        return _glob_payload(
            [],
            truncated=False,
            error=_build_error("sandbox_violation", str(exc)),
        )
    except OSError as exc:
        return _glob_payload(
            [],
            truncated=False,
            error=_build_error("filesystem_error", str(exc)),
        )


@mcp.tool(description=GREP_FILES_DESCRIPTION)
def grep_files(
    pattern: str,
    path: str = ".",
    file_glob: str = "**/*",
    is_regex: bool = False,
    case_sensitive: bool = True,
    context_lines: int = _GREP_DEFAULT_CONTEXT_LINES,
    max_results: int = _GREP_DEFAULT_MAX_RESULTS,
    include_hidden: bool = False,
) -> str:
    if not pattern.strip():
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error("invalid_pattern", "pattern must not be empty."),
        )

    if context_lines < 0:
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error(
                "invalid_context_lines",
                "context_lines must be zero or greater.",
            ),
        )

    if max_results < 1:
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error(
                "invalid_max_results",
                "max_results must be greater than zero.",
            ),
        )

    effective_context_lines = min(context_lines, _GREP_MAX_CONTEXT_LINES)
    effective_max_results = min(max_results, _GREP_MAX_RESULTS)
    effective_file_glob = file_glob or "**/*"

    file_glob_error = _validate_relative_glob_pattern(effective_file_glob, "file_glob")
    if file_glob_error is not None:
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error(
                "invalid_file_glob",
                file_glob_error,
            ),
        )

    try:
        clean_root = _get_safe_path(path or ".")
        if not os.path.exists(clean_root):
            return _grep_payload(
                [],
                pattern=pattern,
                is_regex=is_regex,
                files_searched=0,
                files_traversed=0,
                truncated=False,
                skipped_binary_files=0,
                skipped_large_files=0,
                skipped_permission_denied_files=0,
                error=_build_error("path_not_found", f"path '{path}' does not exist."),
            )
        if not os.path.isdir(clean_root):
            return _grep_payload(
                [],
                pattern=pattern,
                is_regex=is_regex,
                files_searched=0,
                files_traversed=0,
                truncated=False,
                skipped_binary_files=0,
                skipped_large_files=0,
                skipped_permission_denied_files=0,
                error=_build_error(
                    "not_a_directory", f"path '{path}' is not a directory."
                ),
            )

        if is_regex:
            flags = 0 if case_sensitive else regexlib.IGNORECASE
            try:
                matcher = regexlib.compile(pattern, flags)
            except regexlib.error as exc:
                return _grep_payload(
                    [],
                    pattern=pattern,
                    is_regex=is_regex,
                    files_searched=0,
                    files_traversed=0,
                    truncated=False,
                    skipped_binary_files=0,
                    skipped_large_files=0,
                    skipped_permission_denied_files=0,
                    error=_build_error("invalid_regex", str(exc)),
                )

            def line_matches(line: str) -> bool:
                return (
                    matcher.search(line, timeout=_REGEX_MATCH_TIMEOUT_SECONDS)
                    is not None
                )
        else:
            needle = pattern if case_sensitive else pattern.lower()

            def line_matches(line: str) -> bool:
                haystack = line if case_sensitive else line.lower()
                return needle in haystack

        matches: list[dict[str, Any]] = []
        files_searched = 0
        files_traversed = 0
        skipped_binary_files = 0
        skipped_large_files = 0
        skipped_permission_denied_files = 0
        truncated = False
        truncation_reason: str | None = None
        seen_files: set[str] = set()

        for relative_match in globlib.iglob(
            effective_file_glob,
            root_dir=clean_root,
            recursive=True,
            include_hidden=include_hidden,
        ):
            if relative_match in ("", "."):
                continue

            relative_path = Path(relative_match)
            if not include_hidden and _has_hidden_part(relative_path):
                continue

            candidate_path = os.path.join(clean_root, relative_match)
            try:
                clean_candidate = _get_safe_path(candidate_path)
            except PermissionError:
                continue

            if not _is_within_search_root(clean_candidate, clean_root):
                continue

            if not os.path.isfile(clean_candidate):
                continue

            display_path = _to_display_path(relative_path)
            if display_path in seen_files:
                continue

            seen_files.add(display_path)
            files_traversed += 1
            if files_traversed > _GREP_MAX_FILES:
                truncated = True
                truncation_reason = "file_scan_cap"
                break

            try:
                if os.path.getsize(clean_candidate) > _GREP_MAX_FILE_BYTES:
                    skipped_large_files += 1
                    continue
            except (PermissionError, OSError):
                skipped_permission_denied_files += 1
                continue

            try:
                with open(clean_candidate, "r", encoding="utf-8") as handle:
                    lines = handle.read().splitlines()
            except UnicodeDecodeError:
                skipped_binary_files += 1
                continue
            except (PermissionError, OSError):
                skipped_permission_denied_files += 1
                continue

            files_searched += 1
            for line_number, line in enumerate(lines, start=1):
                try:
                    is_match = line_matches(line)
                except TimeoutError:
                    return _grep_payload(
                        matches,
                        pattern=pattern,
                        is_regex=is_regex,
                        files_searched=files_searched,
                        files_traversed=files_traversed,
                        truncated=True,
                        skipped_binary_files=skipped_binary_files,
                        skipped_large_files=skipped_large_files,
                        skipped_permission_denied_files=skipped_permission_denied_files,
                        error=_build_error(
                            "regex_timeout",
                            "Regex search exceeded the safety time limit. Narrow the pattern or use a simpler regex.",
                        ),
                        truncation_reason="regex_timeout",
                    )

                if not is_match:
                    continue

                start_index = max(0, line_number - 1 - effective_context_lines)
                end_index = min(len(lines), line_number + effective_context_lines)
                matches.append(
                    {
                        "file": display_path,
                        "line": line_number,
                        "match": line,
                        "context_before": lines[start_index : line_number - 1],
                        "context_after": lines[line_number:end_index],
                    }
                )

                if len(matches) >= effective_max_results:
                    truncated = True
                    truncation_reason = "max_results"
                    break

            if truncated and truncation_reason == "max_results":
                break

        return _grep_payload(
            matches,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=files_searched,
            files_traversed=files_traversed,
            truncated=truncated,
            skipped_binary_files=skipped_binary_files,
            skipped_large_files=skipped_large_files,
            skipped_permission_denied_files=skipped_permission_denied_files,
            truncation_reason=truncation_reason,
        )
    except PermissionError as exc:
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error("sandbox_violation", str(exc)),
        )
    except OSError as exc:
        return _grep_payload(
            [],
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=_build_error("filesystem_error", str(exc)),
        )


if __name__ == "__main__":
    mcp.run()
