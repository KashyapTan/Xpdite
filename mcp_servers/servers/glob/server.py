import glob as globlib
import os
from pathlib import Path
from typing import Any, TypeVar

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
from mcp_servers.servers.glob.glob_descriptions import GLOB_FILES_DESCRIPTION


mcp = FastMCP("Glob Tools")

BASE_PATH = DEFAULT_BASE_PATH

_GLOB_SCAN_CAP = 1000
_GLOB_DEFAULT_HEAD_LIMIT = 100
_T = TypeVar("_T")


def _glob_payload(
    matches: list[str],
    *,
    available_matches: int,
    truncated: bool,
    applied_limit: int | None = None,
    applied_offset: int | None = None,
    error: dict[str, str] | None = None,
    truncation_reason: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "matches": matches,
        "total": len(matches),
        "available_matches": available_matches,
        "truncated": truncated,
    }
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


def _resolve_search_path(path: str, base_path: str | None) -> tuple[str | None, str | None]:
    normalized_path = (path or ".").strip() or "."
    normalized_base = (base_path or "").strip()

    if normalized_base and normalized_path not in {".", normalized_base}:
        return None, (
            "path and base_path cannot point to different locations. "
            "Use path only; base_path is kept for backward compatibility."
        )

    return normalized_base or normalized_path, None


@mcp.tool(description=GLOB_FILES_DESCRIPTION)
def glob_files(
    pattern: str,
    path: str = ".",
    base_path: str | None = None,
    include_hidden: bool = False,
    exclude: str | None = None,
    head_limit: int | None = None,
    offset: int = 0,
) -> str:
    if not pattern.strip():
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("invalid_pattern", "pattern must not be empty."),
        )

    if offset < 0:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("invalid_offset", "offset must be zero or greater."),
        )

    if head_limit is not None and head_limit < 0:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error(
                "invalid_head_limit",
                "head_limit must be zero or greater.",
            ),
        )

    search_path, path_error = _resolve_search_path(path, base_path)
    if path_error is not None:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("invalid_path", path_error),
        )

    pattern_error = validate_relative_glob_pattern(pattern, "pattern")
    if pattern_error is not None:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("invalid_pattern", pattern_error),
        )

    exclude_patterns = split_glob_patterns(exclude)
    for exclude_pattern in exclude_patterns:
        exclude_error = validate_relative_glob_pattern(exclude_pattern, "exclude")
        if exclude_error is not None:
            return _glob_payload(
                [],
                available_matches=0,
                truncated=False,
                error=build_error("invalid_exclude", exclude_error),
            )

    effective_limit = _GLOB_DEFAULT_HEAD_LIMIT if head_limit is None else head_limit

    try:
        clean_root = get_safe_path(search_path or ".", BASE_PATH)
        if not os.path.exists(clean_root):
            return _glob_payload(
                [],
                available_matches=0,
                truncated=False,
                error=build_error(
                    "path_not_found",
                    f"path '{search_path}' does not exist.",
                ),
            )
        if not os.path.isdir(clean_root):
            return _glob_payload(
                [],
                available_matches=0,
                truncated=False,
                error=build_error(
                    "not_a_directory",
                    f"path '{search_path}' is not a directory.",
                ),
            )

        matches_with_mtime: list[tuple[str, float]] = []
        seen: set[str] = set()
        truncated = False
        truncation_reason: str | None = None

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

            display_path = to_display_path(relative_path)
            if exclude_patterns and any(
                path_matches_glob(display_path, exclude_pattern)
                for exclude_pattern in exclude_patterns
            ):
                continue

            candidate_path = os.path.join(clean_root, relative_match)
            try:
                clean_candidate = get_safe_path(candidate_path, BASE_PATH)
            except PermissionError:
                continue

            if not is_within_search_root(clean_candidate, clean_root):
                continue

            if display_path in seen:
                continue

            seen.add(display_path)
            matches_with_mtime.append((display_path, safe_mtime(clean_candidate)))
            if len(matches_with_mtime) >= _GLOB_SCAN_CAP:
                truncated = True
                truncation_reason = "result_cap"
                break

        matches_with_mtime.sort(key=lambda item: (-item[1], item[0]))
        all_matches = [item[0] for item in matches_with_mtime]
        paged_matches, page_truncated, applied_limit = _apply_offset_limit(
            all_matches,
            offset=offset,
            limit=effective_limit,
        )
        if page_truncated:
            truncated = True
            if truncation_reason is None:
                truncation_reason = (
                    "head_limit" if head_limit is not None else "default_limit"
                )
        elif truncated and applied_limit is None and effective_limit not in {None, 0}:
            applied_limit = effective_limit

        return _glob_payload(
            paged_matches,
            available_matches=len(all_matches),
            truncated=truncated,
            applied_limit=applied_limit,
            applied_offset=offset,
            truncation_reason=truncation_reason,
        )
    except PermissionError as exc:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("sandbox_violation", str(exc)),
        )
    except OSError as exc:
        return _glob_payload(
            [],
            available_matches=0,
            truncated=False,
            error=build_error("filesystem_error", str(exc)),
        )


if __name__ == "__main__":
    mcp.run()
