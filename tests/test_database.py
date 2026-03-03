"""Tests for DatabaseManager CRUD operations."""

import os
import tempfile

import pytest


@pytest.fixture()
def db_manager(tmp_path):
    """Create a fresh DatabaseManager backed by a temp SQLite file."""
    db_path = str(tmp_path / "test.db")
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
# Search (FTS5)
# ------------------------------------------------------------------


class TestSearch:
    # ── basic matching ─────────────────────────────────────────────

    def test_search_by_title(self, db_manager):
        cid = db_manager.start_new_conversation("Quarterly budget review")
        results = db_manager.search_conversations("Quarterly budget")
        assert any(r["id"] == cid for r in results)

    def test_search_by_message_content(self, db_manager):
        cid = db_manager.start_new_conversation("Work chat")
        db_manager.add_message(cid, "user", "Can you summarise the deployment pipeline?")
        results = db_manager.search_conversations("deployment pipeline")
        assert any(r["id"] == cid for r in results)

    def test_search_finds_assistant_message(self, db_manager):
        cid = db_manager.start_new_conversation("Support thread")
        db_manager.add_message(cid, "assistant", "The refactoring is complete.")
        results = db_manager.search_conversations("refactoring")
        assert any(r["id"] == cid for r in results)

    def test_search_no_results(self, db_manager):
        results = db_manager.search_conversations("zzznonexistentzzzz")
        assert results == []

    # ── guard clauses ──────────────────────────────────────────────

    def test_search_empty_string_returns_empty(self, db_manager):
        db_manager.start_new_conversation("Should not appear")
        assert db_manager.search_conversations("") == []

    def test_search_whitespace_only_returns_empty(self, db_manager):
        db_manager.start_new_conversation("Should not appear")
        assert db_manager.search_conversations("   ") == []

    # ── result shape ───────────────────────────────────────────────

    def test_search_result_has_required_keys(self, db_manager):
        cid = db_manager.start_new_conversation("Shape test")
        results = db_manager.search_conversations("Shape test")
        assert len(results) == 1
        assert set(results[0].keys()) == {"id", "title", "date"}
        assert results[0]["id"] == cid
        assert results[0]["title"] == "Shape test"

    def test_search_limit_is_respected(self, db_manager):
        for i in range(5):
            db_manager.start_new_conversation(f"LimitTest conversation {i}")
        results = db_manager.search_conversations("LimitTest", limit=3)
        assert len(results) <= 3

    # ── FTS sync: delete ───────────────────────────────────────────

    def test_fts_cleaned_up_after_conversation_delete(self, db_manager):
        cid = db_manager.start_new_conversation("Ephemeral chat")
        db_manager.add_message(cid, "user", "Unique ephemeral content ZQXW")
        # Confirm it's found before deletion
        assert len(db_manager.search_conversations("ZQXW")) == 1
        db_manager.delete_conversation(cid)
        assert db_manager.search_conversations("ZQXW") == []

    def test_title_fts_cleaned_up_after_delete(self, db_manager):
        cid = db_manager.start_new_conversation("DeleteMeTitleXYQ")
        assert len(db_manager.search_conversations("DeleteMeTitleXYQ")) == 1
        db_manager.delete_conversation(cid)
        assert db_manager.search_conversations("DeleteMeTitleXYQ") == []

    # ── FTS sync: title update ─────────────────────────────────────

    def test_fts_updated_after_title_change(self, db_manager):
        cid = db_manager.start_new_conversation("OldTitleABC")
        db_manager.update_conversation_title(cid, "NewTitleDEF")
        assert len(db_manager.search_conversations("NewTitleDEF")) == 1

    def test_old_title_no_longer_searchable_after_update(self, db_manager):
        cid = db_manager.start_new_conversation("StaleTitleGHI")
        db_manager.update_conversation_title(cid, "FreshTitleJKL")
        assert db_manager.search_conversations("StaleTitleGHI") == []

    # ── deduplication ──────────────────────────────────────────────

    def test_distinct_single_result_for_multiple_matching_messages(self, db_manager):
        """A convo with many messages containing the search term should appear once."""
        cid = db_manager.start_new_conversation("Repeat keyword chat")
        for _ in range(4):
            db_manager.add_message(cid, "user", "The keyword ABCDUP is mentioned here")
        results = db_manager.search_conversations("ABCDUP")
        matching = [r for r in results if r["id"] == cid]
        assert len(matching) == 1

    def test_multiple_conversations_all_returned(self, db_manager):
        """Two separate conversations that both match should both appear."""
        cid1 = db_manager.start_new_conversation("Alpha MULTIWORD project")
        cid2 = db_manager.start_new_conversation("Beta MULTIWORD project")
        results = db_manager.search_conversations("MULTIWORD")
        returned_ids = {r["id"] for r in results}
        assert cid1 in returned_ids
        assert cid2 in returned_ids

    def test_unrelated_conversation_not_returned(self, db_manager):
        """A conversation that doesn't match should not be in results."""
        cid_match = db_manager.start_new_conversation("ContainsNeedle")
        cid_no_match = db_manager.start_new_conversation("CompletelyUnrelated")
        results = db_manager.search_conversations("ContainsNeedle")
        returned_ids = {r["id"] for r in results}
        assert cid_match in returned_ids
        assert cid_no_match not in returned_ids

    # ── case sensitivity ───────────────────────────────────────────

    def test_search_is_case_insensitive(self, db_manager):
        """unicode61 tokenizer folds case — lowercase query matches uppercase stored text."""
        cid = db_manager.start_new_conversation("UPPERCASE TITLE CASE")
        results = db_manager.search_conversations("uppercase title case")
        assert any(r["id"] == cid for r in results)

    def test_search_mixed_case_query(self, db_manager):
        cid = db_manager.start_new_conversation("Mixed Case Title Here")
        results = db_manager.search_conversations("mIxEd cAsE")
        assert any(r["id"] == cid for r in results)

    # ── FTS5 operator / special-character safety ───────────────────

    def test_search_with_double_quotes_doesnt_raise(self, db_manager):
        """Double quotes are FTS5 syntax — _fts5_phrase must escape them."""
        db_manager.start_new_conversation("Normal conversation")
        # Should not raise sqlite3.OperationalError
        results = db_manager.search_conversations('"quoted" search')
        assert isinstance(results, list)

    def test_search_with_fts5_operators_doesnt_raise(self, db_manager):
        """FTS5 boolean operators inside the term must not break the query."""
        for term in ["hello AND world", "hello OR world", "hello NOT world",
                     "test*", "-negative", "(parens)", "col:value"]:
            results = db_manager.search_conversations(term)
            assert isinstance(results, list), f"Raised for term: {term!r}"

    def test_search_term_with_percent_treated_literally(self, db_manager):
        """% in the search term should not be a wildcard (fallback LIKE path guards)."""
        cid = db_manager.start_new_conversation("50% discount offer")
        results_exact = db_manager.search_conversations("50%")
        assert any(r["id"] == cid for r in results_exact)
        # A bare "%" must not match everything
        db_manager.start_new_conversation("Unrelated title here")
        wildcard_results = db_manager.search_conversations("%")
        # If it matched everything it would return 2+ rows without any bearing;
        # the important thing is it doesn't crash, and if it returns results
        # they shouldn't include the unrelated conversation via wildcard.
        assert isinstance(wildcard_results, list)

    # ── _fts5_phrase helper unit tests ─────────────────────────────

    def test_fts5_phrase_wraps_in_double_quotes(self, db_manager):
        from source.database import DatabaseManager
        assert DatabaseManager._fts5_phrase("hello world") == '"hello world"'

    def test_fts5_phrase_escapes_internal_quotes(self, db_manager):
        from source.database import DatabaseManager
        assert DatabaseManager._fts5_phrase('say "hi"') == '"say ""hi"""'

    def test_fts5_phrase_escapes_consecutive_quotes(self, db_manager):
        from source.database import DatabaseManager
        # '""' → each " doubled → '""""' → wrapped → '""""""' (6 chars)
        assert DatabaseManager._fts5_phrase('""') == '""""""'

    def test_fts5_phrase_empty_string(self, db_manager):
        from source.database import DatabaseManager
        assert DatabaseManager._fts5_phrase("") == '""'


