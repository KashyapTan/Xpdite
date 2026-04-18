"""
Ollama ↔ MCP Bridge
====================
This module is the "glue" between Ollama's tool-calling feature and MCP servers.

HOW IT WORKS (the full picture):
────────────────────────────────

  ┌──────────────┐         ┌───────────────────┐         ┌──────────────────┐
  │   You/App    │ ──1──>  │   Ollama Bridge   │ ──2──>  │   Ollama LLM     │
  │  (ask a Q)   │         │  (this file)      │         │  (qwen3, etc.)   │
  └──────────────┘         └───────────────────┘         └──────────────────┘
                                    │  ▲                          │
                                    │  │                          │
                                3   │  │  5                    returns
                           (call    │  │  (return               tool_call
                            tool)   ▼  │  result)               request
                           ┌───────────────────┐                  │
                           │   MCP Server(s)   │ <────────4───────┘
                           │  (demo, gmail..)  │     (bridge routes
                           └───────────────────┘      the call)

  1. You send a question to the bridge (e.g., "What is 5 + 3?")
  2. Bridge sends the question to Ollama WITH a list of available tools
     (gathered from all connected MCP servers)
  3. Ollama decides to call a tool (e.g., add(a=5, b=3))
  4. Bridge routes that tool call to the correct MCP server
  5. MCP server returns the result (8)
  6. Bridge sends the result back to Ollama so it can form a final answer

KEY CONCEPTS:
─────────────
- stdio transport: MCP servers run as child processes. The bridge talks to them
  via stdin/stdout using JSON-RPC messages. This is the simplest transport.
  
- Tool discovery: When the bridge connects to an MCP server, it calls
  `session.list_tools()` to find out what tools are available and their schemas.
  
- Schema conversion: MCP tools have JSON Schema descriptions. Ollama expects
  tools in OpenAI-compatible format. This bridge converts between them.

- Tool routing: When Ollama says "call tool X with args Y", the bridge finds
  which MCP server owns tool X and calls it via the MCP protocol.
"""

import json
from typing import Any
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import chat


