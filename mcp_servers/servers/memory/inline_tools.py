from typing import Any

from mcp_servers.servers.description_format import build_inline_tool_definition
from mcp_servers.servers.memory.memory_descriptions import (
    MEMCOMMIT_DESCRIPTION,
    MEMLIST_DESCRIPTION,
    MEMREAD_DESCRIPTION,
)


MEMORY_INLINE_TOOLS: list[dict[str, Any]] = [
    build_inline_tool_definition(
        "memlist",
        MEMLIST_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Optional relative folder filter inside the memory root.",
                },
            },
            "required": [],
        },
    ),
    build_inline_tool_definition(
        "memread",
        MEMREAD_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative memory file path exactly as returned by memlist.",
                },
            },
            "required": ["path"],
        },
    ),
    build_inline_tool_definition(
        "memcommit",
        MEMCOMMIT_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative .md file path inside the memory root.",
                },
                "title": {
                    "type": "string",
                    "description": "Human-readable title for the memory.",
                },
                "category": {
                    "type": "string",
                    "description": "Logical memory category or folder label, such as 'procedural' or 'projects'.",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance score between 0.0 and 1.0.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short tag strings for later filtering and inspection.",
                },
                "abstract": {
                    "type": "string",
                    "description": "A specific standalone sentence used by memlist as the decision surface.",
                },
                "body": {
                    "type": "string",
                    "description": "Full markdown body for the memory file.",
                },
            },
            "required": ["path", "title", "category", "importance", "tags", "abstract", "body"],
        },
    ),
]
