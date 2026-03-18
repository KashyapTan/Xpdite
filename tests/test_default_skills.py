"""Tests for skill seed files — data integrity of the shipped builtin skills."""

import json
import os

import pytest

from source.config import SKILLS_SEED_DIR


def _load_seed_skills():
    """Walk SKILLS_SEED_DIR and return a list of (name, skill_json_dict) tuples."""
    skills = []
    if not os.path.isdir(SKILLS_SEED_DIR):
        return skills
    for name in os.listdir(SKILLS_SEED_DIR):
        folder = os.path.join(SKILLS_SEED_DIR, name)
        if not os.path.isdir(folder):
            continue
        json_path = os.path.join(folder, "skill.json")
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                skills.append((name, json.load(f)))
    return skills


SEED_SKILLS = _load_seed_skills()


class TestSkillSeeds:
    def test_seed_dir_exists(self):
        assert os.path.isdir(SKILLS_SEED_DIR), f"Missing seed directory: {SKILLS_SEED_DIR}"

    def test_not_empty(self):
        assert len(SEED_SKILLS) > 0, "No skill seeds found"

    @pytest.mark.parametrize("name,data", SEED_SKILLS, ids=[s[0] for s in SEED_SKILLS])
    def test_required_keys_present(self, name, data):
        required = {"name", "description", "slash_command", "trigger_servers", "version"}
        missing = required - set(data.keys())
        assert not missing, f"Skill '{name}' missing keys: {missing}"

    @pytest.mark.parametrize("name,data", SEED_SKILLS, ids=[s[0] for s in SEED_SKILLS])
    def test_skill_md_exists(self, name, data):
        md_path = os.path.join(SKILLS_SEED_DIR, name, "SKILL.md")
        assert os.path.isfile(md_path), f"Missing SKILL.md for '{name}'"

    @pytest.mark.parametrize("name,data", SEED_SKILLS, ids=[s[0] for s in SEED_SKILLS])
    def test_skill_md_not_empty(self, name, data):
        md_path = os.path.join(SKILLS_SEED_DIR, name, "SKILL.md")
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.strip(), f"SKILL.md for '{name}' is empty"

    @pytest.mark.parametrize("name,data", SEED_SKILLS, ids=[s[0] for s in SEED_SKILLS])
    def test_folder_matches_name(self, name, data):
        assert data["name"] == name, f"Folder '{name}' has mismatched name '{data['name']}'"

    def test_skill_names_unique(self):
        names = [data["name"] for _, data in SEED_SKILLS]
        assert len(names) == len(set(names)), "Duplicate skill name found"

    def test_slash_commands_unique(self):
        commands = [data["slash_command"] for _, data in SEED_SKILLS]
        assert len(commands) == len(set(commands)), "Duplicate slash_command found"

    def test_known_skills_present(self):
        names = {data["name"] for _, data in SEED_SKILLS}
        assert "terminal" in names
        assert "filesystem" in names
        assert "websearch" in names
        assert "youtube" in names

    def test_filesystem_skill_mentions_search_tools(self):
        md_path = os.path.join(SKILLS_SEED_DIR, "filesystem", "SKILL.md")
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "glob_files" in content
        assert "grep_files" in content
        assert "Do NOT use `run_command`" in content

    @pytest.mark.parametrize("name,data", SEED_SKILLS, ids=[s[0] for s in SEED_SKILLS])
    def test_trigger_servers_is_list(self, name, data):
        assert isinstance(data["trigger_servers"], list), f"trigger_servers must be list for '{name}'"
