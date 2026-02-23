"""Tests for DatabaseManager CRUD operations."""

import os
import tempfile
from unittest.mock import patch

import pytest


@pytest.fixture()
def db_manager(tmp_path):
    """Create a fresh DatabaseManager backed by a temp SQLite file."""
    db_path = str(tmp_path / "test.db")
    # Prevent _seed_default_skills from importing MCP modules that may not
    # be available in the test environment.
    with patch("source.database.DatabaseManager._seed_default_skills"):
        from source.database import DatabaseManager

        mgr = DatabaseManager(database_path=db_path)

    # On a fresh DB the ALTER TABLE migration for content_blocks runs before
    # the CREATE TABLE, so the column is never added.  Add it manually.
    conn = mgr._get_connection()
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN content_blocks TEXT")
        conn.commit()
    except Exception:
        pass  # already exists
    finally:
        conn.close()

    return mgr


# ------------------------------------------------------------------
# Conversations
# ------------------------------------------------------------------


class TestConversations:
    def test_start_new_conversation_returns_uuid(self, db_manager):
        cid = db_manager.start_new_conversation("Hello World")
        assert isinstance(cid, str)
        assert len(cid) == 36  # UUID4 has 36 chars including hyphens

    def test_get_recent_conversations(self, db_manager):
        c1 = db_manager.start_new_conversation("First")
        c2 = db_manager.start_new_conversation("Second")
        recent = db_manager.get_recent_conversations(limit=10)
        assert len(recent) >= 2
        titles = [c["title"] for c in recent]
        assert "First" in titles
        assert "Second" in titles

    def test_delete_conversation(self, db_manager):
        cid = db_manager.start_new_conversation("ToDelete")
        db_manager.delete_conversation(cid)
        recent = db_manager.get_recent_conversations(limit=100)
        ids = [c["id"] for c in recent]
        assert cid not in ids

    def test_update_conversation_title(self, db_manager):
        cid = db_manager.start_new_conversation("Old Title")
        db_manager.update_conversation_title(cid, "New Title")
        recent = db_manager.get_recent_conversations(limit=100)
        match = [c for c in recent if c["id"] == cid]
        assert match[0]["title"] == "New Title"


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------


class TestMessages:
    def test_add_and_retrieve_message(self, db_manager):
        cid = db_manager.start_new_conversation("Chat")
        db_manager.add_message(cid, "user", "Hello!")
        db_manager.add_message(cid, "assistant", "Hi there!")
        msgs = db_manager.get_full_conversation(cid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello!"
        assert msgs[1]["role"] == "assistant"

    def test_message_with_images(self, db_manager):
        cid = db_manager.start_new_conversation("Images")
        db_manager.add_message(cid, "user", "See this", images=["img1.png", "img2.png"])
        msgs = db_manager.get_full_conversation(cid)
        assert msgs[0]["images"] == ["img1.png", "img2.png"]

    def test_messages_deleted_with_conversation(self, db_manager):
        cid = db_manager.start_new_conversation("TempChat")
        db_manager.add_message(cid, "user", "temp msg")
        db_manager.delete_conversation(cid)
        msgs = db_manager.get_full_conversation(cid)
        assert msgs == []


# ------------------------------------------------------------------
# Token usage
# ------------------------------------------------------------------


class TestTokenUsage:
    def test_add_and_get_token_usage(self, db_manager):
        cid = db_manager.start_new_conversation("Tokens")
        db_manager.add_token_usage(cid, 100, 200)
        usage = db_manager.get_token_usage(cid)
        assert usage["input"] == 100
        assert usage["output"] == 200
        assert usage["total"] == 300

    def test_token_usage_accumulates(self, db_manager):
        cid = db_manager.start_new_conversation("Accumulate")
        db_manager.add_token_usage(cid, 50, 50)
        db_manager.add_token_usage(cid, 30, 70)
        usage = db_manager.get_token_usage(cid)
        assert usage["input"] == 80
        assert usage["output"] == 120


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


class TestSettings:
    def test_set_and_get_setting(self, db_manager):
        db_manager.set_setting("theme", "dark")
        assert db_manager.get_setting("theme") == "dark"

    def test_get_missing_setting_returns_none(self, db_manager):
        assert db_manager.get_setting("nonexistent") is None

    def test_delete_setting(self, db_manager):
        db_manager.set_setting("key", "value")
        db_manager.delete_setting("key")
        assert db_manager.get_setting("key") is None

    def test_overwrite_setting(self, db_manager):
        db_manager.set_setting("k", "v1")
        db_manager.set_setting("k", "v2")
        assert db_manager.get_setting("k") == "v2"


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------


class TestSearch:
    def test_search_conversations(self, db_manager):
        cid = db_manager.start_new_conversation("Unique Title XYZ")
        db_manager.add_message(cid, "user", "some message content")
        results = db_manager.search_conversations("Unique Title XYZ")
        assert any(r["id"] == cid for r in results)

    def test_search_no_results(self, db_manager):
        results = db_manager.search_conversations("zzznonexistentzzzz")
        assert results == []
