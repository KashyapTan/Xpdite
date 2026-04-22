# mcp_servers/ — MCP Tool Servers

MCP extends the LLM with callable tools. In Xpdite, tools run in two modes:

- **Subprocess MCP servers** over stdio JSON-RPC (managed by `source/mcp_integration/core/manager.py`)
- **Inline tools** registered in the manager but executed directly in backend interceptors (no subprocess call path)

---

## Server Inventory

| Server | Mode | Status | Key tools | Notes |
|---|---|---|---|---|
| `filesystem` | Subprocess | ✅ Active | `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file` | Sandboxed file operations |
| `glob` | Subprocess | ✅ Active | `glob_files` | Filename discovery with filtering/pagination |
| `grep` | Subprocess | ✅ Active | `grep_files` | Content search with regex/modes/pagination |
| `websearch` | Subprocess | ✅ Active | `search_web_pages`, `read_website` | DuckDuckGo + multi-tier scraping |
| `windows_mcp` | Subprocess | ✅ Active (best effort) | `list_windows`, `focus_window`, `minimize_window`, `maximize_window`, `close_window`, `take_screenshot` | Started via `uvx windows-mcp` |
| `gmail` | Subprocess | ✅ Conditional | `search_emails`, `read_email`, `send_email`, `reply_to_email`, `create_draft`, `trash_email`, `list_labels`, `modify_labels`, `get_unread_count`, `get_email_thread` | Connects only when Google token is available |
| `calendar` | Subprocess | ✅ Conditional | `get_events`, `search_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `quick_add_event`, `list_calendars`, `get_free_busy` | Connects only when Google token is available |
| `terminal` | Inline | ✅ Active | `run_command`, `get_environment`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process` | Registered via `register_inline_tools`; executed by terminal executor with approval flow |
| `sub_agent` | Inline | ✅ Active | `spawn_agent` | Executed by `source/services/skills_runtime/sub_agent.py` |
| `video_watcher` | Inline | ✅ Active | `watch_youtube_video` | YouTube captions first, Whisper fallback with explicit approval |
| `skills` | Inline | ✅ Active | `list_skills`, `use_skill` | Retrieval-enabled inline tools |
| `memory` | Inline | ✅ Active | `memlist`, `memread`, `memcommit` | Retrieval-enabled memory store tools |
| `scheduler` | Inline | ✅ Active | `create_job`, `list_jobs`, `delete_job`, `pause_job`, `resume_job`, `run_job_now` | Scheduled job orchestration tools |
| `everything` | External Connector | ✅ Available | Demo tool set | Defined in `external_connectors.py`; connect from Settings → Connections |
| `demo` | Subprocess | ✅ Disabled | `add`, `divide` | Local demo server (disabled by default) |
| `discord` | Placeholder | 📝 Stub | — | Placeholder `server.py`; not production-ready |
| `canvas` | Placeholder | 📝 Stub | — | Placeholder `server.py`; not production-ready |
| `github`, `jira`, `notion`, `obsidian`, `outlook`, `slack`, `teams`, `whatsapp`, `yahoo` | Placeholder dirs | 📝 Empty | — | Directory stubs only |

---

## External Connectors

External connectors are MCP servers that are not bundled directly into `mcp_servers/servers/*` runtime startup. They are managed by `source/services/integrations/external_connectors.py` and connected via `init_external_connectors()` during MCP init.

How they work:

1. Connector definitions live in `EXTERNAL_CONNECTORS`.
2. UI reads connector status from `/api/external-connectors`.
3. Enable/disable state persists in settings DB.
4. Enabled connectors auto-reconnect on app startup.

Current registry state:

- `everything` demo connector is available.
- Figma/Slack examples are present as commented templates (not active by default).

### Add a New External Connector

Add a registry entry in `source/services/integrations/external_connectors.py`:

```python
EXTERNAL_CONNECTORS["my_connector"] = {
    "name": "my_connector",
    "display_name": "My Connector",
    "description": "What it provides",
    "command": "npx",  # or "uvx"
    "args": ["-y", "package-name"],
    "services": ["Service1", "Service2"],
    "icon_type": "my_connector",
    "auth_type": "browser",  # or None
}
```

Optional UI polish:

- Add an icon in `src/ui/components/settings/SettingsConnections.tsx`
- Add tool badge/summary mappings in `src/ui/components/chat/toolCallUtils.ts`

