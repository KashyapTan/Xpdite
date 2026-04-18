"""Tests for source/api/mobile_internal.py."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from source.api.mobile_internal import (
    CommandExecution,
    MessageSubmission,
    PairingCheck,
    PairingCodeGeneration,
    PairingVerification,
    WhatsAppConnectionUpdate,
    check_pairing,
    cleanup_expired,
    end_session,
    execute_command,
    generate_pairing_code,
    get_all_sessions,
    get_paired_devices,
    get_session,
    health_check,
    revoke_device,
    submit_message,
    update_whatsapp_connection,
    verify_pairing,
)


class TestMobileInternalApi:
    @pytest.mark.asyncio
    async def test_submit_message_returns_success_and_failure_payloads(self):
        body = MessageSubmission(
            platform="telegram",
            sender_id="user-1",
            message_text="hi",
            thread_id="thread-1",
        )

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.handle_message",
            new_callable=AsyncMock,
            return_value=(True, "queued", "tab-1"),
        ):
            assert await submit_message(body) == {
                "success": True,
                "message": "queued",
                "tab_id": "tab-1",
            }

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.handle_message",
            new_callable=AsyncMock,
            return_value=(False, "pair first", None),
        ):
            assert await submit_message(body) == {
                "success": False,
                "message": "pair first",
                "tab_id": None,
            }

    @pytest.mark.asyncio
    async def test_command_and_pairing_endpoints_delegate(self):
        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.handle_command",
            new_callable=AsyncMock,
            return_value="done",
        ):
            result = await execute_command(
                CommandExecution(
                    platform="telegram",
                    sender_id="user-1",
                    command="help",
                    args=None,
                    thread_id=None,
                )
            )
        assert result == {"response": "done"}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.verify_pairing_code",
            return_value=(True, "paired"),
        ):
            assert await verify_pairing(
                PairingVerification(
                    platform="telegram",
                    sender_id="user-1",
                    display_name="User",
                    code="123456",
                )
            ) == {"success": True, "message": "paired"}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.is_paired",
            return_value=True,
        ):
            assert await check_pairing(
                PairingCheck(platform="telegram", sender_id="user-1")
            ) == {"paired": True}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.generate_pairing_code",
            return_value="654321",
        ):
            assert await generate_pairing_code(
                PairingCodeGeneration(expires_in_seconds=300)
            ) == {"code": "654321", "expires_in_seconds": 300}

    @pytest.mark.asyncio
    async def test_device_and_session_endpoints(self):
        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.get_all_paired_devices",
            return_value=[{"id": 1}],
        ):
            assert await get_paired_devices() == {"devices": [{"id": 1}]}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.revoke_device"
        ) as mock_revoke:
            assert await revoke_device(1) == {"success": True}
        mock_revoke.assert_called_once_with(1)

        with patch(
            "source.infrastructure.database.db.get_all_mobile_sessions",
            return_value=[{"tab_id": "tab-1"}],
        ):
            assert await get_all_sessions() == {"sessions": [{"tab_id": "tab-1"}]}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.get_session",
            return_value={"tab_id": "tab-1"},
        ):
            assert await get_session("telegram", "user-1") == {
                "session": {"tab_id": "tab-1"}
            }

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.get_session",
            return_value=None,
        ):
            with pytest.raises(HTTPException, match="Session not found"):
                await get_session("telegram", "user-1")

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.end_session",
            return_value=True,
        ):
            assert await end_session("telegram", "user-1") == {"success": True}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.end_session",
            return_value=False,
        ):
            with pytest.raises(HTTPException, match="Session not found"):
                await end_session("telegram", "user-1")

    @pytest.mark.asyncio
    async def test_update_whatsapp_connection_resets_force_pairing_and_rewrites_config(self):
        body = WhatsAppConnectionUpdate(status="connected", bot_user_id="bot-1")

        with (
            patch(
                "source.infrastructure.database.db.get_setting",
                return_value=json.dumps({"forcePairing": True}),
            ),
            patch("source.infrastructure.database.db.set_setting") as mock_set,
            patch("source.api.http._write_mobile_channels_config_file") as mock_write,
        ):
            result = await update_whatsapp_connection(body)

        assert result == {"success": True, "status": "connected"}
        mock_set.assert_called_once()
        mock_write.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_health_and_cleanup_endpoints(self):
        assert await health_check() == {"status": "ok"}

        with patch(
            "source.services.integrations.mobile_channel.mobile_channel_service.cleanup_expired_codes",
            return_value=4,
        ):
            assert await cleanup_expired() == {"deleted_codes": 4}
