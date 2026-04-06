"""Tests for source/services/memory_store/memory.py."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from source.services.memory_store.memory import MemoryService


@pytest.fixture()
def memory_env(tmp_path):
    root_dir = tmp_path / "memory"
    service = MemoryService(
        root_dir=root_dir,
        profile_file=root_dir / "profile" / "user_profile.md",
        default_folders=("profile", "semantic", "episodic", "procedural"),
    )
    return service, root_dir


def _write_raw(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


class TestInitialization:
    def test_creates_default_directories(self, memory_env):
        _, root_dir = memory_env

        assert (root_dir / "profile").is_dir()
        assert (root_dir / "semantic").is_dir()
        assert (root_dir / "episodic").is_dir()
        assert (root_dir / "procedural").is_dir()


class TestListingAndReading:
    def test_lists_recursive_memories_across_nested_folders(self, memory_env):
        service, _ = memory_env
        service.upsert_memory(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.8,
            tags=["prefs"],
            abstract="User prefers concise output.",
            body="Keep responses concise.",
        )
        service.upsert_memory(
            path="projects/xpdite/architecture.md",
            title="Architecture",
            category="projects",
            importance=0.9,
            tags=["xpdite", "architecture"],
            abstract="Architecture notes for Xpdite.",
            body="Document the app architecture.",
        )

        listed = service.list_memories()

        assert [item["path"] for item in listed] == [
            "projects/xpdite/architecture.md",
            "semantic/prefs.md",
        ]

    def test_folder_scoped_listing_only_returns_matching_subtree(self, memory_env):
        service, _ = memory_env
        service.upsert_memory(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.8,
            tags=["prefs"],
            abstract="User prefers concise output.",
            body="Keep responses concise.",
        )
        service.upsert_memory(
            path="projects/xpdite/architecture.md",
            title="Architecture",
            category="projects",
            importance=0.9,
            tags=["xpdite", "architecture"],
            abstract="Architecture notes for Xpdite.",
            body="Document the app architecture.",
        )

        listed = service.list_memories("projects")

        assert len(listed) == 1
        assert listed[0]["path"] == "projects/xpdite/architecture.md"
        assert listed[0]["folder"] == "projects/xpdite"
        assert listed[0]["title"] == "Architecture"
        assert listed[0]["abstract"] == "Architecture notes for Xpdite."

    def test_read_returns_full_raw_text(self, memory_env):
        service, root_dir = memory_env
        raw_text = """---
title: "Profile"
category: "profile"
importance: 1
created: "2026-03-20"
updated: "2026-03-20"
last_accessed: "2026-03-20"
tags: ["profile"]
abstract: "Stable facts about the user."
---

## About

Writes Python every day.
"""
        _write_raw(root_dir / "profile" / "user_profile.md", raw_text)

        detail = service.read_memory("profile/user_profile.md", touch_access=False)

        assert detail["raw_text"] == raw_text
        assert "Writes Python every day." in detail["body"]

    def test_front_matter_separator_blank_line_is_not_included_in_body(self, memory_env):
        service, root_dir = memory_env
        raw_text = """---
title: "Profile"
category: "profile"
importance: 1
created: "2026-03-20"
updated: "2026-03-20"
last_accessed: "2026-03-20"
tags: ["profile"]
abstract: "Stable facts about the user."
---

