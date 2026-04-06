"""
Skills inline tool executor.

Handles execution of list_skills and use_skill MCP tools.
These are inline tools (no subprocess) for fast skill discovery.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def execute_skill_tool(tool_name: str, args: dict[str, Any]) -> str:
    """Execute list_skills or use_skill inline tools.

    Args:
        tool_name: Either 'list_skills' or 'use_skill'
        args: Tool arguments (empty for list_skills, {'skill_name': str} for use_skill)

    Returns:
        Tool result as a string formatted for LLM consumption.
    """
    from ...services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()

    if tool_name == "list_skills":
        return _handle_list_skills(manager)
    elif tool_name == "use_skill":
        return _handle_use_skill(manager, args)
    else:
        logger.warning("Unknown skill tool requested: %s", tool_name)
        return f"Unknown skill tool: {tool_name}"


def _handle_list_skills(manager) -> str:
    """List all enabled skills with descriptions."""
    enabled = manager.get_enabled_skills()

    if not enabled:
        return "No skills are currently enabled."

    lines = ["Available skills:", ""]
    for skill in enabled:
        lines.append(f"- **{skill.name}**: {skill.description}")

    lines.append("")
    lines.append("Call use_skill(skill_name) to load full instructions for a skill.")

    return "\n".join(lines)


def _handle_use_skill(manager, args: dict[str, Any]) -> str:
    """Load full SKILL.md content for a specific skill."""
    skill_name = args.get("skill_name", "").strip()

    if not skill_name:
        return "Error: skill_name is required. Call list_skills to see available skills."

    skill = manager.get_skill_by_name(skill_name)

    if skill is None:
        available = [s.name for s in manager.get_enabled_skills()]
        if available:
            return (
                f"Skill '{skill_name}' not found. "
                f"Available skills: {', '.join(sorted(available))}"
            )
        return f"Skill '{skill_name}' not found. No skills are currently enabled."

    if not skill.enabled:
        return f"Skill '{skill_name}' is disabled."

    content = skill.read_content()

    if not content or not content.strip():
        return f"Skill '{skill_name}' has no content (SKILL.md is empty or missing)."

    logger.debug("Loaded skill '%s' (%d chars)", skill_name, len(content))
    return content
