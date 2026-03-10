from typing import Any

from mcp_servers.servers.sub_agent.sub_agent_descriptions import (
    SPAWN_AGENT_DESCRIPTION,
)


def _build_tool_definition(
    name: str, description: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description.strip(),
        "parameters": parameters,
    }


SUB_AGENT_INLINE_TOOLS: list[dict[str, Any]] = [
    _build_tool_definition(
        "spawn_agent",
        SPAWN_AGENT_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Fully self-contained task description. Must include all context the sub-agent needs.",
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