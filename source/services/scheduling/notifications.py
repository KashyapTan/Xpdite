"""
Notification Service.

Manages app-wide notifications for async events like scheduled job
completions and background tab completions.

Notifications are stored in the database and broadcast via WebSocket
to all connected clients. The frontend maintains a local cache of
unread notifications and displays them in the notification bell dropdown.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.connection import broadcast_message
from ...infrastructure.database import db

logger = logging.getLogger(__name__)


class NotificationService:
    """Manages notification lifecycle and broadcasting."""

    async def create(
        self,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a notification and broadcast it to all clients.

        Args:
            notification_type: Type of notification (job_complete, tab_complete, etc.)
            title: Short notification title
            body: Optional preview/description text
            payload: Optional JSON payload with metadata (conversation_id, job_id, tab_id)

        Returns:
            The created notification record
        """
        notification = db.create_notification(
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )

        # Broadcast to all connected clients
        await broadcast_message("notification_added", notification)

        logger.debug(f"Created notification: {notification_type} - {title}")
        return notification

    async def dismiss(self, notification_id: str) -> bool:
        """Dismiss (delete) a notification and broadcast the change.

        Returns True if the notification existed and was deleted.
        """
        notification = db.get_notification(notification_id)
        if not notification:
            return False

        db.delete_notification(notification_id)
        await broadcast_message("notification_dismissed", {"id": notification_id})

        logger.debug(f"Dismissed notification: {notification_id}")
        return True

    async def dismiss_all(self) -> int:
        """Dismiss all notifications and broadcast the change.

        Returns the count of deleted notifications.
        """
        count = db.delete_all_notifications()
        await broadcast_message("notifications_cleared", {})

        logger.debug(f"Cleared all notifications ({count} total)")
        return count

    def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all unread notifications, newest first."""
        return db.list_notifications(limit=limit)

    def get(self, notification_id: str) -> Optional[Dict[str, Any]]:
        """Get a single notification by ID."""
        return db.get_notification(notification_id)

    def count(self) -> int:
        """Get the count of unread notifications."""
        return db.get_notification_count()


# Global singleton instance
notification_service = NotificationService()


async def create_tab_completion_notification(
    tab_id: str, conversation_id: str, title: str, preview: str
) -> Dict[str, Any]:
    """Helper to create a notification for background tab completion.

    Called when a tab that is not currently active finishes generating
    a response.
    """
    return await notification_service.create(
        notification_type="tab_complete",
        title=title,
        body=preview[:150] + "..." if len(preview) > 150 else preview,
        payload={
            "tab_id": tab_id,
            "conversation_id": conversation_id,
        },
    )
