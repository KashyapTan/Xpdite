# mcp_servers/ — MCP Tool Servers

MCP (Model Context Protocol) extends the LLM with callable tools. Each server is an independent Python subprocess communicating over stdio JSON-RPC. The app spawns them at startup and routes tool calls from the LLM to the correct server.

---

## Server Directory

| Server | Status | Key Tools | Notes |
|---|---|---|---|
| `filesystem` | ✅ Active | `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file`, `glob_files`, `grep_files` | Sandboxed — paths are validated |
| `gmail` | ✅ Active | `search_emails`, `read_email`, `send_email`, `reply_to_email`, `create_draft`, `trash_email`, `list_labels`, `modify_labels`, `get_unread_count`, `get_email_thread` | Requires Google OAuth token |
| `calendar` | ✅ Active | `get_events`, `search_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `quick_add_event`, `list_calendars`, `get_free_busy` | Requires Google OAuth token |
| `websearch` | ✅ Active | `search_web_pages`, `read_website` | DuckDuckGo search + HTTP scraping |
| `terminal` | ✅ Active (inline) | `run_command`, `find_files`, `get_environment`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process` | **Never runs as subprocess.** Schemas live in `terminal/inline_tools.py`; execution is inline via `terminal_executor.py` with approval UI. |
| `sub_agent` | ✅ Active (inline) | `spawn_agent` | **Never runs as subprocess.** Schema lives in `sub_agent/inline_tools.py`; registration remains in `manager.py`, interception in `cloud_provider.py` and `handlers.py`, execution is in `services/sub_agent.py`. |
| `video_watcher` | ✅ Active (inline) | `watch_youtube_video` | **Never runs as subprocess.** Schema lives in `video_watcher/inline_tools.py`; execution is inline via `source/services/video_watcher.py` with YouTube-caption fallback approval + Whisper transcription. |
| `skills` | ✅ Active (inline) | `list_skills`, `use_skill` | **Never runs as subprocess.** Schema lives in `skills/inline_tools.py`; execution is inline via `source/mcp_integration/skills_executor.py` for on-demand skill discovery/loading. |
| `demo` | ✅ Disabled | `add`, `divide` | Math demo; disabled by default |
| `discord` | 📝 Placeholder | — | Needs `DISCORD_BOT_TOKEN` in `config/servers.json` |
| `canvas` | 📝 Placeholder | — | Needs `CANVAS_URL` + `CANVAS_TOKEN` |
| `github`, `jira`, `notion`, `obsidian`, `outlook`, `slack`, `teams`, `whatsapp`, `yahoo` | 📝 Placeholder | — | Stub directories only |

---

## File Layout

```
mcp_servers/
├── config/
│   └── servers.json         # Enable/disable servers; per-server env vars and credentials (UI metadata only — backend does not read this)
├── servers/
│   ├── calendar/            ✅ server.py + calander_descriptions.py
│   ├── canvas/              📝 server.py placeholder (no tools yet) — needs CANVAS_URL + CANVAS_TOKEN
│   ├── demo/                ✅ server.py (disabled by default)
│   ├── discord/             📝 server.py placeholder (no tools yet) — needs DISCORD_BOT_TOKEN
│   ├── filesystem/          ✅ server.py + filesystem_descriptions.py
│   ├── gmail/               ✅ server.py + gmail_descriptions.py
│   ├── skills/              ✅ inline_tools.py + skills_descriptions.py (inline-only tool metadata)
│   ├── sub_agent/           ✅ inline_tools.py + sub_agent_descriptions.py (inline-only tool metadata)
│   ├── terminal/            ✅ server.py + terminal_descriptions.py + inline_tools.py + blocklist.py (tools run inline, not as subprocess)
│   ├── video_watcher/       ✅ inline_tools.py + video_watcher_descriptions.py (inline-only tool metadata)
│   ├── websearch/           ✅ server.py + websearch_descriptions.py
│   └── github/, jira/, notion/, obsidian/, outlook/, slack/, teams/, whatsapp/, yahoo/   🗂️ Empty directories (no files)
└── client/
    └── ollama_bridge.py    # Standalone bridge for testing MCP servers outside the main app (not used in production)
```

---

## How to Add a New MCP Server (end-to-end)

### 1. Create the server
```python
# mcp_servers/servers/myserver/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("myserver")

@mcp.tool(description=MCP_TOOL_DESCRIPTION) # MCP_TOOL_DESCRIPTION is what the model reads to decide when and how to use the tool
def do_thing(param: str) -> str:
    return f"result: {param}"

if __name__ == "__main__":
    mcp.run()
```

