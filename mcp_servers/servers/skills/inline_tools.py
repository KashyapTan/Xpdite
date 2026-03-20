"""
Inline tool definitions for skills discovery.

These tools allow the LLM to discover and load skills on-demand,
reducing token usage by only injecting skill content when needed.
"""

from typing import Any

from mcp_servers.servers.description_format import build_inline_tool_definition
from mcp_servers.servers.skills.skills_descriptions import (
    LIST_SKILLS_DESCRIPTION,
    USE_SKILL_DESCRIPTION,
)


SKILLS_INLINE_TOOLS: list[dict[str, Any]] = [
    build_inline_tool_definition(
        "list_skills",
        LIST_SKILLS_DESCRIPTION,
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    build_inline_tool_definition(
        "use_skill",
        USE_SKILL_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "The name of the skill to load "
                        "(e.g., 'terminal', 'filesystem', 'gmail', 'calendar', 'websearch')"
                    ),
                },
            },
            "required": ["skill_name"],
        },
    ),
]
