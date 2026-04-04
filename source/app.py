"""
FastAPI application factory.

Creates and configures the FastAPI application instance.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.websocket import websocket_endpoint
from .api.http import router as http_router
from .api.terminal import router as terminal_router
from .api.mobile_internal import router as mobile_router
from .core.thread_pool import run_in_thread


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    app = FastAPI(
        title="Xpdite API",
        description="Agentic Personal Assistant that can do anything you can",
        version="0.1.0",
    )

    # Intentionally permissive: this is a local desktop app, not a web service.
    # The Electron shell and React dev server both need unrestricted access.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register WebSocket endpoint
    app.add_websocket_route("/ws", websocket_endpoint)

    # Register HTTP REST routes (e.g., /api/models/ollama, /api/models/enabled)
    app.include_router(http_router)

    # Register terminal API routes (e.g., /api/terminal/settings)
    app.include_router(terminal_router)

    # Register mobile channel internal API routes (Channel Bridge <-> Python)
    app.include_router(mobile_router)

    # ── Tab manager initialization ────────────────────────────────
    @app.on_event("startup")
    async def _init_tab_manager():
        from .services.tab_manager_instance import init_tab_manager

        init_tab_manager()

    # ── Mobile channel session restoration ────────────────────────────────
    @app.on_event("startup")
    async def _restore_mobile_sessions():
        from .services.mobile_channel import mobile_channel_service

        mobile_channel_service.restore_sessions_from_db()
        mobile_channel_service.cleanup_expired_codes()
        mobile_channel_service.register_relay_callback()

    # ── Channel Bridge config sync ────────────────────────────────
    @app.on_event("startup")
    async def _sync_mobile_channels_bridge_config():
        from .api.http import _write_mobile_channels_config_file

        try:
            await run_in_thread(_write_mobile_channels_config_file)
        except Exception as e:
            logger.warning("Failed to sync mobile channels config on startup: %s", e)

    # ── File browser indexer lifecycle ────────────────────────────────
    @app.on_event("startup")
    async def _start_file_browser_indexer():
        from .services.file_browser import file_browser_service

        try:
            file_browser_service.start()
        except Exception as e:
            logger.warning("Failed to start file browser indexer: %s", e)

    @app.on_event("shutdown")
    async def _stop_file_browser_indexer():
        from .services.file_browser import file_browser_service

        try:
            file_browser_service.shutdown()
        except Exception as e:
            logger.warning("Failed to stop file browser indexer: %s", e)

    return app


# Create the app instance for uvicorn
app = create_app()
