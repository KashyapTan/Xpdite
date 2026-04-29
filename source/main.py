"""
Xpdite Application Entry Point.

This is the main entry point for the Python backend server.
It initializes all services and starts the FastAPI server.

Architecture:
    source/
    ├── main.py           # This file - entry point
    ├── bootstrap/
    │   └── app_factory.py # FastAPI app factory + startup/shutdown hooks
    ├── infrastructure/
    │   ├── config.py      # Configuration constants
    │   ├── database.py    # SQLite operations
    │   └── screenshot_runtime.py # Screenshot service runtime
    ├── core/             # Core utilities
    │   ├── state.py        # Global state management
    │   ├── connection.py   # WebSocket connections
    │   ├── lifecycle.py    # Cleanup & signals
    │   ├── request_context.py # Request cancellation
    │   └── thread_pool.py  # App-owned thread pool
    ├── api/              # API layer (thin, no business logic)
    │   ├── websocket.py    # WebSocket endpoint
    │   ├── handlers.py     # Message handlers
    │   ├── http.py         # REST API endpoints
    │   └── terminal.py     # Terminal REST endpoints
    ├── mcp_integration/  # MCP tool integration
    │   ├── core/           # Manager, handlers, retrieval, skill injection
    │   └── executors/      # Inline tool executors
    ├── llm/              # LLM integration
    │   ├── core/           # Routing, prompting, key management, shared types
    │   └── providers/      # Provider-specific streaming implementations
    └── services/         # Business logic
        ├── chat/            # Conversation orchestration, queues, tab state
        ├── media/           # Screenshot, transcription, meeting media pipeline
        ├── shell/           # Terminal execution + approvals
        ├── integrations/    # External/mobile/google integrations
        ├── filesystem/      # File browser/indexing
        ├── memory_store/    # Memory persistence service
        ├── skills_runtime/  # Skills management + sub-agent runtime
        └── scheduling/      # Schedules + notifications
"""

import socket
import threading
import time
import asyncio
import logging
import json
import sys as _sys

import uvicorn

# Import configuration (relative to source package)
from .infrastructure.config import (
    SCREENSHOT_FOLDER,
    DEFAULT_PORT,
    MAX_PORT_ATTEMPTS,
    SERVER_BIND_HOST,
)

# Import core components
from .core.state import app_state
from .core.lifecycle import register_signal_handlers

# Import app factory
from .bootstrap.app_factory import app

# Import MCP initialization
from .mcp_integration.core.manager import init_mcp_servers

# Import screenshot service hooks
from .services.media.screenshots import (
    process_screenshot,
    process_screenshot_cancelled,
    process_screenshot_start,
)

# Configure logging before runtime startup.
logging.basicConfig(
    level=logging.INFO,
    # Keep level prefixes visible in the Electron/dev terminal so retrieval and
    # backend lifecycle logs are easy to spot.
    format="[%(levelname)s] %(message)s",
    stream=_sys.stdout,
    force=True,
)
# Silence noisy libraries
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
_OPTIONAL_MCP_RECONNECT_DELAY_SECONDS = 15


def _emit_boot_marker(phase: str, message: str, progress: int) -> None:
    """Emit a structured boot marker to stdout for Electron to parse."""
    marker = json.dumps({"phase": phase, "message": message, "progress": progress})
    print(f"XPDITE_BOOT {marker}", flush=True)  # noqa: T201
    _sys.stdout.flush()


def find_available_port(
    start_port: int = DEFAULT_PORT, max_attempts: int = MAX_PORT_ATTEMPTS
) -> int:
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"Could not find available port in range {start_port}-{start_port + max_attempts - 1}"
    )


async def _start_optional_services() -> None:
    """Start non-critical services after HTTP startup is already underway."""
    await asyncio.sleep(0)

    async def _start_google_servers() -> None:
        try:
            from .infrastructure.config import GOOGLE_TOKEN_FILE
            import os

            if os.path.exists(GOOGLE_TOKEN_FILE):
                from .mcp_integration.core.manager import mcp_manager

                await mcp_manager.connect_google_servers()
                logger.info("Gmail & Calendar MCP servers started (token found)")
            else:
                logger.info("No Google token found — skipping Gmail & Calendar servers")
        except Exception as e:
            logger.warning("Failed to start Google servers (non-fatal): %s", e)

    async def _start_scheduler_service() -> None:
        try:
            from .services.scheduling.scheduler import scheduler_service

            await scheduler_service.start()
            logger.info("Scheduler service started")
        except Exception as e:
            logger.warning("Failed to start scheduler service (non-fatal): %s", e)

    async def _start_optional_mcp_servers() -> None:
        try:
            # Marketplace/plugin reconnects can clone/index user-installed MCP
            # bundles. Keep that work out of the renderer/backend boot window.
            await asyncio.sleep(_OPTIONAL_MCP_RECONNECT_DELAY_SECONDS)

            from .mcp_integration.core.manager import connect_optional_mcp_servers

            await connect_optional_mcp_servers()
        except Exception as e:
            logger.warning("Failed to start optional MCP servers (non-fatal): %s", e)

    await asyncio.gather(
        _start_google_servers(),
        _start_scheduler_service(),
    )
    await _start_optional_mcp_servers()