First body line.
Second body line.
"""
        _write_raw(root_dir / "profile" / "user_profile.md", raw_text)

        detail = service.read_memory("profile/user_profile.md", touch_access=False)

        assert detail["body"] == "First body line.\nSecond body line."

    def test_explicit_read_updates_last_accessed_without_changing_updated(self, memory_env):
        service, _ = memory_env
        created = service.upsert_memory(
            path="procedural/sqlite_fix.md",
            title="SQLite Fix",
            category="procedural",
            importance=0.85,
            tags=["sqlite"],
            abstract="Use one SQLite connection per request.",
            body="Always open a fresh connection per request.",
        )

        time.sleep(0.02)
        read_back = service.read_memory("procedural/sqlite_fix.md", touch_access=True)

        assert read_back["created"] == created["created"]
        assert read_back["updated"] == created["updated"]
        assert read_back["last_accessed"] != created["last_accessed"]

    def test_profile_read_can_skip_access_timestamp_mutation(self, memory_env):
        service, _ = memory_env
        created = service.upsert_memory(
            path="profile/user_profile.md",
            title="User Profile",
            category="profile",
            importance=1.0,
            tags=["profile"],
            abstract="Stable profile facts.",
            body="Preferred stack: Python and React.",
        )

        time.sleep(0.02)
        read_back = service.read_memory("profile/user_profile.md", touch_access=False)

        assert read_back["last_accessed"] == created["last_accessed"]

    def test_explicit_read_preserves_unknown_front_matter_fields(self, memory_env):
        service, root_dir = memory_env
        raw_text = """---
title: "Profile"
category: "profile"
importance: 1
created: "2026-03-20"
updated: "2026-03-20"
last_accessed: "2026-03-20"
owner: "kashyap"
tags: ["profile"]
abstract: "Stable facts about the user."
---

Body
"""
        file_path = root_dir / "profile" / "user_profile.md"
        _write_raw(file_path, raw_text)

        detail = service.read_memory("profile/user_profile.md", touch_access=True)

        rewritten = file_path.read_text(encoding="utf-8")
        assert detail["last_accessed"] != "2026-03-20"
        assert 'owner: "kashyap"' in rewritten

    def test_explicit_read_updates_last_accessed_even_with_parse_warning(self, memory_env):
        service, root_dir = memory_env
        raw_text = """---
title: "Profile"
category: "profile"
importance: 1
created: "2026-03-20"
updated: "2026-03-20"
last_accessed: "2026-03-20"
badline
tags: ["profile"]
abstract: "Stable facts about the user."
---

