"""
Skill injection engine.

Handles injection of full skill content (SKILL.md) into system prompts when:
  1. User explicitly requests via slash commands
  2. YouTube URL is detected in the query (special case)

For on-demand skill discovery, the LLM can use the list_skills and use_skill
MCP tools instead of relying on auto-injection.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, List

logger = logging.getLogger(__name__)
_YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE,
)

if TYPE_CHECKING:
    from ...services.skills_runtime.skills import Skill, SkillManager


def _get_manager() -> "SkillManager":
    from ...services.skills_runtime.skills import get_skill_manager
    return get_skill_manager()


# ── Full skill injection ────────────────────────────────────────


def get_skills_to_inject(
    forced_skills: List["Skill"],
    user_query: str = "",
) -> List["Skill"]:
    """Return ordered list of Skill objects to fully inject.

    Rules:
    - ``forced_skills`` are always included (from slash commands).
    - YouTube URL detection: if the query contains a YouTube link and
      the youtube skill is enabled, auto-inject it (no slash command needed).

    This function no longer performs auto-detection based on retrieved tools.
    For on-demand skill discovery, the LLM should use list_skills/use_skill tools.
    """
    # If the user explicitly invoked slash commands, return those directly
    if forced_skills:
        return list(forced_skills)

    manager = _get_manager()
    enabled_by_name = {s.name: s for s in manager.get_enabled_skills()}

    # YouTube URL detection: auto-inject youtube skill when URL is present
    youtube_skill = enabled_by_name.get("youtube")
    if youtube_skill is not None and user_query and _YOUTUBE_URL_RE.search(user_query):
        return [youtube_skill]

    # No forced skills and no YouTube URL — return empty list
    # The LLM can use list_skills/use_skill tools to discover and load skills
    return []


def build_skills_prompt_block(
    skills: List["Skill"],
) -> str:
    """Format a system prompt block containing full skill content.

    Args:
        skills: Skills whose full ``SKILL.md`` should be injected.

    Returns empty string if there is nothing to inject.
    """
    if not skills:
        return ""

    blocks = [s.read_content().strip() for s in skills]
    joined = "\n\n---\n\n".join(b for b in blocks if b)

    if not joined:
        return ""

    return f"\n\n## Active Skills\n\n{joined}\n"

