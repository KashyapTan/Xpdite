"""Helpers for provider-native prompt cache request metadata."""

from __future__ import annotations

import copy
from typing import Any


_EPHEMERAL_CACHE_CONTROL = {"type": "ephemeral"}


def _cache_control() -> dict[str, str]:
    return dict(_EPHEMERAL_CACHE_CONTROL)


def mark_messages_for_anthropic_prompt_cache(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark the stable system prompt block as an Anthropic cache breakpoint."""
    marked_messages = copy.deepcopy(messages)
    for message in marked_messages:
        if message.get("role") != "system":
            continue

        content = message.get("content")
        if isinstance(content, str) and content:
            message["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": _cache_control(),
                }
            ]
            break

        if isinstance(content, list):
            for block in reversed(content):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and block.get("text")
                ):
                    block["cache_control"] = _cache_control()
                    break
            break

    return marked_messages


def mark_tools_for_anthropic_prompt_cache(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Mark stable tool definitions as Anthropic-cacheable when tools are sent."""
    if not tools:
        return tools

    marked_tools = copy.deepcopy(tools)
    marked_tools[-1]["cache_control"] = _cache_control()
    return marked_tools
