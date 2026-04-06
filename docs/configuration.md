# Configuration Reference

This document covers all configurable aspects of Xpdite.

## Python Backend Configuration

### Constants (`source/infrastructure/config.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `PROJECT_ROOT` | Auto-detected | Root directory of the project |
| `SCREENSHOT_FOLDER` | `user_data/screenshots` | Where screenshots are stored |
| `DEFAULT_PORT` | `8000` | Starting port for the FastAPI server |
| `DEFAULT_MODEL` | `qwen3-vl:8b-instruct` | Default Ollama model |
| `MAX_MCP_TOOL_ROUNDS` | `30` | Maximum tool call iterations per query |
| `GOOGLE_TOKEN_FILE` | `user_data/google/token.json` | Stored OAuth credentials |

### Capture Modes (`CaptureMode` enum)

| Mode | Description |
|------|-------------|
| `fullscreen` | Captures the entire screen automatically |
| `precision` | Opens a region selector overlay for manual selection |
| `none` | No automatic screenshot capture |

### Port Auto-Discovery

The server probes ports starting from `DEFAULT_PORT` (8000) up to 8009. The first available port is used. This prevents conflicts when multiple instances run or when a stale process holds a port.

### CORS Configuration (`source/bootstrap/app_factory.py`)

By default, CORS allows all origins for development:

```python
allow_origins=["*"]
allow_methods=["*"]
allow_headers=["*"]
```

Restrict this in production deployments if needed.

## Electron Configuration

### Window Settings (`src/electron/main.ts`)

| Setting | Value | Purpose |
|---------|-------|---------|
| `width` / `height` | 550 x 550 | Normal mode dimensions |
| Mini mode | 52 x 52 | Minimized dimensions |
| `frame` | `false` | Frameless window |
| `transparent` | `true` | Transparent background |
| `alwaysOnTop` | `true` | Stays on top of other windows |
| `level` | `screen-saver` | On top of even full-screen apps |
| `skipTaskbar` | `true` | Hidden from taskbar |
| `contentProtection` | `true` | Prevents screen recording / capture |

## MCP Server Configuration

### Server Registry (`mcp_servers/config/servers.json`)

Each server entry:

```json
{
    "server_name": {
        "enabled": true,
        "module": "mcp_servers.servers.server_name.server",
        "env": {
            "ENV_VAR": "value"
        }
    }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | Yes | Whether the server is active |
| `module` | Yes | Python module path |
| `env` | No | Environment variables passed to the server process |

### Currently Registered Servers

| Server | Enabled | Tools |
|--------|---------|-------|
| `demo` | Yes | `add`, `divide` |
| `filesystem` | Yes | `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file` |
| `websearch` | Yes | `search_web_pages`, `read_website` |
| `gmail` | Dynamic | Search, read, send, reply, draft, trash, labels, unread count |
| `calendar` | Dynamic | List events, search, create, update, delete, quick add, free/busy |
| `discord` | No | Placeholder |
| `canvas` | No | Placeholder |

> **Note:** Gmail and Calendar servers are started dynamically only after the user connects their Google account in Settings.

## Frontend Configuration

### Vite Dev Server (`vite.config.ts`)

| Setting | Value |
|---------|-------|
| Port | 5123 |
| Base path | `./` (relative, for Electron) |
| Output directory | `dist-react` |
| Plugin | `@vitejs/plugin-react` |

### Router (`src/ui/main.tsx`)

Uses `createHashRouter` (required for Electron, which uses `file://` protocol):

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | `App` | Main chat interface |
| `/settings` | `Settings` | Application settings (Models, Connections, Tools, Skills, Meeting, System Prompt) |
| `/history` | `ChatHistory` | Conversation browser with full-text search |
| `/album` | `MeetingAlbum` | Past meeting recordings list |
| `/recorder` | `MeetingRecorder` | Live meeting recording UI |
| `/recording/:id` | `MeetingRecordingDetail` | Recording detail + AI analysis + action execution |

## Build Configuration

### Electron Builder (`electron-builder.json`)

| Setting | Value |
|---------|-------|
| App ID | `com.kashyap-tanuku.xpdite` |
| Product Name | `Xpdite` |
| Windows targets | `nsis` (installer), `portable` |
| Architecture | `x64` |
| Extra resources | `dist-python` -> `python-server` |

### PyInstaller (`build-server.spec`)

Bundles the Python backend into a single executable at `dist-python/main.exe`. Includes all Python dependencies and the MCP server files.

## Database Configuration

### SQLite Settings

| Setting | Value | Reason |
|---------|-------|--------|
| `check_same_thread` | `False` | FastAPI uses thread pools |
| Location | `user_data/xpdite_app.db` | Persistent across sessions |
| WAL mode | **Enabled** (`PRAGMA journal_mode=WAL`) | Concurrent reads during streaming writes |
| Busy timeout | `5000 ms` | Avoids SQLITE_BUSY errors under load |

### Settings Table

Application settings are stored as key-value pairs in the `settings` table:

| Key | Value Type | Description |
|-----|-----------|-------------|
| `enabled_models` | JSON array | List of enabled model names |
| `api_key_anthropic` | Encrypted string | Anthropic API key |
| `api_key_openai` | Encrypted string | OpenAI API key |
| `api_key_gemini` | Encrypted string | Google Gemini API key |
| `encryption_salt` | Hex string | Salt for Fernet encryption |
| `tool_always_on` | JSON array | Tools always included in context |
| `tool_retriever_top_k` | String/Number | Number of semantic tool matches |
| `system_prompt_template` | String | Custom system prompt template |

### Skills (Filesystem-Backed)

Skills are **not** stored in the DB. They are filesystem folders under `user_data/skills/`:

- **Builtin skills**: `user_data/skills/builtin/<name>/` — seeded from `source/skills_seed/` on startup
- **User skills**: `user_data/skills/user/<name>/`
- **Enabled/disabled state**: `user_data/skills/preferences.json`

Each skill folder contains `skill.json` (name, description, slash_command, trigger_servers, version) and `SKILL.md` (the full prompt content injected when triggered).

### Additional DB Tables

| Table | Description |
|-------|-------------|
| `message_response_versions` | Stores alternate assistant responses for retry/edit (indexed by `assistant_message_id` + `response_index`) |
| `terminal_events` | Full audit trail for every terminal command (command, exit_code, output, cwd, duration_ms, pty, background, denied) |
| `meeting_recordings` | Meeting session rows with status (`recording`/`processing`/`completed`/`failed`), Tier1/Tier2 transcripts, AI summary/actions |
| `conversations_fts` | FTS5 virtual table for full-text conversation search (auto-updated by triggers) |
| `messages_fts` | FTS5 virtual table for full-text message search (auto-updated by triggers) |

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `GOOGLE_TOKEN_FILE` | Gmail/Calendar MCP | Path to stored OAuth token JSON |
| `GOOGLE_CREDENTIALS_PATH` | Google Auth | Path to OAuth client config (embedded in app) |
| `DISCORD_BOT_TOKEN` | Discord MCP | Discord bot authentication token (placeholder) |
| `CANVAS_API_TOKEN` | Canvas MCP | Canvas LMS API token (placeholder) |
| `CANVAS_BASE_URL` | Canvas MCP | Canvas instance URL (placeholder) |
| `XPDITE_USER_DATA_DIR` | Core | Override the default `user_data/` directory path |
