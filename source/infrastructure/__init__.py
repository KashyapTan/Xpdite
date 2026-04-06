"""Backend infrastructure package.

Contains infrastructure adapters and runtime primitives.
Exports are lazy to avoid import-time side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "DatabaseManager",
    "ScreenshotService",
    "db",
]

if TYPE_CHECKING:
    from .infrastructure.database import DatabaseManager, db
    from .screenshot_runtime import ScreenshotService


def __getattr__(name: str) -> Any:
    if name in {"DatabaseManager", "db"}:
        from .infrastructure.database import DatabaseManager, db

        return {"DatabaseManager": DatabaseManager, "db": db}[name]
    if name == "ScreenshotService":
        from .screenshot_runtime import ScreenshotService

        return ScreenshotService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
