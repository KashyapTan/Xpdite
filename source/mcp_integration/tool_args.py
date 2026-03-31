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
from typing import Any, Dict, Optional, Tuple

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


def normalize_tool_args(raw_args: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Normalize raw model tool args to a dictionary.

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
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return {}, f"invalid JSON arguments ({exc.msg})"

        if isinstance(parsed, dict):
            return parsed, None
        return {}, f"tool arguments must be a JSON object, got {type(parsed).__name__}"

    return {}, f"unsupported argument type: {type(raw_args).__name__}"


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
        return _sanitize_sensitive_tool_args(value)

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

