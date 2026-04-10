# mcp_servers/ — MCP Tool Servers

MCP (Model Context Protocol) extends the LLM with callable tools. Each server is an independent Python subprocess communicating over stdio JSON-RPC. The app spawns them at startup and routes tool calls from the LLM to the correct server.

---

## Server Directory

| Server | Status | Key Tools | Notes |
|---|---|---|---|
| `filesystem` | ✅ Active | `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file`, `glob_files`, `grep_files` | Sandboxed — paths are validated; `glob_files` is mtime-sorted and `grep_files` supports structured modes/pagination |
| `gmail` | ✅ Active | `search_emails`, `read_email`, `send_email`, `reply_to_email`, `create_draft`, `trash_email`, `list_labels`, `modify_labels`, `get_unread_count`, `get_email_thread` | Requires Google OAuth token |
| `calendar` | ✅ Active | `get_events`, `search_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `quick_add_event`, `list_calendars`, `get_free_busy` | Requires Google OAuth token |
| `websearch` | ✅ Active | `search_web_pages`, `read_website` | DuckDuckGo search + multi-tier HTTP/browser scraping with concurrent execution |
| `windows_mcp` | ✅ Active | `list_windows`, `focus_window`, `minimize_window`, `maximize_window`, `close_window`, `take_screenshot` | Windows automation via uvx |
| `terminal` | ✅ Active (inline) | `run_command`, `find_files`, `get_environment`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process` | **Never runs as subprocess.** Schemas live in `terminal/inline_tools.py`; execution is inline via `terminal_executor.py` with approval UI, explicit shell selection, and shell-specific safety checks. |
| `sub_agent` | ✅ Active (inline) | `spawn_agent` | **Never runs as subprocess.** Schema lives in `sub_agent/inline_tools.py`; registration remains in `manager.py`, interception in `cloud_provider.py` and `handlers.py`, execution is in `services/sub_agent.py`. |
| `video_watcher` | ✅ Active (inline) | `watch_youtube_video` | **Never runs as subprocess.** Schema lives in `video_watcher/inline_tools.py`; execution is inline via `source/services/media/video_watcher.py` with YouTube-caption fallback approval + Whisper transcription. |
| `skills` | ✅ Active (inline) | `list_skills`, `use_skill` | **Never runs as subprocess.** Schema lives in `skills/inline_tools.py`; execution is inline via `source/mcp_integration/executors/skills_executor.py` for on-demand skill discovery/loading. |
| `figma` | 🔌 External | Design tools via mcp-remote | User-enabled via Settings → Connections. Uses `npx mcp-remote` to bridge Figma's remote MCP server. |
| `demo` | ✅ Disabled | `add`, `divide` | Math demo; disabled by default |
| `discord` | 📝 Placeholder | — | Needs `DISCORD_BOT_TOKEN` in `config/servers.json` |
| `canvas` | 📝 Placeholder | — | Needs `CANVAS_URL` + `CANVAS_TOKEN` |
| `github`, `jira`, `notion`, `obsidian`, `outlook`, `slack`, `teams`, `whatsapp`, `yahoo` | 📝 Placeholder | — | Stub directories only |

---

## External Connectors

External connectors are MCP servers that are **not bundled** with Xpdite. They include third-party services like Figma, GitHub, etc. that:

1. May require authentication (OAuth, API keys)
2. Use stdio transport via bridge tools like `npx mcp-remote` or `uvx`
3. Are enabled/disabled by users in Settings → Connections
4. Auto-reconnect on app startup if previously enabled

### How External Connectors Work

1. **Registry**: Connectors are defined in `source/services/integrations/external_connectors.py` in the `EXTERNAL_CONNECTORS` dict
2. **UI**: They appear automatically in Settings → Connections with Connect/Disconnect buttons
3. **State**: Enabled/disabled state is persisted in the settings DB
4. **Connection**: On connect, the subprocess is spawned; on app restart, enabled connectors auto-reconnect

### Currently Available External Connectors

