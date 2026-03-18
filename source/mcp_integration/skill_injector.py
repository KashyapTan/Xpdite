"""
Skill injection engine.

Two-phase injection:
  1. **Compact manifest** — a short one-liner-per-skill list injected into
     every system prompt so the agent knows what capabilities exist.
  2. **Full skill injection** — the complete ``SKILL.md`` content, injected
     only when triggered by a slash command or auto-detected dominant tool
     server.

This module is focused on *injection logic*.  All filesystem I/O, caching,
and CRUD live in ``source.services.skills.SkillManager``.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, Dict, List

logger = logging.getLogger(__name__)
_YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE,
)

if TYPE_CHECKING:
    from ..services.skills import Skill, SkillManager


def _get_manager() -> "SkillManager":
    from ..services.skills import get_skill_manager
    return get_skill_manager()


# ── Phase 1: compact manifest ────────────────────────────────────


def build_skill_manifest() -> str:
    """Build the always-injected compact manifest.

    Includes the real filesystem path to the skills directory so the LLM
    can self-serve any skill (or its reference docs) via the ``read_file``
    and ``list_directory`` MCP tools.

    Example output::

        ## Available Skills
        Skills directory: C:/Users/.../user_data/skills
        Each skill folder contains SKILL.md (full instructions) and optionally
        a references/ subfolder with supplementary docs. Use read_file and
        list_directory to explore any skill when you need more guidance.

        - **terminal** (builtin) — Guidance for terminal command execution. Folder: C:/.../builtin/terminal
        - **gmail** (builtin) — Guidance for Gmail operations. Folder: C:/.../builtin/gmail
    """
    from ..config import SKILLS_DIR as _skills_dir_val

    manager = _get_manager()
    enabled = manager.get_enabled_skills()
    if not enabled:
        return ""

    # Use forward slashes for readability even on Windows.
    skills_root = str(_skills_dir_val).replace("\\", "/")

    lines = [
        "## Available Skills",
        f"Skills directory: {skills_root}",
        "Each skill folder contains SKILL.md (full instructions) and optionally "
        "a references/ subfolder with supplementary docs. Use the read_file and "
        "list_directory tools to explore any skill when you need more guidance.",
        "",
    ]
    for skill in enabled:
        folder = str(skill.folder_path).replace("\\", "/")
        lines.append(
            f"- **{skill.name}** ({skill.source}) — {skill.description} "
            f"Folder: {folder}"
        )
    return "\n".join(lines) + "\n"


# ── Phase 2: full skill injection ────────────────────────────────


def get_skills_to_inject(
    retrieved_tools: List[Dict],
    forced_skills: List["Skill"],
    mcp_manager: Any = None,
    user_query: str = "",
) -> List["Skill"]:
    """Return ordered list of Skill objects to fully inject.

    Rules:
    - ``forced_skills`` are always included (from slash commands).
    - Auto-detection only runs when there are **no** forced skills.
      If the user explicitly chose a skill via slash command, respect
      that intent and don't pile on extra skills.
    - From the retrieved tools, find the dominant MCP server category.
    - If that server name matches a skill's ``trigger_servers`` and the
      skill isn't already forced, add it.
    - Result: forced_skills, OR forced_skills + up to 1 auto-detected skill.
    """
    # If the user explicitly invoked slash commands, return those directly —
    # no auto-detection needed.
    if forced_skills:
        return list(forced_skills)

    manager = _get_manager()
    enabled_by_name = {s.name: s for s in manager.get_enabled_skills()}

    # Explicit URL detection path for YouTube: this skill has no trigger_servers
    # by design (inline tool), so we activate it when the user includes a
    # YouTube link in the query.
    youtube_skill = enabled_by_name.get("youtube")
    if youtube_skill is not None and user_query and _YOUTUBE_URL_RE.search(user_query):
        return [youtube_skill]

    # Build a reverse map: server name → skills that trigger on it
    server_to_skills: Dict[str, "Skill"] = {}
    for skill in enabled_by_name.values():
        for srv in skill.trigger_servers:
            existing = server_to_skills.get(srv)
            if existing is not None and existing.name != skill.name:
                logger.debug(
                    "Trigger server '%s' already claimed by skill '%s'; "
                    "ignoring duplicate from '%s'",
                    srv, existing.name, skill.name,
                )
            server_to_skills.setdefault(srv, skill)

    # Count tools per server category
    category_counts: Counter = Counter()
    if mcp_manager and retrieved_tools:
        for tool in retrieved_tools:
            func = tool.get("function", {})
            tool_name = func.get("name", "")
            if tool_name:
                server = mcp_manager.get_tool_server_name(tool_name)
                if server:
                    category_counts[server] += 1

    # Auto-detect: pick the dominant server's skill if available
    auto_skill: "Skill" | None = None
    if category_counts:
        dominant_server = category_counts.most_common(1)[0][0]
        candidate = server_to_skills.get(dominant_server)
        if candidate:
            auto_skill = candidate

    result: list["Skill"] = []
    if auto_skill:
        result.append(auto_skill)

    return result


def build_skills_prompt_block(
    skills: List["Skill"],
    manifest: str = "",
) -> str:
    """Format a system prompt block containing the manifest + full skill content.

    Args:
        skills: Skills whose full ``SKILL.md`` should be injected.
        manifest: The compact manifest (from ``build_skill_manifest``).

    Returns empty string if there is nothing to inject.
    """
    parts: list[str] = []

    if manifest:
        parts.append(manifest)

    if skills:
        blocks = [s.read_content().strip() for s in skills]
        joined = "\n\n---\n\n".join(b for b in blocks if b)
        if joined:
            parts.append(f"## Active Skills\n\n{joined}")

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts) + "\n"