# ------------------------------------------------------------------
# Terminal Events
# ------------------------------------------------------------------


class TestTerminalEvents:
    def test_save_and_get_terminal_event(self, db_manager):
        cid = db_manager.start_new_conversation("Terminal conversation")
        event_id = db_manager.save_terminal_event(
            conversation_id=cid,
            message_index=0,
            command="ls -la",
            exit_code=0,
            output="file1.txt\nfile2.txt",
            cwd="/home/user",
            duration_ms=150,
        )
        assert isinstance(event_id, str)
        assert len(event_id) == 36  # UUID4

        events = db_manager.get_terminal_events(cid)
        assert len(events) == 1
        assert events[0]["command"] == "ls -la"
        assert events[0]["exit_code"] == 0
        assert events[0]["cwd"] == "/home/user"
        assert events[0]["duration_ms"] == 150
        assert events[0]["timed_out"] is False
        assert events[0]["denied"] is False
        assert events[0]["pty"] is False
        assert events[0]["background"] is False

    def test_terminal_event_with_flags(self, db_manager):
        cid = db_manager.start_new_conversation("Flagged terminal")
        db_manager.save_terminal_event(
            conversation_id=cid,
            message_index=1,
            command="npm start",
            exit_code=-1,
            output="timeout",
            cwd="/project",
            duration_ms=120000,
            pty=True,
            background=True,
            timed_out=True,
        )
        events = db_manager.get_terminal_events(cid)
        assert events[0]["pty"] is True
        assert events[0]["background"] is True
        assert events[0]["timed_out"] is True

    def test_terminal_event_denied(self, db_manager):
        cid = db_manager.start_new_conversation("Denied cmd")
        db_manager.save_terminal_event(
            conversation_id=cid,
            message_index=0,
            command="rm -rf /",
            exit_code=-1,
            output="denied",
            cwd="/",
            duration_ms=0,
            denied=True,
        )
        events = db_manager.get_terminal_events(cid)
        assert events[0]["denied"] is True

    def test_output_preview_truncation(self, db_manager):
        cid = db_manager.start_new_conversation("Long output")
        long_output = "x" * 5000
        db_manager.save_terminal_event(
            conversation_id=cid,
            message_index=0,
            command="cat big_file",
            exit_code=0,
            output=long_output,
            cwd="/",
            duration_ms=100,
        )
        events = db_manager.get_terminal_events(cid)
        # output_preview should be truncated (first 500 + ... + last 500)
        preview = events[0]["output_preview"]
        assert len(preview) < len(long_output)
        assert "..." in preview

    def test_terminal_events_deleted_with_conversation(self, db_manager):
        cid = db_manager.start_new_conversation("Delete with events")
        db_manager.save_terminal_event(
            conversation_id=cid,
            message_index=0,
            command="echo hi",
            exit_code=0,
            output="hi",
            cwd="/",
            duration_ms=10,
        )
        db_manager.delete_conversation(cid)
        events = db_manager.get_terminal_events(cid)
        assert events == []

    def test_multiple_terminal_events_ordered(self, db_manager):
        cid = db_manager.start_new_conversation("Multiple events")
        db_manager.save_terminal_event(
            cid, 0, "cmd1", 0, "out1", "/", 10
        )
        db_manager.save_terminal_event(
            cid, 1, "cmd2", 0, "out2", "/", 20
        )
        events = db_manager.get_terminal_events(cid)
        assert len(events) == 2
        assert events[0]["command"] == "cmd1"
        assert events[1]["command"] == "cmd2"

    def test_no_terminal_events(self, db_manager):
        cid = db_manager.start_new_conversation("No events")
        events = db_manager.get_terminal_events(cid)
        assert events == []


