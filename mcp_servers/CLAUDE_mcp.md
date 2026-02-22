# mcp_servers/ — MCP Tool Servers

MCP (Model Context Protocol) extends the LLM with callable tools. Each server is an independent Python subprocess communicating over stdio JSON-RPC. The app spawns them at startup and routes tool calls from the LLM to the correct server.

---

## Server Directory

| Server | Status | Key Tools | Notes |
|---|---|---|---|
| `filesystem` | ✅ Active | `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file` | Sandboxed — paths are validated |
| `gmail` | ✅ Active | `search_emails`, `read_email`, `send_email`, `reply_to_email`, `create_draft`, `trash_email`, `list_labels`, `modify_labels`, `get_unread_count`, `get_email_thread` | Requires Google OAuth token |
| `calendar` | ✅ Active | `get_events`, `search_events`, `create_event`, `update_event`, `delete_event`, `quick_add_event`, `list_calendars`, `get_free_busy` | Requires Google OAuth token |
| `websearch` | ✅ Active | `search_web_pages`, `read_website` | DuckDuckGo search + HTTP scraping |
| `terminal` | ✅ Active (inline) | `run_command`, `find_files`, `get_environment`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process` | **Never runs as subprocess.** Executed inline by `terminal_executor.py` with approval UI. |
| `demo` | ✅ Disabled | `add`, `divide` | Math demo; disabled by default |
| `discord` | 📝 Placeholder | — | Needs `DISCORD_BOT_TOKEN` in `config/servers.json` |
| `canvas` | 📝 Placeholder | — | Needs `CANVAS_URL` + `CANVAS_TOKEN` |
| `github`, `jira`, `notion`, `obsidian`, `outlook`, `slack`, `teams`, `whatsapp`, `yahoo` | 📝 Placeholder | — | Stub directories only |

---

## File Layout

```
mcp_servers/
├── config/
│   └── servers.json         # Enable/disable servers; per-server env vars and credentials
├── servers/
│   └── <name>/
│       ├── server.py                  # Tool definitions via @mcp.tool()
│       └── <name>_descriptions.py    # Long docstrings kept separate to keep server.py clean
└── client/
    └── ollama_bridge.py    # Standalone bridge for testing MCP servers outside the main app
```

---

## How to Add a New MCP Server (end-to-end)

### 1. Create the server
```python
# mcp_servers/servers/myserver/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("myserver")

@mcp.tool(description=MCP_TOOL_DESCRIPTION) # MCP_TOOL_DESCRIPTION is the descripiton that the model will read in order to decicde weather or not to use a tool
def do_thing(param: str) -> str:
    return f"result: {param}"

if __name__ == "__main__":
    mcp.run()
```

Keep descriptions crisp — the tool retriever uses them for semantic search, so vague descriptions lead to low retrieval scores.

### 2. Connect in `source/mcp_integration/manager.py`
Inside `init_mcp_servers()`:
```python
await mcp_manager.connect_server(
    "myserver",
    sys.executable,
    [str(PROJECT_ROOT / "mcp_servers" / "servers" / "myserver" / "server.py")]
)
```

### 3. (Optional) Update `config/servers.json`
Add an entry for UI display in Settings. The backend does **not** read this file — it is metadata only.

### 4. (Optional) Add a skill
Create an entry in `source/mcp_integration/default_skills.py` with `skill_name` matching the server name. The skill's `content` is injected into the system prompt whenever your tools are active, giving the model domain-specific guidance.

### 5. That's it
Tools are auto-discovered on startup, indexed by the semantic retriever, and routed automatically when the LLM calls them.

---

## Gotchas

**The `terminal` server is a special case.** Its tools are intercepted by `terminal_executor.py` before they reach the subprocess. The subprocess isn't even spawned for terminal tools. Do not add terminal logic to `server.py` expecting it to run — put it in `terminal_executor.py`.

**PYTHONPATH is injected automatically.** `manager.py` ensures `PROJECT_ROOT` is in the child process's `PYTHONPATH` so servers can use `from mcp_servers.servers.xxx import ...` style imports.

**MCP subprocess lifecycle uses a background asyncio Task.** The `stdio_client` + `ClientSession` context managers must open and close on the *same* asyncio task. Do not try to disconnect a server from an HTTP handler — it will raise a `RuntimeError` from anyio's cancel scope check.

**Tool output is truncated at 100,000 characters.** If a tool returns unexpectedly large output (e.g., a huge file read), it will be silently truncated before being sent to the LLM. Design tools to return summaries rather than raw large blobs.

**Placeholder servers have stub `server.py` files.** Running them will fail or return empty results. Check `config/servers.json` `"enabled"` before assuming a server works.

**Google-authenticated servers (`gmail`, `calendar`)** require a valid `user_data/google/token.json`. If the token is missing or expired, the tools will fail. Users must complete OAuth via Settings → Google.
