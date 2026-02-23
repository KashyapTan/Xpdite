"""Tests for source/mcp_integration/skill_injector.py."""

from unittest.mock import MagicMock
from source.mcp_integration.skill_injector import get_skills_to_inject, build_skills_prompt_block


def _make_skill(name, enabled=True, content="skill content"):
    return {
        "id": 1,
        "skill_name": name,
        "display_name": name.title(),
        "slash_command": name,
        "content": content,
        "is_default": True,
        "is_modified": False,
        "enabled": enabled,
        "created_at": 0.0,
        "updated_at": 0.0,
    }


def _make_db(skills):
    db = MagicMock()
    db.get_all_skills.return_value = skills
    return db


def _make_mcp_manager(tool_server_map=None):
    mgr = MagicMock()
    if tool_server_map:
        mgr.get_tool_server_name.side_effect = lambda name: tool_server_map.get(name, "")
    else:
        mgr.get_tool_server_name.return_value = ""
    return mgr


class TestGetSkillsToInject:
    def test_no_skills_no_tools(self):
        db = _make_db([])
        result = get_skills_to_inject([], [], db)
        assert result == []

    def test_forced_skills_returned(self):
        forced = [_make_skill("terminal")]
        db = _make_db([_make_skill("terminal")])
        result = get_skills_to_inject([], forced, db)
        assert len(result) == 1
        assert result[0]["skill_name"] == "terminal"

    def test_auto_skill_from_dominant_server(self):
        db = _make_db([_make_skill("filesystem"), _make_skill("terminal")])
        mcp = _make_mcp_manager({"read_file": "filesystem", "write_file": "filesystem"})
        tools = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "write_file"}},
        ]
        result = get_skills_to_inject(tools, [], db, mcp_manager=mcp)
        assert len(result) == 1
        assert result[0]["skill_name"] == "filesystem"

    def test_auto_skill_not_duplicated_with_forced(self):
        """If the dominant server skill is already forced, it shouldn't appear twice."""
        fs_skill = _make_skill("filesystem")
        db = _make_db([fs_skill])
        mcp = _make_mcp_manager({"read_file": "filesystem"})
        tools = [{"function": {"name": "read_file"}}]
        result = get_skills_to_inject(tools, [fs_skill], db, mcp_manager=mcp)
        names = [s["skill_name"] for s in result]
        assert names.count("filesystem") == 1

    def test_disabled_skill_not_in_pool(self):
        db = _make_db([_make_skill("terminal", enabled=False)])
        mcp = _make_mcp_manager({"run_command": "terminal"})
        tools = [{"function": {"name": "run_command"}}]
        result = get_skills_to_inject(tools, [], db, mcp_manager=mcp)
        assert result == []

    def test_no_mcp_manager_no_auto_skill(self):
        db = _make_db([_make_skill("terminal")])
        tools = [{"function": {"name": "run_command"}}]
        result = get_skills_to_inject(tools, [], db, mcp_manager=None)
        assert result == []

    def test_forced_plus_auto(self):
        forced = [_make_skill("websearch")]
        db = _make_db([_make_skill("terminal"), _make_skill("websearch")])
        mcp = _make_mcp_manager({"run_command": "terminal"})
        tools = [{"function": {"name": "run_command"}}]
        result = get_skills_to_inject(tools, forced, db, mcp_manager=mcp)
        names = [s["skill_name"] for s in result]
        assert "websearch" in names
        assert "terminal" in names


class TestBuildSkillsPromptBlock:
    def test_empty_skills(self):
        assert build_skills_prompt_block([]) == ""

    def test_single_skill(self):
        skills = [_make_skill("terminal", content="Use terminal for commands.")]
        result = build_skills_prompt_block(skills)
        assert "Active Skills" in result
        assert "Use terminal for commands." in result

    def test_multiple_skills_separated(self):
        skills = [
            _make_skill("terminal", content="Terminal instructions"),
            _make_skill("filesystem", content="Filesystem instructions"),
        ]
        result = build_skills_prompt_block(skills)
        assert "Terminal instructions" in result
        assert "Filesystem instructions" in result
        assert "---" in result  # separator between skills

    def test_whitespace_trimmed(self):
        skills = [_make_skill("test", content="  content with spaces  ")]
        result = build_skills_prompt_block(skills)
        assert "content with spaces" in result