Body
"""
        file_path = root_dir / "profile" / "user_profile.md"
        _write_raw(file_path, raw_text)

        detail = service.read_memory("profile/user_profile.md", touch_access=True)

        rewritten = file_path.read_text(encoding="utf-8")
        assert detail["parse_warning"]
        assert detail["last_accessed"] != "2026-03-20"
        assert f'last_accessed: "{detail["last_accessed"]}"' in rewritten

    def test_crlf_front_matter_is_parsed_and_touched(self, memory_env):
        service, root_dir = memory_env
        raw_text = (
            "---\r\n"
            'title: "Profile"\r\n'
            'category: "profile"\r\n'
            "importance: 1\r\n"
            'created: "2026-03-20"\r\n'
            'updated: "2026-03-20"\r\n'
            'last_accessed: "2026-03-20"\r\n'
            'tags: ["profile"]\r\n'
            'abstract: "Stable facts about the user."\r\n'
            "---\r\n"
            "\r\n"
            "Body\r\n"
        )
        file_path = root_dir / "profile" / "user_profile.md"
        _write_raw(file_path, raw_text)

        detail = service.read_memory("profile/user_profile.md", touch_access=True)

        assert detail["title"] == "Profile"
        assert detail["body"] == "Body"
        assert detail["last_accessed"] != "2026-03-20"


class TestWriting:
    def test_new_file_commit_writes_metadata_and_body(self, memory_env):
        service, root_dir = memory_env

        detail = service.upsert_memory(
            path="episodic/2026-03-29_debug_session.md",
            title="Debug Session",
            category="episodic",
            importance=0.75,
            tags=["debug"],
            abstract="Summarizes a debugging session.",
            body="Solved a race condition.",
        )

        file_path = root_dir / "episodic" / "2026-03-29_debug_session.md"
        assert file_path.exists()
        assert detail["created"]
        assert detail["updated"]
        assert detail["last_accessed"]
        assert "Solved a race condition." in file_path.read_text(encoding="utf-8")

    def test_overwrite_preserves_original_created_timestamp(self, memory_env):
        service, _ = memory_env
        first = service.upsert_memory(
            path="procedural/fix.md",
            title="Fix",
            category="procedural",
            importance=0.6,
            tags=["fix"],
            abstract="First abstract.",
            body="First body.",
        )

        time.sleep(0.02)
        second = service.upsert_memory(
            path="procedural/fix.md",
            title="Fix Updated",
            category="procedural",
            importance=0.9,
            tags=["fix", "updated"],
            abstract="Updated abstract.",
            body="Updated body.",
        )

        assert second["created"] == first["created"]
        assert second["updated"] != first["updated"]
        assert second["title"] == "Fix Updated"
        assert second["tags"] == ["fix", "updated"]

    def test_upsert_creates_intermediate_directories(self, memory_env):
        service, root_dir = memory_env

        service.upsert_memory(
            path="projects/xpdite/issues/known_bug.md",
            title="Known Bug",
            category="projects",
            importance=0.55,
            tags=["bug"],
            abstract="Tracks a known bug.",
            body="A known bug in the planner.",
        )

        assert (root_dir / "projects" / "xpdite" / "issues" / "known_bug.md").exists()


class TestValidationAndDeletion:
    @pytest.mark.parametrize(
        "path",
        [
            "../escape.md",
            "C:/absolute.md",
            "C:relative.md",
            "/absolute.md",
            "notes.txt",
        ],
    )
    def test_rejects_invalid_memory_paths(self, memory_env, path):
        service, _ = memory_env

        with pytest.raises(ValueError):
            service.upsert_memory(
                path=path,
                title="Bad",
                category="semantic",
                importance=0.5,
                tags=[],
                abstract="Bad path.",
                body="Bad path.",
            )

    @pytest.mark.parametrize("folder", ["../escape", "C:/escape", "C:escape", "/escape"])
    def test_rejects_invalid_folder_filters(self, memory_env, folder):
        service, _ = memory_env

        with pytest.raises(ValueError):
            service.list_memories(folder)

    def test_listing_skips_symlinks_that_escape_memory_root(self, memory_env, tmp_path):
        service, root_dir = memory_env
        outside_file = tmp_path / "outside.md"
        outside_file.write_text("outside", encoding="utf-8")
        symlink_path = root_dir / "semantic" / "external.md"
        try:
            symlink_path.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks are not available in this environment.")

        listed = service.list_memories()

        assert listed == []

    def test_malformed_front_matter_falls_back_with_warning(self, memory_env):
        service, root_dir = memory_env
        _write_raw(
            root_dir / "semantic" / "broken.md",
            "---\ntitle: Broken memory\nabstract: Missing closing delimiter\n",
        )

        listed = service.list_memories()
        detail = service.read_memory("semantic/broken.md", touch_access=False)

        assert listed[0]["title"] == "Broken"
        assert "closing delimiter" in listed[0]["parse_warning"]
        assert "closing delimiter" in detail["parse_warning"]

    def test_delete_removes_single_memory(self, memory_env):
        service, root_dir = memory_env
        service.upsert_memory(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.5,
            tags=["prefs"],
            abstract="Stores a preference.",
            body="Be concise.",
        )

        deleted = service.delete_memory("semantic/prefs.md")

        assert deleted is True
        assert not (root_dir / "semantic" / "prefs.md").exists()

    def test_clear_all_recreates_default_folders(self, memory_env):
        service, root_dir = memory_env
        service.upsert_memory(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.5,
            tags=["prefs"],
            abstract="Stores a preference.",
            body="Be concise.",
        )
        service.upsert_memory(
            path="projects/xpdite/note.md",
            title="Project Note",
            category="projects",
            importance=0.7,
            tags=["project"],
            abstract="Stores a project note.",
            body="Remember the release checklist.",
        )

        deleted_count = service.clear_all_memories()

        assert deleted_count == 2
        assert (root_dir / "profile").is_dir()
        assert (root_dir / "semantic").is_dir()
        assert (root_dir / "episodic").is_dir()
        assert (root_dir / "procedural").is_dir()
        assert not any(root_dir.rglob("*.md"))
