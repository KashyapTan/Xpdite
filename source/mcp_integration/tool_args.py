"""
Helpers for normalizing model-emitted MCP tool arguments.

Some providers (especially Ollama variants) may emit tool arguments as:
- a dict
- a JSON string
- an empty string / None
- malformed JSON

Tool loops should never crash on these shapes. Invalid args are returned as
structured errors so callers can feed them back to the model when appropriate.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_TOOL_ARG_KEYS = (
    "api_key",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "session",
    "key",
)

# Tools where empty-object args are a safe recovery fallback when the model
# emits malformed argument JSON. These tools either take no required arguments
# or can operate meaningfully with defaults.
_EMPTY_ARGS_FALLBACK_TOOLS = {
    "list_skills",
    "memlist",
    "get_environment",
    "end_session_mode",
}


def _repair_json(raw: str) -> Optional[str]:
    """Attempt to repair common JSON issues from LLM tool call arguments.

    Handles:
    - Trailing garbage after a valid JSON object (common with cloud Ollama models)
    - Leading/trailing whitespace and newlines
    - Control characters that break JSON parsing
    - Truncated JSON by closing unclosed brackets/braces

    Returns the repaired JSON string, or None if repair failed.
    """
    if not raw or not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    # Remove control characters except \n, \r, \t (which are valid in JSON strings)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    # If it doesn't start with { or [, try to find the first JSON object
    if not text.startswith("{") and not text.startswith("["):
        obj_start = text.find("{")
        arr_start = text.find("[")
        if obj_start == -1 and arr_start == -1:
            return None
        if obj_start == -1:
            text = text[arr_start:]
        elif arr_start == -1:
            text = text[obj_start:]
        else:
            text = text[min(obj_start, arr_start) :]

    # Try to extract valid JSON object/array by finding matching brackets
    repaired = _extract_json_object(text)
    if repaired:
        return repaired

    # Fallback: try to close unclosed brackets for truncated JSON
    repaired = _close_truncated_json(text)
    if repaired:
        return repaired

    return None


def _extract_json_object(text: str) -> Optional[str]:
    """Extract the first complete JSON object or array from text.

    This handles trailing garbage after a valid JSON object, which is common
    when models emit extra text after the tool call arguments.
    """
    if not text:
        return None

    # Determine if we're looking for object or array
    if text.startswith("{"):
        open_char, close_char = "{", "}"
    elif text.startswith("["):
        open_char, close_char = "[", "]"
    else:
        return None

    depth = 0
    in_string = False
    escape_next = False
    end_pos = -1

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                end_pos = i
                break

    if end_pos == -1:
        return None

    candidate = text[: end_pos + 1]

    # Validate it's actually valid JSON
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return None


def _close_truncated_json(text: str) -> Optional[str]:
    """Attempt to close truncated JSON by adding missing brackets/braces.

    This is a last-resort repair for JSON that was cut off mid-stream.
    """
    if not text:
        return None

    # Count unclosed brackets/braces (accounting for strings)
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False

    for char in text:
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            open_braces += 1
        elif char == "}":
            open_braces -= 1
        elif char == "[":
            open_brackets += 1
        elif char == "]":
            open_brackets -= 1

    # If we're inside a string, close it first
    if in_string:
        text = text + '"'

    # Add missing closing brackets/braces
    closing = "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    if not closing:
        return None

    candidate = text + closing

    try:
        json.loads(candidate)
        logger.debug("Repaired truncated JSON by adding: %s", closing)
        return candidate
    except json.JSONDecodeError:
        return None


def normalize_tool_args(raw_args: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Normalize raw model tool args to a dictionary.

    Includes robust JSON repair for common LLM issues like:
    - Trailing text after JSON object
    - Truncated JSON
    - Control characters

    Returns:
        (args_dict, error_message)
        - error_message is None when normalization succeeds.
        - On malformed JSON or unsupported types, returns {} and an error string.
    """
    if raw_args is None:
        return {}, None

    if isinstance(raw_args, dict):
        return raw_args, None

    if isinstance(raw_args, str):
        text = raw_args.strip()
        if not text:
            return {}, None

        # First, try direct parsing (fast path for well-formed JSON)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed, None
            return (
                {},
                f"tool arguments must be a JSON object, got {type(parsed).__name__}",
            )
        except json.JSONDecodeError:
            pass

        # JSON parsing failed — attempt repair
        repaired = _repair_json(text)
        if repaired:
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    logger.debug(
                        "Repaired malformed tool arguments (%d -> %d chars)",
                        len(text),
                        len(repaired),
                    )
                    return parsed, None
                return (
                    {},
                    f"tool arguments must be a JSON object, got {type(parsed).__name__}",
                )
            except json.JSONDecodeError as exc:
                return {}, f"invalid JSON arguments after repair ({exc.msg})"

        # Repair failed — return error with truncated preview
        preview = text[:100] + "..." if len(text) > 100 else text
        return {}, f"invalid JSON arguments (could not parse or repair): {preview}"

    return {}, f"unsupported argument type: {type(raw_args).__name__}"


