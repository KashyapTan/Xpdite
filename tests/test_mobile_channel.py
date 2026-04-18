"""Tests for source/services/integrations/mobile_channel.py."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from source.services.integrations.mobile_channel import (
    MobileChannelService,
    canonical_sender_id,
)


class TestMobileChannelServiceCanonicalization:
    def test_whatsapp_sender_id_strips_device_suffix(self):
        canonical = canonical_sender_id("whatsapp", "15551234567:12@s.whatsapp.net")

        assert canonical == "15551234567@s.whatsapp.net"

    def test_non_whatsapp_sender_id_unchanged(self):
        canonical = canonical_sender_id("telegram", "123456789")

        assert canonical == "123456789"


class TestMobileChannelServicePairingAndSessions:
    def test_verify_pairing_code_short_circuits_when_already_paired(self):
        service = MobileChannelService()

        with patch.object(service, "is_paired", return_value=True):
            success, message = service.verify_pairing_code(
                "telegram", "user-1", "User", "123456"
            )

        assert success is True
        assert "already paired" in message

    def test_verify_pairing_code_rejects_invalid_codes(self):
        service = MobileChannelService()

        with (
            patch.object(service, "is_paired", return_value=False),
            patch(
                "source.services.integrations.mobile_channel.db.verify_pairing_code",
                return_value=False,
            ),
        ):
            success, message = service.verify_pairing_code(
                "telegram", "user-1", "User", "123456"
            )

        assert success is False
        assert "Invalid or expired pairing code" in message

    def test_verify_pairing_code_creates_device_pairing(self):
        service = MobileChannelService()

        with (
            patch.object(service, "is_paired", return_value=False),
            patch(
                "source.services.integrations.mobile_channel.db.verify_pairing_code",
                return_value=True,
            ),
            patch(
                "source.services.integrations.mobile_channel.db.add_paired_device"
            ) as add_device,
        ):
            success, message = service.verify_pairing_code(
                "telegram", " user-1 ", "User", "123456"
            )

        assert success is True
        assert "Successfully paired" in message
        add_device.assert_called_once_with("telegram", "user-1", "User")

    def test_generate_pairing_code_persists_expiry(self):
        service = MobileChannelService()

        with (
            patch("source.services.integrations.mobile_channel.secrets.randbelow", return_value=23),
            patch(
                "source.services.integrations.mobile_channel.db.create_pairing_code"
            ) as create_code,
        ):
            code = service.generate_pairing_code(expires_in_seconds=120)

        assert code == "100023"
        create_code.assert_called_once_with("100023", 120)

    def test_get_or_create_session_returns_existing_session(self):
        service = MobileChannelService()
        session = {"tab_id": "tab-1", "model_override": "model-a"}

        with (
            patch(
                "source.services.integrations.mobile_channel.db.get_mobile_session",
                return_value=session,
            ),
            patch(
                "source.services.integrations.mobile_channel.db.update_paired_device_activity"
            ) as update_activity,
        ):
            result, is_new = service.get_or_create_session("telegram", "user-1")

        assert result is session
        assert is_new is False
        update_activity.assert_called_once_with("telegram", "user-1")

    def test_get_or_create_session_creates_and_tracks_new_session(self):
        service = MobileChannelService()
        created_session = {"tab_id": "mobile-telegram-abcdef12"}

        with (
            patch(
                "source.services.integrations.mobile_channel.db.get_mobile_session",
                side_effect=[None, created_session],
            ),
            patch(
                "source.services.integrations.mobile_channel.db.create_mobile_session"
            ) as create_session,
            patch(
                "source.services.integrations.mobile_channel.db.update_paired_device_activity"
            ) as update_activity,
            patch(
                "source.services.integrations.mobile_channel.uuid.uuid4",
                return_value=SimpleNamespace(hex="abcdef1234567890"),
            ),
        ):
            session, is_new = service.get_or_create_session("telegram", "user-1")

        assert session is created_session
        assert is_new is True
        assert service._mobile_tabs["mobile-telegram-abcdef12"] == (
            "telegram",
            "user-1",
            None,
        )
        create_session.assert_called_once_with(
            "telegram", "user-1", "mobile-telegram-abcdef12"
        )
        update_activity.assert_called_once_with("telegram", "user-1")

    def test_end_session_deletes_db_record_and_tracking(self):
        service = MobileChannelService()
        service._mobile_tabs["tab-1"] = ("telegram", "user-1", None)

        with (
            patch(
                "source.services.integrations.mobile_channel.db.get_mobile_session",
                return_value={"tab_id": "tab-1"},
            ),
            patch(
                "source.services.integrations.mobile_channel.db.delete_mobile_session"
            ) as delete_session,
        ):
            result = service.end_session("telegram", "user-1")

        assert result is True
        assert "tab-1" not in service._mobile_tabs
        delete_session.assert_called_once_with("telegram", "user-1")


class TestMobileChannelServiceStreaming:
    @pytest.mark.asyncio
    async def test_enqueue_broadcast_event_processes_events_in_order_per_tab(self):
        service = MobileChannelService()
        service._mobile_tabs["tab-1"] = ("telegram", "user-1", "thread-1")
        observed: list[tuple[str, str]] = []

        async def fake_chunk(
            tab_id: str,
            platform: str,
            sender_id: str,
            thread_id: str | None,
            content: str,
        ) -> None:
            observed.append(("chunk", str(content)))
            await asyncio.sleep(0)

        async def fake_finalize(
            tab_id: str,
            platform: str,
            sender_id: str,
            thread_id: str | None,
        ) -> None:
            observed.append(("complete", tab_id))
            await asyncio.sleep(0)

        with (
            patch.object(service, "_handle_streaming_chunk", side_effect=fake_chunk),
            patch.object(service, "_finalize_streaming", side_effect=fake_finalize),
        ):
            await service.enqueue_broadcast_event("response_chunk", "first", "tab-1")
            await service.enqueue_broadcast_event("response_complete", "", "tab-1")
            await service.enqueue_broadcast_event("response_chunk", "second", "tab-1")

            worker = service._relay_workers["tab-1"]
            await worker

        assert observed == [
            ("chunk", "first"),
            ("complete", "tab-1"),
            ("chunk", "second"),
        ]

        await service.close()

    @pytest.mark.asyncio
    async def test_finalize_streaming_waits_for_conversation_saved(self):
        service = MobileChannelService()
        service._streaming_state["tab-1"] = {
            "accumulated_text": "partial final answer",
            "last_edit_time": 0.0,
            "last_typing_time": 0.0,
            "platform": "telegram",
            "sender_id": "user-1",
            "thread_id": "thread-1",
            "posted_message_id": "msg-1",
            "response_complete_seen": False,
        }

        with patch.object(
            service, "relay_edit_message", AsyncMock(return_value=True)
        ) as edit_mock:
            await service._finalize_streaming(
                "tab-1",
                "telegram",
                "user-1",
                "thread-1",
            )

        edit_mock.assert_awaited_once_with(
            "telegram",
            "thread-1",
            "msg-1",
            "partial final answer",
            render_mode="raw",
        )
        assert service._streaming_state["tab-1"]["response_complete_seen"] is True
        assert "tab-1" not in service._pending_response_completion

        await service.close()

    @pytest.mark.asyncio
    async def test_conversation_saved_edits_streamed_message_with_saved_turn_text(self):
        service = MobileChannelService()
        service._streaming_state["tab-1"] = {
            "accumulated_text": "stale streamed answer",
            "last_edit_time": 0.0,
            "last_typing_time": 0.0,
            "platform": "telegram",
            "sender_id": "user-1",
            "thread_id": "thread-1",
            "posted_message_id": "msg-1",
            "response_complete_seen": True,
        }

        payload = {
            "conversation_id": "conv-1",
            "operation": "submit",
            "turn": {
                "assistant": {
                    "content": "current persisted answer",
                }
            },
        }

        with patch.object(
            service, "relay_edit_message", AsyncMock(return_value=True)
        ) as edit_mock:
            await service._handle_conversation_saved(
                "tab-1",
                "telegram",
                "user-1",
                "thread-1",
                payload,
            )

        edit_mock.assert_awaited_once_with(
            "telegram",
            "thread-1",
            "msg-1",
            "current persisted answer",
            render_mode="markdown",
        )
        assert "tab-1" not in service._streaming_state
        assert "tab-1" not in service._pending_response_completion

        await service.close()

    @pytest.mark.asyncio
    async def test_conversation_saved_posts_non_streamed_response_after_completion(self):
        service = MobileChannelService()
        service._pending_response_completion["tab-1"] = {
            "platform": "telegram",
            "sender_id": "user-1",
            "thread_id": "thread-1",
        }

        payload = {
            "conversation_id": "conv-1",
            "operation": "submit",
            "turn": {
                "assistant": {
                    "content": "non-streamed final answer",
                }
            },
        }

        with patch.object(
            service, "relay_response", AsyncMock(return_value=True)
        ) as response_mock:
            await service._handle_conversation_saved(
                "tab-1",
                "telegram",
                "user-1",
                "thread-1",
                payload,
            )

        response_mock.assert_awaited_once_with(
            "telegram",
            "user-1",
            "non-streamed final answer",
            "thread-1",
            render_mode="markdown",
        )
        assert "tab-1" not in service._pending_response_completion

        await service.close()

    def test_extract_message_text_uses_content_blocks_and_variants(self):
        service = MobileChannelService()

        assert (
            service._extract_message_text(
                {
                    "content": "",
                    "content_blocks": [
                        {"type": "text", "content": "from content blocks"},
                    ],
                }
            )
            == "from content blocks"
        )

        assert (
            service._extract_message_text(
                {
                    "content": "",
                    "active_response_index": 1,
                    "response_variants": [
                        {"response_index": 0, "content": "old"},
                        {
                            "response_index": 1,
                            "content": "",
                            "content_blocks": [
                                {"type": "text", "content": "active variant text"},
                            ],
                        },
                    ],
                }
            )
            == "active variant text"
        )


class TestMobileChannelServiceCommands:
    @pytest.mark.asyncio
    async def test_handle_message_requires_pairing(self):
        service = MobileChannelService()

        with patch.object(service, "is_paired", return_value=False):
            success, message, tab_id = await service.handle_message(
                "telegram", "user-1", "hi"
            )

        assert success is False
        assert "pair first" in message.lower()
        assert tab_id is None

    @pytest.mark.asyncio
    async def test_handle_message_uses_session_defaults_and_reports_queue_position(self):
        service = MobileChannelService()
        queue = AsyncMock()
        queue.enqueue.return_value = 2
        tab_session = SimpleNamespace(queue=queue)

        with (
            patch.object(service, "is_paired", return_value=True),
            patch.object(
                service,
                "get_or_create_session",
                return_value=({"tab_id": "tab-1", "model_override": None}, True),
            ),
            patch(
                "source.services.integrations.mobile_channel.db.get_paired_device_default_model",
                return_value="model-a",
            ),
            patch(
                "source.services.chat.tab_manager_instance.tab_manager",
                SimpleNamespace(get_or_create=lambda tab_id: tab_session),
            ),
        ):
            success, message, tab_id = await service.handle_message(
                "telegram", "user-1", "hello", thread_id="thread-1"
            )

        assert success is True
        assert tab_id == "tab-1"
        assert "Started new conversation." in message
        assert "Queue position: 2" in message
        queue.enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_command_cancels_active_queue_and_pending_approvals(self):
        service = MobileChannelService()
        queue = AsyncMock()
        tab_session = type("TabSession", (), {"queue": queue})()

        with (
            patch.object(service, "get_session", return_value={"tab_id": "tab-1"}),
            patch.object(service, "is_paired", return_value=True),
            patch(
                "source.services.chat.tab_manager_instance.tab_manager",
                type("TabManagerRef", (), {"get_session": lambda self, tab_id: tab_session})(),
            ),
            patch(
                "source.services.integrations.mobile_channel.broadcast_to_tab",
                new_callable=AsyncMock,
            ) as mock_broadcast,
            patch(
                "source.services.shell.terminal.terminal_service.cancel_all_pending"
            ) as mock_cancel_terminal,
            patch(
                "source.services.media.video_watcher.video_watcher_service.cancel_all_pending"
            ) as mock_cancel_video,
        ):
            result = await service.handle_command("telegram", "user-1", "stop")

        assert result == "Stopped the current generation."
        queue.stop_current.assert_awaited_once_with()
        mock_cancel_terminal.assert_called_once_with()
        mock_cancel_video.assert_called_once_with()
        mock_broadcast.assert_awaited_once_with(
            "tab-1", "generation_stopped", {"source": "mobile"}
        )

    @pytest.mark.asyncio
    async def test_stop_command_returns_message_when_no_active_session(self):
        service = MobileChannelService()

        with (
            patch.object(service, "is_paired", return_value=True),
            patch.object(service, "get_session", return_value=None),
        ):
            result = await service.handle_command("telegram", "user-1", "stop")

        assert result == "No active conversation to stop."

    def test_status_model_and_default_commands_cover_branching(self):
        service = MobileChannelService()

        with (
            patch.object(
                service, "get_session", return_value={"tab_id": "tab-1", "model_override": None}
            ),
            patch(
                "source.services.integrations.mobile_channel.db.get_paired_device_default_model",
                return_value=None,
            ),
            patch(
                "source.services.integrations.mobile_channel.db.get_enabled_models",
                return_value=["alpha", "beta", "beta-fast"],
            ),
            patch(
                "source.services.chat.tab_manager_instance.tab_manager",
                SimpleNamespace(
                    get_session=lambda tab_id: SimpleNamespace(
                        queue=SimpleNamespace(size=lambda: 2)
                    )
                ),
            ),
            patch(
                "source.services.integrations.mobile_channel.db.update_mobile_session"
            ) as update_mobile_session,
            patch.object(
                service, "get_or_create_session", return_value=({"tab_id": "tab-1"}, True)
            ) as get_or_create_session,
            patch(
                "source.services.integrations.mobile_channel.db.set_paired_device_default_model"
            ) as set_default_model,
        ):
            status = service._cmd_status("telegram", "user-1")
            listed = service._cmd_model("telegram", "user-1", None)
            ambiguous = service._cmd_model("telegram", "user-1", "bet")
            switched = service._cmd_model("telegram", "user-1", "alpha")
            default_missing = service._cmd_default("telegram", "user-1", None)
            default_set = service._cmd_default("telegram", "user-1", "alpha")

        assert "Session: Active" in status
        assert "Queue: 2 message(s) waiting" in status
        assert "Available models:" in listed
        assert "(active)" in listed
        assert "Ambiguous match." in ambiguous
        assert switched == "Switched to alpha"
        assert "No default model set" in default_missing
        assert default_set == "Default model set to alpha for this device."
        update_mobile_session.assert_any_call("telegram", "user-1", model_override="alpha")
        get_or_create_session.assert_not_called()
        set_default_model.assert_called_once_with("telegram", "user-1", "alpha")


class TestMobileChannelServiceRelay:
    @pytest.mark.asyncio
    async def test_relay_helpers_cover_success_and_http_errors(self):
        service = MobileChannelService()
        success_response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"message_id": "msg-1"},
        )
        success_client = SimpleNamespace(post=AsyncMock(return_value=success_response))
        error_client = SimpleNamespace(
            post=AsyncMock(side_effect=httpx.HTTPError("boom"))
        )

        with patch.object(service, "_get_client", AsyncMock(return_value=success_client)):
            message_id = await service.relay_to_platform(
                "telegram", "user-1", "response", "hello", "thread-1"
            )
            typing_sent = await service.relay_typing("telegram", "thread-1")
            edited = await service.relay_edit_message(
                "telegram", "thread-1", "msg-1", "updated"
            )

        assert message_id == "msg-1"
        assert typing_sent is True
        assert edited is True

        with patch.object(service, "_get_client", AsyncMock(return_value=error_client)):
            failed = await service.relay_to_platform(
                "telegram", "user-1", "response", "hello"
            )

        assert failed is None
        assert await service.relay_typing("telegram", None) is False

    @pytest.mark.asyncio
    async def test_handle_broadcast_event_relays_tool_results_and_errors(self):
        service = MobileChannelService()
        service._mobile_tabs["tab-1"] = ("telegram", "user-1", "thread-1")
        service._streaming_state["tab-1"] = {"posted_message_id": "msg-1"}
        service._pending_response_completion["tab-1"] = {"thread_id": "thread-1"}

        with (
            patch.object(service, "relay_tool_status", AsyncMock()) as relay_tool_status,
            patch.object(service, "relay_to_platform", AsyncMock()) as relay_to_platform,
            patch.object(service, "relay_error", AsyncMock()) as relay_error,
        ):
            await service.handle_broadcast_event(
                "tool_call",
                {"name": "memory_lookup", "status": "calling"},
                "tab-1",
            )
            await service.handle_broadcast_event(
                "tool_call",
                {"name": "memory_lookup", "status": "complete", "result": "x" * 250},
                "tab-1",
            )
            await service.handle_broadcast_event("error", "boom", "tab-1")

        relay_tool_status.assert_awaited_once_with(
            "telegram", "user-1", "memory_lookup", "thread-1"
        )
        relay_to_platform.assert_awaited_once()
        assert "tab-1" not in service._streaming_state
        assert "tab-1" not in service._pending_response_completion
        relay_error.assert_awaited_once_with("telegram", "user-1", "boom", "thread-1")

    def test_restore_sessions_cleanup_and_sanitize_for_platform(self):
        service = MobileChannelService()

        with patch(
            "source.services.integrations.mobile_channel.db.get_all_mobile_sessions",
            return_value=[
                {
                    "tab_id": "tab-1",
                    "platform": "whatsapp",
                    "sender_id": "15551234567:12@s.whatsapp.net",
                }
            ],
        ):
            restored = service.restore_sessions_from_db()

        assert restored == 1
        assert service._mobile_tabs["tab-1"] == (
            "whatsapp",
            "15551234567@s.whatsapp.net",
            None,
        )

        with patch(
            "source.services.integrations.mobile_channel.db.cleanup_expired_pairing_codes",
            return_value=4,
        ):
            assert service.cleanup_expired_codes() == 4

        telegram_text = service._sanitize_for_platform("x" * 4100, "telegram")
        discord_text = service._sanitize_for_platform("x" * 4100, "discord")
        assert "[Message truncated due to length]" in telegram_text
        assert len(discord_text) == 4100
