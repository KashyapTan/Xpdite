"""Tests for source/services/skills_runtime/skills.py — SkillManager service."""

import json
from pathlib import Path

import pytest

from source.services.skills_runtime.skills import SkillManager


# ── Helpers ───────────────────────────────────────────────────────


def _make_seed_skill(seed_dir: Path, name: str, **overrides) -> None:
    """Write a minimal seed skill folder into *seed_dir*."""
    folder = seed_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "description": overrides.get("description", f"{name} description"),
        "slash_command": overrides.get("slash_command", name),
        "trigger_servers": overrides.get("trigger_servers", [name]),
        "version": overrides.get("version", "1.0.0"),
    }
    (folder / "skill.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (folder / "SKILL.md").write_text(
        overrides.get("content", f"# {name}\nDefault content for {name}."),
        encoding="utf-8",
    )


@pytest.fixture()
def skill_env(tmp_path):
    """Create a disposable SkillManager with temp directories."""
    skills_dir = tmp_path / "skills"
    builtin_dir = skills_dir / "builtin"
    user_dir = skills_dir / "user"
    seed_dir = tmp_path / "skills_seed"
    prefs_file = skills_dir / "preferences.json"

    # Create at least one seed skill
    _make_seed_skill(seed_dir, "terminal")
    _make_seed_skill(seed_dir, "filesystem")

    mgr = SkillManager(
        skills_dir=skills_dir,
        builtin_dir=builtin_dir,
        user_dir=user_dir,
        seed_dir=seed_dir,
        preferences_file=prefs_file,
    )
    mgr.initialize()
    return mgr, tmp_path, seed_dir


# ── Initialization & Seeding ─────────────────────────────────────


class TestInitialization:
    def test_creates_directories(self, skill_env):
        mgr, tmp_path, _ = skill_env
        assert (tmp_path / "skills" / "builtin").is_dir()
        assert (tmp_path / "skills" / "user").is_dir()

    def test_seeds_builtins(self, skill_env):
        mgr, tmp_path, _ = skill_env
        assert (tmp_path / "skills" / "builtin" / "terminal" / "skill.json").exists()
        assert (tmp_path / "skills" / "builtin" / "filesystem" / "SKILL.md").exists()

    def test_cache_populated(self, skill_env):
        mgr, *_ = skill_env
        skills = mgr.get_all_skills()
        names = {s.name for s in skills}
        assert "terminal" in names
        assert "filesystem" in names

    def test_all_skills_enabled_by_default(self, skill_env):
        mgr, *_ = skill_env
        for skill in mgr.get_all_skills():
            assert skill.enabled is True


class TestSeedOverwrite:
    def test_seed_overwrites_on_reinit(self, skill_env):
        mgr, tmp_path, _ = skill_env
        # Manually change a builtin file
        md_path = tmp_path / "skills" / "builtin" / "terminal" / "SKILL.md"
        md_path.write_text("MODIFIED", encoding="utf-8")
        assert md_path.read_text(encoding="utf-8") == "MODIFIED"

        # Re-initialize — should overwrite
        mgr.initialize()
        assert md_path.read_text(encoding="utf-8") != "MODIFIED"

    def test_missing_seed_dir_no_crash(self, tmp_path):
        mgr = SkillManager(
            skills_dir=tmp_path / "skills",
            builtin_dir=tmp_path / "skills" / "builtin",
            user_dir=tmp_path / "skills" / "user",
            seed_dir=tmp_path / "nonexistent_seed",
            preferences_file=tmp_path / "skills" / "preferences.json",
        )
        mgr.initialize()  # Should not raise
        assert mgr.get_all_skills() == []


class TestNativeSkillMarkdown:
    def test_loads_native_skill_md_without_skill_json(self, tmp_path):
        skills_dir = tmp_path / "skills"
        builtin_dir = skills_dir / "builtin"
        user_dir = skills_dir / "user"
        seed_dir = tmp_path / "skills_seed"
        prefs_file = skills_dir / "preferences.json"

        native_folder = seed_dir / "planner-skill"
        native_folder.mkdir(parents=True, exist_ok=True)
        (native_folder / "SKILL.md").write_text(
            "---\nname: planner\ncommand: planner:triage\ndescription: Planner skill\n---\n# Planner\n",
            encoding="utf-8",
        )

        mgr = SkillManager(
            skills_dir=skills_dir,
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            seed_dir=seed_dir,
            preferences_file=prefs_file,
        )
        mgr.initialize()

        skill = mgr.get_skill_by_slash_command("planner:triage")
        assert skill is not None
        assert skill.name == "planner"
        assert skill.source == "builtin"