def merge_streamed_tool_call_arguments(existing: str, incoming: str) -> str:
    """Merge streamed tool-argument chunks across provider styles.

    Providers do not all stream function arguments the same way:
    - incremental deltas (append behavior)
    - cumulative snapshots (replace behavior)
    - occasional duplicate snapshots

    This helper reconstructs a stable argument string that works for both.
    """
    if not incoming:
        return existing

    if not existing:
        return incoming

    if incoming == existing:
        return existing

    # Cumulative snapshot (new chunk already contains prior text).
    if len(incoming) > len(existing) and incoming.startswith(existing):
        return incoming

    # Duplicate or shorter reset snapshot.
    if (
        len(incoming) < len(existing) and existing.startswith(incoming)
    ) or existing.endswith(incoming):
        return existing

    # Incremental delta chunk.
    return existing + incoming


def should_fallback_to_empty_args(fn_name: str) -> bool:
    """Whether malformed args for this tool can safely fall back to ``{}``."""
    return fn_name in _EMPTY_ARGS_FALLBACK_TOOLS


def _sanitize_sensitive_tool_args(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_lower = key.lower()
            if any(fragment in key_lower for fragment in _SENSITIVE_TOOL_ARG_KEYS):
                redacted[key] = _REDACTED_VALUE
            else:
                redacted[key] = _sanitize_sensitive_tool_args(item)
        return redacted

    if isinstance(value, list):
        return [_sanitize_sensitive_tool_args(item) for item in value]

    return value


def sanitize_tool_args(fn_name: str, server_name: str, value: Any) -> Any:
    """Redact tool arguments before logging, broadcasting, or persisting them."""
    if not isinstance(value, dict):
        return value

    # Memory server: only allow specific keys through unredacted
    if server_name == "memory":
        if fn_name == "memcommit":
            allowed_keys = {"path", "category", "importance", "tags"}
        elif fn_name == "memread":
            allowed_keys = {"path"}
        elif fn_name == "memlist":
            allowed_keys = {"folder"}
        else:
            allowed_keys = set()

        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            if key in allowed_keys:
                sanitized[key] = _sanitize_sensitive_tool_args(item)
            else:
                sanitized[key] = _REDACTED_VALUE
        return sanitized

    return _sanitize_sensitive_tool_args(value)


def format_tool_arg_error(
    fn_name: str,
    error: str,
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """Format a tool argument error message with schema hints.

    When a model fails to provide valid tool arguments, this function
    generates a helpful error message that includes the expected parameter
    schema to help the model self-correct on retry.

    Args:
        fn_name: The tool name that failed
        error: The original error message
        schema: The tool's JSON Schema (optional, from mcp_manager.get_tool_schema)

    Returns:
        A formatted error message with schema hints
    """
    msg = f"Error calling tool '{fn_name}': {error}"

    if not schema:
        return msg

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return msg

    msg += "\n\nExpected parameters:"
    for param_name, param_info in properties.items():
        param_type = param_info.get("type", "any")
        param_desc = param_info.get("description", "")
        is_required = param_name in required

        req_marker = " (required)" if is_required else " (optional)"
        desc_part = f" - {param_desc}" if param_desc else ""

        msg += f"\n  - {param_name}: {param_type}{req_marker}{desc_part}"

    return msg