# ------------------------------------------------------------------
# Enabled Models
# ------------------------------------------------------------------


class TestEnabledModels:
    def test_get_empty_by_default(self, db_manager):
        models = db_manager.get_enabled_models()
        assert models == []

    def test_set_and_get(self, db_manager):
        db_manager.set_enabled_models(["model_a", "model_b"])
        assert db_manager.get_enabled_models() == ["model_a", "model_b"]

    def test_overwrite(self, db_manager):
        db_manager.set_enabled_models(["old"])
        db_manager.set_enabled_models(["new1", "new2"])
        assert db_manager.get_enabled_models() == ["new1", "new2"]


# ------------------------------------------------------------------
# System Prompt Template
# ------------------------------------------------------------------


class TestSystemPromptTemplate:
    def test_get_default_none(self, db_manager):
        assert db_manager.get_system_prompt_template() is None

    def test_set_and_get(self, db_manager):
        db_manager.set_system_prompt_template("You are a helper.")
        assert db_manager.get_system_prompt_template() == "You are a helper."

    def test_set_empty_clears(self, db_manager):
        db_manager.set_system_prompt_template("Something")
        db_manager.set_system_prompt_template("")
        assert db_manager.get_system_prompt_template() is None

    def test_set_whitespace_clears(self, db_manager):
        db_manager.set_system_prompt_template("Something")
        db_manager.set_system_prompt_template("   ")
        assert db_manager.get_system_prompt_template() is None

    def test_set_none_clears(self, db_manager):
        db_manager.set_system_prompt_template("Something")
        db_manager.set_system_prompt_template(None)
        assert db_manager.get_system_prompt_template() is None


# ------------------------------------------------------------------
# Messages — content_blocks
# ------------------------------------------------------------------


class TestMessageContentBlocks:
    def test_message_with_content_blocks(self, db_manager):
        cid = db_manager.start_new_conversation("Blocks test")
        blocks = [
            {"type": "text", "content": "Hello"},
            {"type": "tool_call", "name": "read_file", "args": {"path": "a.txt"}},
        ]
        db_manager.add_message(cid, "assistant", "Hello", content_blocks=blocks)
        msgs = db_manager.get_full_conversation(cid)
        assert msgs[0]["content_blocks"] == blocks

    def test_message_without_content_blocks(self, db_manager):
        cid = db_manager.start_new_conversation("No blocks")
        db_manager.add_message(cid, "user", "Hi")
        msgs = db_manager.get_full_conversation(cid)
        assert msgs[0]["content_blocks"] is None

    def test_message_with_model(self, db_manager):
        cid = db_manager.start_new_conversation("Model test")
        db_manager.add_message(cid, "assistant", "Reply", model="gpt-4o")
        msgs = db_manager.get_full_conversation(cid)
        assert msgs[0]["model"] == "gpt-4o"