| Connector | Transport | Auth | Notes |
|-----------|-----------|------|-------|
| **Figma** | `npx mcp-remote` → HTTP | OAuth (browser) | Design file access. Rate limits: Starter 6/month, Pro 200/day, Enterprise 600/day |

### How to Add a New External Connector

1. **Add to the registry** in `source/services/integrations/external_connectors.py`:

```python
EXTERNAL_CONNECTORS["my_connector"] = {
    "name": "my_connector",
    "display_name": "My Connector",
    "description": "What it provides",
    "command": "npx",  # or "uvx" for Python-based servers
    "args": ["-y", "package-name", "additional", "args"],
    "services": ["Service1", "Service2"],  # Badges shown in UI
    "icon_type": "my_connector",  # Icon identifier for frontend
    "auth_type": "browser",  # "browser", "api_key", or None
    "env": None,  # Optional env vars dict
}
```

2. **Add the icon** (optional) in `SettingsConnections.tsx`:

```tsx
// In the ConnectorIcon component's switch statement:
case 'my_connector':
  return (
    <svg viewBox="0 0 24 24" width="28" height="28">
      {/* Your SVG paths */}
    </svg>
  );
```

3. **Add tool display config** (optional) in `src/ui/components/chat/toolCallUtils.ts`:

```typescript
// In TOOL_DISPLAY_CONFIG:
my_connector: {
  badge: 'MY-CONNECTOR',
  summaryNoun: 'connector action',
  tools: {
    some_tool: (args) => `Doing something with ${args.param}`,
  },
},
```

4. **That's it!** The connector will:
   - Appear in Settings → Connections automatically
   - Be connectable/disconnectable by users
   - Auto-reconnect on app restart if enabled
   - Have its tools appear in chat with reasonable fallback display

### External Connector Types

**Browser Auth (`auth_type: "browser"`)**: 
Uses `mcp-remote` or similar bridge that handles OAuth internally. When the user clicks Connect, the subprocess starts and may open a browser window for authentication.

**API Key Auth (`auth_type: "api_key"`)** *(planned)*:
Requires an API key stored in settings. The key is passed as an environment variable to the subprocess.

**No Auth (`auth_type: null`)**:
Public MCP servers that don't require authentication.

---

## File Layout