class McpOllamaBridge:
    """
    Connects to one or more MCP servers and makes their tools available
    to Ollama for tool-calling.
    
    Usage:
        bridge = McpOllamaBridge(model="qwen3-vl:8b-instruct")
        await bridge.connect_server("demo", "python", ["path/to/server.py"])
        response = await bridge.chat("What is 5 + 3?")
        await bridge.cleanup()
    """

    def __init__(self, model: str = "qwen3-vl:8b-instruct"):
        """
        Args:
            model: The Ollama model to use. Must support tool calling.
                   Models that support tools: qwen3, llama3.1, mistral, etc.
                   NOTE: Vision models like qwen3-vl may NOT support tool calling.
        """
        self.model = model
        
        # Maps: tool_name -> {"session": ClientSession, "server_name": str}
        # This is how we know which server to route a tool call to.
        self._tool_registry: dict[str, dict[str, Any]] = {}
        
        # Store the currently connected server sessions & their cleanup contexts
        self._connections: dict[str, dict[str, Any]] = {}
        
        # Ollama-formatted tool definitions (built from MCP tool schemas)
        self._ollama_tools: list[dict] = []
        
        # Conversation history for multi-turn chat
        self._chat_history: list[dict[str, Any]] = []
    
    async def connect_server(self, server_name: str, command: str, args: list[str], env: dict[str, str] | None = None):
        """
        Connect to an MCP server by launching it as a subprocess.
        
        This is the "stdio" transport — the most common way to connect to
        MCP servers. The bridge launches the server as a child process and
        communicates with it via stdin/stdout.
        
        Args:
            server_name: A friendly name for this server (e.g., "demo")
            command: The command to run (e.g., "python")
            args: Arguments to the command (e.g., ["servers/demo/server.py"])
            env: Optional environment variables for the server process
        """
        # Create the server parameters — this tells the MCP client HOW to
        # launch the server process.
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )
        
        # stdio_client() is an async context manager that:
        # 1. Spawns the server as a subprocess
        # 2. Connects stdin/stdout pipes
        # 3. Returns read/write streams for JSON-RPC communication
        #
        # We need to manage the context manually since we want the connection
        # to stay alive across multiple chat() calls.
        
        stdio_ctx = stdio_client(server_params)
        session_ctx = None
        session = None

        try:
            # Enter the stdio_client context
            read, write = await stdio_ctx.__aenter__()

            # Enter the ClientSession context
            session_ctx = ClientSession(read, write)
            session = await session_ctx.__aenter__()

            # Initialize the MCP connection (required handshake)
            await session.initialize()

            # Discover all tools this server provides before we mark the
            # connection as live. That avoids leaking half-open connections if
            # initialization or discovery fails partway through.
            tools_result = await session.list_tools()
        except Exception:
            if session_ctx is not None:
                try:
                    await session_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            try:
                await stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            raise

        # Store the contexts so we can clean up later
        self._connections[server_name] = {
            "session": session,
            "stdio_ctx": stdio_ctx,
            "session_ctx": session_ctx,
        }
        
        for tool in tools_result.tools:
            # Register the tool so we can route calls to the right server
            self._tool_registry[tool.name] = {
                "session": session,
                "server_name": server_name,
            }
            
            # Convert MCP tool schema → Ollama tool format
            # MCP gives us:  { name, description, inputSchema: { type: "object", properties: {...}, required: [...] } }
            # Ollama wants:  { type: "function", function: { name, description, parameters: { type, properties, required } } }
            ollama_tool = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                },
            }
            self._ollama_tools.append(ollama_tool)
            print(f"  Registered tool: {tool.name} (from {server_name})")
        
        print(f"Connected to MCP server '{server_name}' — {len(tools_result.tools)} tool(s) available")
    
    async def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Route a tool call to the correct MCP server and return the result.
        
        When Ollama decides to call a tool, this method:
        1. Looks up which MCP server owns the tool
        2. Calls the tool via the MCP protocol
        3. Extracts and returns the text result
        """
        if tool_name not in self._tool_registry:
            return f"Error: Unknown tool '{tool_name}'"
        
        entry = self._tool_registry[tool_name]
        session: ClientSession = entry["session"]
        
        # Call the tool via MCP protocol
        result = await session.call_tool(tool_name, arguments=arguments)
        
        # Extract the text from the result
        # MCP returns a list of content blocks (text, image, etc.)
        output_parts = []
        for content_block in result.content:
            if hasattr(content_block, "text"):
                output_parts.append(content_block.text)
            else:
                output_parts.append(str(content_block))
        
        return "\n".join(output_parts) if output_parts else "Tool returned no output."
    
    async def chat(self, user_message: str) -> str:
        """
        Send a message to Ollama with MCP tools available.
        
        This implements the full tool-calling loop:
        1. Send user message + tool definitions to Ollama
        2. If Ollama wants to call a tool → call it via MCP → send result back
        3. Repeat until Ollama gives a final text response
        
        Args:
            user_message: The user's question or instruction
            
        Returns:
            The final text response from Ollama
        """
        # Add user message to history
        self._chat_history.append({"role": "user", "content": user_message})
        
        # Send to Ollama WITH tool definitions
        response = chat(
            model=self.model,
            messages=self._chat_history,
            tools=self._ollama_tools if self._ollama_tools else None,
        )
        
        # Check if Ollama wants to call tool(s)
        # The tool-calling loop: Ollama might call multiple tools in sequence
        while response.message.tool_calls:
            # Record the assistant tool-call request once per Ollama response,
            # even if that response contains multiple tool calls.
            self._chat_history.append(response.message.model_dump())

            # Process each tool call
            for tool_call in response.message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = tool_call.function.arguments
                
                print(f"Ollama calling tool: {fn_name}({fn_args})")
                
                # Route to the correct MCP server
                result = await self._call_mcp_tool(fn_name, fn_args)
                print(f"Tool result: {result[0:10]}...")  # Print first 100 chars of result
                
                # Add the tool result to history so Ollama can see it
                self._chat_history.append({
                    "role": "tool",
                    "content": str(result),
                })
            
            # Send the tool results back to Ollama for a final response
            response = chat(
                model=self.model,
                messages=self._chat_history,
                tools=self._ollama_tools if self._ollama_tools else None,
            )
        
        # We have a final text response (no more tool calls)
        final_text = response.message.content or ""
        self._chat_history.append({"role": "assistant", "content": final_text})
        
        return final_text
    
    def clear_history(self):
        """Clear conversation history for a fresh start."""
        self._chat_history = []
    
    async def cleanup(self):
        """Disconnect from all MCP servers and clean up resources."""
        for name, conn in list(self._connections.items()):
            disconnect_error = None

            try:
                await conn["session_ctx"].__aexit__(None, None, None)
            except Exception as exc:
                disconnect_error = exc

            try:
                await conn["stdio_ctx"].__aexit__(None, None, None)
            except Exception as exc:
                if disconnect_error is None:
                    disconnect_error = exc

            if disconnect_error is None:
                print(f"Disconnected from MCP server '{name}'")
            else:
                print(f"Error disconnecting from '{name}': {disconnect_error}")
        self._connections.clear()
        self._tool_registry.clear()
        self._ollama_tools.clear()


# ── Convenience function to load servers from config ───────────────────

def load_server_config() -> dict:
    """Load server configuration from mcp_servers/config/servers.json"""
    config_path = Path(__file__).parent.parent / "config" / "servers.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)
