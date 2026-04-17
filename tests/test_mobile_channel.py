"""Tests for source/services/integrations/mobile_channel.py."""

import asyncio
from unittest.mock import AsyncMock, patch

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
