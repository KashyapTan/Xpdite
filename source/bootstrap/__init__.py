"""Backend bootstrap package.

Contains application wiring and startup composition code.
Exports are lazy to avoid importing FastAPI wiring until needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["app", "create_app"]

if TYPE_CHECKING:
    from .app_factory import app, create_app


def __getattr__(name: str) -> Any:
    if name in {"app", "create_app"}:
        from .app_factory import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
