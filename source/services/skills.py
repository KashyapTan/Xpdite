"""
Filesystem-backed skill management service.

Skills are self-contained folders stored in ``user_data/skills/``.
Builtin skills live under ``builtin/`` and are overwritten from seed files
on every app startup.  User skills live under ``user/`` and can override
builtins by sharing the same ``name`` field in ``skill.json``.

A lightweight ``preferences.json`` in the skills root stores user toggles
(enabled/disabled) so builtin overwrites never reset them.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Strict pattern for skill names and filenames — no path traversal.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_safe_name(value: str, label: str = "name") -> None:
    """Raise ValueError if *value* contains path traversal or illegal chars."""
    if not value or not _SAFE_NAME_RE.match(value):
        raise ValueError(
            f"Invalid {label}: must contain only letters, digits, hyphens, "
            f"and underscores (got {value!r})"
        )


# ── Data model ────────────────────────────────────────────────────

@dataclass
class Skill:
    """In-memory representation of a skill folder."""

    name: str
    description: str
    slash_command: Optional[str]
    trigger_servers: List[str]
    version: str
    source: str  # "builtin" | "user"
    folder_path: Path
    enabled: bool = True
    overridden_by_user: bool = False

    # Lazily loaded — not read until explicitly requested.
    # NOTE: the cache lives on the Skill *instance*.  After _reload_cache()
    # new instances are created with _content=None so stale data is not served.
    # However, callers who captured a reference to an old Skill object will
    # still see the old cached content until they re-fetch from the manager.
    _content: Optional[str] = field(default=None, repr=False)

    def read_content(self) -> str:
        """Read ``SKILL.md`` from disk (cached after first call)."""
        if self._content is None:
            skill_md = self.folder_path / "SKILL.md"
            if skill_md.exists():
                self._content = skill_md.read_text(encoding="utf-8")
            else:
                self._content = ""
        return self._content

    def invalidate_content_cache(self) -> None:
        self._content = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the REST API / frontend."""
        return {
            "name": self.name,
            "description": self.description,
            "slash_command": self.slash_command,
            "trigger_servers": self.trigger_servers,
            "version": self.version,
            "source": self.source,
            "enabled": self.enabled,
            "overridden_by_user": self.overridden_by_user,
            "folder_path": str(self.folder_path),
        }


# ── Manager ───────────────────────────────────────────────────────

