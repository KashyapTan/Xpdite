"""MCP integration exports.

Lazy exports avoid importing the tool-call handlers during startup when the
caller only needs the manager or vice versa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "McpToolManager",
    "mcp_manager",
    "init_mcp_servers",
    "handle_mcp_tool_calls",
    "terminal_executor",
]

if TYPE_CHECKING:
    from .core.handlers import handle_mcp_tool_calls
    from .core.manager import McpToolManager, init_mcp_servers, mcp_manager
    from .executors import terminal_executor


def __getattr__(name: str) -> Any:
    if name in {"McpToolManager", "mcp_manager", "init_mcp_servers"}:
        from .core.manager import McpToolManager, init_mcp_servers, mcp_manager

        mapping = {
            "McpToolManager": McpToolManager,
            "mcp_manager": mcp_manager,
            "init_mcp_servers": init_mcp_servers,
        }
        return mapping[name]
    if name == "handle_mcp_tool_calls":
        from .core.handlers import handle_mcp_tool_calls

        return handle_mcp_tool_calls
    if name == "terminal_executor":
        from .executors import terminal_executor

        return terminal_executor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
