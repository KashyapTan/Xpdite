"""
MCP Tool Manager.

Manages MCP server connections and tool routing for the main app.
"""

import asyncio
import os
import sys
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

from ..config import PROJECT_ROOT
from .retriever import retriever


class McpToolManager:
    """
    Manages MCP server connections and tool routing.

    This is the in-app version of the bridge. It:
    1. Launches MCP servers as child processes (stdio transport)
    2. Discovers their tools and converts schemas to Ollama format
    3. Routes tool calls from Ollama to the correct MCP server
    4. Returns results back so Ollama can form a final answer

    HOW TO ADD A NEW TOOL SERVER:
    ─────────────────────────────
    1. Create your server in mcp_servers/servers/<name>/server.py
       (use @mcp.tool() decorators — see demo/server.py for example)

    2. In this file's init_mcp_servers() function, add:
       await mcp_manager.connect_server(
           "your_server_name",
           sys.executable,
           [str(PROJECT_ROOT / "mcp_servers" / "servers" / "your_name" / "server.py")]
       )

    3. That's it! The tools will automatically be:
       - Discovered and registered
       - Sent to Ollama with every chat request
       - Routed and executed when Ollama calls them
       - Displayed in the UI response
    """

    def __init__(self):
        self._tool_registry: Dict[str, Any] = {}  # tool_name -> {session, server_name}
        self._connections: Dict[
            str, Any
        ] = {}  # server_name -> {session, stdio_ctx, session_ctx}
        self._ollama_tools: List[Dict] = []  # Ollama-formatted tool definitions
        self._raw_tools: List[
            Dict
        ] = []  # Raw tool schemas (name, description, inputSchema)
        self._initialized = False

    async def connect_server(
        self, server_name: str, command: str, args: list, env: dict = None
    ):
        """Connect to an MCP server by launching it as a subprocess.

        Spawns a background asyncio Task that holds the stdio + session
        context managers open.  This ensures ``__aenter__`` and ``__aexit__``
        always run in the *same* task, avoiding anyio's
        "cancel scope in a different task" RuntimeError when disconnecting
        from an HTTP handler.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            logger.warning("mcp import failed: %s", e)
            logger.warning("Run: pip install 'mcp[cli]'")
            logger.warning(
                "Skipping server '%s'. Tools will not be available.", server_name
            )
            return

        try:
            # Ensure PROJECT_ROOT is in PYTHONPATH so child processes can
            # resolve absolute imports like "from mcp_servers.servers.xxx import ..."
            if env is None:
                env = {**os.environ}
            project_root_str = str(PROJECT_ROOT)
            existing_pypath = env.get("PYTHONPATH", "")
            if existing_pypath:
                if project_root_str not in existing_pypath.split(os.pathsep):
                    env["PYTHONPATH"] = project_root_str + os.pathsep + existing_pypath
            else:
                env["PYTHONPATH"] = project_root_str

            server_params = StdioServerParameters(command=command, args=args, env=env)

            # -- Background‑task lifecycle pattern --
            # A dedicated task holds the stdio + session context managers
            # open and waits on a shutdown event.  disconnect_server() sets
            # the event so the *same* task exits the scopes cleanly.
            shutdown_event = asyncio.Event()
            connected_event = asyncio.Event()
            connection_data: Dict[str, Any] = {}

            async def _server_lifecycle():
                """Run inside its own asyncio Task."""
                try:
                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            connection_data["session"] = session
                            connected_event.set()
                            # Keep context managers alive until told to shut down
                            await shutdown_event.wait()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    if not connected_event.is_set():
                        connection_data["error"] = exc
                        connected_event.set()

            task = asyncio.create_task(
                _server_lifecycle(), name=f"mcp-server-{server_name}"
            )

            # Wait for the session to become available (or for an error)
            await connected_event.wait()

            if "error" in connection_data:
                raise connection_data["error"]

            session = connection_data["session"]

            self._connections[server_name] = {
                "session": session,
                "shutdown_event": shutdown_event,
                "task": task,
            }

            # Discover tools
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                self._tool_registry[tool.name] = {
                    "session": session,
                    "server_name": server_name,
                }
                ollama_tool = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema
                        if tool.inputSchema
                        else {"type": "object", "properties": {}},
                    },
                }
                self._ollama_tools.append(ollama_tool)

                # Store raw schema for cross-provider conversion
                self._raw_tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema
                        if tool.inputSchema
                        else {"type": "object", "properties": {}},
                    }
                )

                print_name = tool.name  # noqa: avoid f-string in loop
                logger.debug("Registered tool: %s (from %s)", tool.name, server_name)

            logger.info(
                "Connected to '%s' — %d tool(s)", server_name, len(tools_result.tools)
            )
            # Re-embed tools for the retriever (blocking call, run in thread)
            from ..core.thread_pool import run_in_thread
            try:
                await run_in_thread(retriever.embed_tools, self._ollama_tools)
            except Exception as e:
                logger.warning("Tool embedding failed (non-fatal): %s", e)
        except Exception as e:
            logger.error("Error connecting to '%s': %s", server_name, e)
            logger.warning("The server will work without '%s' tools.", server_name)

    def register_inline_tools(
        self, server_name: str, tools: List[Dict[str, Any]]
    ) -> None:
        """Register tool schemas without spawning a subprocess.

        Use this for tools that are intercepted at the handler layer and
        never routed to an MCP server (e.g. terminal tools).  Each item
        in *tools* must have: name, description, parameters (JSON Schema).

        The tool registry entry has ``session=None`` so ``call_tool()``
        will return an error if something accidentally tries to call the
        MCP session — the handler layer should intercept first.
        """
        for tool in tools:
            name = tool["name"]
            description = tool.get("description", "")
            parameters = tool.get("parameters", {"type": "object", "properties": {}})

            self._tool_registry[name] = {
                "session": None,  # no subprocess — intercepted at handler layer
                "server_name": server_name,
            }

            ollama_tool = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
            self._ollama_tools.append(ollama_tool)

            self._raw_tools.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": parameters,
                }
            )

            logger.debug("Registered inline tool: %s (from %s)", name, server_name)

        logger.info("Registered %d inline tool(s) for '%s'", len(tools), server_name)
        # Re-embed tools for the retriever
        retriever.embed_tools(self._ollama_tools)

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Route a tool call to the correct MCP server."""
        if tool_name not in self._tool_registry:
            return f"Error: Unknown tool '{tool_name}'"

        entry = self._tool_registry[tool_name]
        session = entry["session"]

        if session is None:
            return (
                f"Error: Tool '{tool_name}' is an inline tool "
                f"(server '{entry['server_name']}') and cannot be called via MCP "
                f"session. It must be handled by the inline tool executor."
            )

        import asyncio

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=180.0,  # 3 min safety ceiling
            )
        except asyncio.TimeoutError:
            server = entry.get("server_name", "unknown")
            return f"Error: Tool '{tool_name}' (server '{server}') timed out after 180s"

        output_parts = []
        for block in result.content:
            if hasattr(block, "text"):
                output_parts.append(block.text)
            else:
                output_parts.append(str(block))

        return "\n".join(output_parts) if output_parts else "Tool returned no output."

    def get_ollama_tools(self) -> List[Dict] | None:
        """Return tool definitions in Ollama format, or None if no tools."""
        return self._ollama_tools if self._ollama_tools else None

    def get_tool_server_name(self, tool_name: str) -> str:
        """Get the server name that owns a tool."""
        entry = self._tool_registry.get(tool_name)
        return entry["server_name"] if entry else "unknown"

    def has_tools(self) -> bool:
        """Check if any tools are registered."""
        return len(self._ollama_tools) > 0

    def get_server_tools(self) -> Dict[str, List[str]]:
        """Return a mapping of server names to their tool names."""
        servers: Dict[str, List[str]] = {}
        for tool_name, entry in self._tool_registry.items():
            server_name = entry["server_name"]
            if server_name not in servers:
                servers[server_name] = []
            servers[server_name].append(tool_name)
        return servers

    def get_anthropic_tools(self) -> List[Dict] | None:
        """Return tool definitions in Anthropic format, or None if no tools."""
        if not self._raw_tools:
            return None
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in self._raw_tools
        ]

    def get_openai_tools(self) -> List[Dict] | None:
        """Return tool definitions in OpenAI format, or None if no tools."""
        if not self._raw_tools:
            return None
        tools = []
        for t in self._raw_tools:
            # OpenAI wants parameters without the extra JSON Schema keys
            # that some MCP servers include
            params = dict(t["input_schema"])
            params.pop("additionalProperties", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": params,
                    },
                }
            )
        return tools

    def get_gemini_tools(self) -> List[Any] | None:
        """Return tool definitions in Gemini format, or None if no tools."""
        if not self._raw_tools:
            return None
        try:
            from google.genai import types

            declarations = []
            for t in self._raw_tools:
                # Clean up the schema for Gemini
                params = dict(t["input_schema"])
                params.pop("additionalProperties", None)

                declarations.append(
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=params,
                    )
                )
            return [types.Tool(function_declarations=declarations)]
        except ImportError:
            logger.warning(
                "google-genai not installed, cannot convert tools to Gemini format"
            )
            return None

    async def disconnect_server(self, server_name: str):
        """Disconnect a single MCP server by name."""
        conn = self._connections.get(server_name)
        if not conn:
            return

        # Signal the background task to exit, which cleanly runs
        # __aexit__ on the session + stdio context managers in the
        # same task that entered them.
        shutdown_event: asyncio.Event = conn["shutdown_event"]
        task: asyncio.Task = conn["task"]

        shutdown_event.set()

        try:
            await asyncio.wait_for(task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Server '%s' did not shut down in time, cancelling", server_name)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception as e:
            logger.error("Error shutting down '%s': %s", server_name, e)

        logger.info("Disconnected from '%s'", server_name)

        # Remove from connections
        self._connections.pop(server_name, None)

        # Remove tools belonging to this server
        tools_to_remove = [
            name
            for name, entry in self._tool_registry.items()
            if entry["server_name"] == server_name
        ]
        for tool_name in tools_to_remove:
            self._tool_registry.pop(tool_name, None)

        # Rebuild tool lists without this server's tools
        self._ollama_tools = [
            t
            for t in self._ollama_tools
            if t["function"]["name"] not in tools_to_remove
        ]
        self._raw_tools = [
            t for t in self._raw_tools if t["name"] not in tools_to_remove
        ]

        logger.info("Removed %d tool(s) from '%s'", len(tools_to_remove), server_name)
        # Re-embed tools for the retriever
        retriever.embed_tools(self._ollama_tools)

    def is_server_connected(self, server_name: str) -> bool:
        """Check if a specific MCP server is currently connected."""
        return server_name in self._connections

    async def connect_google_servers(self):
        """Connect Gmail and Calendar MCP servers with Google OAuth env vars."""
        from ..config import GOOGLE_TOKEN_FILE

        import os

        if not os.path.exists(GOOGLE_TOKEN_FILE):
            logger.info("Google token not found, skipping Google servers")
            return

        # Build env dict with token path for the child processes
        env = {
            **os.environ,
            "GOOGLE_TOKEN_FILE": str(GOOGLE_TOKEN_FILE),
        }

        # Connect Gmail server
        if not self.is_server_connected("gmail"):
            await self.connect_server(
                "gmail",
                sys.executable,
                [str(PROJECT_ROOT / "mcp_servers" / "servers" / "gmail" / "server.py")],
                env=env,
            )

        # Connect Calendar server
        if not self.is_server_connected("calendar"):
            await self.connect_server(
                "calendar",
                sys.executable,
                [
                    str(
                        PROJECT_ROOT
                        / "mcp_servers"
                        / "servers"
                        / "calendar"
                        / "server.py"
                    )
                ],
                env=env,
            )

        logger.info(
            "Google servers connected — %d total tool(s) available", len(self._ollama_tools)
        )

    async def disconnect_google_servers(self):
        """Disconnect Gmail and Calendar MCP servers."""
        if self.is_server_connected("gmail"):
            await self.disconnect_server("gmail")
        if self.is_server_connected("calendar"):
            await self.disconnect_server("calendar")
        logger.info("Google servers disconnected")

    async def cleanup(self):
        """Disconnect from all MCP servers."""
        for name in list(self._connections):
            try:
                await self.disconnect_server(name)
            except Exception as e:
                logger.error("Error disconnecting from '%s': %s", name, e)
        self._initialized = False


# Global MCP tool manager singleton
mcp_manager = McpToolManager()


async def init_mcp_servers():
    """
    Connect to all enabled MCP servers.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  HOW TO ADD YOUR OWN MCP TOOL SERVER:                           ║
    ║                                                                  ║
    ║  1. Create mcp_servers/servers/<name>/server.py                  ║
    ║  2. Add @mcp.tool() functions in it                             ║
    ║  3. Add a connect_server() call below                           ║
    ║  4. Restart the app — your tools are now available!              ║
    ╚══════════════════════════════════════════════════════════════════╝
    """
    if mcp_manager._initialized:
        logger.warning("Already initialized — skipping double init")
        return

    # ── Demo server (add two numbers) ──────────────────────────────
    # await mcp_manager.connect_server(
    #     "demo",
    #     sys.executable,
    #     [str(PROJECT_ROOT / "mcp_servers" / "servers" / "demo" / "server.py")],
    # )

    # ── Filesystem server ──────────────────────────────────────────
    await mcp_manager.connect_server(
        "filesystem",
        sys.executable,
        [str(PROJECT_ROOT / "mcp_servers" / "servers" / "filesystem" / "server.py")],
    )

    await mcp_manager.connect_server(
        "websearch",
        sys.executable,
        [str(PROJECT_ROOT / "mcp_servers" / "servers" / "websearch" / "server.py")],
    )

    # ── Terminal tools (inline — no subprocess) ─────────────────────
    # Terminal tools are intercepted at the handler layer and executed
    # directly by terminal_executor.py.  We register their schemas here
    # so they appear in the tool list sent to LLMs, but no MCP server
    # subprocess is spawned.
    from mcp_servers.servers.terminal.terminal_descriptions import (
        GET_ENVIRONMENT_DESCRIPTION,
        RUN_COMMAND_DESCRIPTION,
        FIND_FILES_DESCRIPTION,
        REQUEST_SESSION_MODE_DESCRIPTION,
        END_SESSION_MODE_DESCRIPTION,
        SEND_INPUT_DESCRIPTION,
        READ_OUTPUT_DESCRIPTION,
        KILL_PROCESS_DESCRIPTION,
    )

    mcp_manager.register_inline_tools(
        "terminal",
        [
            {
                "name": "get_environment",
                "description": GET_ENVIRONMENT_DESCRIPTION.strip(),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "run_command",
                "description": RUN_COMMAND_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (absolute path)",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Seconds before force-killing (max 120 foreground, 1800 background)",
                            "default": 120,
                        },
                        "pty": {
                            "type": "boolean",
                            "description": "Use PTY for interactive/TUI commands",
                            "default": False,
                        },
                        "background": {
                            "type": "boolean",
                            "description": "Run in background, return session_id",
                            "default": False,
                        },
                        "yield_ms": {
                            "type": "integer",
                            "description": "Ms to wait before returning for background processes",
                            "default": 10000,
                        },
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "find_files",
                "description": FIND_FILES_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (e.g. '*.py', '**/*.ts')",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Directory to search in",
                        },
                    },
                    "required": ["pattern"],
                },
            },
            {
                "name": "request_session_mode",
                "description": REQUEST_SESSION_MODE_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Why you need autonomous operation",
                        },
                    },
                    "required": ["reason"],
                },
            },
            {
                "name": "end_session_mode",
                "description": END_SESSION_MODE_DESCRIPTION.strip(),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "send_input",
                "description": SEND_INPUT_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID from run_command",
                        },
                        "input_text": {
                            "type": "string",
                            "description": "Text to send to the session",
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "Auto-press Enter after input",
                            "default": True,
                        },
                        "wait_ms": {
                            "type": "integer",
                            "description": "Ms to wait after sending before returning output",
                            "default": 3000,
                        },
                    },
                    "required": ["session_id", "input_text"],
                },
            },
            {
                "name": "read_output",
                "description": READ_OUTPUT_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID from run_command",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of recent lines to return",
                            "default": 50,
                        },
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "kill_process",
                "description": KILL_PROCESS_DESCRIPTION.strip(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID from run_command",
                        },
                    },
                    "required": ["session_id"],
                },
            },
        ],
    )

    # ── Add more servers here as you implement them ────────────────
    # Example:
    # await mcp_manager.connect_server(
    #     "my_server",
    #     sys.executable,
    #     [str(PROJECT_ROOT / "mcp_servers" / "servers" / "my_server" / "server.py")],
    # )

    mcp_manager._initialized = True
    logger.info("Ready — %d total tool(s) available", len(mcp_manager._ollama_tools))