def start_server():
    """Start FastAPI server in the current thread & store its loop."""
    _emit_boot_marker("loading_runtime", "Loading AI runtime", 20)

    try:
        port = find_available_port()
        logger.info("Starting server on port %d", port)
    except RuntimeError as e:
        logger.error("Error finding available port: %s", e)
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Ensure the default tab exists before any hotkey-driven screenshot
    # work is scheduled from the background listener thread.
    from .services.chat.tab_manager_instance import init_tab_manager

    init_tab_manager()

    app_state.server_loop_holder["loop"] = loop
    app_state.server_loop_holder["port"] = port

    # Initialize MCP servers
    _emit_boot_marker("initializing_mcp", "Connecting tool servers", 45)
    try:
        loop.run_until_complete(init_mcp_servers())
    except Exception as e:
        logger.warning("MCP server initialization failed (non-fatal): %s", e)

    # Start uvicorn server
    _emit_boot_marker("starting_http", "Preparing chat features", 75)
    config = uvicorn.Config(
        app, host=SERVER_BIND_HOST, port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    loop.create_task(_start_optional_services(), name="xpdite-optional-startup")
    loop.run_until_complete(server.serve())


def bootstrap_backend_server():
    """Backward-compatible alias for start_server()."""
    start_server()


def start_screenshot_service():
    """Start the screenshot service."""
    try:
        from .infrastructure.screenshot_runtime import ScreenshotService

        app_state.screenshot_service = ScreenshotService(
            process_screenshot, process_screenshot_start, process_screenshot_cancelled
        )
        app_state.service_thread = threading.Thread(
            target=app_state.screenshot_service.start_listener,
            args=(SCREENSHOT_FOLDER,),
            daemon=True,
        )
        app_state.service_thread.start()
        logger.info("Screenshot service started")
    except Exception as e:
        logger.error("Error starting screenshot service: %s", e)


def start_transcription_service():
    """Start the transcription service."""
    try:
        from .services.media.transcription import TranscriptionService

        # Initialize the service (model loads lazily on first use)
        app_state.transcription_service = TranscriptionService()
        logger.info("Transcription service initialized")
    except Exception as e:
        logger.error("Error starting transcription service: %s", e)


def main():
    """Main entry point."""
    # Register signal handlers for graceful shutdown
    register_signal_handlers()

    # Cleanup old extracted images from previous sessions (>24 hours old)
    try:
        from .services.media.file_extractor import FileExtractor

        removed = FileExtractor.cleanup_extracted_images(max_age_hours=24)
        if removed > 0:
            logger.info(
                "Cleaned up %d old extracted images from previous sessions", removed
            )
    except Exception as e:
        logger.warning("Failed to cleanup old extracted images (non-fatal): %s", e)

    logger.info("=" * 50)
    logger.info("  XPDITE - AI Desktop Assistant")
    logger.info("=" * 50)
    logger.info("Starting services...")

    # Start FastAPI server in background thread
    app_state.server_thread = threading.Thread(target=start_server, daemon=True)
    app_state.server_thread.start()

    # Wait for server loop to be ready
    server_ready = threading.Event()

    def _poll_server_ready():
        for _ in range(50):
            if app_state.server_loop_holder.get("loop") is not None:
                server_ready.set()
                return
            time.sleep(0.1)

    poll_thread = threading.Thread(target=_poll_server_ready, daemon=True)
    poll_thread.start()
    if not server_ready.wait(timeout=15.0):
        logger.error("Server loop not initialized; aborting startup.")
        raise SystemExit(1)

    port = app_state.server_loop_holder.get("port", DEFAULT_PORT)

    # Wait a bit more for services to fully initialize
    time.sleep(0.5)

    # Start screenshot service
    start_screenshot_service()

    # Start transcription service
    start_transcription_service()

    logger.info("Server running at: http://localhost:%d", port)
    logger.info("WebSocket endpoint: ws://localhost:%d/ws", port)
    logger.info("Hotkeys: Alt + . - Take region screenshot")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        from .core.lifecycle import cleanup_resources

        cleanup_resources()


if __name__ == "__main__":
    main()
