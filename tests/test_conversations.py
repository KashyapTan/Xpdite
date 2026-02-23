"""Tests for source/services/conversations.py — slash command extraction."""

from unittest.mock import patch, MagicMock

from source.services.conversations import _extract_skill_slash_commands_sync


def _make_skill(name, slash_command, enabled=True):
    return {
        "id": 1,
        "skill_name": name,
        "display_name": name.title(),
        "slash_command": slash_command,
        "content": f"Skill {name} content",
        "is_default": True,
        "is_modified": False,
        "enabled": enabled,
        "created_at": 0.0,
        "updated_at": 0.0,
    }


class TestExtractSkillSlashCommands:
    def _call(self, message, skills):
        mock_db = MagicMock()
        mock_db.get_all_skills.return_value = skills
        with patch("source.services.conversations.db", mock_db):
            return _extract_skill_slash_commands_sync(message)

    def test_no_slash_commands(self):
        matched, cleaned = self._call("hello world", [])
        assert matched == []
        assert cleaned == "hello world"

    def test_single_slash_command(self):
        skills = [_make_skill("terminal", "terminal")]
        matched, cleaned = self._call("/terminal run this", skills)
        assert len(matched) == 1
        assert matched[0]["skill_name"] == "terminal"
        assert cleaned == "run this"

    def test_multiple_slash_commands(self):
        skills = [
            _make_skill("terminal", "terminal"),
            _make_skill("websearch", "websearch"),
        ]
        matched, cleaned = self._call("/terminal /websearch do stuff", skills)
        assert len(matched) == 2
        names = {s["skill_name"] for s in matched}
        assert names == {"terminal", "websearch"}
        assert cleaned == "do stuff"

    def test_unknown_slash_command_preserved(self):
        skills = [_make_skill("terminal", "terminal")]
        matched, cleaned = self._call("/unknown hello", skills)
        assert matched == []
        assert "/unknown" in cleaned
        assert "hello" in cleaned

    def test_disabled_skill_not_matched(self):
        skills = [_make_skill("terminal", "terminal", enabled=False)]
        matched, cleaned = self._call("/terminal run this", skills)
        assert matched == []
        assert cleaned == "run this"

    def test_slash_in_middle_of_message(self):
        skills = [_make_skill("websearch", "websearch")]
        matched, cleaned = self._call("please /websearch for python docs", skills)
        assert len(matched) == 1
        assert cleaned == "please for python docs"

    def test_empty_message(self):
        matched, cleaned = self._call("", [])
        assert matched == []
        assert cleaned == ""

    def test_case_sensitivity(self):
        """Slash command matching is case-sensitive (lowercase)."""
        skills = [_make_skill("terminal", "terminal")]
        matched, _ = self._call("/Terminal run this", skills)
        # "/Terminal" → token[1:].lower() = "terminal" → matches
        assert len(matched) == 1
