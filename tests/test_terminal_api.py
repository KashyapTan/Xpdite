"""Tests for source/api/terminal.py endpoints."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import source.api.terminal as terminal_api


class TestTerminalApi:
    @pytest.mark.asyncio
    async def test_get_terminal_settings_returns_service_and_approval_data(self):
        mock_service = MagicMock()
        mock_service.ask_level = "on-miss"
        mock_service.session_mode = True

        with (
            patch.object(terminal_api, "terminal_service", mock_service),
            patch.object(terminal_api, "get_approval_count", return_value=7),
        ):
            result = await terminal_api.get_terminal_settings()

        assert result == {
            "ask_level": "on-miss",
            "session_mode": True,
            "approval_count": 7,
        }

    @pytest.mark.asyncio
    async def test_set_ask_level_updates_service_value(self):
        mock_service = MagicMock()
        mock_service.ask_level = "on-miss"

        with patch.object(terminal_api, "terminal_service", mock_service):
            result = await terminal_api.set_ask_level(
                terminal_api.AskLevelRequest(level="off")
            )

        assert mock_service.ask_level == "off"
        assert result == {"ask_level": "off"}

    @pytest.mark.asyncio
    async def test_set_ask_level_rejects_invalid_values(self):
        mock_service = MagicMock()
        mock_service.ask_level = "on-miss"

        with patch.object(terminal_api, "terminal_service", mock_service):
            with pytest.raises(HTTPException) as exc:
                await terminal_api.set_ask_level(SimpleNamespace(level="invalid-level"))

        assert exc.value.status_code == 400
        assert "Invalid ask level" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_clear_approval_history_clears_and_returns_empty_count(self):
        with patch.object(terminal_api, "clear_approvals") as clear_mock:
            result = await terminal_api.clear_approval_history()

        clear_mock.assert_called_once_with()
        assert result == {"cleared": True, "approval_count": 0}