---

## File Layout

```text
mcp_servers/
├── __init__.py
├── requirements.txt
├── test_demo.py
├── config/
│   └── servers.json         # UI metadata only; backend startup does not rely on this for live wiring
├── servers/
│   ├── __init__.py
│   ├── description_format.py
│   ├── calendar/            # subprocess server
│   ├── canvas/              # placeholder stub
│   ├── demo/                # subprocess demo server
│   ├── discord/             # placeholder stub
│   ├── filesystem/          # subprocess server (+ sandbox)
│   ├── glob/                # subprocess server
│   ├── gmail/               # subprocess server
│   ├── grep/                # subprocess server
│   ├── memory/              # inline_tools.py (+ descriptions)
│   ├── scheduler/           # inline_tools.py
│   ├── skills/              # inline_tools.py (+ descriptions)
│   ├── sub_agent/           # inline_tools.py (+ descriptions)
│   ├── terminal/            # inline_tools.py + subprocess fallback server code
│   ├── video_watcher/       # inline_tools.py (+ descriptions)
│   ├── websearch/           # subprocess server
│   └── github/, jira/, notion/, obsidian/, outlook/, slack/, teams/, whatsapp/, yahoo/  # stubs
└── client/
    ├── __init__.py
    └── ollama_bridge.py
```

---

## Adding Servers

### Add a New Subprocess MCP Server

1. Create `mcp_servers/servers/<name>/server.py` with `FastMCP` tool definitions.
2. Register connection in `source/mcp_integration/core/manager.py` inside `init_mcp_servers()` using `connect_server(...)`.
3. (Optional) Add UI metadata entry to `mcp_servers/config/servers.json`.
4. (Optional) Add/update skills under `source/skills_seed/<name>/` if tool-specific prompting helps.
5. Update `src/ui/components/chat/toolCallUtils.ts` for friendly badges/summaries.

### Add a New Inline Tool Server

1. Define schemas in `mcp_servers/servers/<name>/inline_tools.py`.
2. Register with `mcp_manager.register_inline_tools("<name>", ...)` in `init_mcp_servers()`.
3. Add interception/execution in both paths:
   - Cloud provider path: `source/llm/providers/cloud_provider.py`
   - Ollama tool loop path: `source/mcp_integration/core/handlers.py`
4. Implement executor/service logic under `source/mcp_integration/executors/` and/or `source/services/`.

---

## Gotchas

**Inline tools are not MCP subprocess calls.** If a tool is registered inline, `mcp_manager.call_tool()` should not be the execution path; intercept in provider/handler layers.

**Timeout behavior is manager-defined.** Tool calls use server-specific read timeouts: default 90s, `websearch` 25s, with an additional 5s `asyncio.wait_for` buffer.

**Tool output is normalized to Markdown before it reaches the model/UI.** Structured JSON-style payloads from subprocess MCP tools are converted into Markdown summaries plus fenced content blocks at the app layer, so tools like `read_file`, `glob_files`, and `grep_files` can keep returning structured data internally without exposing raw JSON to the model.

**Tool output is truncated at 200,000 chars.** Design tools to return focused payloads.

**Subprocess lifecycle is task-bound.** `stdio_client` and `ClientSession` must enter/exit on the same background task; do not bypass manager lifecycle rules.

**`PYTHONPATH` is injected for child servers.** Manager prepends project root so `mcp_servers.*` imports resolve in subprocesses.

**Terminal is approval-gated and inline-executed.** Do not rely on `mcp_servers/servers/terminal/server.py` for primary runtime behavior.

**Sub-agent is inline and restricted.** `spawn_agent` executes in `source/services/skills_runtime/sub_agent.py`; it excludes terminal tools and recursive `spawn_agent` calls. The `spawn_agent` tool has a control-plane exception keeping it always included in the available tools list regardless of semantic retrieval. Cloud tool execution strictly rejects unlisted tools to prevent hallucinations.

**Video watcher is inline.** `watch_youtube_video` executes via `video_watcher_executor.py` and emits approval blocks before Whisper fallback when captions are unavailable.

**Google tools require OAuth token.** `gmail`/`calendar` need a valid `user_data/google/token.json` created through Settings.

**Placeholder servers are scaffolds only.** Stub directories/files are not production-ready implementations.

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
