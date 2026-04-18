"""Tests for source/services/scheduling/notifications.py."""

from unittest.mock import AsyncMock, patch

import pytest

from source.services.scheduling.notifications import (
    NotificationService,
    create_tab_completion_notification,
)


class TestNotificationService:
    @pytest.mark.asyncio
    async def test_create_persists_and_broadcasts_notification(self):
        service = NotificationService()
        notification = {"id": "n1", "title": "Done"}

        with (
            patch(
                "source.services.scheduling.notifications.db.create_notification",
                return_value=notification,
            ) as mock_create,
            patch(
                "source.services.scheduling.notifications.broadcast_message",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            result = await service.create(
                notification_type="job_complete",
                title="Done",
                body="Finished",
                payload={"job_id": "job-1"},
            )

        assert result == notification
        mock_create.assert_called_once_with(
            notification_type="job_complete",
            title="Done",
            body="Finished",
            payload={"job_id": "job-1"},
        )
        mock_broadcast.assert_awaited_once_with("notification_added", notification)

    @pytest.mark.asyncio
    async def test_dismiss_returns_false_when_notification_missing(self):
        service = NotificationService()

        with (
            patch(
                "source.services.scheduling.notifications.db.get_notification",
                return_value=None,
            ),
            patch(
                "source.services.scheduling.notifications.broadcast_message",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            result = await service.dismiss("missing")

        assert result is False
        mock_broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dismiss_deletes_and_broadcasts(self):
        service = NotificationService()

        with (
            patch(
                "source.services.scheduling.notifications.db.get_notification",
                return_value={"id": "n1"},
            ),
            patch(
                "source.services.scheduling.notifications.db.delete_notification"
            ) as mock_delete,
            patch(
                "source.services.scheduling.notifications.broadcast_message",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            result = await service.dismiss("n1")

        assert result is True
        mock_delete.assert_called_once_with("n1")
        mock_broadcast.assert_awaited_once_with(
            "notification_dismissed", {"id": "n1"}
        )

    @pytest.mark.asyncio
    async def test_dismiss_all_returns_count_and_broadcasts(self):
        service = NotificationService()

        with (
            patch(
                "source.services.scheduling.notifications.db.delete_all_notifications",
                return_value=3,
            ),
            patch(
                "source.services.scheduling.notifications.broadcast_message",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            result = await service.dismiss_all()

        assert result == 3
        mock_broadcast.assert_awaited_once_with("notifications_cleared", {})

    def test_list_get_and_count_delegate_to_database(self):
        service = NotificationService()

        with (
            patch(
                "source.services.scheduling.notifications.db.list_notifications",
                return_value=[{"id": "n1"}],
            ) as mock_list,
            patch(
                "source.services.scheduling.notifications.db.get_notification",
                return_value={"id": "n2"},
            ) as mock_get,
            patch(
                "source.services.scheduling.notifications.db.get_notification_count",
                return_value=7,
            ) as mock_count,
        ):
            assert service.list(limit=25) == [{"id": "n1"}]
            assert service.get("n2") == {"id": "n2"}
            assert service.count() == 7

        mock_list.assert_called_once_with(limit=25)
        mock_get.assert_called_once_with("n2")
        mock_count.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_tab_completion_notification_truncates_preview():
    preview = "x" * 151

    with patch(
        "source.services.scheduling.notifications.notification_service.create",
        new_callable=AsyncMock,
        return_value={"id": "n1"},
    ) as mock_create:
        result = await create_tab_completion_notification(
            "tab-1",
            "conv-1",
            "Background tab finished",
            preview,
        )

    assert result == {"id": "n1"}
    mock_create.assert_awaited_once_with(
        notification_type="tab_complete",
        title="Background tab finished",
        body=("x" * 150) + "...",
        payload={"tab_id": "tab-1", "conversation_id": "conv-1"},
    )
