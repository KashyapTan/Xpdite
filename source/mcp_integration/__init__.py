"""MCP integration exports.

Lazy exports avoid importing the tool-call handlers during startup when the
caller only needs the manager or vice versa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["McpToolManager", "mcp_manager", "init_mcp_servers", "handle_mcp_tool_calls"]

if TYPE_CHECKING:
    from .handlers import handle_mcp_tool_calls
    from .manager import McpToolManager, init_mcp_servers, mcp_manager


def __getattr__(name: str) -> Any:
    if name in {"McpToolManager", "mcp_manager", "init_mcp_servers"}:
        from .manager import McpToolManager, init_mcp_servers, mcp_manager

        mapping = {
            "McpToolManager": McpToolManager,
            "mcp_manager": mcp_manager,
            "init_mcp_servers": init_mcp_servers,
        }
        return mapping[name]
    if name == "handle_mcp_tool_calls":
        from .handlers import handle_mcp_tool_calls

        return handle_mcp_tool_calls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
