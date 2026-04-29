from typing import Any

from mcp_servers.servers.description_format import build_inline_tool_definition
from mcp_servers.servers.sub_agent.sub_agent_descriptions import (
    SPAWN_AGENT_DESCRIPTION,
)


SUB_AGENT_INLINE_TOOLS: list[dict[str, Any]] = [
    build_inline_tool_definition(
        "spawn_agent",
        SPAWN_AGENT_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Fully self-contained task description for the sub-agent to execute now. Must include all context the sub-agent needs.",
                },
                "model_tier": {
                    "type": "string",
                    "description": "Model tier: 'fast' (default, cheap), 'smart' (mid-tier), 'self' (same model as caller)",
                    "enum": ["fast", "smart", "self"],
                    "default": "fast",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Human-readable label for display (e.g. 'Code Reviewer', 'Web Researcher')",
                    "default": "Sub-Agent",
                },
            },
            "required": ["instruction"],
        },
    )
]
