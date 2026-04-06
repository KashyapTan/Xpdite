"""
External MCP Connectors Service.

Manages external MCP server connections (Figma, Slack, GitHub, etc.) that are not
bundled with the app. These connectors:

1. May require authentication (OAuth via browser, API keys, etc.)
2. Use stdio transport via tools like `npx` (mcp-remote) or `uvx`
3. Persist their enabled/disabled state across app restarts
4. Auto-reconnect on app startup if previously enabled

## How to Add a New External Connector

1. Add a new entry to EXTERNAL_CONNECTORS dict below with:
   - name: Unique identifier (used in settings storage)
   - display_name: Human-readable name shown in UI
   - description: Brief explanation of what it provides
   - command: The executable to run (e.g., "npx", "uvx")
   - args: Arguments to pass to the command
   - services: List of service badges to show in UI (e.g., ["Design", "Figma"])
   - icon_type: Icon identifier for the frontend
   - auth_type: "browser" (OAuth via browser popup), or None

2. If it needs special handling, add interception logic in:
   - source/mcp_integration/core/handlers.py (for tool execution)
   - source/llm/providers/cloud_provider.py (for streaming tool execution)

3. Update frontend icon in SettingsConnections.tsx if needed
"""

import logging
from typing import Any, TypedDict, Optional, Literal

from ...infrastructure.database import db

logger = logging.getLogger(__name__)


class ExternalConnector(TypedDict):
    """Definition of an external MCP connector."""

    name: str  # Unique identifier
    display_name: str  # Human-readable name
    description: str  # Brief explanation
    command: str  # Executable (npx, uvx, etc.)
    args: list[str]  # Command arguments
    services: list[str]  # Service badges for UI
    icon_type: str  # Icon identifier for frontend
    auth_type: Optional[Literal["browser"]]  # Auth method ("browser" = OAuth popup)


# ============================================
# External Connector Registry
# ============================================
# Add new connectors here. They will automatically appear in the
# Settings > Connections page and can be enabled/disabled by users.

EXTERNAL_CONNECTORS: dict[str, ExternalConnector] = {
    # "Everything" demo server - no auth required, good for testing
    # Includes sample tools, resources, and prompts for testing MCP features
    # https://github.com/modelcontextprotocol/servers/tree/main/src/everything
    "everything": {
        "name": "everything",
        "display_name": "Everything (Demo)",
        "description": "Demo server with sample tools for testing",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "services": ["Demo"],
        "icon_type": "everything",
        "auth_type": None,  # No authentication required
    },
    # NOTE: Figma and Slack MCP servers require pre-registered OAuth apps.
    # They use dynamic client registration which third-party apps can't use.
    # Uncomment these if/when we have registered OAuth credentials.
    #
    # "figma": {
    #     "name": "figma",
    #     "display_name": "Figma",
    #     "description": "Design files and components",
    #     "command": "npx",
    #     "args": ["-y", "mcp-remote@latest", "https://mcp.figma.com/mcp", "--transport", "http-only"],
    #     "services": ["Design"],
    #     "icon_type": "figma",
    #     "auth_type": "browser",
    # },
    # "slack": {
    #     "name": "slack",
    #     "display_name": "Slack",
    #     "description": "Messages, channels, and search",
    #     "command": "npx",
    #     "args": ["-y", "mcp-remote@latest", "https://mcp.slack.com/mcp", "--transport", "http-only"],
    #     "services": ["Messaging"],
    #     "icon_type": "slack",
    #     "auth_type": "browser",
    # },
}


def _setting_key(connector_name: str) -> str:
    """Get the settings key for a connector's enabled state."""
    return f"external_connector:{connector_name}:enabled"


def _error_key(connector_name: str) -> str:
    """Get the settings key for a connector's last error."""
    return f"external_connector:{connector_name}:last_error"


