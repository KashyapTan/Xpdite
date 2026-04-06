"""Tests for source/mcp_integration/executors/skills_executor.py."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from source.mcp_integration.executors.skills_executor import execute_skill_tool


def _skill(name: str, *, enabled: bool = True, content: str = "content"):
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        enabled=enabled,
        read_content=Mock(return_value=content),
    )


class _FakeManager:
    def __init__(self, enabled_skills=None, by_name=None):
        self._enabled = list(enabled_skills or [])
        self._by_name = dict(by_name or {})

    def get_enabled_skills(self):
        return list(self._enabled)

    def get_skill_by_name(self, name: str):
        return self._by_name.get(name)


class TestExecuteSkillTool:
    def test_unknown_tool_returns_error(self):
        manager = _FakeManager()
        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("unknown", {})

        assert result == "Unknown skill tool: unknown"

    def test_list_skills_returns_empty_message_when_none_enabled(self):
        manager = _FakeManager(enabled_skills=[])
        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("list_skills", {})

        assert result == "No skills are currently enabled."

    def test_list_skills_formats_enabled_skills(self):
        alpha = _skill("alpha")
        beta = _skill("beta")
        manager = _FakeManager(enabled_skills=[alpha, beta])

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("list_skills", {})

        assert "Available skills:" in result
        assert "- **alpha**: alpha description" in result
        assert "- **beta**: beta description" in result
        assert "Call use_skill(skill_name)" in result

    def test_use_skill_requires_skill_name(self):
        manager = _FakeManager()
        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {})

        assert "skill_name is required" in result

    def test_use_skill_not_found_lists_available_enabled_skills(self):
        alpha = _skill("alpha")
        manager = _FakeManager(enabled_skills=[alpha], by_name={})

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {"skill_name": "missing"})

        assert result == "Skill 'missing' not found. Available skills: alpha"

    def test_use_skill_not_found_without_enabled_skills(self):
        manager = _FakeManager(enabled_skills=[], by_name={})

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {"skill_name": "missing"})

        assert result == "Skill 'missing' not found. No skills are currently enabled."

    def test_use_skill_returns_disabled_message_for_disabled_skill(self):
        disabled_skill = _skill("planner", enabled=False)
        manager = _FakeManager(by_name={"planner": disabled_skill})

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {"skill_name": "planner"})

        assert result == "Skill 'planner' is disabled."

    def test_use_skill_handles_empty_content(self):
        empty_skill = _skill("notes", content="   ")
        manager = _FakeManager(by_name={"notes": empty_skill})

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {"skill_name": "notes"})

        assert result == "Skill 'notes' has no content (SKILL.md is empty or missing)."

    def test_use_skill_returns_skill_content(self):
        rich_skill = _skill("writer", content="# Writer\nFollow style guide.")
        manager = _FakeManager(by_name={"writer": rich_skill})

        with patch("source.services.skills_runtime.skills.get_skill_manager", return_value=manager):
            result = execute_skill_tool("use_skill", {"skill_name": "writer"})

        assert result == "# Writer\nFollow style guide."
