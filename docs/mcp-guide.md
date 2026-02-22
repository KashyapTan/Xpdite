# MCP Integration Guide

This guide covers the Model Context Protocol (MCP) integration in Xpdite, how to use existing tools, and how to build new ones.

## What is MCP?

The Model Context Protocol is a standardized way to give LLMs access to external tools. Think of it as a "USB port for AI" -- any tool that implements the MCP interface can be plugged into any MCP-compatible LLM application.

**Key concepts:**
- **Transport**: Xpdite uses `stdio` (standard input/output) to communicate with MCP servers
- **Protocol**: JSON-RPC 2.0 over the transport layer
- **Tool Discovery**: Servers declare their available tools with JSON Schema definitions
- **Isolation**: Each MCP server runs as an independent child process

## How Tool Calls Work

### Ollama Models

1. User sends query
2. **Phase 1** (detection): Non-streamed call with `think=False` to detect tool requests
   - Images are included so the model can analyze visual content (e.g., extract a URL from a screenshot)
3. If tool calls detected:
   a. Tools executed via `McpToolManager` (or `terminal_executor` for terminal tools)
   b. `tool_call` and `tool_result` broadcast to the frontend in real-time
   c. **Phase 2** (streaming loop): Follow-up response is streamed — the model's commentary ("Let me search for that…") appears live between tool rounds
   d. Loop repeats (up to 30 rounds) until a round contains no tool calls
4. Returns `{already_streamed: True}` to signal that content has already been broadcast

### Cloud Models (Anthropic / OpenAI / Gemini)

1. User sends query
2. `router.py` calls `retrieve_relevant_tools()` to select semantically relevant tool names
3. `stream_cloud_chat()` is called with `allowed_tool_names` — tools handled **inline during streaming**
4. The provider streams text in real-time; when tool calls appear mid-stream, they are executed inline:
   a. Tools executed via `McpToolManager` (or `terminal_executor` for terminal tools)
   b. `tool_call` + `tool_result` broadcast to the frontend
   c. Results fed back to the model and streaming continues
5. Loop repeats (up to 30 rounds) until a response round contains no tool calls
6. The user sees the entire process (text → tool → text → tool → text) as one continuous, transparent flow

## Inline Tool Registration (Ghost Process Prevention)

For tools that require deep integration with the core application (like terminal execution or system settings), Xpdite uses **Inline Tool Registration**.

Instead of spawning a standalone MCP server as a child process, these tools are registered directly in the `McpToolManager`. This avoids the overhead of "ghost processes" -- servers that exist purely to provide schemas but whose execution is intercepted by the backend.

- **Implementation**: Handled via `mcp_manager.register_inline_tools(server_name, tools)`.
- **Execution**: Intercepted in `mcp_integration/handlers.py` or `mcp_integration/cloud_tool_handlers.py` and routed to a dedicated internal executor (e.g., `terminal_executor.py`).
- **Benefits**: Lower memory usage, faster startup, and deterministic lifecycle management (e.g., stopping a request immediately kills associated terminal processes).

## Tool Retrieval and Selection

As the number of available tools grows, sending all tool definitions to the LLM can exceed context limits or confuse the model. Xpdite implements a **Semantic Tool Retriever** to dynamically select the most relevant tools for each query.

### How Retrieval Works

1. **Embedding**: On startup, Xpdite generates semantic embeddings for all available tool names and descriptions.
2. **Query Vectorization**: When a user sends a query, it is converted into a vector using an embedding model (e.g., `nomic-embed-text` via Ollama).
3. **Similarity Search**: The retriever calculates cosine similarity between the query vector and all tool vectors.
4. **Filtering**:
   - **Always-on Tools**: Tools manually enabled by the user in Settings are always included.
   - **Top-K Matches**: The top `K` semantically similar tools are added to the list.
5. **Inference**: Only the selected subset of tools is sent to the LLM.

### Configuration

Users can configure retrieval behavior in **Settings > Tools**:
- **Top K Retrieved Tools**: Control how many semantic matches to include (default: 5).
- **Connected MCP Servers**: Manually toggle tools to be "Always On".

## Active Servers

### Demo Calculator (`demo`)

