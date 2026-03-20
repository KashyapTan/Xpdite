"""Tests for source/mcp_integration/skill_injector.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from source.mcp_integration.skill_injector import (
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


def _mock_manager(skills):
    """Return a mock SkillManager with the given skills list."""
    manager = MagicMock()
    enabled = [s for s in skills if s.enabled]
    manager.get_enabled_skills.return_value = enabled
    return manager


class TestGetSkillsToInject:
    def test_no_skills_no_forced(self):
        """No skills returned when no forced skills and no YouTube URL."""
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([]),
        ):
            result = get_skills_to_inject(forced_skills=[])
        assert result == []

    def test_forced_skills_returned(self):
        """Forced skills (from slash commands) are always returned."""
        terminal = _make_skill("terminal")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ):
            result = get_skills_to_inject(forced_skills=[terminal])
        assert len(result) == 1
        assert result[0].name == "terminal"

    def test_multiple_forced_skills(self):
        """Multiple forced skills from multiple slash commands."""
        terminal = _make_skill("terminal")
        filesystem = _make_skill("filesystem")
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal, filesystem]),
        ):
            result = get_skills_to_inject(forced_skills=[terminal, filesystem])
        assert len(result) == 2
        names = [s.name for s in result]
        assert "terminal" in names
        assert "filesystem" in names

    def test_youtube_skill_auto_injected_from_url(self):
        """YouTube skill is auto-injected when query contains a YouTube URL."""
        youtube = _make_skill("youtube", trigger_servers=[])
        query = "Can you summarize this? https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject(forced_skills=[], user_query=query)
        assert len(result) == 1
        assert result[0].name == "youtube"

    def test_youtube_skill_with_youtu_be_url(self):
        """YouTube skill is auto-injected for youtu.be short URLs."""
        youtube = _make_skill("youtube", trigger_servers=[])
        query = "Check this out: https://youtu.be/dQw4w9WgXcQ"
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject(forced_skills=[], user_query=query)
        assert len(result) == 1
        assert result[0].name == "youtube"

    def test_youtube_skill_not_auto_injected_without_url(self):
        """YouTube skill is NOT auto-injected when no YouTube URL present."""
        youtube = _make_skill("youtube", trigger_servers=[])
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject(forced_skills=[], user_query="Summarize that video")
        assert result == []

    def test_disabled_youtube_skill_not_injected(self):
        """Disabled YouTube skill is not auto-injected even with URL."""
        youtube = _make_skill("youtube", enabled=False, trigger_servers=[])
        query = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube]),
        ):
            result = get_skills_to_inject(forced_skills=[], user_query=query)
        # Disabled skill not in enabled list, so not returned
        assert result == []

    def test_forced_skills_take_priority_over_youtube(self):
        """When forced skills are present, even with YouTube URL, only forced returned."""
        youtube = _make_skill("youtube", trigger_servers=[])
        terminal = _make_skill("terminal")
        query = "https://www.youtube.com/watch?v=test"
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([youtube, terminal]),
        ):
            result = get_skills_to_inject(forced_skills=[terminal], user_query=query)
        # Forced skills returned, YouTube not auto-added
        assert len(result) == 1
        assert result[0].name == "terminal"

    def test_no_auto_detection_without_youtube_url(self):
        """No skills auto-injected without YouTube URL or forced skills.
        
        Unlike the old behavior, there is no auto-detection based on retrieved tools.
        The LLM should use list_skills/use_skill tools instead.
        """
        terminal = _make_skill("terminal", trigger_servers=["terminal"])
        with patch(
            "source.mcp_integration.skill_injector._get_manager",
            return_value=_mock_manager([terminal]),
        ):
            result = get_skills_to_inject(forced_skills=[], user_query="Run a command")
        assert result == []


class TestBuildSkillsPromptBlock:
    def test_empty_skills(self):
        """Empty list returns empty string."""
        assert build_skills_prompt_block([]) == ""

    def test_single_skill(self):
        """Single skill content is included with Active Skills header."""
        skills = [_make_skill("terminal", content="Use terminal for commands.")]
        result = build_skills_prompt_block(skills)
        assert "Active Skills" in result
        assert "Use terminal for commands." in result

    def test_multiple_skills_separated(self):
        """Multiple skills are separated by horizontal rules."""
        skills = [
            _make_skill("terminal", content="Terminal instructions"),
            _make_skill("filesystem", content="Filesystem instructions"),
        ]
        result = build_skills_prompt_block(skills)
        assert "Terminal instructions" in result
        assert "Filesystem instructions" in result
        assert "---" in result

    def test_whitespace_trimmed(self):
        """Skill content whitespace is trimmed."""
        skills = [_make_skill("test", content="  content with spaces  ")]
        result = build_skills_prompt_block(skills)
        assert "content with spaces" in result

    def test_empty_content_skill_skipped(self):
        """Skills with empty content don't add empty blocks."""
        skills = [
            _make_skill("empty", content=""),
            _make_skill("nonempty", content="Has content"),
        ]
        result = build_skills_prompt_block(skills)
        assert "Has content" in result
        # Should not have double separators or empty sections
        assert "---\n\n---" not in result

    def test_all_empty_content_returns_empty(self):
        """If all skills have empty content, return empty string."""
        skills = [
            _make_skill("empty1", content=""),
            _make_skill("empty2", content="   "),
        ]
        result = build_skills_prompt_block(skills)
        assert result == ""
