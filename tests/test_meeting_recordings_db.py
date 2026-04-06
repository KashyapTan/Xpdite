"""Tests for meeting recording database operations."""

import time

import pytest


@pytest.fixture()
def db_manager(tmp_path):
    """Create a fresh DatabaseManager backed by a temp SQLite file."""
    db_path = str(tmp_path / "test.db")
    from source.infrastructure.database import DatabaseManager

    mgr = DatabaseManager(database_path=db_path)
    return mgr


class TestCreateMeetingRecording:
    def test_creates_recording_returns_id(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test Meeting", time.time())
        assert rec_id is not None
        assert isinstance(rec_id, str)
        assert len(rec_id) == 36  # UUID format

    def test_recording_has_default_status(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["status"] == "recording"

    def test_recording_stores_title_and_timestamp(self, db_manager):
        ts = time.time()
        rec_id = db_manager.create_meeting_recording("Sprint Planning", ts)
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["title"] == "Sprint Planning"
        assert rec["started_at"] == ts


class TestUpdateMeetingRecording:
    def test_updates_status(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        db_manager.update_meeting_recording(rec_id, status="ready")
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["status"] == "ready"

    def test_updates_multiple_fields(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        ended = time.time() + 3600
        db_manager.update_meeting_recording(
            rec_id, ended_at=ended, duration_seconds=3600, status="ready"
        )
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["ended_at"] == ended
        assert rec["duration_seconds"] == 3600
        assert rec["status"] == "ready"

    def test_ignores_unknown_fields(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        db_manager.update_meeting_recording(rec_id, bogus_field="nope")
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec is not None  # No crash, no change

    def test_updates_title(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Temp Name", time.time())
        db_manager.update_meeting_recording(rec_id, title="AI-Generated Title")
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["title"] == "AI-Generated Title"


class TestAppendTier1Transcript:
    def test_appends_text(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        db_manager.append_tier1_transcript(rec_id, "Hello. ")
        db_manager.append_tier1_transcript(rec_id, "World.")
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["tier1_transcript"] == "Hello. World."

    def test_starts_empty(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["tier1_transcript"] == ""


class TestGetMeetingRecordings:
    def test_returns_empty_list(self, db_manager):
        recs = db_manager.get_meeting_recordings()
        assert recs == []

    def test_returns_recordings_ordered_by_time(self, db_manager):
        ts1 = time.time()
        ts2 = ts1 + 100
        db_manager.create_meeting_recording("Older", ts1)
        db_manager.create_meeting_recording("Newer", ts2)
        recs = db_manager.get_meeting_recordings()
        assert len(recs) == 2
        assert recs[0]["title"] == "Newer"
        assert recs[1]["title"] == "Older"

    def test_pagination(self, db_manager):
        for i in range(5):
            db_manager.create_meeting_recording(f"Meeting {i}", time.time() + i)
        page1 = db_manager.get_meeting_recordings(limit=2, offset=0)
        page2 = db_manager.get_meeting_recordings(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        # No overlap
        ids = {r["id"] for r in page1} | {r["id"] for r in page2}
        assert len(ids) == 4

    def test_list_excludes_transcripts(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        db_manager.append_tier1_transcript(rec_id, "Some text")
        recs = db_manager.get_meeting_recordings()
        assert "tier1_transcript" not in recs[0]


class TestGetMeetingRecording:
    def test_returns_none_for_missing_id(self, db_manager):
        rec = db_manager.get_meeting_recording("nonexistent")
        assert rec is None

    def test_returns_full_detail(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        rec = db_manager.get_meeting_recording(rec_id)
        assert rec["id"] == rec_id
        assert rec["tier1_transcript"] == ""
        assert rec["tier2_transcript_json"] is None
        assert rec["ai_summary"] is None
        assert rec["ai_actions_json"] is None
        assert rec["ai_title_generated"] is False


class TestDeleteMeetingRecording:
    def test_deletes_recording(self, db_manager):
        rec_id = db_manager.create_meeting_recording("Test", time.time())
        db_manager.delete_meeting_recording(rec_id)
        assert db_manager.get_meeting_recording(rec_id) is None

    def test_delete_nonexistent_is_noop(self, db_manager):
        db_manager.delete_meeting_recording("nonexistent")  # No crash


class TestSearchMeetingRecordings:
    def test_search_by_title(self, db_manager):
        db_manager.create_meeting_recording("Sprint Planning", time.time())
        db_manager.create_meeting_recording("Design Review", time.time())
        results = db_manager.search_meeting_recordings("Sprint")
        assert len(results) == 1
        assert results[0]["title"] == "Sprint Planning"

    def test_search_empty_query(self, db_manager):
        db_manager.create_meeting_recording("Test", time.time())
        results = db_manager.search_meeting_recordings("")
        assert results == []

    def test_search_no_results(self, db_manager):
        db_manager.create_meeting_recording("Sprint", time.time())
        results = db_manager.search_meeting_recordings("nonexistent")
        assert results == []