A reference implementation for testing and learning.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add` | `a: float, b: float` | Adds two numbers |
| `divide` | `a: float, b: float` | Divides two numbers (50 decimal places) |

### Filesystem Tools (`filesystem`)

File system operations with path-traversal protection.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `list_directory` | `path: str` | Lists files sorted by modification time |
| `read_file` | `path: str` | Reads UTF-8 text file content |
| `write_file` | `path: str, content: str` | Writes or overwrites a file |
| `create_folder` | `path: str, folder_name: str` | Creates a new directory |
| `move_file` | `source_path: str, destination_folder: str` | Moves a file |
| `rename_file` | `source_path: str, new_name: str` | Renames a file in place |

**Security**: All paths are validated against a `BASE_PATH` to prevent directory traversal attacks.

### Web Search (`websearch`)

Internet search and web page reading capabilities.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_web_pages` | `query: str` | Searches the web via DuckDuckGo, returns URLs and snippets |
| `read_website` | `url: str` | Reads a web page and extracts clean markdown content |

**Features**:
- Uses DuckDuckGo for privacy-respecting search
- `read_website` uses crawl4ai with stealth mode (rotating User-Agents, noise reduction, randomized timing)
- Falls back to trafilatura for content extraction if crawl4ai fails

### Terminal Tools (`terminal`)

**Handled inline — no child process spawned.** Integrated with a multi-layer security system and approval flow.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_environment` | none | Returns OS, shell, cwd, and versions of common tools |
| `run_command` | `command, cwd, pty, background, timeout` | Runs a shell command. `pty=True` for TUIs; `background=True` for persistence. |
| `find_files` | `pattern, directory` | Glob-based file search |
| `request_session_mode` | `reason` | Request autonomous multi-step execution |
| `end_session_mode` | none | Manually end autonomous execution (note: sessions auto-expire after each turn) |
| `send_input` | `session_id, input_text` | Type into a persistent background PTY session |
| `read_output` | `session_id` | Read recent history from a background session |
| `kill_process` | `session_id` | Terminate a background session |

**Security**:
1. **Blocklist**: Prevents destructive commands (e.g., `rm -rf /`).
2. **PATH Protection**: Prevents `PATH` injection; uses a locked execution environment.
3. **Timeout**: 120s hard ceiling for foreground commands.
4. **Approval Flow**: Configurable "ask level" (Always/On-Miss/Off).

### Gmail Tools (`gmail`)

**Requires Google Account connection in Settings.**

| Tool | Description |
|------|-------------|
| `search_emails` | Search emails using Gmail query syntax (e.g., "is:unread") |
| `read_email` | Get full content and attachments of an email |
| `send_email` | Compose and send a new email |
| `reply_to_email` | Reply to a specific email thread |
| `create_draft` | Create a draft email without sending |
| `trash_email` | Move an email to trash |
| `get_unread_count` | Check unread count in inbox |
| `modify_labels` | Add/remove labels (e.g., archive, star) |

### Calendar Tools (`calendar`)

**Requires Google Account connection in Settings.**

| Tool | Description |
|------|-------------|
| `get_events` | List upcoming events for the next N days |
| `search_events` | Search events by keyword |
| `create_event` | Create a new calendar event |
| `quick_add_event` | Create event from natural language text |
| `update_event` | Update an existing event |
| `delete_event` | Delete an event |
| `get_free_busy` | Check availability for a time range |
| `list_calendars` | List all available calendars |

### Placeholder Servers

These servers have skeleton files but are not yet functional:
- **Discord** - Message reading/sending via Bot Token
- **Canvas** - LMS assignment and grade retrieval

## Adding a New MCP Server

### Step 1: Create the Server

Create a new directory under `mcp_servers/servers/` with a `server.py` file:

```python
# mcp_servers/servers/my_tool/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Tool Name")

@mcp.tool()
def my_function(param1: str, param2: int = 10) -> str:
    """Clear description of what this tool does and when the LLM should use it.
    
    This docstring is critical -- it's the only way the LLM knows when
    and how to use your tool. Be specific about:
    - What the tool does
    - When to use it vs. other tools
    - What the parameters mean
    - What the return value contains
    """
    result = do_something(param1, param2)
    return f"Result: {result}"