Keep descriptions crisp and consistent — the tool retriever uses them for semantic search, so vague descriptions lead to low retrieval scores.
Use the shared helper in `mcp_servers/servers/description_format.py` and keep each description in this order:
- `Purpose:` literal output prefix for what the tool does
- `Use when:` literal output prefix for when the LLM should choose it
- `Inputs:` literal output prefix for the important parameters and format constraints
- `Returns:` literal output prefix for what comes back
- `Notes:` optional literal output prefix only when workflow or safety guidance matters

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
Create a folder under `source/skills_seed/<your_name>/` with two files:
- `skill.json` — `{ name, description, slash_command, trigger_servers, version }`
- `SKILL.md` — the prompt content injected when the skill is active.

The skill is auto-seeded to `user_data/skills/builtin/` on every app startup. `trigger_servers` should list your new server name so the skill auto-injects when relevant tools are retrieved. Skills are managed by `SkillManager` in `source/services/skills.py`.

### 5. That's it
Tools are auto-discovered on startup, indexed by the semantic retriever, and routed automatically when the LLM calls them.

### 6. UI follow-up for chat tool calls
If the new server's tool calls should display nicely in the chat timeline, update `src/ui/components/chat/toolCallUtils.ts` and the related summary usage in `src/ui/components/chat/ToolCallsDisplay.tsx` so the server badge and per-tool descriptions stay human-friendly.

---

## Gotchas

**The `terminal` server is a special case.** Its tools are intercepted by `terminal_executor.py` before they reach the subprocess. The subprocess isn't even spawned for terminal tools. Do not add terminal logic to `server.py` expecting it to run — put it in `terminal_executor.py`.

**PYTHONPATH is injected automatically.** `manager.py` ensures `PROJECT_ROOT` is in the child process's `PYTHONPATH` so servers can use `from mcp_servers.servers.xxx import ...` style imports.

**MCP subprocess lifecycle uses a background asyncio Task.** The `stdio_client` + `ClientSession` context managers must open and close on the *same* asyncio task. Do not try to disconnect a server from an HTTP handler — it will raise a `RuntimeError` from anyio's cancel scope check.

**Tool output is truncated at 100,000 characters.** If a tool returns unexpectedly large output (e.g., a huge file read), it will be silently truncated before being sent to the LLM. Design tools to return summaries rather than raw large blobs.

**Placeholder servers have stub `server.py` files.** Running them will fail or return empty results. Check `config/servers.json` `"enabled"` before assuming a server works.

**Google-authenticated servers (`gmail`, `calendar`)** require a valid `user_data/google/token.json`. If the token is missing or expired, the tools will fail. Users must complete OAuth via Settings → Google.

**The `sub_agent` server is an inline tool like `terminal`.** The `spawn_agent` schema lives in `mcp_servers/servers/sub_agent/inline_tools.py` and is registered in `manager.py`'s `init_mcp_servers()` via `register_inline_tools("sub_agent", SUB_AGENT_INLINE_TOOLS)`. Tool calls are intercepted in both `cloud_provider.py` (`_execute_and_broadcast_tool`) and `handlers.py` (Ollama tool loop) before reaching the MCP subprocess router. Sub-agents have no access to terminal tools or `spawn_agent` itself (enforced by `_EXCLUDED_TOOLS` set in `services/sub_agent.py`). Tier-to-model mapping is configurable via Settings → Sub-Agents (stored as `sub_agent_tier_fast` / `sub_agent_tier_smart` in the `settings` DB table).

**The `video_watcher` server is also inline-only.** The `watch_youtube_video` schema lives in `mcp_servers/servers/video_watcher/inline_tools.py` and is registered in `manager.py` via `register_inline_tools("video_watcher", VIDEO_WATCHER_INLINE_TOOLS)`. Execution is intercepted in `cloud_provider.py` and `mcp_integration/handlers.py` and handled by `source/mcp_integration/video_watcher_executor.py` + `source/services/video_watcher.py`. When captions are unavailable, it emits a `youtube_transcription_approval` chat block and waits for user approval before Whisper transcription.

**The `skills` server is inline-only and retrieval-enabled.** `list_skills` and `use_skill` are registered via `register_inline_tools("skills", SKILLS_INLINE_TOOLS, skip_embed=False)` so they can be semantically retrieved by the tool retriever. Execution is handled inline by `source/mcp_integration/skills_executor.py` (no subprocess).
