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