class SkillManager:
    """Filesystem-first skill loader, cache, and CRUD manager.

    **Thread-safety note:** all public methods that touch the filesystem
    should be called from the event loop via ``run_in_thread`` when invoked
    from async handlers.  The in-memory cache is not locked because all
    writes go through the single uvicorn event loop.
    """

    def __init__(
        self,
        skills_dir: Path,
        builtin_dir: Path,
        user_dir: Path,
        seed_dir: Path,
        preferences_file: Path,
    ) -> None:
        self._skills_dir = skills_dir
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._seed_dir = seed_dir
        self._preferences_file = preferences_file

        # In-memory cache: maps skill name → Skill
        self._cache: Dict[str, Skill] = {}
        # Preferences (disabled skill names)
        self._disabled: set[str] = set()

    # ── Initialization (call once at startup) ─────────────────────

    def initialize(self) -> None:
        """Seed builtins, load preferences, populate cache."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._builtin_dir.mkdir(parents=True, exist_ok=True)
        self._user_dir.mkdir(parents=True, exist_ok=True)

        self._seed_builtins()
        self._load_preferences()
        self._reload_cache()
        logger.info(
            "SkillManager initialized: %d skill(s) loaded (%d builtin, %d user)",
            len(self._cache),
            sum(1 for s in self._cache.values() if s.source == "builtin"),
            sum(1 for s in self._cache.values() if s.source == "user"),
        )

    # ── Seeding ───────────────────────────────────────────────────

    def _seed_builtins(self) -> None:
        """Copy seed skill folders into ``builtin/``, overwriting every time."""
        if not self._seed_dir.exists():
            logger.warning("Skill seed directory not found: %s", self._seed_dir)
            return

        for src_folder in self._seed_dir.iterdir():
            if not src_folder.is_dir():
                continue
            skill_json = src_folder / "skill.json"
            if not skill_json.exists():
                continue
            dest = self._builtin_dir / src_folder.name
            # Overwrite builtin folder entirely
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src_folder, dest)
            logger.debug("Seeded builtin skill: %s", src_folder.name)

    # ── Preferences ───────────────────────────────────────────────

    def _load_preferences(self) -> None:
        """Load ``preferences.json`` (disabled skill names)."""
        if self._preferences_file.exists():
            try:
                data = json.loads(
                    self._preferences_file.read_text(encoding="utf-8")
                )
                self._disabled = set(data.get("disabled", []))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read skill preferences: %s", exc)
                self._disabled = set()
        else:
            self._disabled = set()

    def _save_preferences(self) -> None:
        """Persist current disabled set to disk."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        data = {"disabled": sorted(self._disabled)}
        self._preferences_file.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    # ── Cache ─────────────────────────────────────────────────────

    def _reload_cache(self) -> None:
        """Scan both directories and rebuild the in-memory cache."""
        self._cache.clear()

        builtin_skills: Dict[str, Skill] = {}
        user_skills: Dict[str, Skill] = {}

        # Load builtins first
        for skill in self._scan_directory(self._builtin_dir, source="builtin"):
            builtin_skills[skill.name] = skill

        # Load user skills (overrides builtins with same name)
        for skill in self._scan_directory(self._user_dir, source="user"):
            user_skills[skill.name] = skill

        # Merge: user skills take precedence
        for name, skill in builtin_skills.items():
            if name in user_skills:
                skill.overridden_by_user = True
            skill.enabled = name not in self._disabled
            self._cache[name] = skill

        for name, skill in user_skills.items():
            skill.enabled = name not in self._disabled
            self._cache[name] = skill  # overwrites builtin if same name

    def _scan_directory(self, directory: Path, source: str) -> List[Skill]:
        """Load all valid skill folders from a directory."""
        skills: list[Skill] = []
        if not directory.exists():
            return skills

        for folder in sorted(directory.iterdir()):
            if not folder.is_dir():
                continue
            skill = self._load_skill_folder(folder, source)
            if skill is not None:
                skills.append(skill)

        return skills

    def _load_skill_folder(self, folder: Path, source: str) -> Optional[Skill]:
        """Parse a single skill folder.  Returns None on invalid/missing files."""
        skill_json_path = folder / "skill.json"
        if not skill_json_path.exists():
            return None

        try:
            meta = json.loads(skill_json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Bad skill.json in %s: %s", folder, exc)
            return None

        name = meta.get("name")
        if not name:
            logger.warning("skill.json missing 'name' in %s", folder)
            return None

        return Skill(
            name=name,
            description=meta.get("description", ""),
            slash_command=meta.get("slash_command"),
            trigger_servers=meta.get("trigger_servers", []),
            version=meta.get("version", "0.0.0"),
            source=source,
            folder_path=folder,
        )

    # ── Public read API ───────────────────────────────────────────

    def get_all_skills(self) -> List[Skill]:
        """Return all skills (user overrides replace builtins)."""
        return list(self._cache.values())

    def get_all_skills_with_overrides(self) -> List[Dict[str, Any]]:
        """Return all skills for the UI, including overridden builtins.

        Overridden builtins appear with ``overridden_by_user=True``
        followed by the user skill that overrides them.
        """
        result: list[Dict[str, Any]] = []
        # Show overridden builtins first (greyed out in UI)
        for folder in sorted(self._builtin_dir.iterdir()) if self._builtin_dir.exists() else []:
            if not folder.is_dir():
                continue
            skill = self._load_skill_folder(folder, "builtin")
            if skill is None:
                continue
            if skill.name in self._cache and self._cache[skill.name].source == "user":
                skill.overridden_by_user = True
                skill.enabled = skill.name not in self._disabled
                result.append(skill.to_dict())
        # Then add all active skills from cache
        for skill in self._cache.values():
            result.append(skill.to_dict())
        return result

    def get_enabled_skills(self) -> List[Skill]:
        """Return only enabled, non-overridden skills."""
        return [s for s in self._cache.values() if s.enabled]

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        return self._cache.get(name)

    def get_skill_by_slash_command(self, command: str) -> Optional[Skill]:
        for skill in self._cache.values():
            if skill.slash_command == command:
                return skill
        return None

    def get_skill_content(self, name: str) -> Optional[str]:
        """Read full SKILL.md for a skill."""
        skill = self._cache.get(name)
        if skill is None:
            return None
        return skill.read_content()

    # ── Public write API ──────────────────────────────────────────

    def toggle_skill(self, name: str, enabled: bool) -> bool:
        """Enable or disable a skill.  Returns False if skill not found."""
        skill = self._cache.get(name)
        if skill is None:
            return False

        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)

        skill.enabled = enabled
        self._save_preferences()
        return True

    def create_user_skill(
        self,
        name: str,
        description: str,
        slash_command: Optional[str],
        content: str,
        trigger_servers: Optional[List[str]] = None,
    ) -> Skill:
        """Create a new user skill folder.  Raises ValueError on conflict."""
        _validate_safe_name(name, "skill name")

        # Validate name uniqueness among user skills
        existing = self._cache.get(name)
        if existing and existing.source == "user":
            raise ValueError(f"User skill '{name}' already exists")

        # Validate slash command uniqueness
        if slash_command:
            for s in self._cache.values():
                if s.slash_command == slash_command and s.source == "user":
                    raise ValueError(
                        f"Slash command '/{slash_command}' already in use by '{s.name}'"
                    )

        folder = self._user_dir / name
        folder.mkdir(parents=True, exist_ok=True)

        meta = {
            "name": name,
            "description": description,
            "slash_command": slash_command,
            "trigger_servers": trigger_servers or [],
            "version": "1.0.0",
        }
        (folder / "skill.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        (folder / "SKILL.md").write_text(content, encoding="utf-8")

        # Rebuild cache
        self._reload_cache()
        return self._cache[name]

    def update_user_skill(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        slash_command: Optional[str] = ...,  # type: ignore[assignment]
        content: Optional[str] = None,
        trigger_servers: Optional[List[str]] = None,
    ) -> Skill:
        """Update an existing user skill.  Raises ValueError on problems."""
        skill = self._cache.get(name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")
        if skill.source != "user":
            raise ValueError("Cannot edit builtin skills")

        # Read current metadata
        meta_path = skill.folder_path / "skill.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        if description is not None:
            meta["description"] = description
        if slash_command is not ...:
            # Validate uniqueness if changing
            if slash_command and slash_command != skill.slash_command:
                for s in self._cache.values():
                    if s.slash_command == slash_command and s.name != name:
                        raise ValueError(
                            f"Slash command '/{slash_command}' already in use by '{s.name}'"
                        )
            meta["slash_command"] = slash_command
        if trigger_servers is not None:
            meta["trigger_servers"] = trigger_servers

        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if content is not None:
            (skill.folder_path / "SKILL.md").write_text(content, encoding="utf-8")
            skill.invalidate_content_cache()

        self._reload_cache()
        return self._cache[name]

    def delete_user_skill(self, name: str) -> bool:
        """Delete a user skill folder.  Returns False if not found or builtin."""
        skill = self._cache.get(name)
        if skill is None or skill.source != "user":
            return False

        shutil.rmtree(skill.folder_path, ignore_errors=True)
        self._disabled.discard(name)
        self._save_preferences()
        self._reload_cache()
        return True

    def add_reference_file(self, name: str, filename: str, content: str) -> None:
        """Add a reference .md file to a user skill's references/ folder."""
        # Strip .md suffix for validation, then re-add
        stem = filename.removesuffix(".md")
        _validate_safe_name(stem, "reference filename")

        skill = self._cache.get(name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")
        if skill.source != "user":
            raise ValueError("Cannot add references to builtin skills")

        refs_dir = skill.folder_path / "references"
        refs_dir.mkdir(exist_ok=True)
        (refs_dir / filename).write_text(content, encoding="utf-8")


# ── Singleton ─────────────────────────────────────────────────────

_instance: Optional[SkillManager] = None
_instance_lock = threading.Lock()


def get_skill_manager() -> SkillManager:
    """Return the global SkillManager singleton, creating it on first call."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        # Double-checked locking — another thread may have created it.
        if _instance is not None:
            return _instance
        from ..config import (
            SKILLS_DIR,
            BUILTIN_SKILLS_DIR,
            USER_SKILLS_DIR,
            SKILLS_SEED_DIR,
            SKILLS_PREFERENCES_FILE,
        )

        _instance = SkillManager(
            skills_dir=SKILLS_DIR,
            builtin_dir=BUILTIN_SKILLS_DIR,
            user_dir=USER_SKILLS_DIR,
            seed_dir=SKILLS_SEED_DIR,
            preferences_file=SKILLS_PREFERENCES_FILE,
        )
        _instance.initialize()
        return _instance
    return _instance  # unreachable but keeps type checkers happy
