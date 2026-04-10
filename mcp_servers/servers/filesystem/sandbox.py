import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any


USERNAME = os.getenv("USERNAME") or os.getenv("USER") or Path.home().name
DEFAULT_BASE_PATH = os.path.abspath(str(Path.home()))

VCS_DIRECTORY_NAMES = frozenset({".git", ".svn", ".hg", ".bzr", ".jj", ".sl"})
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")


def get_safe_path(path: str, base_path: str) -> str:
    """Resolve a path and ensure it stays within the configured sandbox root."""
    expanded_path = os.path.expanduser(path)
    target_path = os.path.realpath(expanded_path)
    safe_base = os.path.realpath(base_path)

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


def json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def build_error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def to_display_path(relative_path: str | Path) -> str:
    path_obj = relative_path if isinstance(relative_path, Path) else Path(relative_path)
    display_path = path_obj.as_posix()
    return display_path or "."


def has_hidden_part(relative_path: str | Path) -> bool:
    parts = (
        relative_path.parts
        if isinstance(relative_path, Path)
        else Path(relative_path).parts
    )
    return any(part.startswith(".") for part in parts if part not in ("", ".", ".."))


def has_vcs_part(relative_path: str | Path) -> bool:
    parts = (
        relative_path.parts
        if isinstance(relative_path, Path)
        else Path(relative_path).parts
    )
    return any(part in VCS_DIRECTORY_NAMES for part in parts)


def should_skip_relative_path(
    relative_path: str | Path,
    *,
    include_hidden: bool,
) -> bool:
    if has_vcs_part(relative_path):
        return True
    if not include_hidden and has_hidden_part(relative_path):
        return True
    return False


def is_within_search_root(candidate_path: str, search_root: str) -> bool:
    resolved_candidate = os.path.realpath(candidate_path)
    resolved_root = os.path.realpath(search_root)
    try:
        return resolved_root == os.path.commonpath([resolved_root, resolved_candidate])
    except ValueError:
        return False


def validate_relative_glob_pattern(pattern: str, field_name: str) -> str | None:
    normalized = pattern.replace("\\", "/")
    if os.path.isabs(pattern):
        return (
            f"{field_name} must be relative to the search root, not an absolute path."
        )
    if WINDOWS_DRIVE_PATTERN.match(normalized):
        return f"{field_name} must not be drive-qualified."

    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        return f"{field_name} must not contain parent-directory segments."
    return None


def safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def split_glob_patterns(value: str | None) -> list[str]:
    """Split comma/whitespace separated glob lists without breaking brace groups."""
    if value is None:
        return []

    patterns: list[str] = []
    current: list[str] = []
    brace_depth = 0

    for char in value.strip():
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)

        if brace_depth == 0 and (char == "," or char.isspace()):
            if current:
                pattern = "".join(current).strip()
                if pattern:
                    patterns.append(pattern)
                current.clear()
            continue

        current.append(char)

    if current:
        pattern = "".join(current).strip()
        if pattern:
            patterns.append(pattern)

    return patterns


def path_matches_glob(display_path: str, pattern: str) -> bool:
    posix_path = PurePosixPath(display_path)
    if posix_path.match(pattern):
        return True
    if pattern.startswith("**/"):
        return posix_path.match(pattern[3:])
    return False