# ── Preferences ──────────────────────────────────────────────────


class TestPreferences:
    def test_toggle_disabled_persists(self, skill_env):
        mgr, tmp_path, _ = skill_env
        mgr.toggle_skill("terminal", False)
        assert mgr.get_skill_by_name("terminal").enabled is False

        # Read raw file
        prefs = json.loads(
            (tmp_path / "skills" / "preferences.json").read_text(encoding="utf-8")
        )
        assert "terminal" in prefs["disabled"]

    def test_toggle_enabled_removes_from_disabled(self, skill_env):
        mgr, tmp_path, _ = skill_env
        mgr.toggle_skill("terminal", False)
        mgr.toggle_skill("terminal", True)
        assert mgr.get_skill_by_name("terminal").enabled is True

        prefs = json.loads(
            (tmp_path / "skills" / "preferences.json").read_text(encoding="utf-8")
        )
        assert "terminal" not in prefs["disabled"]

    def test_toggle_nonexistent_returns_false(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.toggle_skill("nonexistent", False) is False

    def test_preferences_survive_reinit(self, skill_env):
        mgr, *_ = skill_env
        mgr.toggle_skill("terminal", False)
        mgr.initialize()
        assert mgr.get_skill_by_name("terminal").enabled is False

    def test_corrupt_preferences_handled(self, skill_env):
        mgr, tmp_path, _ = skill_env
        prefs_path = tmp_path / "skills" / "preferences.json"
        prefs_path.write_text("NOT VALID JSON", encoding="utf-8")
        mgr.initialize()  # Should not raise
        # All skills should default to enabled
        for s in mgr.get_all_skills():
            assert s.enabled is True


# ── Read API ─────────────────────────────────────────────────────


class TestReadAPI:
    def test_get_all_skills(self, skill_env):
        mgr, *_ = skill_env
        skills = mgr.get_all_skills()
        assert len(skills) == 2

    def test_get_enabled_skills_excludes_disabled(self, skill_env):
        mgr, *_ = skill_env
        mgr.toggle_skill("terminal", False)
        enabled = mgr.get_enabled_skills()
        names = {s.name for s in enabled}
        assert "terminal" not in names
        assert "filesystem" in names

    def test_get_skill_by_name(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.get_skill_by_name("terminal")
        assert skill is not None
        assert skill.name == "terminal"

    def test_get_skill_by_name_missing(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.get_skill_by_name("nope") is None

    def test_get_skill_by_slash_command(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.get_skill_by_slash_command("terminal")
        assert skill is not None
        assert skill.name == "terminal"

    def test_get_skill_by_slash_command_missing(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.get_skill_by_slash_command("nope") is None

    def test_get_skill_content(self, skill_env):
        mgr, *_ = skill_env
        content = mgr.get_skill_content("terminal")
        assert content is not None
        assert "terminal" in content.lower()

    def test_get_skill_content_missing(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.get_skill_content("nope") is None


class TestMarketplaceIsolation:
    def test_custom_manager_skips_marketplace_scan_by_default(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        builtin_dir = skills_dir / "builtin"
        user_dir = skills_dir / "user"
        seed_dir = tmp_path / "skills_seed"
        prefs_file = skills_dir / "preferences.json"

        _make_seed_skill(seed_dir, "terminal")

        def _unexpected_marketplace_lookup():
            raise AssertionError("custom managers should not scan marketplace installs by default")

        monkeypatch.setattr(
            "source.services.marketplace.service.get_marketplace_service",
            _unexpected_marketplace_lookup,
        )

        mgr = SkillManager(
            skills_dir=skills_dir,
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            seed_dir=seed_dir,
            preferences_file=prefs_file,
        )

        mgr.initialize()

        assert mgr.get_skill_by_name("terminal") is not None


# ── Skill dataclass ──────────────────────────────────────────────


class TestSkillDataclass:
    def test_to_dict(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.get_skill_by_name("terminal")
        d = skill.to_dict()
        assert d["name"] == "terminal"
        assert d["source"] == "builtin"
        assert isinstance(d["trigger_servers"], list)
        assert isinstance(d["enabled"], bool)

    def test_read_content_caches(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.get_skill_by_name("terminal")
        c1 = skill.read_content()
        c2 = skill.read_content()
        assert c1 is c2  # Same object reference — cached

    def test_invalidate_content_cache(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.get_skill_by_name("terminal")
        _ = skill.read_content()
        skill.invalidate_content_cache()
        assert skill._content is None


# ── User CRUD ────────────────────────────────────────────────────


class TestUserCRUD:
    def test_create_user_skill(self, skill_env):
        mgr, *_ = skill_env
        skill = mgr.create_user_skill(
            name="my_skill",
            description="Custom skill",
            slash_command="myskill",
            content="# My Skill\nDo custom things.",
        )
        assert skill.name == "my_skill"
        assert skill.source == "user"
        assert mgr.get_skill_by_name("my_skill") is not None

    def test_create_duplicate_user_skill_raises(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="custom1", description="A", slash_command="c1", content="stuff"
        )
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_user_skill(
                name="custom1", description="B", slash_command="c2", content="stuff"
            )

    def test_create_user_skill_overrides_builtin(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="terminal",
            description="My terminal",
            slash_command="terminal",
            content="Custom terminal behavior",
        )
        skill = mgr.get_skill_by_name("terminal")
        assert skill.source == "user"
        assert "Custom terminal" in skill.read_content()

    def test_create_duplicate_slash_command_raises(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="s1", description="A", slash_command="shared", content="data"
        )
        with pytest.raises(ValueError, match="already in use"):
            mgr.create_user_skill(
                name="s2", description="B", slash_command="shared", content="data"
            )

    def test_update_user_skill(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="editable", description="V1", slash_command="ed", content="V1 content"
        )
        updated = mgr.update_user_skill(
            "editable", description="V2", content="V2 content"
        )
        assert updated.description == "V2"
        assert mgr.get_skill_content("editable") == "V2 content"

    def test_update_builtin_raises(self, skill_env):
        mgr, *_ = skill_env
        with pytest.raises(ValueError, match="Cannot edit builtin"):
            mgr.update_user_skill("terminal", description="hacked")

    def test_update_nonexistent_raises(self, skill_env):
        mgr, *_ = skill_env
        with pytest.raises(ValueError, match="not found"):
            mgr.update_user_skill("nope", description="hacked")

    def test_delete_user_skill(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="deleteme", description="D", slash_command="del", content="bye"
        )
        assert mgr.delete_user_skill("deleteme") is True
        assert mgr.get_skill_by_name("deleteme") is None

    def test_delete_builtin_returns_false(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.delete_user_skill("terminal") is False

    def test_delete_nonexistent_returns_false(self, skill_env):
        mgr, *_ = skill_env
        assert mgr.delete_user_skill("nope") is False


# ── Reference files ──────────────────────────────────────────────


class TestReferenceFiles:
    def test_add_reference_file(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="reftest", description="R", slash_command="ref", content="content"
        )
        mgr.add_reference_file("reftest", "notes.md", "# Notes\nSome notes.")
        refs_dir = mgr.get_skill_by_name("reftest").folder_path / "references"
        assert (refs_dir / "notes.md").exists()
        assert "Some notes" in (refs_dir / "notes.md").read_text(encoding="utf-8")

    def test_add_reference_to_builtin_raises(self, skill_env):
        mgr, *_ = skill_env
        with pytest.raises(ValueError, match="Cannot add references to builtin"):
            mgr.add_reference_file("terminal", "hack.md", "hacked")

    def test_add_reference_to_nonexistent_raises(self, skill_env):
        mgr, *_ = skill_env
        with pytest.raises(ValueError, match="not found"):
            mgr.add_reference_file("nope", "file.md", "data")


# ── Overrides UI helper ──────────────────────────────────────────


class TestOverridesUI:
    def test_overridden_builtin_appears_in_list(self, skill_env):
        mgr, *_ = skill_env
        mgr.create_user_skill(
            name="terminal",
            description="Custom terminal",
            slash_command="terminal",
            content="Custom",
        )
        all_dicts = mgr.get_all_skills_with_overrides()
        overridden = [d for d in all_dicts if d.get("overridden_by_user")]
        assert len(overridden) >= 1
        # There should be both the overridden builtin and the user version
        names = [d["name"] for d in all_dicts]
        assert names.count("terminal") == 2