if __name__ == "__main__":
    mcp.run()  # Starts stdio transport
```

### Step 2: Register the Server

Add your server to the MCP initialization in `source/mcp_integration/manager.py` -> `init_mcp_servers()`:

```python
await mcp_manager.connect_server(
    "my_tool",                    # Server name (used in routing)
    sys.executable,               # Python interpreter
    [str(PROJECT_ROOT / "mcp_servers" / "servers" / "my_tool" / "server.py")]
)
```

Also add it to `mcp_servers/config/servers.json`:

```json
{
    "my_tool": {
        "enabled": true,
        "module": "mcp_servers.servers.my_tool.server",
        "description": "Description of what this server provides"
    }
}
```

### Step 3: Test and Restart

Test the server standalone:

```bash
python -m mcp_servers.servers.my_tool.server
```

Then restart the app. Tools are auto-discovered and registered with the LLM.

## Best Practices

### Tool Descriptions

The LLM decides which tools to use based solely on the docstring. Write descriptions that are:

- **Specific**: "Searches the web using DuckDuckGo and returns the top 5 results with titles, URLs, and snippets"
- **Action-oriented**: Start with a verb ("Reads", "Creates", "Searches")
- **Contextual**: Explain when to use this tool vs. others
- **Parameter-aware**: Describe what each parameter expects

### Error Handling

Return errors as strings rather than raising exceptions:

```python
@mcp.tool()
def safe_tool(path: str) -> str:
    """Does something safely."""
    try:
        result = risky_operation(path)
        return f"Success: {result}"
    except FileNotFoundError:
        return f"Error: File not found at {path}"
    except Exception as e:
        return f"Error: {str(e)}"
```

### Descriptions File Pattern

For complex tools, keep docstrings in a separate `descriptions.py` file:

```python
# mcp_servers/servers/my_tool/descriptions.py
MY_FUNCTION_DESC = """
Detailed multi-line description that guides the LLM
on exactly how and when to use this tool.
"""

# mcp_servers/servers/my_tool/server.py
from .descriptions import MY_FUNCTION_DESC

@mcp.tool(description=MY_FUNCTION_DESC)
def my_function(item_id: str) -> str:
    ...
```

## Debugging

### Check Server Registration

Look for `[MCP]` log entries on startup:

```
[MCP] Connecting to server: my_tool
[MCP] Server my_tool connected, discovered 2 tools
[MCP] Registered tool: my_function (server: my_tool)
```

### Test Tool Execution

Tool calls appear as cards in the UI:

```
+------------------------------------------+
| TOOL: my_function                        |
| Server: my_tool                          |
| Arguments: {"param1": "test"}            |
| Result: "Success: ..."                   |
+------------------------------------------+
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Tool not discovered | Missing type hints | Add type annotations to all parameters |
| Tool never called | Poor docstring | Rewrite with clearer description |
| Server crash on startup | Missing dependency | Check `requirements.txt` and install deps |
| "Tool call timeout" | Long-running operation | Add async support or increase timeout |
| Tools not used with images | By design | Tool detection is skipped when images are in context for some models |

## Architecture

```
source/mcp_integration/
  manager.py        # McpToolManager: launches servers, discovers tools,
                    #   handles inline registration, routes calls.
                    #   Uses background asyncio Tasks for stable lifecycle.
  handlers.py       # Ollama tool loop: Phase 1 detects tool requests (non-streamed),
                    #   Phase 2 streams follow-up responses in real-time.
                    #   retrieve_relevant_tools() shared by Ollama and cloud paths.
  terminal_executor.py # Unified terminal execution logic — used by both
                    #   handlers.py (Ollama) and cloud_provider.py (cloud models)

mcp_servers/
  client/
    ollama_bridge.py  # Standalone bridge (for testing outside the app)
  config/
    servers.json      # Server registration and configuration
  servers/
    demo/             # Reference calculator server
    filesystem/       # File system operations
    websearch/        # Web search + page reading
    terminal/         # Ghost process (inline tools reference)
    gmail/            # Email operations (search, send, read)
    calendar/         # Calendar operations (events, free/busy)
```
