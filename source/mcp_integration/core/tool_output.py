"""Helpers for normalizing MCP tool outputs into Markdown-friendly text."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_LANG_RE = re.compile(r"^[a-zA-Z0-9_+-]{1,20}$")


def format_tool_output(result: Any) -> str | dict[str, Any]:
    """Convert structured tool output into Markdown, preserving image payloads."""
    if isinstance(result, dict) and result.get("type") == "image":
        return result

    if isinstance(result, str):
        parsed = _parse_json_string(result)
        if parsed is None:
            return result
        return _render_markdown(parsed)

    if isinstance(result, (dict, list, tuple)):
        return _render_markdown(result)

    return str(result)


def _parse_json_string(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None

    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _render_markdown(value: Any) -> str:
    if isinstance(value, dict):
        return _render_dict(value)
    if isinstance(value, (list, tuple)):
        return _render_list(list(value))
    if value is None:
        return "_No data returned._"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _render_dict(data: dict[str, Any]) -> str:
    if not data:
        return "_No data returned._"

    if "error" in data and isinstance(data["error"], dict):
        return _render_error_dict(data["error"], data)

    if "content" in data and isinstance(data["content"], str):
        return _render_content_dict(data)

    sections: list[str] = []
    scalar_lines = _scalar_lines(data)
    if scalar_lines:
        sections.append("\n".join(scalar_lines))

    for key, value in data.items():
        if _is_scalar(value):
            continue
        rendered = _render_named_section(key, value)
        if rendered:
            sections.append(rendered)

    return "\n\n".join(section for section in sections if section).strip() or "_No data returned._"


def _render_error_dict(error: dict[str, Any], full_payload: dict[str, Any]) -> str:
    code = error.get("code", "error")
    message = error.get("message", "Tool returned an error.")
    lines = [f"**Error (`{code}`):** {message}"]

    extras = {
        key: value
        for key, value in full_payload.items()
        if key != "error" and _is_scalar(value)
    }
    if extras:
        lines.append("")
        lines.extend(_scalar_lines(extras))
    return "\n".join(lines)


def _render_content_dict(data: dict[str, Any]) -> str:
    content = data.get("content", "")
    sections: list[str] = []

    summary = data.get("chunk_summary")
    if isinstance(summary, str) and summary.strip():
        sections.append(summary.strip())

    meta_keys = [
        "file_format",
        "file_size_bytes",
        "total_chars",
        "chars_returned",
        "offset",
        "next_offset",
        "has_more",
        "mime_type",
        "title",
        "url",
    ]
    meta = {
        key: data[key]
        for key in meta_keys
        if key in data and _is_scalar(data[key]) and key != "content"
    }
    if meta:
        sections.append("\n".join(_scalar_lines(meta)))

    if content:
        language = _fence_language(data.get("file_format"))
        sections.append(f"```{language}\n{content}\n```" if language else f"```\n{content}\n```")
    else:
        sections.append("_No content returned._")

    extra_sections: list[str] = []
    for key, value in data.items():
        if key in {"content", "chunk_summary", *meta.keys()}:
            continue
        if _is_scalar(value):
            continue
        rendered = _render_named_section(key, value)
        if rendered:
            extra_sections.append(rendered)

    return "\n\n".join(sections + extra_sections)


def _render_list(items: list[Any]) -> str:
    if not items:
        return "_No items._"

    if all(_is_scalar(item) for item in items):
        return "\n".join(f"- {_format_scalar(item)}" for item in items)

    rendered_items: list[str] = []
    for index, item in enumerate(items, start=1):
        rendered = _render_markdown(item)
        rendered_items.append(f"{index}. {rendered.replace(chr(10), chr(10) + '   ')}")
    return "\n".join(rendered_items)


def _render_named_section(key: str, value: Any) -> str:
    title = _humanize_key(key)
    rendered = _render_markdown(value)
    if "\n" in rendered:
        return f"**{title}:**\n{rendered}"
    return f"**{title}:** {rendered}"


def _scalar_lines(data: dict[str, Any]) -> list[str]:
    return [f"- **{_humanize_key(key)}:** {_format_scalar(value)}" for key, value in data.items() if _is_scalar(value)]


def _format_scalar(value: Any) -> str:
    if value is None:
        return "_None_"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _fence_language(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return normalized if _FENCE_LANG_RE.match(normalized) else ""
