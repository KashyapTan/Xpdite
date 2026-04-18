"""
Demo MCP Server — "Add Two Numbers"
====================================
This is the simplest possible MCP server. It exposes a single tool called
`add` that takes two numbers and returns their sum.

HOW IT WORKS:
1. We import FastMCP from the official MCP Python SDK.
2. We create a server instance with a human-readable name.
3. We decorate a plain Python function with @mcp.tool() to register it
   as a tool that LLMs can call.
4. When this script is run, it starts the server using the "stdio" transport,
   meaning it communicates via standard input/output (stdin/stdout).
   This is how MCP clients (like our Ollama bridge) talk to it.

RUN DIRECTLY (for testing with MCP Inspector):
    python -m mcp_servers.servers.demo.server

Or from the mcp_servers directory:
    python servers/demo/server.py
"""

from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.demo.demo_descriptions import (
    ADD_DESCRIPTION,
    DIVIDE_DESCRIPTION,
)

# ── Create the MCP server ──────────────────────────────────────────────
# The name is what clients see when they connect.
mcp = FastMCP("Demo Calculator")


# ── Register tools ─────────────────────────────────────────────────────
@mcp.tool(description=DIVIDE_DESCRIPTION)
def divide(a: float, b: float) -> str:
    """
    Divide two numbers and return the result rounded to up to 50 decimal places.
    
    Args:
        a: The first number
        b: The second number
    
    Returns:
        The result of dividing a by b
    """
    if b == 0:
        return "Error: Cannot divide by zero."
    return f"{a / b:.50f}"

@mcp.tool(description=ADD_DESCRIPTION)
def add(a: float, b: float) -> str:
    """
    Add two numbers and return the result.
    
    Args:
        a: The first number
        b: The second number
    
    Returns:
        The sum of a and b
    """
    return f"{a + b}"


# ── Entry point ────────────────────────────────────────────────────────
# mcp.run() starts the server. By default it uses "stdio" transport,
# which means it reads JSON-RPC messages from stdin and writes responses
# to stdout. This is the standard way MCP clients launch and talk to
# MCP servers.
if __name__ == "__main__":
    mcp.run()