```text
mcp_servers/
├── __init__.py
├── requirements.txt         # Dependencies for MCP servers
├── test_demo.py             # pytest script for testing MCP servers
├── config/
│   └── servers.json         # Enable/disable servers; per-server env vars and credentials (UI metadata only — backend does not read this)
├── servers/
│   ├── __init__.py
│   ├── description_format.py# Shared format for tool descriptions
│   ├── calendar/            ✅ server.py + calander_descriptions.py
│   ├── canvas/              📝 server.py + canvas_descriptions.py (placeholder, no tools yet) — needs CANVAS_URL + CANVAS_TOKEN
│   ├── demo/                ✅ server.py + demo_descriptions.py (disabled by default)
│   ├── discord/             📝 server.py + discord_descriptions.py (placeholder, no tools yet) — needs DISCORD_BOT_TOKEN
│   ├── filesystem/          ✅ server.py + filesystem_descriptions.py
│   ├── gmail/               ✅ server.py + gmail_descriptions.py
│   ├── skills/              ✅ inline_tools.py + skills_descriptions.py (inline-only tool metadata)
│   ├── sub_agent/           ✅ inline_tools.py + sub_agent_descriptions.py (inline-only tool metadata)
│   ├── terminal/            ✅ server.py + terminal_descriptions.py + inline_tools.py + blocklist.py (tools run inline, not as subprocess)
│   ├── video_watcher/       ✅ inline_tools.py + video_watcher_descriptions.py (inline-only tool metadata)
│   ├── websearch/           ✅ server.py + websearch_descriptions.py
│   └── github/, jira/, notion/, obsidian/, outlook/, slack/, teams/, whatsapp/, yahoo/   🗂️ Empty directories (no files)
└── client/
    ├── __init__.py
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

### 2. Connect in `source/mcp_integration/core/manager.py`
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

The skill is auto-seeded to `user_data/skills/builtin/` on every app startup. `trigger_servers` should list your new server name so the skill auto-injects when relevant tools are retrieved. Skills are managed by `SkillManager` in `source/services/skills_runtime/skills.py`.

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

**The `video_watcher` server is also inline-only.** The `watch_youtube_video` schema lives in `mcp_servers/servers/video_watcher/inline_tools.py` and is registered in `manager.py` via `register_inline_tools("video_watcher", VIDEO_WATCHER_INLINE_TOOLS)`. Execution is intercepted in `cloud_provider.py` and `mcp_integration/handlers.py` and handled by `source/mcp_integration/executors/video_watcher_executor.py` + `source/services/media/video_watcher.py`. When captions are unavailable, it emits a `youtube_transcription_approval` chat block and waits for user approval before Whisper transcription.

**The `skills` server is inline-only and retrieval-enabled.** `list_skills` and `use_skill` are registered via `register_inline_tools("skills", SKILLS_INLINE_TOOLS, skip_embed=False)` so they can be semantically retrieved by the tool retriever. Execution is handled inline by `source/mcp_integration/executors/skills_executor.py` (no subprocess).

---

## Websearch Architecture

The `websearch` MCP server provides two tools: `search_web_pages` (DuckDuckGo search) and `read_website` (web scraping). The scraping system uses a multi-tier architecture with concurrent execution for optimal performance.

### Tier System

| Tier | Method | Timeout | Use Case |
|------|--------|---------|----------|
| **Tier 1 (curl)** | httpx + curl_cffi | 7s | Fast HTTP fetch for static sites |
| **Tier 2 (camoufox)** | Camoufox browser | 10s | JS-heavy sites, anti-bot bypass |
| **Tier 3 (nodriver)** | undetected-chromedriver | 12s | Maximum stealth (disabled by default) |

### Concurrent Execution Flow

```
┌─────────────────────────────────────────────────────────┐
│  scrape_concurrent(url, mode)                           │
├─────────────────────────────────────────────────────────┤
│  1. Special handlers (Twitter/Medium) tried first       │
│  2. Tier 1 starts immediately                           │
│  3. After 1.5s stagger delay, browser tiers start       │
│  4. First result > 5000 chars wins (early return)       │
│  5. If all finish, best result is selected              │
│  6. Access restriction detection on final content       │
└─────────────────────────────────────────────────────────┘
```

### Thresholds (benchmarked on 260 URLs)

| Threshold | Value | Source |
|-----------|-------|--------|
| Success (early return) | 5,000 chars | P25 of successful extractions |
| Sparse content warning | 500 chars | P10 of successful extractions |
| Global timeout | 12s | P99 latency + buffer |

### Access Restriction Detection

The scraper detects 30+ signals indicating login walls, paywalls, and CAPTCHAs. When detected:
- Warning is added to output metadata
- Suggestions offered (try different mode, check credentials, etc.)
- Content still returned if available (some paywalled sites show partial content)

### Browser Pool

Camoufox browser instances are pooled (default 2) for faster subsequent requests. Pool management is automatic via `_get_camoufox_browser()` / `_return_camoufox_browser()`.

### Key Files

- `mcp_servers/servers/websearch/server.py` — main implementation
- `mcp_servers/servers/websearch/websearch_descriptions.py` — tool descriptions
- `scripts/benchmark_websearch.py` — benchmark script for tuning thresholds
- `scripts/benchmark_urls.json` — 260 URLs across 11 categories for benchmarking
- `tests/test_websearch_server.py` — unit tests (32 tests)

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEBSEARCH_ENABLE_EXTERNAL_RELAYS` | false | Enable Freedium/Archive.is relays for Medium |
| `WEBSEARCH_ENABLE_UNSAFE_TIER3_BROWSER` | false | Enable nodriver tier (requires manual setup) |
