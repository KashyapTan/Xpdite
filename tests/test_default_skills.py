"""Tests for source/mcp_integration/default_skills.py — skill data integrity."""

from source.mcp_integration.default_skills import DEFAULT_SKILLS


class TestDefaultSkills:
    def test_not_empty(self):
        assert len(DEFAULT_SKILLS) > 0

    def test_required_keys_present(self):
        required = {"skill_name", "display_name", "slash_command", "content"}
        for skill in DEFAULT_SKILLS:
            missing = required - set(skill.keys())
            assert not missing, f"Skill {skill.get('skill_name', '?')} missing keys: {missing}"

    def test_skill_names_unique(self):
        names = [s["skill_name"] for s in DEFAULT_SKILLS]
        assert len(names) == len(set(names)), "Duplicate skill_name found"

    def test_slash_commands_unique(self):
        commands = [s["slash_command"] for s in DEFAULT_SKILLS]
        assert len(commands) == len(set(commands)), "Duplicate slash_command found"

    def test_content_not_empty(self):
        for skill in DEFAULT_SKILLS:
            assert skill["content"].strip(), f"Skill {skill['skill_name']} has empty content"

    def test_known_skills_present(self):
        names = {s["skill_name"] for s in DEFAULT_SKILLS}
        assert "terminal" in names
        assert "filesystem" in names
        assert "websearch" in names

    def test_display_names_not_empty(self):
        for skill in DEFAULT_SKILLS:
            assert skill["display_name"].strip(), f"Skill {skill['skill_name']} has empty display_name"
