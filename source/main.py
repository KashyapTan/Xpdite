"""
Xpdite Application Entry Point.

This is the main entry point for the Python backend server.
It initializes all services and starts the FastAPI server.

Architecture:
    source/
    ├── main.py           # This file - entry point
    ├── app.py            # FastAPI app factory
    ├── config.py         # Configuration constants
    ├── database.py       # SQLite operations
    ├── ss.py             # Screenshot service
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
    │   ├── manager.py      # Tool manager
    │   ├── handlers.py     # Tool call handlers (Ollama)
    │   ├── retriever.py    # Semantic tool retrieval
    │   └── terminal_executor.py # Terminal tool execution
    ├── llm/              # LLM integration
    │   ├── router.py       # Provider dispatch
    │   ├── ollama_provider.py  # Ollama streaming
    │   ├── cloud_provider.py   # Anthropic/OpenAI/Gemini
    │   ├── key_manager.py  # API key encryption
    │   └── prompt.py       # System prompt builder
    └── services/         # Business logic
        ├── screenshots.py  # Screenshot handling
        ├── conversations.py # Conversation handling
        ├── terminal.py     # Terminal/PTY service
        ├── transcription.py # Audio transcription
        ├── google_auth.py  # Google OAuth
        └── approval_history.py # Command approval cache
"""

import sys
import os
import socket
import threading
import time
import asyncio
import logging
import uvicorn

# Configure logging before anything else
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import configuration (relative to source package)
from .config import SCREENSHOT_FOLDER, DEFAULT_PORT, MAX_PORT_ATTEMPTS

# Import core components
from .core.state import app_state
from .core.lifecycle import register_signal_handlers

# Import app factory
from .app import app

# Import MCP initialization
from .mcp_integration.manager import init_mcp_servers

# Import screenshot service hooks
from .services.screenshots import process_screenshot, process_screenshot_start


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


def start_server():
    """Start FastAPI server in the current thread & store its loop."""
    try:
        port = find_available_port()
        logger.info("Starting server on port %d", port)
    except RuntimeError as e:
        logger.error("Error finding available port: %s", e)
        return

    loop = asyncio.new_event_loop()
    app_state.server_loop_holder["loop"] = loop
    app_state.server_loop_holder["port"] = port
    asyncio.set_event_loop(loop)

    # Initialize MCP servers
    try:
        loop.run_until_complete(init_mcp_servers())
    except Exception as e:
        logger.warning("MCP server initialization failed (non-fatal): %s", e)

    # Conditionally start Google MCP servers if user has connected their account
    try:
        from .config import GOOGLE_TOKEN_FILE
        import os

        if os.path.exists(GOOGLE_TOKEN_FILE):
            from .mcp_integration.manager import mcp_manager

            loop.run_until_complete(mcp_manager.connect_google_servers())
            logger.info("Gmail & Calendar MCP servers started (token found)")
        else:
            logger.info("No Google token found — skipping Gmail & Calendar servers")
    except Exception as e:
        logger.warning("Failed to start Google servers (non-fatal): %s", e)

    # Start uvicorn server
    config = uvicorn.Config(
        app, host="0.0.0.0", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


def start_screenshot_service():
    """Start the screenshot service."""
    try:
        from .ss import ScreenshotService

        app_state.screenshot_service = ScreenshotService(
            process_screenshot, process_screenshot_start
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
        from .services.transcription import TranscriptionService

        # Initialize the service (model loads lazily on first use)
        app_state.transcription_service = TranscriptionService()
        logger.info("Transcription service initialized")
    except Exception as e:
        logger.error("Error starting transcription service: %s", e)


def main():
    """Main entry point."""
    # Register signal handlers for graceful shutdown
    register_signal_handlers()

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
    if not server_ready.wait(timeout=5.0):
        logger.warning("Server loop not initialized; continuing anyway.")

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
