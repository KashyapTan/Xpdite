import glob as globlib
import os
from pathlib import Path
from typing import Any, TypeVar

import regex as regexlib
from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.filesystem.sandbox import (
    DEFAULT_BASE_PATH,
    build_error,
    get_safe_path,
    is_within_search_root,
    json_response,
    path_matches_glob,
    safe_mtime,
    should_skip_relative_path,
    split_glob_patterns,
    to_display_path,
    validate_relative_glob_pattern,
)
from mcp_servers.servers.grep.grep_descriptions import GREP_FILES_DESCRIPTION


mcp = FastMCP("Grep Tools")

BASE_PATH = DEFAULT_BASE_PATH

_GREP_DEFAULT_CONTEXT_LINES = 2
_GREP_MAX_CONTEXT_LINES = 10
_GREP_DEFAULT_MAX_RESULTS = 100
_GREP_MAX_RESULTS = 500
_GREP_MAX_FILE_BYTES = 1_000_000
_GREP_MAX_FILES = 10_000
_GREP_DEFAULT_HEAD_LIMIT = 250
_REGEX_MATCH_TIMEOUT_SECONDS = 0.05
_GREP_MAX_OUTPUT_LINE_CHARS = 500
_T = TypeVar("_T")

_TYPE_EXTENSIONS = {
    "py": (".py", ".pyi"),
    "python": (".py", ".pyi"),
    "js": (".js", ".mjs", ".cjs"),
    "javascript": (".js", ".mjs", ".cjs"),
    "jsx": (".jsx",),
    "ts": (".ts", ".tsx", ".mts", ".cts"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "tsx": (".tsx",),
    "json": (".json", ".jsonc"),
    "yaml": (".yaml", ".yml"),
    "yml": (".yaml", ".yml"),
    "md": (".md", ".mdx"),
    "markdown": (".md", ".mdx"),
    "html": (".html", ".htm"),
    "css": (".css", ".scss", ".sass", ".less"),
    "shell": (".sh", ".bash", ".zsh", ".ksh"),
    "sh": (".sh", ".bash", ".zsh", ".ksh"),
    "powershell": (".ps1", ".psm1", ".psd1"),
    "ps1": (".ps1", ".psm1", ".psd1"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "c": (".c", ".h"),
    "cpp": (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"),
    "ruby": (".rb",),
    "rb": (".rb",),
    "php": (".php", ".phtml"),
    "sql": (".sql",),
    "xml": (".xml",),
    "toml": (".toml",),
    "ini": (".ini", ".cfg", ".conf"),
}


def _grep_payload(
    matches: list[dict[str, Any]] | None,
    *,
    mode: str,
    pattern: str,
    is_regex: bool,
    files_searched: int,
    files_traversed: int,
    truncated: bool,
    skipped_binary_files: int,
    skipped_large_files: int,
    skipped_permission_denied_files: int,
    files: list[str] | None = None,
    counts: list[dict[str, Any]] | None = None,
    applied_limit: int | None = None,
    applied_offset: int | None = None,
    error: dict[str, str] | None = None,
    truncation_reason: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "mode": mode,
        "files_searched": files_searched,
        "files_traversed": files_traversed,
        "skipped_binary_files": skipped_binary_files,
        "skipped_large_files": skipped_large_files,
        "skipped_permission_denied_files": skipped_permission_denied_files,
        "truncated": truncated,
        "pattern": pattern,
        "is_regex": is_regex,
    }
    if matches is not None:
        payload["matches"] = matches
        payload["total_matches"] = len(matches)
    if files is not None:
        payload["files"] = files
        payload["total_files"] = len(files)
    if counts is not None:
        payload["counts"] = counts
        payload["total_files"] = len(counts)
        payload["total_matches"] = sum(item.get("count", 0) for item in counts)
    if applied_limit is not None:
        payload["applied_limit"] = applied_limit
    if applied_offset:
        payload["applied_offset"] = applied_offset
    if truncation_reason is not None:
        payload["truncation_reason"] = truncation_reason
    if error is not None:
        payload["error"] = error
    return json_response(payload)


def _apply_offset_limit(
    items: list[_T],
    *,
    offset: int,
    limit: int | None,
) -> tuple[list[_T], bool, int | None]:
    sliced = items[offset:] if offset else items
    if limit is None or limit == 0:
        return sliced, False, None
    truncated = len(sliced) > limit
    return sliced[:limit], truncated, limit if truncated else None


def _truncate_output_line(line: str) -> str:
    if len(line) <= _GREP_MAX_OUTPUT_LINE_CHARS:
        return line
    return line[: _GREP_MAX_OUTPUT_LINE_CHARS - 3] + "..."


def _normalize_glob_filter(
    file_glob: str,
    glob_value: str | None,
) -> tuple[list[str] | None, dict[str, str] | None]:
    normalized_glob = (glob_value or "").strip()
    normalized_file_glob = (file_glob or "").strip() or "**/*"

    if normalized_glob and normalized_file_glob not in {"**/*", normalized_glob}:
        return None, build_error(
            "invalid_file_glob",
            "Use either glob or file_glob, not two different glob filters.",
        )

    combined = normalized_glob or normalized_file_glob
    patterns = split_glob_patterns(combined) or ["**/*"]
    for pattern in patterns:
        error = validate_relative_glob_pattern(pattern, "file_glob")
        if error is not None:
            return None, build_error("invalid_file_glob", error)
    return patterns, None


def _normalize_type_filter(
    type_name: str | None,
) -> tuple[tuple[str, ...] | None, dict[str, str] | None]:
    if type_name is None:
        return None, None

    normalized = type_name.strip().lower()
    if not normalized:
        return None, None

    extensions = _TYPE_EXTENSIONS.get(normalized)
    if extensions is None:
        return None, build_error(
            "invalid_type",
            "Unsupported type filter. Try one of: py, ts, js, md, json, powershell.",
        )

    return extensions, None


def _iter_candidate_files(
    *,
    clean_root: str,
    include_hidden: bool,
    glob_patterns: list[str],
    type_extensions: tuple[str, ...] | None,
) -> tuple[list[tuple[str, str]], bool]:
    candidates: list[tuple[str, str]] = []
    seen_files: set[str] = set()
    truncated = False

    for pattern in glob_patterns:
        for relative_match in globlib.iglob(
            pattern,
            root_dir=clean_root,
            recursive=True,
            include_hidden=include_hidden,
        ):
            if relative_match in ("", "."):
                continue

            relative_path = Path(relative_match)
            if should_skip_relative_path(relative_path, include_hidden=include_hidden):
                continue

            candidate_path = os.path.join(clean_root, relative_match)
            try:
                clean_candidate = get_safe_path(candidate_path, BASE_PATH)
            except PermissionError:
                continue

            if not is_within_search_root(clean_candidate, clean_root):
                continue
            if not os.path.isfile(clean_candidate):
                continue

            display_path = to_display_path(relative_path)
            if display_path in seen_files:
                continue

            if type_extensions and not display_path.lower().endswith(type_extensions):
                continue

            seen_files.add(display_path)
            candidates.append((display_path, clean_candidate))
            if len(candidates) >= _GREP_MAX_FILES:
                truncated = True
                return candidates, truncated

    return candidates, truncated


def _build_multiline_match_records(
    text: str,
    matcher: regexlib.Pattern,
    *,
    display_path: str,
    context_lines: int,
) -> tuple[list[dict[str, Any]], int]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []

    for match in matcher.finditer(text, timeout=_REGEX_MATCH_TIMEOUT_SECONDS):
        start_offset, end_offset = match.span()
        start_line_index = text.count("\n", 0, start_offset)
        end_line_index = text.count("\n", 0, end_offset)
        start_context = max(0, start_line_index - context_lines)
        end_context = min(len(lines), end_line_index + 1 + context_lines)

        records.append(
            {
                "file": display_path,
                "line": start_line_index + 1,
                "end_line": end_line_index + 1,
                "match": _truncate_output_line(match.group(0)),
                "context_before": [
                    _truncate_output_line(line)
                    for line in lines[start_context:start_line_index]
                ],
                "context_after": [
                    _truncate_output_line(line)
                    for line in lines[end_line_index + 1 : end_context]
                ],
            }
        )

    return records, len(records)


@mcp.tool(description=GREP_FILES_DESCRIPTION)
def grep_files(
    pattern: str,
    path: str = ".",
    file_glob: str = "**/*",
    glob: str | None = None,
    is_regex: bool = False,
    case_sensitive: bool = True,
    context_lines: int = _GREP_DEFAULT_CONTEXT_LINES,
    context: int | None = None,
    max_results: int = _GREP_DEFAULT_MAX_RESULTS,
    include_hidden: bool = False,
    output_mode: str = "files_with_matches",
    head_limit: int | None = None,
    offset: int = 0,
    type: str | None = None,
    multiline: bool = False,
) -> str:
    if not pattern.strip():
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error("invalid_pattern", "pattern must not be empty."),
        )

    if context_lines < 0:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error(
                "invalid_context_lines",
                "context_lines must be zero or greater.",
            ),
        )

    if context is not None and context < 0:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error("invalid_context", "context must be zero or greater."),
        )

    if max_results < 1:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error(
                "invalid_max_results",
                "max_results must be greater than zero.",
            ),
        )

    if output_mode not in {"content", "files_with_matches", "count"}:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error(
                "invalid_output_mode",
                "output_mode must be one of: content, files_with_matches, count.",
            ),
        )

    if head_limit is not None and head_limit < 0:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error(
                "invalid_head_limit",
                "head_limit must be zero or greater.",
            ),
        )

    if offset < 0:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error("invalid_offset", "offset must be zero or greater."),
        )

    if multiline and not is_regex:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error(
                "invalid_multiline_mode",
                "multiline requires is_regex=true.",
            ),
        )

    effective_context_lines = min(
        context if context is not None else context_lines,
        _GREP_MAX_CONTEXT_LINES,
    )
    effective_max_results = min(max_results, _GREP_MAX_RESULTS)
    default_head_limit = (
        effective_max_results if output_mode == "content" else _GREP_DEFAULT_HEAD_LIMIT
    )
    effective_head_limit = default_head_limit if head_limit is None else head_limit
    pagination_limit = None if effective_head_limit == 0 else effective_head_limit
    required_result_count = (
        None if pagination_limit is None else offset + pagination_limit
    )

    glob_patterns, glob_error = _normalize_glob_filter(file_glob, glob)
    if glob_error is not None:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=glob_error,
        )

    type_extensions, type_error = _normalize_type_filter(type)
    if type_error is not None:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=type_error,
        )

    try:
        clean_target = get_safe_path(path or ".", BASE_PATH)
        if not os.path.exists(clean_target):
            return _grep_payload(
                [],
                mode=output_mode,
                pattern=pattern,
                is_regex=is_regex,
                files_searched=0,
                files_traversed=0,
                truncated=False,
                skipped_binary_files=0,
                skipped_large_files=0,
                skipped_permission_denied_files=0,
                error=build_error("path_not_found", f"path '{path}' does not exist."),
            )

        if is_regex:
            flags = 0 if case_sensitive else regexlib.IGNORECASE
            if multiline:
                flags |= regexlib.MULTILINE | regexlib.DOTALL
            try:
                matcher = regexlib.compile(pattern, flags)
            except regexlib.error as exc:
                return _grep_payload(
                    [],
                    mode=output_mode,
                    pattern=pattern,
                    is_regex=is_regex,
                    files_searched=0,
                    files_traversed=0,
                    truncated=False,
                    skipped_binary_files=0,
                    skipped_large_files=0,
                    skipped_permission_denied_files=0,
                    error=build_error("invalid_regex", str(exc)),
                )
        else:
            matcher = None
            needle = pattern if case_sensitive else pattern.lower()

        matches: list[dict[str, Any]] = []
        matched_files_with_mtime: list[tuple[str, float]] = []
        match_counts_with_mtime: list[tuple[str, int, float]] = []
        files_searched = 0
        files_traversed = 0
        skipped_binary_files = 0
        skipped_large_files = 0
        skipped_permission_denied_files = 0
        truncated = False
        truncation_reason: str | None = None

        if os.path.isfile(clean_target):
            display_path = os.path.basename(clean_target)
            if (
                glob_patterns
                and not any(path_matches_glob(display_path, item) for item in glob_patterns)
            ) or (
                type_extensions and not display_path.lower().endswith(type_extensions)
            ):
                candidate_files: list[tuple[str, str]] = []
            else:
                candidate_files = [(display_path, clean_target)]
        else:
            candidate_files, scan_cap_hit = _iter_candidate_files(
                clean_root=clean_target,
                include_hidden=include_hidden,
                glob_patterns=glob_patterns or ["**/*"],
                type_extensions=type_extensions,
            )
            if scan_cap_hit:
                truncated = True
                truncation_reason = "file_scan_cap"

        for display_path, clean_candidate in candidate_files:
            files_traversed += 1

            try:
                if os.path.getsize(clean_candidate) > _GREP_MAX_FILE_BYTES:
                    skipped_large_files += 1
                    continue
            except (PermissionError, OSError):
                skipped_permission_denied_files += 1
                continue

            try:
                with open(clean_candidate, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except UnicodeDecodeError:
                skipped_binary_files += 1
                continue
            except (PermissionError, OSError):
                skipped_permission_denied_files += 1
                continue

            files_searched += 1

            if multiline and matcher is not None:
                try:
                    file_matches, matched_count_for_file = _build_multiline_match_records(
                        text,
                        matcher,
                        display_path=display_path,
                        context_lines=effective_context_lines,
                    )
                except TimeoutError:
                    return _grep_payload(
                        matches,
                        mode=output_mode,
                        pattern=pattern,
                        is_regex=is_regex,
                        files_searched=files_searched,
                        files_traversed=files_traversed,
                        truncated=True,
                        skipped_binary_files=skipped_binary_files,
                        skipped_large_files=skipped_large_files,
                        skipped_permission_denied_files=skipped_permission_denied_files,
                        error=build_error(
                            "regex_timeout",
                            "Regex search exceeded the safety time limit. Narrow the pattern or use a simpler regex.",
                        ),
                        truncation_reason="regex_timeout",
                    )

                if matched_count_for_file == 0:
                    continue

                if output_mode == "files_with_matches":
                    matched_files_with_mtime.append(
                        (display_path, safe_mtime(clean_candidate))
                    )
                elif output_mode == "count":
                    match_counts_with_mtime.append(
                        (display_path, matched_count_for_file, safe_mtime(clean_candidate))
                    )
                else:
                    matches.extend(file_matches)

                if (
                    required_result_count is not None
                    and (
                        (output_mode == "content" and len(matches) >= required_result_count)
                        or (
                            output_mode == "files_with_matches"
                            and len(matched_files_with_mtime) >= required_result_count
                        )
                        or (
                            output_mode == "count"
                            and len(match_counts_with_mtime) >= required_result_count
                        )
                    )
                ):
                    truncated = True
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "default_limit"
                    )
                    break
                continue

            lines = text.splitlines()
            matched_count_for_file = 0
            for line_number, line in enumerate(lines, start=1):
                try:
                    if matcher is not None:
                        is_match = (
                            matcher.search(line, timeout=_REGEX_MATCH_TIMEOUT_SECONDS)
                            is not None
                        )
                    else:
                        haystack = line if case_sensitive else line.lower()
                        is_match = needle in haystack
                except TimeoutError:
                    return _grep_payload(
                        matches,
                        mode=output_mode,
                        pattern=pattern,
                        is_regex=is_regex,
                        files_searched=files_searched,
                        files_traversed=files_traversed,
                        truncated=True,
                        skipped_binary_files=skipped_binary_files,
                        skipped_large_files=skipped_large_files,
                        skipped_permission_denied_files=skipped_permission_denied_files,
                        error=build_error(
                            "regex_timeout",
                            "Regex search exceeded the safety time limit. Narrow the pattern or use a simpler regex.",
                        ),
                        truncation_reason="regex_timeout",
                    )

                if not is_match:
                    continue

                matched_count_for_file += 1
                if output_mode == "files_with_matches":
                    matched_files_with_mtime.append(
                        (display_path, safe_mtime(clean_candidate))
                    )
                    break
                if output_mode == "count":
                    continue

                start_index = max(0, line_number - 1 - effective_context_lines)
                end_index = min(len(lines), line_number + effective_context_lines)
                matches.append(
                    {
                        "file": display_path,
                        "line": line_number,
                        "match": _truncate_output_line(line),
                        "context_before": [
                            _truncate_output_line(item)
                            for item in lines[start_index : line_number - 1]
                        ],
                        "context_after": [
                            _truncate_output_line(item)
                            for item in lines[line_number:end_index]
                        ],
                    }
                )

                if (
                    required_result_count is not None
                    and len(matches) >= required_result_count
                ):
                    truncated = True
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "max_results"
                    )
                    break

            if output_mode == "count" and matched_count_for_file > 0:
                match_counts_with_mtime.append(
                    (display_path, matched_count_for_file, safe_mtime(clean_candidate))
                )
                if (
                    required_result_count is not None
                    and len(match_counts_with_mtime) >= required_result_count
                ):
                    truncated = True
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "default_limit"
                    )
                    break

            if output_mode == "files_with_matches" and matched_count_for_file > 0:
                if (
                    required_result_count is not None
                    and len(matched_files_with_mtime) >= required_result_count
                ):
                    truncated = True
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "default_limit"
                    )
                    break

            if truncated and truncation_reason in {"max_results", "head_limit", "default_limit"}:
                break

        if output_mode == "files_with_matches":
            matched_files_with_mtime.sort(key=lambda item: (-item[1], item[0]))
            paged_files, page_truncated, applied_limit = _apply_offset_limit(
                [item[0] for item in matched_files_with_mtime],
                offset=offset,
                limit=pagination_limit,
            )
            if page_truncated:
                truncated = True
                if truncation_reason is None:
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "default_limit"
                    )
            elif truncated and applied_limit is None and pagination_limit is not None:
                applied_limit = pagination_limit

            return _grep_payload(
                None,
                mode=output_mode,
                pattern=pattern,
                is_regex=is_regex,
                files_searched=files_searched,
                files_traversed=files_traversed,
                truncated=truncated,
                skipped_binary_files=skipped_binary_files,
                skipped_large_files=skipped_large_files,
                skipped_permission_denied_files=skipped_permission_denied_files,
                files=paged_files,
                applied_limit=applied_limit,
                applied_offset=offset,
                truncation_reason=truncation_reason,
            )

        if output_mode == "count":
            match_counts_with_mtime.sort(key=lambda item: (-item[2], item[0]))
            paged_counts, page_truncated, applied_limit = _apply_offset_limit(
                [
                    {"file": file_path, "count": count}
                    for file_path, count, _mtime in match_counts_with_mtime
                ],
                offset=offset,
                limit=pagination_limit,
            )
            if page_truncated:
                truncated = True
                if truncation_reason is None:
                    truncation_reason = (
                        "head_limit" if head_limit is not None else "default_limit"
                    )
            elif truncated and applied_limit is None and pagination_limit is not None:
                applied_limit = pagination_limit

            return _grep_payload(
                None,
                mode=output_mode,
                pattern=pattern,
                is_regex=is_regex,
                files_searched=files_searched,
                files_traversed=files_traversed,
                truncated=truncated,
                skipped_binary_files=skipped_binary_files,
                skipped_large_files=skipped_large_files,
                skipped_permission_denied_files=skipped_permission_denied_files,
                counts=paged_counts,
                applied_limit=applied_limit,
                applied_offset=offset,
                truncation_reason=truncation_reason,
            )

        paged_matches, page_truncated, applied_limit = _apply_offset_limit(
            matches,
            offset=offset,
            limit=pagination_limit,
        )
        if page_truncated:
            truncated = True
            if truncation_reason is None:
                truncation_reason = (
                    "head_limit" if head_limit is not None else "max_results"
                )
        elif truncated and applied_limit is None and pagination_limit is not None:
            applied_limit = pagination_limit

        return _grep_payload(
            paged_matches,
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=files_searched,
            files_traversed=files_traversed,
            truncated=truncated,
            skipped_binary_files=skipped_binary_files,
            skipped_large_files=skipped_large_files,
            skipped_permission_denied_files=skipped_permission_denied_files,
            applied_limit=applied_limit,
            applied_offset=offset,
            truncation_reason=truncation_reason,
        )
    except PermissionError as exc:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error("sandbox_violation", str(exc)),
        )
    except OSError as exc:
        return _grep_payload(
            [],
            mode=output_mode,
            pattern=pattern,
            is_regex=is_regex,
            files_searched=0,
            files_traversed=0,
            truncated=False,
            skipped_binary_files=0,
            skipped_large_files=0,
            skipped_permission_denied_files=0,
            error=build_error("filesystem_error", str(exc)),
        )


if __name__ == "__main__":
    mcp.run()