class ExternalConnectorService:
    """
    Manages external MCP connector state and lifecycle.

    This service handles:
    - Listing available connectors with their status
    - Enabling/disabling connectors (persisted to DB)
    - Tracking connection errors
    - Providing connector info for frontend display

    Actual MCP server connection is handled by McpToolManager.
    """

    def get_all_connectors(self) -> list[dict[str, Any]]:
        """
        Get all available external connectors with their current status.

        Returns list of connector info dicts suitable for API response.
        """
        from ...mcp_integration.core.manager import mcp_manager

        result = []
        for name, connector in EXTERNAL_CONNECTORS.items():
            enabled = self.is_enabled(name)
            connected = mcp_manager.is_server_connected(name)
            last_error = self.get_last_error(name)

            result.append(
                {
                    "name": connector["name"],
                    "display_name": connector["display_name"],
                    "description": connector["description"],
                    "services": connector["services"],
                    "icon_type": connector["icon_type"],
                    "auth_type": connector["auth_type"],
                    "enabled": enabled,
                    "connected": connected,
                    "last_error": last_error,
                }
            )

        return sorted(result, key=lambda x: x["display_name"])

    def get_connector(self, name: str) -> Optional[ExternalConnector]:
        """Get a connector definition by name."""
        return EXTERNAL_CONNECTORS.get(name)

    def is_enabled(self, name: str) -> bool:
        """Check if a connector is enabled in settings."""
        value = db.get_setting(_setting_key(name))
        return value == "true"

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Set a connector's enabled state."""
        if name not in EXTERNAL_CONNECTORS:
            raise ValueError(f"Unknown connector: {name}")
        db.set_setting(_setting_key(name), "true" if enabled else "false")
        logger.info("Connector '%s' enabled=%s", name, enabled)

    def get_last_error(self, name: str) -> Optional[str]:
        """Get the last error message for a connector, if any."""
        return db.get_setting(_error_key(name))

    def set_last_error(self, name: str, error: Optional[str]) -> None:
        """Store or clear the last error for a connector."""
        if error:
            db.set_setting(_error_key(name), error)
        else:
            db.delete_setting(_error_key(name))

    def get_enabled_connectors(self) -> list[str]:
        """Get names of all enabled connectors."""
        return [name for name in EXTERNAL_CONNECTORS if self.is_enabled(name)]


# Singleton instance
external_connectors = ExternalConnectorService()


async def connect_external_connector(name: str) -> dict[str, Any]:
    """
    Connect an external MCP server.

    This:
    1. Validates the connector exists
    2. Marks it as enabled
    3. Connects via McpToolManager
    4. Returns success/failure status

    Args:
        name: Connector identifier
    """
    from ...mcp_integration.core.manager import mcp_manager

    connector = external_connectors.get_connector(name)
    if not connector:
        return {"success": False, "error": f"Unknown connector: {name}"}

    # Clear any previous error
    external_connectors.set_last_error(name, None)

    try:
        # Connect via MCP manager
        await mcp_manager.connect_server(
            server_name=name,
            command=connector["command"],
            args=connector["args"],
        )

        # Check if actually connected (connect_server doesn't raise on all failures)
        if not mcp_manager.is_server_connected(name):
            error_msg = "Connection failed - server did not start"
            external_connectors.set_last_error(name, error_msg)
            return {"success": False, "error": error_msg}

        # Mark as enabled for auto-reconnect on restart
        external_connectors.set_enabled(name, True)

        logger.info("External connector '%s' connected successfully", name)
        return {"success": True}

    except Exception as e:
        error_msg = str(e)[:500]
        logger.error("Failed to connect external connector '%s': %s", name, error_msg)
        external_connectors.set_last_error(name, error_msg)
        return {"success": False, "error": error_msg}


async def disconnect_external_connector(name: str) -> dict[str, Any]:
    """
    Disconnect an external MCP server.

    This:
    1. Disconnects via McpToolManager
    2. Marks it as disabled
    3. Clears any stored errors
    """
    from ...mcp_integration.core.manager import mcp_manager

    connector = external_connectors.get_connector(name)
    if not connector:
        return {"success": False, "error": f"Unknown connector: {name}"}

    try:
        # Disconnect if connected
        if mcp_manager.is_server_connected(name):
            await mcp_manager.disconnect_server(name)

        # Mark as disabled
        external_connectors.set_enabled(name, False)
        external_connectors.set_last_error(name, None)

        logger.info("External connector '%s' disconnected", name)
        return {"success": True}

    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(
            "Failed to disconnect external connector '%s': %s", name, error_msg
        )
        return {"success": False, "error": error_msg}


async def init_external_connectors() -> None:
    """
    Initialize all enabled external connectors on app startup.

    Called from init_mcp_servers() to auto-reconnect previously enabled
    connectors.
    """
    import asyncio

    enabled = external_connectors.get_enabled_connectors()
    if not enabled:
        logger.debug("No external connectors enabled")
        return

    logger.info("Connecting %d enabled external connector(s)...", len(enabled))

    async def _connect_one(name: str) -> None:
        try:
            result = await connect_external_connector(name)
            if not result.get("success"):
                logger.warning(
                    "External connector '%s' failed to auto-connect: %s",
                    name,
                    result.get("error"),
                )
        except Exception as e:
            logger.warning("External connector '%s' auto-connect error: %s", name, e)

    # Connect in parallel with individual timeouts
    tasks = [asyncio.wait_for(_connect_one(name), timeout=60.0) for name in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for name, result in zip(enabled, results):
        if isinstance(result, asyncio.TimeoutError):
            external_connectors.set_last_error(name, "Connection timed out")
            logger.warning(
                "External connector '%s' timed out during auto-connect", name
            )
        elif isinstance(result, Exception):
            external_connectors.set_last_error(name, str(result)[:500])
