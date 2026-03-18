"""Tests for source/mcp_integration/skill_injector.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from source.mcp_integration.skill_injector import (
    build_skill_manifest,
    build_skills_prompt_block,
    get_skills_to_inject,
)
from source.services.skills import Skill


def _make_skill(
    name,
    enabled=True,
    content="skill content",
    trigger_servers=None,
    source="builtin",
):
    """Helper to create a Skill dataclass instance for testing."""
    s = Skill(
        name=name,
        description=f"{name.title()} skill",
        slash_command=name,
        trigger_servers=trigger_servers or [name],
        version="1.0",
        source=source,
        folder_path=Path(f"user_data/skills/{source}/{name}"),
        enabled=enabled,
    )
    s._content = content
    return s


def _make_mcp_manager(tool_server_map=None):
    mgr = MagicMock()
    if tool_server_map:
        mgr.get_tool_server_name.side_effect = lambda n: tool_server_map.get(n, "")
    else:
        mgr.get_tool_server_name.return_value = ""
    return mgr


def _mock_manager(skills):
    """Return a mock SkillManager with the given skills list."""
    manager = MagicMock()
    enabled = [s for s in skills if s.enabled]
    manager.get_enabled_skills.return_value = enabled
    return manager


class TestGetSkillsToInject:
    def test_no_skills_no_tools(self):
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([]),
        ):
            result = get_skills_to_inject([], [])
        assert result == []

    def test_forced_skills_returned(self):
        terminal = _make_skill("terminal")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ):
            result = get_skills_to_inject([], [terminal])
        assert len(result) == 1
        assert result[0].name == "terminal"

    def test_auto_skill_from_dominant_server(self):
        fs_skill = _make_skill("filesystem", trigger_servers=["filesystem"])
        terminal = _make_skill("terminal", trigger_servers=["terminal"])
        mcp = _make_mcp_manager({"read_file": "filesystem", "write_file": "filesystem"})
        tools = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "write_file"}},
        ]
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([fs_skill, terminal]),
        ):
            result = get_skills_to_inject(tools, [], mcp_manager=mcp)
        assert len(result) == 1
        assert result[0].name == "filesystem"

    def test_auto_skill_not_duplicated_with_forced(self):
        """When forced skills are present, auto-detect is skipped entirely."""
        fs_skill = _make_skill("filesystem", trigger_servers=["filesystem"])
        mcp = _make_mcp_manager({"read_file": "filesystem"})
        tools = [{"function": {"name": "read_file"}}]
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([fs_skill]),
        ):
            result = get_skills_to_inject(tools, [fs_skill], mcp_manager=mcp)
        # Only the forced skill is returned — no auto-detect when forced.
        assert len(result) == 1
        assert result[0].name == "filesystem"

    def test_disabled_skill_not_in_pool(self):
        terminal = _make_skill("terminal", enabled=False, trigger_servers=["terminal"])
        mcp = _make_mcp_manager({"run_command": "terminal"})
        tools = [{"function": {"name": "run_command"}}]
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ):
            result = get_skills_to_inject(tools, [], mcp_manager=mcp)
        assert result == []

    def test_no_mcp_manager_no_auto_skill(self):
        terminal = _make_skill("terminal", trigger_servers=["terminal"])
        tools = [{"function": {"name": "run_command"}}]
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ):
            result = get_skills_to_inject(tools, [], mcp_manager=None)
        assert result == []

    def test_youtube_skill_auto_injected_from_url(self):
        youtube = _make_skill("youtube", trigger_servers=[])
        query = "Can you summarize this? https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject([], [], user_query=query)
        assert len(result) == 1
        assert result[0].name == "youtube"

    def test_youtube_skill_not_auto_injected_without_url(self):
        youtube = _make_skill("youtube", trigger_servers=[])
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject([], [], user_query="Summarize that video")
        assert result == []

    def test_forced_skips_auto_detect(self):
        """When the user uses a slash command, only forced skills are returned.
        Auto-detect is skipped — the user declared their intent explicitly."""
        websearch = _make_skill("websearch", trigger_servers=["websearch"])
        terminal = _make_skill("terminal", trigger_servers=["terminal"])
        mcp = _make_mcp_manager({"run_command": "terminal"})
        tools = [{"function": {"name": "run_command"}}]
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal, websearch]),
        ):
            result = get_skills_to_inject(tools, [websearch], mcp_manager=mcp)
        # Only websearch (the forced skill) — terminal is NOT auto-added.
        assert len(result) == 1
        assert result[0].name == "websearch"


class TestBuildSkillManifest:
    def test_empty_when_no_skills(self):
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([]),
        ):
            result = build_skill_manifest()
        assert result == ""

    def test_lists_enabled_skills(self):
        terminal = _make_skill("terminal")
        filesystem = _make_skill("filesystem")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal, filesystem]),
        ):
            result = build_skill_manifest()
        assert "## Available Skills" in result
        assert "**terminal**" in result
        assert "**filesystem**" in result

    def test_manifest_includes_navigation_instructions(self):
        terminal = _make_skill("terminal")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ), patch("source.config.SKILLS_DIR", Path("/fake/skills")):
            result = build_skill_manifest()
        assert "Skills directory:" in result
        assert "read_file" in result
        assert "list_directory" in result
        assert "references/" in result

    def test_manifest_shows_folder_paths(self):
        terminal = _make_skill("terminal")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ), patch("source.config.SKILLS_DIR", Path("/fake/skills")):
            result = build_skill_manifest()
        # Folder path should appear (forward-slashed)
        assert "Folder:" in result
        assert "(builtin)" in result


class TestBuildSkillsPromptBlock:
    def test_empty_skills_no_manifest(self):
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
        assert "---" in result

    def test_manifest_included(self):
        manifest = "## Available Skills\n- **terminal** — desc"
        result = build_skills_prompt_block([], manifest=manifest)
        assert "Available Skills" in result

    def test_manifest_plus_skills(self):
        manifest = "## Available Skills\n- **terminal** — desc"
        skills = [_make_skill("terminal", content="Full terminal docs")]
        result = build_skills_prompt_block(skills, manifest=manifest)
        assert "Available Skills" in result
        assert "Full terminal docs" in result

    def test_whitespace_trimmed(self):
        skills = [_make_skill("test", content="  content with spaces  ")]
        result = build_skills_prompt_block(skills)
        assert "content with spaces" in result
