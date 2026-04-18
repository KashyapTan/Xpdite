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
_CANONICAL_COMMAND_RE = re.compile(r"^[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _validate_safe_name(value: str, label: str = "name") -> None:
    """Raise ValueError if *value* contains path traversal or illegal chars."""
    if not value or not _SAFE_NAME_RE.match(value):
        raise ValueError(
            f"Invalid {label}: must contain only letters, digits, hyphens, "
            f"and underscores (got {value!r})"
        )


def _validate_slash_command(value: str, label: str = "slash command") -> None:
    if not value or not _CANONICAL_COMMAND_RE.match(value):
        raise ValueError(
            f"Invalid {label}: must use segment(:segment)* with letters, digits, hyphens, and underscores"
        )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_meta, body = match.groups()
    metadata: dict[str, Any] = {}
    current_list_key: Optional[str] = None

    for line in raw_meta.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            metadata.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not raw_value:
            metadata[key] = []
            current_list_key = key
            continue
        if raw_value.startswith("[") and raw_value.endswith("]"):
            items = [
                item.strip().strip("'\"") for item in raw_value[1:-1].split(",")
            ]
            metadata[key] = [item for item in items if item]
            continue
        metadata[key] = raw_value.strip("'\"")

    return metadata, body


# ── Data model ────────────────────────────────────────────────────

@dataclass
class Skill:
    """In-memory representation of a skill folder."""

    name: str
    description: str
    slash_command: Optional[str]
    trigger_servers: List[str]
    version: str
    source: str  # "builtin" | "user" | "marketplace"
    folder_path: Path
    canonical_id: Optional[str] = None
    enabled: bool = True
    overridden_by_user: bool = False
    install_id: Optional[str] = None
    folder_slug: Optional[str] = None
    content_path: Optional[Path] = None

    # Lazily loaded — not read until explicitly requested.
    # NOTE: the cache lives on the Skill *instance*.  After _reload_cache()
    # new instances are created with _content=None so stale data is not served.
    # However, callers who captured a reference to an old Skill object will
    # still see the old cached content until they re-fetch from the manager.
    _content: Optional[str] = field(default=None, repr=False)

    def read_content(self) -> str:
        """Read ``SKILL.md`` from disk (cached after first call)."""
        if self._content is None:
            content_path = self.content_path or (self.folder_path / "SKILL.md")
            if content_path.exists():
                self._content = content_path.read_text(encoding="utf-8")
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
            "canonical_id": self.canonical_id,
            "trigger_servers": self.trigger_servers,
            "version": self.version,
            "source": self.source,
            "enabled": self.enabled,
            "overridden_by_user": self.overridden_by_user,
            "folder_path": str(self.folder_path),
            "install_id": self.install_id,
            "folder_slug": self.folder_slug,
            "content_path": str(self.content_path) if self.content_path else None,
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
        *,
        include_marketplace: bool = False,
    ) -> None:
        self._skills_dir = skills_dir
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._seed_dir = seed_dir
        self._preferences_file = preferences_file
        self._include_marketplace = include_marketplace

        # In-memory cache: maps skill name → Skill
        self._cache: Dict[str, Skill] = {}
        # Preferences (disabled skill names)
        self._disabled: set[str] = set()

    @staticmethod
    def _preference_key(skill: Skill) -> str:
        return skill.canonical_id or skill.slash_command or skill.name

    def _is_skill_enabled(self, skill: Skill) -> bool:
        pref_key = self._preference_key(skill)
        return pref_key not in self._disabled and skill.name not in self._disabled

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
            "SkillManager initialized: %d skill(s) loaded (%d builtin, %d user, %d marketplace)",
            len(self._cache),
            sum(1 for s in self._cache.values() if s.source == "builtin"),
            sum(1 for s in self._cache.values() if s.source == "user"),
            sum(1 for s in self._cache.values() if s.source == "marketplace"),
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
            skill_md = src_folder / "SKILL.md"
            if not skill_json.exists() and not skill_md.exists():
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
        marketplace_skills: Dict[str, Skill] = {}

        # Load builtins first
        for skill in self._scan_directory(self._builtin_dir, source="builtin"):
            builtin_skills[skill.name] = skill

        # Load user skills (overrides builtins with same name)
        for skill in self._scan_directory(self._user_dir, source="user"):
            user_skills[skill.name] = skill

        for skill in self._scan_marketplace_skills():
            marketplace_skills[skill.name] = skill

        # Merge: user skills take precedence
        for name, skill in builtin_skills.items():
            if name in user_skills:
                skill.overridden_by_user = True
            skill.enabled = self._is_skill_enabled(skill)
            self._cache[name] = skill

        for name, skill in user_skills.items():
            skill.enabled = self._is_skill_enabled(skill)
            self._cache[name] = skill  # overwrites builtin if same name

        for name, skill in marketplace_skills.items():
            skill.enabled = self._is_skill_enabled(skill)
            if name not in self._cache:
                self._cache[name] = skill

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

    def _scan_marketplace_skills(self) -> List[Skill]:
        if not self._include_marketplace:
            return []

        from ..marketplace.service import get_marketplace_service

        service = get_marketplace_service()
        skills: list[Skill] = []
        for install in service.list_installs():
            if not install.get("enabled"):
                continue
            component_manifest = install.get("component_manifest") or {}
            if install["item_kind"] == "skill":
                skill = self._load_marketplace_skill_install(install, component_manifest)
                if skill is not None:
                    skills.append(skill)
            elif install["item_kind"] == "plugin":
                skills.extend(
                    self._load_marketplace_plugin_install(install, component_manifest)
                )
        return skills

    def _load_marketplace_skill_install(
        self, install: Dict[str, Any], component_manifest: Dict[str, Any]
    ) -> Optional[Skill]:
        skill_path_value = component_manifest.get("skill_path")
        if not skill_path_value:
            return None
        skill_path = Path(str(skill_path_value))
        if not skill_path.exists():
            return None

        metadata, _body = _parse_frontmatter(skill_path.read_text(encoding="utf-8"))
        slash_command = str(
            metadata.get("slash_command")
            or metadata.get("command")
            or install.get("canonical_id")
            or metadata.get("name")
            or install["display_name"]
        )
        if slash_command:
            _validate_slash_command(slash_command)

        name = str(metadata.get("name") or install["display_name"])
        return Skill(
            name=name,
            description=str(metadata.get("description") or install["display_name"]),
            slash_command=slash_command or None,
            canonical_id=install.get("canonical_id") or slash_command or name,
            trigger_servers=list(metadata.get("trigger_servers") or []),
            version=str(metadata.get("version") or "1.0.0"),
            source="marketplace",
            folder_path=skill_path.parent,
            install_id=install["id"],
            folder_slug=skill_path.parent.name,
            content_path=skill_path,
        )

    def _load_marketplace_plugin_install(
        self, install: Dict[str, Any], component_manifest: Dict[str, Any]
    ) -> List[Skill]:
        plugin_manifest = component_manifest.get("plugin_manifest") or {}
        plugin_id = str(
            install.get("canonical_id")
            or plugin_manifest.get("name")
            or install["display_name"]
        )
        if plugin_id:
            _validate_slash_command(plugin_id)

        skills: list[Skill] = []
        for item in component_manifest.get("skills") or []:
            metadata = item.get("metadata") or {}
            skill_name = str(item.get("name") or metadata.get("name") or "skill")
            local_command = str(
                item.get("slash_command")
                or metadata.get("slash_command")
                or metadata.get("command")
                or skill_name
            )
            slash_command = (
                local_command
                if ":" in local_command
                else f"{plugin_id}:{local_command}"
            )
            _validate_slash_command(slash_command)
            skill_path = Path(str(item.get("path") or install["install_root"]))
            skills.append(
                Skill(
                    name=f"{plugin_id}:{skill_name}",
                    description=str(item.get("description") or metadata.get("description") or ""),
                    slash_command=slash_command,
                    canonical_id=slash_command,
                    trigger_servers=list(metadata.get("trigger_servers") or []),
                    version=str(plugin_manifest.get("version") or "1.0.0"),
                    source="marketplace",
                    folder_path=skill_path.parent if skill_path.name.lower() == "skill.md" else skill_path,
                    install_id=install["id"],
                    folder_slug=skill_path.parent.name if skill_path.name.lower() == "skill.md" else skill_path.name,
                    content_path=skill_path if skill_path.name.lower() == "skill.md" else None,
                )
            )
        for item in component_manifest.get("commands") or []:
            metadata = item.get("metadata") or {}
            command_name = str(
                item.get("slash_command")
                or metadata.get("slash_command")
                or metadata.get("command")
                or item.get("name")
                or "command"
            ).strip()
            if not command_name:
                continue
            _validate_slash_command(command_name)
            command_path = Path(str(item.get("path") or install["install_root"]))
            skills.append(
                Skill(
                    name=command_name,
                    description=str(item.get("description") or metadata.get("description") or ""),
                    slash_command=command_name,
                    canonical_id=command_name,
                    trigger_servers=[],
                    version=str(plugin_manifest.get("version") or "1.0.0"),
                    source="marketplace",
                    folder_path=command_path.parent,
                    install_id=install["id"],
                    folder_slug=command_path.stem,
                    content_path=command_path,
                )
            )
        return skills

    def _load_skill_folder(self, folder: Path, source: str) -> Optional[Skill]:
        """Parse a single skill folder.  Returns None on invalid/missing files."""
        skill_json_path = folder / "skill.json"
        skill_md_path = folder / "SKILL.md"
        if not skill_json_path.exists() and not skill_md_path.exists():
            return None

        meta: dict[str, Any] = {}
        if skill_json_path.exists():
            try:
                meta = json.loads(skill_json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Bad skill.json in %s: %s", folder, exc)
                return None
        elif skill_md_path.exists():
            try:
                meta, _body = _parse_frontmatter(skill_md_path.read_text(encoding="utf-8"))
            except OSError as exc:
                logger.warning("Bad SKILL.md in %s: %s", folder, exc)
                return None

        name = meta.get("name")
        if not name:
            logger.warning("skill.json missing 'name' in %s", folder)
            return None

        slash_command = meta.get("slash_command") or meta.get("command")
        if slash_command:
            _validate_slash_command(str(slash_command))

        return Skill(
            name=name,
            description=meta.get("description", ""),
            slash_command=slash_command,
            canonical_id=slash_command or name,
            trigger_servers=meta.get("trigger_servers", []),
            version=meta.get("version", "0.0.0"),
            source=source,
            folder_path=folder,
            folder_slug=folder.name,
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
                skill.enabled = self._is_skill_enabled(skill)
                result.append(skill.to_dict())
        # Then add all active skills from cache
        for skill in self._cache.values():
            result.append(skill.to_dict())
        return result

    def get_enabled_skills(self) -> List[Skill]:
        """Return only enabled, non-overridden skills."""
        return [s for s in self._cache.values() if s.enabled]

    def reload(self) -> None:
        self._reload_cache()

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        skill = self._cache.get(name)
        if skill is not None:
            return skill
        for candidate in self._cache.values():
            if candidate.slash_command == name or candidate.canonical_id == name:
                return candidate
        return None

    def get_skill_by_slash_command(self, command: str) -> Optional[Skill]:
        for skill in self._cache.values():
            if (skill.slash_command or "").lower() == command.lower():
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
        skill = self.get_skill_by_name(name)
        if skill is None:
            return False

        pref_key = self._preference_key(skill)
        if enabled:
            self._disabled.discard(pref_key)
            self._disabled.discard(skill.name)
        else:
            self._disabled.add(pref_key)

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
            _validate_slash_command(slash_command)
            for s in self._cache.values():
                if s.slash_command == slash_command and not (
                    s.source == "builtin" and s.name == name
                ):
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
                _validate_slash_command(slash_command)
                for s in self._cache.values():
                    if s.slash_command == slash_command and s.name != name and not (
                        s.source == "builtin" and s.name == name
                    ):
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
        from ...infrastructure.config import SKILLS_DIR, BUILTIN_SKILLS_DIR, USER_SKILLS_DIR, SKILLS_SEED_DIR, SKILLS_PREFERENCES_FILE

        _instance = SkillManager(
            skills_dir=SKILLS_DIR,
            builtin_dir=BUILTIN_SKILLS_DIR,
            user_dir=USER_SKILLS_DIR,
            seed_dir=SKILLS_SEED_DIR,
            preferences_file=SKILLS_PREFERENCES_FILE,
            include_marketplace=True,
        )
        _instance.initialize()
        return _instance
    return _instance  # unreachable but keeps type checkers happy
