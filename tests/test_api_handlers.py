"""Tests for source/api/handlers.py message handlers."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import source.api.handlers as handlers
from source.core.state import app_state
from source.services.query_queue import QueueFullError


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, message: str):
        self.sent.append(json.loads(message))


def _make_session():
    queue = SimpleNamespace(
        enqueue=AsyncMock(),
        stop_current=AsyncMock(),
        cancel_item=AsyncMock(),
        reset_conversation=MagicMock(),
        resolved_conversation_id=None,
    )
    state = SimpleNamespace(screenshot_list=[], chat_history=[])
    return SimpleNamespace(state=state, queue=queue)


class _FakeTabManager:
    def __init__(self, session=None, tab_ids=None):
        self.session = session or _make_session()
        self.created: list[str] = []
        self.closed: list[str] = []
        self.tab_ids = list(tab_ids or ["default", "tab-1", "tab-2"])

    def create_tab(self, tab_id: str):
        if tab_id == "boom":
            raise ValueError("Tab exploded")
        self.created.append(tab_id)
        if tab_id not in self.tab_ids:
            self.tab_ids.append(tab_id)
        return self.session

    async def close_tab(self, tab_id: str):
        self.closed.append(tab_id)
        self.tab_ids = [existing for existing in self.tab_ids if existing != tab_id]

    def get_or_create(self, _tab_id: str):
        return self.session

    def get_session(self, _tab_id: str):
        return self.session

    def get_state(self, _tab_id: str):
        return self.session.state

    def get_all_tab_ids(self):
        return list(self.tab_ids)


@pytest.fixture(autouse=True)
def _restore_app_state():
    saved_model = app_state.selected_model
    saved_capture_mode = app_state.capture_mode
    saved_active_tab = app_state.active_tab_id
    yield
    app_state.selected_model = saved_model
    app_state.capture_mode = saved_capture_mode
    app_state.active_tab_id = saved_active_tab


@pytest.fixture()
def websocket():
    return _FakeWebSocket()


@pytest.fixture()
def handler(websocket):
    return handlers.MessageHandler(websocket)


class TestRoutingAndTabs:
    @pytest.mark.asyncio
    async def test_handle_dispatches_known_message_and_tracks_tab(self, handler):
        handler._handle_tab_activated = AsyncMock()

        await handler.handle({"type": "tab_activated", "tab_id": "tab-7"})

        assert app_state.active_tab_id == "tab-7"
        handler._handle_tab_activated.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_unknown_type_is_noop(self, handler):
        app_state.active_tab_id = "before"
        await handler.handle({"type": "unknown_event", "tab_id": "tab-1"})
        assert app_state.active_tab_id == "tab-1"
        assert handler.websocket.sent == []

    @pytest.mark.asyncio
    async def test_handle_tab_closed_keeps_current_active_tab(self, handler):
        manager = _FakeTabManager(tab_ids=["default", "tab-active", "tab-background"])
        handler._get_tab_manager = lambda: manager
        app_state.active_tab_id = "tab-active"

        await handler.handle({"type": "tab_closed", "tab_id": "tab-background"})

        assert manager.closed == ["tab-background"]
        assert app_state.active_tab_id == "tab-active"

    @pytest.mark.asyncio
    async def test_tab_created_success_and_value_error(self, handler, websocket):
        manager = _FakeTabManager()
        handler._get_tab_manager = lambda: manager

        await handler._handle_tab_created({"tab_id": "tab-1"})
        assert manager.created == ["tab-1"]

        await handler._handle_tab_created({"tab_id": "boom"})
        assert websocket.sent[-1]["type"] == "error"
        assert "Tab exploded" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_tab_closed_and_activated(self, handler):
        manager = _FakeTabManager()
        handler._get_tab_manager = lambda: manager

        await handler._handle_tab_closed({"tab_id": "tab-2"})
        await handler._handle_tab_activated({"tab_id": "tab-2"})

        assert manager.closed == ["tab-2"]
        assert app_state.active_tab_id == "tab-2"

    @pytest.mark.asyncio
    async def test_tab_closed_switches_active_when_closed_tab_was_active(self, handler):
        manager = _FakeTabManager(tab_ids=["default", "tab-2"])
        handler._get_tab_manager = lambda: manager
        app_state.active_tab_id = "tab-2"

        await handler._handle_tab_closed({"tab_id": "tab-2"})

        assert manager.closed == ["tab-2"]
        assert app_state.active_tab_id == "default"


class TestSubmitQuery:
    @pytest.mark.asyncio
    async def test_submit_query_empty_content_returns_error(self, handler, websocket):
        await handler._handle_submit_query({"tab_id": "t1", "content": "   "})

        assert websocket.sent[-1]["type"] == "error"
        assert websocket.sent[-1]["content"] == "Empty query"

    @pytest.mark.asyncio
    async def test_submit_query_enqueues_with_cleaned_llm_query_and_model(
        self, handler
    ):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        forced_skills = [SimpleNamespace(name="terminal")]
        with patch.object(
            handlers.ConversationService,
            "extract_skill_slash_commands",
            new=AsyncMock(return_value=(forced_skills, "clean query")),
        ):
            await handler._handle_submit_query(
                {
                    "tab_id": "tab-a",
                    "content": " /terminal clean query ",
                    "capture_mode": "precision",
                    "model": "openai/gpt-4o",
                }
            )

        assert app_state.selected_model == "openai/gpt-4o"
        queued = session.queue.enqueue.await_args.args[0]
        assert queued.tab_id == "tab-a"
        assert queued.content == "/terminal clean query"
        assert queued.llm_query == "clean query"
        assert queued.forced_skills == forced_skills
        assert queued.model == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_submit_query_fullscreen_captures_before_enqueue(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        token = object()
        with (
            patch.object(
                handlers.ConversationService,
                "extract_skill_slash_commands",
                new=AsyncMock(return_value=([], "hello")),
            ),
            patch.object(
                handlers.ScreenshotHandler, "capture_fullscreen", new=AsyncMock()
            ) as mock_capture,
            patch.object(
                handlers, "set_current_tab_id", return_value=token
            ) as mock_set_tab,
            patch.object(handlers, "reset_current_tab_id") as mock_reset_tab,
        ):
            await handler._handle_submit_query(
                {
                    "tab_id": "tab-full",
                    "content": "hello",
                    "capture_mode": "fullscreen",
                }
            )

        mock_set_tab.assert_called_once_with("tab-full")
        mock_capture.assert_awaited_once_with(tab_state=session.state)
        mock_reset_tab.assert_called_once_with(token)
        session.queue.enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_query_queue_full_broadcasts_queue_full(self, handler):
        session = _make_session()
        session.queue.enqueue = AsyncMock(side_effect=QueueFullError("full"))
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        with (
            patch.object(
                handlers.ConversationService,
                "extract_skill_slash_commands",
                new=AsyncMock(return_value=([], "hello")),
            ),
            patch.object(
                handlers, "broadcast_to_tab", new=AsyncMock()
            ) as mock_broadcast,
        ):
            await handler._handle_submit_query(
                {
                    "tab_id": "tab-q",
                    "content": "hello",
                    "capture_mode": "none",
                }
            )

        mock_broadcast.assert_awaited_once_with(
            "tab-q", "queue_full", {"tab_id": "tab-q"}
        )


class TestTurnActions:
    @pytest.mark.asyncio
    async def test_retry_missing_message_id(self, handler, websocket):
        await handler._handle_retry_message({"tab_id": "t1", "message_id": "  "})
        assert websocket.sent[-1]["type"] == "error"
        assert "Missing message_id" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_retry_message_not_found(self, handler, websocket):
        with patch.object(handlers.db, "get_message_by_id", return_value=None):
            await handler._handle_retry_message(
                {"tab_id": "t1", "message_id": "msg-missing"}
            )
        assert websocket.sent[-1]["type"] == "error"
        assert "could not be found" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_retry_incomplete_turn(self, handler, websocket):
        with (
            patch.object(
                handlers.db,
                "get_message_by_id",
                return_value={
                    "conversation_id": "conv-1",
                    "turn_id": "turn-1",
                    "role": "assistant",
                },
            ),
            patch.object(
                handlers.db, "get_turn_messages", return_value=[{"role": "user"}]
            ),
        ):
            await handler._handle_retry_message({"tab_id": "t1", "message_id": "msg-1"})
        assert websocket.sent[-1]["type"] == "error"
        assert "incomplete" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_edit_rejects_non_user_target(self, handler, websocket):
        with (
            patch.object(
                handlers.db,
                "get_message_by_id",
                return_value={
                    "conversation_id": "conv-1",
                    "turn_id": "turn-1",
                    "role": "assistant",
                },
            ),
            patch.object(
                handlers.db,
                "get_turn_messages",
                return_value=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi", "model": "m"},
                ],
            ),
        ):
            await handler._handle_edit_message(
                {
                    "tab_id": "t1",
                    "message_id": "msg-1",
                    "content": "updated",
                }
            )
        assert websocket.sent[-1]["type"] == "error"
        assert "Only user messages" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_retry_success_enqueues_and_sets_resolved_conversation(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        target_message = {
            "conversation_id": "conv-9",
            "turn_id": "turn-9",
            "role": "assistant",
        }
        turn_messages = [
            {"role": "user", "content": "retry me"},
            {"role": "assistant", "content": "ok", "model": "model-x"},
        ]

        with (
            patch.object(handlers.db, "get_message_by_id", return_value=target_message),
            patch.object(handlers.db, "get_turn_messages", return_value=turn_messages),
            patch.object(
                handlers.ConversationService,
                "extract_skill_slash_commands",
                new=AsyncMock(return_value=([], "retry me")),
            ),
        ):
            await handler._handle_retry_message(
                {"tab_id": "tab-r", "message_id": "msg-9"}
            )

        assert session.queue.resolved_conversation_id == "conv-9"
        queued = session.queue.enqueue.await_args.args[0]
        assert queued.action == "retry"
        assert queued.target_message_id == "msg-9"
        assert queued.conversation_id is None


class TestSetActiveResponse:
    @pytest.mark.asyncio
    async def test_set_active_response_invalid_index(self, handler, websocket):
        await handler._handle_set_active_response(
            {"tab_id": "t1", "message_id": "m", "response_index": "bad"}
        )
        assert websocket.sent[-1]["type"] == "error"
        assert "Invalid response_index" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_set_active_response_invalid_selection(self, handler, websocket):
        await handler._handle_set_active_response(
            {"tab_id": "t1", "message_id": "", "response_index": -1}
        )
        assert websocket.sent[-1]["type"] == "error"
        assert "invalid active response" in websocket.sent[-1]["content"]

    @pytest.mark.asyncio
    async def test_set_active_response_value_error_broadcasts(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        token = object()
        with (
            patch.object(handlers, "set_current_tab_id", return_value=token),
            patch.object(handlers, "reset_current_tab_id") as mock_reset,
            patch.object(
                handlers.ConversationService,
                "set_active_response_variant",
                side_effect=ValueError("invalid version"),
            ),
            patch.object(handlers, "broadcast_to_tab", new=AsyncMock()) as mock_bcast,
        ):
            await handler._handle_set_active_response(
                {"tab_id": "tab-s", "message_id": "m-1", "response_index": 2}
            )

        mock_bcast.assert_awaited_once_with("tab-s", "error", "invalid version")
        mock_reset.assert_called_once_with(token)


class TestQueueAndContextControls:
    @pytest.mark.asyncio
    async def test_stop_streaming_stops_queue_and_cancels_pending_approvals(
        self, handler
    ):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        with (
            patch.object(
                handlers.terminal_service, "cancel_all_pending"
            ) as terminal_cancel,
            patch.object(
                handlers.video_watcher_service, "cancel_all_pending"
            ) as yt_cancel,
        ):
            await handler._handle_stop_streaming({"tab_id": "tab-stop"})

        session.queue.stop_current.assert_awaited_once()
        terminal_cancel.assert_called_once_with()
        yt_cancel.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_cancel_queued_item_passes_item_id(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        await handler._handle_cancel_queued_item(
            {"tab_id": "tab-q", "item_id": "item-1"}
        )
        session.queue.cancel_item.assert_awaited_once_with("item-1")

    @pytest.mark.asyncio
    async def test_clear_context_calls_service_and_resets_queue_conversation(
        self, handler
    ):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        token = object()
        with (
            patch.object(handlers, "set_current_tab_id", return_value=token),
            patch.object(handlers, "reset_current_tab_id") as mock_reset,
            patch.object(
                handlers.ConversationService,
                "clear_context",
                new=AsyncMock(),
            ) as mock_clear,
        ):
            await handler._handle_clear_context({"tab_id": "tab-clear"})

        mock_clear.assert_awaited_once_with(tab_state=session.state)
        session.queue.reset_conversation.assert_called_once_with()
        mock_reset.assert_called_once_with(token)

    @pytest.mark.asyncio
    async def test_resume_conversation_updates_queue_resolved_id(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        token = object()
        with (
            patch.object(handlers, "set_current_tab_id", return_value=token),
            patch.object(handlers, "reset_current_tab_id"),
            patch.object(
                handlers.ConversationService,
                "resume_conversation",
                new=AsyncMock(),
            ) as mock_resume,
        ):
            await handler._handle_resume_conversation(
                {"tab_id": "tab-r", "conversation_id": "conv-22"}
            )

        mock_resume.assert_awaited_once_with("conv-22", tab_state=session.state)
        assert session.queue.resolved_conversation_id == "conv-22"


class TestScreenshotAndCaptureMode:
    @pytest.mark.asyncio
    async def test_remove_screenshot_routes_tab_state(self, handler):
        session = _make_session()
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager

        with patch.object(
            handlers.ScreenshotHandler,
            "remove_screenshot",
            new=AsyncMock(),
        ) as mock_remove:
            await handler._handle_remove_screenshot({"tab_id": "t", "id": "ss-1"})

        mock_remove.assert_awaited_once_with("ss-1", tab_state=session.state)

    @pytest.mark.asyncio
    async def test_remove_screenshot_unknown_tab_fails_closed(self, handler):
        manager = _FakeTabManager()
        manager.get_state = lambda _tab_id: None
        handler._get_tab_manager = lambda: manager

        with patch.object(
            handlers.ScreenshotHandler,
            "remove_screenshot",
            new=AsyncMock(),
        ) as mock_remove:
            await handler._handle_remove_screenshot({"tab_id": "missing", "id": "ss-1"})

        mock_remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_capture_mode_allows_known_values_only(self, handler):
        original = app_state.capture_mode

        await handler._handle_set_capture_mode({"mode": "precision"})
        assert app_state.capture_mode == "precision"

        await handler._handle_set_capture_mode({"mode": "invalid-mode"})
        assert app_state.capture_mode == "precision"

        app_state.capture_mode = original


class TestConversationEndpoints:
    @pytest.mark.asyncio
    async def test_get_conversations_and_search_load_delete(self, handler, websocket):
        with (
            patch.object(
                handlers.ConversationService,
                "get_conversations",
                return_value=[{"id": "c1"}],
            ),
            patch.object(
                handlers.ConversationService,
                "search_conversations",
                return_value=[{"id": "c2"}],
            ),
            patch.object(
                handlers.ConversationService,
                "get_full_conversation",
                return_value=[{"role": "user", "content": "hi"}],
            ),
            patch.object(
                handlers.ConversationService, "delete_conversation"
            ) as mock_delete,
        ):
            await handler._handle_get_conversations({"limit": 10, "offset": 0})
            assert websocket.sent[-1]["type"] == "conversations_list"

            await handler._handle_search_conversations({"query": "term"})
            assert websocket.sent[-1]["type"] == "conversations_list"
            assert websocket.sent[-1]["content"] == [{"id": "c2"}]

            await handler._handle_load_conversation({"conversation_id": "c1"})
            assert websocket.sent[-1]["type"] == "conversation_loaded"

            await handler._handle_delete_conversation({"conversation_id": "c1"})
            assert websocket.sent[-1]["type"] == "conversation_deleted"
            mock_delete.assert_called_once_with("c1")


class TestMeetingHandlers:
    @pytest.mark.asyncio
    async def test_get_meeting_recordings_uses_limit_offset(self, handler, websocket):
        with patch.object(
            handlers.db,
            "get_meeting_recordings",
            return_value=[{"recording_id": "rec-1"}],
        ) as mock_get:
            await handler._handle_get_meeting_recordings({"limit": 5, "offset": 10})

        mock_get.assert_called_once_with(limit=5, offset=10)
        assert websocket.sent[-1] == {
            "type": "meeting_recordings_list",
            "content": [{"recording_id": "rec-1"}],
        }

    @pytest.mark.asyncio
    async def test_load_meeting_recording_sends_payload_when_id_present(
        self, handler, websocket
    ):
        with patch.object(
            handlers.db,
            "get_meeting_recording",
            return_value={"recording_id": "rec-2", "title": "Sync"},
        ) as mock_get:
            await handler._handle_load_meeting_recording({"recording_id": "rec-2"})

        mock_get.assert_called_once_with("rec-2")
        assert websocket.sent[-1] == {
            "type": "meeting_recording_loaded",
            "content": {"recording_id": "rec-2", "title": "Sync"},
        }

    @pytest.mark.asyncio
    async def test_search_meeting_recordings_query_and_default_paths(
        self, handler, websocket
    ):
        with (
            patch.object(
                handlers.db,
                "search_meeting_recordings",
                return_value=[{"recording_id": "rec-search"}],
            ) as mock_search,
            patch.object(
                handlers.db,
                "get_meeting_recordings",
                return_value=[{"recording_id": "rec-default"}],
            ) as mock_get,
        ):
            await handler._handle_search_meeting_recordings({"query": "roadmap"})
            assert websocket.sent[-1]["content"] == [{"recording_id": "rec-search"}]

            await handler._handle_search_meeting_recordings({"query": ""})
            assert websocket.sent[-1]["content"] == [{"recording_id": "rec-default"}]

        mock_search.assert_called_once_with("roadmap")
        mock_get.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_delete_meeting_recording_removes_audio_and_handles_oserror(
        self, handler, websocket
    ):
        with (
            patch.object(
                handlers.db,
                "get_meeting_recording",
                side_effect=[
                    {"audio_file_path": "C:/tmp/rec-1.wav"},
                    {"audio_file_path": "C:/tmp/rec-2.wav"},
                ],
            ) as mock_get,
            patch.object(handlers.db, "delete_meeting_recording") as mock_delete,
            patch("os.remove", side_effect=[None, OSError("locked")]) as mock_remove,
        ):
            await handler._handle_delete_meeting_recording({"recording_id": "rec-1"})
            await handler._handle_delete_meeting_recording({"recording_id": "rec-2"})

        assert mock_get.call_count == 2
        assert mock_delete.call_count == 2
        mock_remove.assert_any_call("C:/tmp/rec-1.wav")
        mock_remove.assert_any_call("C:/tmp/rec-2.wav")
        assert websocket.sent[-1] == {
            "type": "meeting_recording_deleted",
            "content": {"recording_id": "rec-2"},
        }

    @pytest.mark.asyncio
    async def test_meeting_get_status_and_compute_info(self, handler, websocket):
        with (
            patch(
                "source.services.meeting_recorder.meeting_recorder_service",
                SimpleNamespace(
                    get_status=MagicMock(return_value={"is_recording": False})
                ),
            ),
            patch(
                "source.services.gpu_detector.get_compute_info",
                return_value={"backend": "cpu", "available": True},
            ) as mock_compute,
        ):
            await handler._handle_meeting_get_status({})
            await handler._handle_meeting_get_compute_info({})

        assert websocket.sent[-2] == {
            "type": "meeting_recording_status",
            "content": {"is_recording": False},
        }
        assert websocket.sent[-1] == {
            "type": "meeting_compute_info",
            "content": {"backend": "cpu", "available": True},
        }
        mock_compute.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_meeting_get_settings_defaults_and_saved_values(
        self, handler, websocket
    ):
        with patch.object(
            handlers.db,
            "get_setting",
            side_effect=[None, None, None, "small", "true", "false"],
        ) as mock_get:
            await handler._handle_meeting_get_settings({})
            await handler._handle_meeting_get_settings({})

        assert websocket.sent[-2] == {
            "type": "meeting_settings",
            "content": {
                "whisper_model": "base",
                "keep_audio": "false",
                "diarization_enabled": "true",
            },
        }
        assert websocket.sent[-1] == {
            "type": "meeting_settings",
            "content": {
                "whisper_model": "small",
                "keep_audio": "true",
                "diarization_enabled": "false",
            },
        }
        assert mock_get.call_count == 6

    @pytest.mark.asyncio
    async def test_meeting_update_settings_applies_valid_model_only(
        self, handler, websocket
    ):
        fake_recorder = SimpleNamespace(set_model_size=MagicMock())
        with (
            patch(
                "source.services.meeting_recorder.meeting_recorder_service",
                fake_recorder,
            ),
            patch.object(handlers.db, "set_setting") as mock_set,
            patch.object(
                handlers.db,
                "get_setting",
                side_effect=["tiny", "true", "false", "tiny", "true", "false"],
            ),
        ):
            await handler._handle_meeting_update_settings(
                {
                    "settings": {
                        "whisper_model": "tiny",
                        "keep_audio": "true",
                        "diarization_enabled": "false",
                    }
                }
            )
            await handler._handle_meeting_update_settings(
                {"settings": {"whisper_model": "invalid"}}
            )

        fake_recorder.set_model_size.assert_called_once_with("tiny")
        assert mock_set.call_count == 3
        assert websocket.sent[-1] == {
            "type": "meeting_settings",
            "content": {
                "whisper_model": "tiny",
                "keep_audio": "true",
                "diarization_enabled": "false",
            },
        }

    @pytest.mark.asyncio
    async def test_meeting_start_recording_success(self, handler, websocket):
        with patch(
            "source.services.meeting_recorder.meeting_recorder_service",
            SimpleNamespace(
                start_recording=AsyncMock(return_value={"recording_id": "r1"}),
                stop_recording=AsyncMock(),
            ),
        ):
            await handler._handle_meeting_start_recording({})

        assert websocket.sent[-1]["type"] == "meeting_recording_started"

    @pytest.mark.asyncio
    async def test_meeting_stop_recording_success(self, handler, websocket):
        with patch(
            "source.services.meeting_recorder.meeting_recorder_service",
            SimpleNamespace(
                start_recording=AsyncMock(),
                stop_recording=AsyncMock(
                    return_value={"recording_id": "r1", "status": "processing"}
                ),
            ),
        ):
            await handler._handle_meeting_stop_recording({})

        assert websocket.sent[-1]["type"] == "meeting_recording_stopped"

    @pytest.mark.asyncio
    async def test_meeting_start_recording_error(self, handler, websocket):
        with patch(
            "source.services.meeting_recorder.meeting_recorder_service",
            SimpleNamespace(
                start_recording=AsyncMock(side_effect=RuntimeError("already running")),
                stop_recording=AsyncMock(),
            ),
        ):
            await handler._handle_meeting_start_recording({})

        assert websocket.sent[-1]["type"] == "meeting_recording_error"

    @pytest.mark.asyncio
    async def test_meeting_stop_recording_error(self, handler, websocket):
        with patch(
            "source.services.meeting_recorder.meeting_recorder_service",
            SimpleNamespace(
                start_recording=AsyncMock(),
                stop_recording=AsyncMock(side_effect=RuntimeError("not running")),
            ),
        ):
            await handler._handle_meeting_stop_recording({})

        assert websocket.sent[-1]["type"] == "meeting_recording_error"

    @pytest.mark.asyncio
    async def test_meeting_audio_chunk_decodes_and_forwards_bytes(self, handler):
        payload = base64.b64encode(b"\x00\x01\x02").decode("ascii")
        fake_service = SimpleNamespace(handle_audio_chunk=MagicMock())

        with patch(
            "source.services.meeting_recorder.meeting_recorder_service",
            fake_service,
        ):
            await handler._handle_meeting_audio_chunk({"audio": payload})

        fake_service.handle_audio_chunk.assert_called_once_with(b"\x00\x01\x02")

    @pytest.mark.asyncio
    async def test_meeting_generate_analysis_missing_recording_id(
        self, handler, websocket
    ):
        await handler._handle_meeting_generate_analysis({})
        assert websocket.sent[-1]["type"] == "meeting_analysis_error"
        assert "Missing recording_id" in websocket.sent[-1]["content"]["error"]

    @pytest.mark.asyncio
    async def test_meeting_generate_analysis_broadcasts_complete(
        self, handler, websocket, monkeypatch
    ):
        tasks: list[asyncio.Task] = []
        original_create_task = asyncio.create_task

        def _track_task(coro):
            task = original_create_task(coro)
            tasks.append(task)
            return task

        monkeypatch.setattr(asyncio, "create_task", _track_task)

        fake_analysis = SimpleNamespace(
            generate_analysis=AsyncMock(
                return_value={
                    "summary": "Meeting summary",
                    "actions": [{"type": "task", "description": "Do thing"}],
                    "parse_error": False,
                }
            )
        )
        with (
            patch(
                "source.services.meeting_recorder.meeting_analysis_service",
                fake_analysis,
            ),
            patch.object(handlers, "broadcast_message", new=AsyncMock()) as mock_bcast,
        ):
            await handler._handle_meeting_generate_analysis({"recording_id": "rec-1"})
            await asyncio.gather(*tasks)

        assert websocket.sent[-1]["type"] == "meeting_analysis_started"
        mock_bcast.assert_any_await(
            "meeting_analysis_complete",
            {
                "recording_id": "rec-1",
                "summary": "Meeting summary",
                "actions": [{"type": "task", "description": "Do thing"}],
                "parse_error": False,
            },
        )

    @pytest.mark.asyncio
    async def test_meeting_generate_analysis_broadcasts_error_on_failed_result(
        self, handler, monkeypatch
    ):
        tasks: list[asyncio.Task] = []
        original_create_task = asyncio.create_task

        def _track_task(coro):
            task = original_create_task(coro)
            tasks.append(task)
            return task

        monkeypatch.setattr(asyncio, "create_task", _track_task)

        fake_analysis = SimpleNamespace(
            generate_analysis=AsyncMock(
                return_value={"error": "llm failure", "summary": None, "actions": []}
            )
        )
        with (
            patch(
                "source.services.meeting_recorder.meeting_analysis_service",
                fake_analysis,
            ),
            patch.object(handlers, "broadcast_message", new=AsyncMock()) as mock_bcast,
        ):
            await handler._handle_meeting_generate_analysis({"recording_id": "rec-2"})
            await asyncio.gather(*tasks)

        mock_bcast.assert_any_await(
            "meeting_analysis_error",
            {"recording_id": "rec-2", "error": "llm failure"},
        )

    @pytest.mark.asyncio
    async def test_meeting_execute_action_calendar_and_unsupported_and_exception(
        self, handler, websocket
    ):
        with patch(
            "source.mcp_integration.manager.mcp_manager.call_tool",
            new=AsyncMock(return_value="Created event"),
        ) as mock_call:
            await handler._handle_meeting_execute_action(
                {
                    "recording_id": "rec-1",
                    "action_index": 0,
                    "action": {
                        "type": "calendar_event",
                        "title": "Follow-up",
                        "date": "2026-01-01",
                        "time": "10:00",
                        "duration_minutes": 45,
                        "description": "Discuss roadmap",
                    },
                }
            )

        mock_call.assert_awaited_once_with(
            "create_event",
            {
                "title": "Follow-up",
                "start": "2026-01-01T10:00:00",
                "end": "2026-01-01T10:45:00",
                "description": "Discuss roadmap",
            },
        )
        assert websocket.sent[-1]["type"] == "meeting_action_result"
        assert websocket.sent[-1]["content"]["success"] is True

        await handler._handle_meeting_execute_action(
            {
                "recording_id": "rec-1",
                "action_index": 1,
                "action": {"type": "unknown_action"},
            }
        )
        assert websocket.sent[-1]["content"]["success"] is False
        assert "not executable" in websocket.sent[-1]["content"]["result"]

        with patch(
            "source.mcp_integration.manager.mcp_manager.call_tool",
            new=AsyncMock(side_effect=RuntimeError("tool exploded")),
        ):
            await handler._handle_meeting_execute_action(
                {
                    "recording_id": "rec-1",
                    "action_index": 2,
                    "action": {
                        "type": "email",
                        "to": "a@example.com",
                        "subject": "Hello",
                        "body": "Body",
                    },
                }
            )
        assert websocket.sent[-1]["content"]["success"] is False
        assert isinstance(websocket.sent[-1]["content"]["result"], str)
        assert websocket.sent[-1]["content"]["result"] != ""

    @pytest.mark.asyncio
    async def test_meeting_execute_action_email_and_error_string_result(
        self, handler, websocket
    ):
        with patch(
            "source.mcp_integration.manager.mcp_manager.call_tool",
            new=AsyncMock(side_effect=["Draft created", "Error: quota exceeded"]),
        ) as mock_call:
            await handler._handle_meeting_execute_action(
                {
                    "recording_id": "rec-email",
                    "action_index": 3,
                    "action": {
                        "type": "email",
                        "to": "user@example.com",
                        "subject": "Status",
                        "body": "Body text",
                    },
                }
            )
            await handler._handle_meeting_execute_action(
                {
                    "recording_id": "rec-email",
                    "action_index": 4,
                    "action": {
                        "type": "email",
                        "to": "user@example.com",
                        "subject": "Status",
                        "body": "Body text",
                    },
                }
            )

        assert mock_call.await_count == 2
        mock_call.assert_any_await(
            "create_draft",
            {"to": "user@example.com", "subject": "Status", "body": "Body text"},
        )
        assert websocket.sent[-2]["content"]["success"] is True
        assert websocket.sent[-2]["content"]["result"] == "Draft created"
        assert websocket.sent[-1]["content"]["success"] is False
        assert websocket.sent[-1]["content"]["result"] == "Error: quota exceeded"

    def test_calc_end_time_falls_back_on_parse_error(self, handler):
        assert (
            handler._calc_end_time("bad-date", "bad-time", 30) == "bad-dateTbad-time:00"
        )


class TestTerminalAndYouTubeHandlers:
    @pytest.mark.asyncio
    async def test_terminal_and_youtube_response_handlers(self, handler):
        with (
            patch.object(
                handlers.terminal_service, "resolve_approval"
            ) as mock_resolve_approval,
            patch.object(
                handlers.terminal_service, "resolve_session"
            ) as mock_resolve_session,
            patch.object(
                handlers.video_watcher_service,
                "resolve_transcription_approval",
            ) as mock_resolve_youtube,
            patch.object(
                handlers.terminal_service, "end_session", new=AsyncMock()
            ) as mock_end,
            patch.object(
                handlers.terminal_service, "kill_running_command", new=AsyncMock()
            ) as mock_kill,
            patch.object(
                handlers.terminal_service, "resize_all_pty", new=AsyncMock()
            ) as mock_resize,
        ):
            await handler._handle_terminal_approval_response(
                {"request_id": "req-1", "approved": True, "remember": True}
            )
            await handler._handle_terminal_session_response({"approved": False})
            await handler._handle_youtube_transcription_approval_response(
                {"request_id": "yt-1", "approved": True}
            )
            await handler._handle_terminal_stop_session({})
            await handler._handle_terminal_kill_command({})
            await handler._handle_terminal_resize({"cols": 140, "rows": 40})
            await handler._handle_terminal_resize({"cols": 999, "rows": 40})

        mock_resolve_approval.assert_called_once_with("req-1", True, True)
        mock_resolve_session.assert_called_once_with(False)
        mock_resolve_youtube.assert_called_once_with("yt-1", True)
        mock_end.assert_awaited_once()
        mock_kill.assert_awaited_once()
        mock_resize.assert_awaited_once_with(140, 40)

    @pytest.mark.asyncio
    async def test_terminal_set_ask_level_accepts_known_values_only(self, handler):
        original_level = handlers.terminal_service.ask_level

        await handler._handle_terminal_set_ask_level({"level": "always"})
        assert handlers.terminal_service.ask_level == "always"

        await handler._handle_terminal_set_ask_level({"level": "invalid"})
        assert handlers.terminal_service.ask_level == "always"

        handlers.terminal_service.ask_level = original_level
