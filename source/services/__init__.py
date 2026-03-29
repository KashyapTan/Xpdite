"""Business logic service exports.

Keep package exports lazy so importing one service module does not eagerly pull
in the entire conversation + LLM stack during backend startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["ScreenshotHandler", "ConversationService"]

if TYPE_CHECKING:
    from .conversations import ConversationService
    from .screenshots import ScreenshotHandler


def __getattr__(name: str) -> Any:
    if name == "ScreenshotHandler":
        from .screenshots import ScreenshotHandler

        return ScreenshotHandler
    if name == "ConversationService":
        from .conversations import ConversationService

        return ConversationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
