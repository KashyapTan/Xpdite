# Claude.MD - LLM Development Guide

## Project Overview

Electron + React + Python desktop app for AI chat with screenshot and voice capabilities. Key features:
- Ollama LLM integration (default: qwen3-vl:8b-instruct) with streaming and model selection
- **Hybrid LLM Support**: Seamlessly switch between local Ollama models and cloud providers (Anthropic, OpenAI, Gemini)
- Screenshot capture (Alt+. hotkey, fullscreen + precision modes) with vision model processing
- Voice-to-text transcription via faster-whisper
- WebSocket-based bidirectional communication (FastAPI backend)
- REST API for model management and configuration
- SQLite chat history persistence with search
- **Secure Key Management**: Encrypted storage for API keys (Fernet)
- **Google Integration**: OAuth 2.0 flow for Gmail and Calendar access
- **Semantic Tool Retrieval**: Dynamically select relevant MCP tools using vector embeddings (Top-K)
- MCP (Model Context Protocol) tool integration (demo, filesystem, websearch, gmail, calendar, terminal)
- **Integrated Terminal**: LLM-driven command execution with 4-layer security (blocklist, PATH protection, hard timeout, approval prompts)
- Web search and page reading via DuckDuckGo + crawl4ai
- Stop streaming support for interrupting AI responses
- **Customizable System Prompt**: User-editable system prompt with dynamic variable interpolation
- **Skills and Slash Commands**: Dynamic behavioral guidance injected into the system prompt based on active tools or manual slash commands (e.g., `/fs`)

## Architecture

```
Electron (main.ts) -> Window mgmt, Python lifecycle, IPC bridge
    |
    +---> React (src/ui/) -> WebSocket client, REST client, UI rendering
    +---> Python (source/main.py) -> FastAPI WS+REST server, Ollama, MCP
              |
              +---> database.py -> SQLite (conversations, messages, settings)
              +---> ss.py -> Screenshot capture (Alt+., tkinter overlay, DPI-aware)
              +---> transcription.py -> Voice-to-text (faster-whisper, pyaudio)
              +---> MCP servers -> stdio child processes (demo, filesystem, websearch, gmail, calendar, terminal)
              +---> ollama_provider.py -> Local Ollama streaming
              +---> cloud_provider.py -> Cloud LLM streaming with inline tool calling (Claude, GPT, Gemini)
              +---> router.py -> Routes requests to appropriate provider
```

## Tech Stack

**Frontend**: React 19 + TypeScript 5.8 + Vite 6 + React Router 7 + react-markdown + xterm.js
**Backend**: Python 3.13+ + FastAPI + Ollama + Cloud SDKs (Anthropic/OpenAI/Google) + SQLite3 + MCP
**Desktop**: Electron 37+ (frameless, always-on-top, screen-saver level)
**LLM Tools**: MCP SDK, DuckDuckGo Search, crawl4ai, trafilatura
**Voice**: faster-whisper, pyaudio
**Security**: Fernet encryption (cryptography) for API keys, Google OAuth 2.0
**Utils**: pynput (hotkeys), Pillow (images), tkinter (overlays), PyInstaller (bundling), UV (package manager)

## Directory Structure (Essential Paths)

```
src/
  electron/               # main.ts, pythonApi.ts, preload.ts, utils.ts
  ui/
    pages/                 # App.tsx, ChatHistory.tsx, Settings.tsx
    components/            # Layout.tsx, TitleBar.tsx, WebSocketContext.tsx
      chat/                # ChatMessage, ThinkingSection, ToolCallsDisplay, CodeBlock, SlashCommandMenu, LoadingDots
      input/               # QueryInput, ModeSelector, ScreenshotChips, TokenUsagePopup, SlashCommandChips
      settings/            # SettingsModels.tsx, SettingsApiKey.tsx, SettingsConnections.tsx, SettingsTools.tsx, SettingsSystemPrompt.tsx, SettingsSkills.tsx
      terminal/            # TerminalPanel, ApprovalCard, SessionBanner, TerminalCard
    hooks/                 # useChatState, useScreenshots, useTokenUsage
    services/              # api.ts (REST + WS command factory)
    types/                 # index.ts (TypeScript interfaces)
    CSS/                   # Component stylesheets
source/                    # Python backend
  main.py                  # Entry point (services init, Uvicorn, port discovery)
  app.py                   # FastAPI app factory with CORS
  config.py                # Centralized constants (ports, models, limits)
  database.py              # SQLite ops (conversations, messages, settings)
  ss.py                    # Screenshot service (DPI-aware, multi-monitor)
  api/
    websocket.py           # /ws endpoint, message routing
    http.py                # /api/* REST endpoints (health, models, keys, auth)
    handlers.py            # WebSocket message handler logic (MessageHandler class)
  core/
    state.py               # Global mutable state (AppState singleton)
    request_context.py     # Request lifecycle (RequestContext class)
    connection.py          # WebSocket connection registry (ConnectionManager)
    lifecycle.py           # Graceful shutdown & cleanup
    thread_pool.py         # Async execution helper
  services/
    conversations.py       # Chat flow orchestration (submit, resume, clear)
    screenshots.py         # Screenshot lifecycle (capture -> broadcast)
    transcription.py       # Voice-to-text via faster-whisper
    google_auth.py         # Google OAuth 2.0 flow manager
    terminal.py            # Terminal approval flow, session mode, event queuing
    approval_history.py    # Persistent approval memory (exec-approvals.json)
  llm/
    router.py              # Routes requests to Ollama or Cloud providers
    ollama_provider.py     # Ollama streaming bridge
    cloud_provider.py      # Anthropic/OpenAI/Gemini streaming with inline tool calling
    key_manager.py         # Encrypted API key storage
    prompt.py              # Builds the dynamic system prompt with variable interpolation
  mcp_integration/
    manager.py             # MCP server process management + inline tool registration
    retriever.py           # Semantic tool retriever (Top-K selection)
    handlers.py            # Tool call routing loop (up to 30 rounds)
    cloud_tool_handlers.py # Legacy cloud tool handler (superseded by inline tool calling in cloud_provider.py)
    skill_injector.py      # Dynamic skill injection based on tool category
    default_skills.py      # Hardcoded system instructions for default skills
    terminal_executor.py   # Unified terminal tool executor (shared by all providers)
mcp_servers/
  client/                  # ollama_bridge.py (standalone bridge for testing)
  config/                  # servers.json (server registry)
  servers/
    demo/                  # Calculator (add, divide)
    filesystem/            # File ops (list, read, write, create, move, rename)
    websearch/             # Web search (search_web_pages, read_website)
    terminal/              # Terminal tools (run_command, get_environment, find_files, session mode)
    gmail/                 # Gmail tools (search, read, send, reply, labels)
    calendar/              # Calendar tools (events, free/busy)
    discord/               # Placeholder
    canvas/                # Placeholder
docs/                      # Production documentation
  architecture.md          # System architecture overview
  getting-started.md       # Setup and installation guide
  development.md           # Developer guide
  api-reference.md         # WebSocket & REST API reference
  mcp-guide.md             # MCP integration guide
  configuration.md         # Configuration reference
  contributing.md          # Contributing guidelines
dist-electron/             # Compiled TS -> JS
dist-react/                # Built React app
dist-python/               # PyInstaller output (main.exe)
user_data/                 # Persistent app data (DB, screenshots)
```

## Key Files & Implementation Details

### `source/main.py` (188 lines)
**Backend Entry Point**

- `find_available_port(start_port, max_attempts)`: Probes ports 8000-8009
- `start_server()`: Initializes asyncio loop, starts MCP servers, runs Uvicorn
- `start_screenshot_service()`: Starts `ScreenshotService` in daemon thread
- `start_transcription_service()`: Initializes Whisper transcription
- `main()`: Registers signal handlers, starts all threads, keeps process alive
- Stores asyncio loop in `app_state.server_loop_holder` for cross-thread scheduling

### `source/config.py` (30 lines)
**Centralized Configuration**
- `PROJECT_ROOT`: Auto-detected project root
- `SCREENSHOT_FOLDER`: `user_data/screenshots`
- `DEFAULT_PORT`: 8000
- `DEFAULT_MODEL`: `qwen3-vl:8b-instruct`
- `MAX_MCP_TOOL_ROUNDS`: 30
- `CaptureMode` enum: fullscreen, precision, none

### `source/app.py` (45 lines)
**FastAPI App Factory**
- `create_app() -> FastAPI`: Sets up CORS (all origins for dev), mounts `/ws` and `/api` routes

### `source/api/websocket.py` (86 lines)
**WebSocket Endpoint**
- On connect: sends `ready` message + active screenshots
- Routes all incoming message types to `MessageHandler`
- Supported types: `submit_query`, `clear_context`, `remove_screenshot`, `set_capture_mode`, `stop_streaming`, `get_conversations`, `load_conversation`, `delete_conversation`, `search_conversations`, `resume_conversation`, `stop_recording`

### `source/api/handlers.py` (156 lines)
**Message Handler Logic**
- `_handle_submit_query`: Extracts slash commands, updates `app_state.selected_model`, launches `ConversationService.submit_query`
- `_handle_stop_recording`: Uses `asyncio.to_thread` for transcription
- `_handle_get_skills`, `_handle_upsert_skill`, `_handle_delete_skill`, `_handle_reset_skill`: CRUD operations for user skills
- All handlers use `ConnectionManager.broadcast_json()` for responses

### `source/api/http.py` (528 lines)
**REST API Endpoints**
- `GET /api/health`: Health check
- `GET /api/models/ollama`: Lists locally installed Ollama models
- `GET /api/models/anthropic|openai|gemini`: Lists cloud provider models (requires key)
- `GET /api/models/enabled`: Fetches enabled models
- `PUT /api/models/enabled`: Updates enabled models
- `GET /api/keys`: Gets API key status (masked)
- `PUT /api/keys/{provider}`: Saves encrypted API key
- `GET /api/google/status`: Checks OAuth connection
- `POST /api/google/connect`: Initiates OAuth flow
- `GET /api/settings/system-prompt`: Fetches custom system prompt template
- `PUT /api/settings/system-prompt`: Updates custom system prompt template
- `GET /api/skills`: Lists all skills (default + custom)
- `POST /api/skills`: Creates/updates a skill
- `DELETE /api/skills/{skill_name}`: Deletes a custom skill
- `POST /api/skills/{skill_name}/reset`: Resets default skill content

### `source/database.py` (367 lines)
**SQLite Operations with Thread Safety**

Critical patterns:
- `check_same_thread=False` enables FastAPI thread pool access
- JSON serialization for image arrays and settings
- `settings` table for key-value storage (e.g., enabled models)
- `model` column in messages table tracks which model generated each response

Tables:
- `conversations`: id (UUID), title, created_at, updated_at, total_input_tokens, total_output_tokens
- `messages`: num_messages (PK), conversation_id (FK), role, content, images (JSON), model, created_at
- `settings`: key (PK), value
- `skills`: skill_name (PK), display_name, slash_command, content, is_default, is_modified, enabled, created_at, updated_at

Key functions:
- `start_new_conversation(title)`, `add_message(...)`, `get_recent_conversations(limit, offset)`
- `get_full_conversation(id)`, `add_token_usage(...)`, `get_token_usage(...)`
- `get_enabled_models()`, `set_enabled_models(...)`
- `get_system_prompt_template()`, `set_system_prompt_template(...)`

### `source/core/state.py` (90 lines)
**Global Mutable State**
- `AppState` class (singleton):
  - `screenshot_list`: Active screenshots in context
  - `current_request`: Active `RequestContext` (replaces raw `is_streaming`/`stop_streaming`)
  - `_request_lock`: Async lock for request lifecycle transitions
  - `is_streaming` / `stop_streaming`: Legacy flags kept for backward compat
  - `capture_mode`: Current screenshot behavior (CaptureMode enum)
  - `chat_history`: In-memory multi-turn conversation history
  - `server_loop_holder`: Stores main asyncio loop for thread-safe scheduling
  - `selected_model`: Currently selected Ollama model

### `source/core/request_context.py`
**Request Lifecycle**
- `RequestContext` class: replaces `stream_lock + is_streaming + stop_streaming` with a single lifecycle object
- `cancel()`: Signal cancellation from the handler layer
- `mark_done()`: Called in the `finally` block of `submit_query`
- `on_cancel(callback)`: Register cleanup callbacks (e.g. terminal kill)
- `is_done` / `is_cancelled` properties for status checks

### `source/core/connection.py` (64 lines)
**WebSocket Connection Registry**
- `ConnectionManager` class: tracks active WebSocket connections
- `broadcast(message)`, `broadcast_json(type, content)`: Send to all clients

### `source/core/lifecycle.py` (97 lines)
**Shutdown & Cleanup**
- Cleans up MCP server subprocesses
- Stops screenshot hotkey listener
- Clears temporary screenshot folder

### `source/ss.py` (484 lines)
**Screenshot Service with Hotkey and Overlay**

Components:
1. `ScreenshotService`: Global hotkey listener (Alt+.)
   - Thread-safe with `_lock` (prevents concurrent captures)
   - Callbacks: `start_callback` (on capture begin), `callback` (on complete)
   - Runs in dedicated background thread
2. `RegionSelector`: Tkinter fullscreen overlay
   - Click-drag rectangle selection
   - DPI-aware coordinate transformation (Windows ctypes)
   - ESC to cancel
3. Helper functions: `take_fullscreen_screenshot()`, `take_region_screenshot()`, `create_thumbnail()`, `copy_image_to_clipboard()`

**Critical**: DPI scaling on Windows requires coordinate transformation for multi-monitor setups. Extensive Windows ctypes code handles DPI awareness.

### `source/services/conversations.py` (190 lines)
**Conversation Logic**
- `submit_query`: Handles user input, image processing, auto-screenshot, Ollama streaming, persistence, token tracking. **Now incorporates skill injection** via `skill_injector`.
- Creates a `RequestContext` for lifecycle management; auto-expires terminal session mode in `finally`
- `resume_conversation`: Reconstructs chat state from DB, regenerates thumbnails, restores token counts
- `clear_context`: Resets state for new chat, clears screenshots
- Post-response: broadcasts `conversation_saved`, `tool_calls_summary`, clears used screenshots

### `source/services/transcription.py` (136 lines)
**Voice-to-Text Service**
- `TranscriptionService` class: uses `faster-whisper` with `base.en` model
- Records 16kHz mono audio via `pyaudio` into a queue
- Transcribes on stop, broadcasts result via WebSocket

### `source/llm/ollama_provider.py` (333 lines)
**Ollama Streaming Bridge**
- Producer-consumer pattern: background thread runs Ollama generator, main thread consumes via asyncio queue
- Separates `thinking` tokens from `content` tokens (Qwen-style reasoning support)
- Fallback: if stream is empty (tool-calling edge case), performs non-streamed `chat` call
- Handles "unexpected" tool calls that appear mid-text-stream
- Broadcasts `thinking_chunk`, `response_chunk`, and completion messages
- Handles `pre_computed_response` with `already_streamed: True` — when the MCP tool loop has already streamed content (interleaved tool calls), skips re-broadcasting the final response

### `source/llm/prompt.py`
**System Prompt Builder**
- `build_system_prompt(...)`: Assembles the LLM system prompt with dynamic interpolations (time, os, user custom template)

### `source/mcp_integration/manager.py` (192 lines)
**MCP Server Manager**
- `McpToolManager`: Launches MCP servers as subprocesses via stdio transport
- `register_inline_tools(server_name, tools)`: Registers tool schemas without spawning a subprocess (used for terminal tools)
- Discovers tools via JSON-RPC handshake
- Converts JSON Schema to Ollama, Anthropic, OpenAI, and Gemini function-calling formats
- Routes tool calls to correct server process
- Active servers on startup: filesystem, websearch (terminal tools registered inline)
- **Background Task Lifecycle**: Each MCP connection is held open by a dedicated asyncio Task (instead of direct `__aenter__`/`__aexit__` calls), preventing anyio "cancel scope in a different task" `RuntimeError` during shutdown

### `source/mcp_integration/handlers.py`
**Ollama Tool Call Loop with Interleaved Streaming**
- `retrieve_relevant_tools(user_query)`: Shared helper that selects the top-K semantically relevant tools; used by both the Ollama and cloud provider paths via `router.py`
- **Phase 1** (detection): Non-streamed call with `think=False` to detect tool requests (workaround for Ollama bug #10976: `think+tools=empty output`)
- **Phase 2** (streaming loop): After tools are detected, `_stream_tool_follow_up()` streams follow-up responses in real-time — the model's intermediate text ("Let me search for that…") appears to the user between tool executions
- `_stream_tool_follow_up(messages, tools, loop)`: Runs Ollama's streaming generator in a background thread, broadcasts text chunks via `safe_schedule`, collects further tool calls for the next round
- Returns `pre_computed_response = {"already_streamed": True, ...}` when tools were used, so `ollama_provider.py` skips re-broadcasting the response
- **Includes images in tool detection calls** so the model can analyze image content (e.g. extract URLs from screenshots) when deciding which tools to call
- Broadcasts `tool_call` and `tool_result` messages to frontend
- **Terminal interception**: `run_command` routed through approval flow, `request_session_mode`/`end_session_mode` handled inline
- Defers terminal event DB saves when `conversation_id` is None (first message); flushed after conversation creation

### `source/mcp_integration/terminal_executor.py`
**Unified Terminal Tool Executor**
- Single source of truth for ALL terminal tool execution (run_command, send_input, read_output, kill_process, get_environment, find_files, request_session_mode, end_session_mode)
- Used by `handlers.py` (Ollama) and directly within `cloud_provider.py` (cloud providers)
- Handles approval flow, PTY execution, notice task lifecycle (try/finally), and DB persistence
- `_save_terminal_event()`: Defers DB writes when conversation_id is not yet assigned

### `source/services/terminal.py`
**Terminal Approval & Session Management**
- `TerminalService` singleton: manages approval flow, session mode, running command tracking
- `check_approval(command, cwd)`: checks ask level (always/on-miss/off), blocks via `asyncio.Event` for user response
- `resolve_approval(request_id, approved, remember)`: unblocks pending approval
- `request_session(reason)` / `resolve_session(approved)`: session mode negotiation
- `end_session()`: ends active session, broadcasts `terminal_session_ended`
- `track_running_command()` / `check_running_notices()`: 10s running notice timer
- `broadcast_output()` / `broadcast_complete()`: forward command results to xterm panel
- `queue_terminal_event()` / `flush_pending_events()`: deferred DB saves for pre-conversation events
- `reset()`: clears state on context clear

### `source/services/approval_history.py`
**Persistent Approval Memory**
- Stores approved command signatures in `user_data/exec-approvals.json`
- `is_command_approved(command)`: checks if normalized command was previously approved
- `remember_approval(command)`: saves SHA256 hash of normalized command
- `_normalize_command()`: extracts base command (program + first 2 args) for fuzzy matching

### `source/api/terminal.py`
**Terminal REST API**
- `GET /api/terminal/settings`: returns ask_level, session_mode, approval_count
- `PUT /api/terminal/settings/ask-level`: updates approval prompt level
- `DELETE /api/terminal/approvals`: clears all remembered approvals

### `src/electron/main.ts` (148 lines)
**Electron Main Process**

Window config:
- 450x450 normal, 52x52 mini
- `frame: false`, `transparent: true`, `alwaysOnTop: true`, `level: 'screen-saver'`
- `skipTaskbar: true`, `setContentProtection(true)`

IPC handlers:
- `set-mini-mode`: Resizes window, repositions to top-right of previous bounds
- `focus-window`: Brings to foreground

**Python lifecycle** (prod only):
- Starts Python server on `app.whenReady()`
- Stops on `app.quit()`
- Dev mode skips (dev:pyserver script handles it)

### `src/electron/pythonApi.ts` (341 lines)
**Python Process Management**
- `startPythonServer()`: Finds available port, spawns Python/exe
- `stopPythonServer()`: Kills process and orphans
- `getServerPort()`: Returns discovered port
- Aggressive cleanup of stale processes on target ports
- Startup verification via stdout monitoring + health check

### `src/ui/pages/App.tsx` (588 lines)
**Main Chat Interface**
- **Architecture**: Modular composition using custom hooks and components
- **State**: `useChatState` (chat logic), `useScreenshots` (images), `useTokenUsage` (stats)
- **Local state**: `selectedModel`, `enabledModels`, `isRecording`
- **WebSocket handling**: thinking_chunk, response_chunk, tool_call, tool_result, conversation_resumed, screenshot_start/ready, transcription_result
- **Rendering**: Delegates to `ResponseArea` (chat history) and `QueryInput` (user interaction)

### `src/ui/pages/ChatHistory.tsx` (202 lines)
**Conversation Browser**
- WebSocket-based conversation fetching (`get_conversations`)
- Debounced search (`search_conversations`)
- Groups chats by "Today", "Yesterday", or specific dates
- Resume conversation on click

### `src/ui/pages/Settings.tsx` (85 lines)
**Tabbed Settings Interface**
- Implements Models, Connections, Tools, and Prompt tabs
- Extensible for future settings categories

### `src/ui/components/settings/SettingsModels.tsx` (166 lines)
**Model Management UI**
- Fetches installed models via `GET /api/models/ollama`
- Fetches enabled models via `GET /api/models/enabled`
- Toggle switches to enable/disable models via `PUT /api/models/enabled`

### `src/ui/components/settings/SettingsApiKey.tsx` (157 lines)
**API Key Management**
- Secure input for Anthropic, OpenAI, and Gemini keys
- Shows validation state and masked keys
- Communicates with `PUT /api/keys/{provider}`

### `src/ui/components/settings/SettingsConnections.tsx` (152 lines)
**Google Integration**
- Connect/Disconnect Google account
- Visual status of Gmail/Calendar access
- Handles OAuth flow via `POST /api/google/connect`

### `src/ui/components/settings/SettingsTools.tsx` (173 lines)
**Tool Retrieval UI**
- Configure Top-K dynamic tool selection
- Toggle "Always On" tools for MCP servers
- Communicates with `GET/PUT /api/settings/tools`

### `src/ui/components/settings/SettingsSystemPrompt.tsx`
**System Prompt UI**
- Allows user to set a custom system prompt template
- Provides variables to interpolate (`{{current_datetime}}`, etc.)
- Communicates with `GET/PUT /api/settings/system-prompt`

### `src/ui/hooks/`
- **`useChatState.ts`**: Core chat logic. Manages `chatHistory` array, streaming buffers (thinking, response), `toolCalls`, status, and refs.
- **`useScreenshots.ts`**: Manages screenshot carousel, `captureMode`, and `screenshotsRef`.
- **`useTokenUsage.ts`**: Tracks cumulative token usage (input, output, total, limit).

### `src/ui/services/api.ts` (191 lines)
**API Client**
- Singleton `api` object with REST fetch wrappers (`getOllamaModels`, `getEnabledModels`, `setEnabledModels`, `getSystemPrompt`, `setSystemPrompt`)
- `createApiService()`: Factory for WS-based commands (`submitQuery`, `clearContext`, etc.)

### `src/ui/types/index.ts` (134 lines)
**TypeScript Interfaces**
- `ChatMessage`, `ToolCall`, `Screenshot`, `TokenUsage`, `WebSocketMessage`
- Global `Window` interface for `electronAPI`

### `src/ui/components/chat/`
- **`ChatMessage.tsx`**: Individual message rendering with markdown
- **`ThinkingSection.tsx`**: Collapsible reasoning display
- **`ToolCallsDisplay.tsx`**: MCP tool execution cards with human-readable labels and collapsible results
- **`CodeBlock.tsx`**: Syntax-highlighted code blocks

### `src/ui/components/input/`
- **`QueryInput.tsx`**: User input with screenshot attachments
- **`ModeSelector.tsx`**: Screenshot capture mode selector
- **`ScreenshotChips.tsx`**: Screenshot thumbnail chips with remove
- **`TokenUsagePopup.tsx`**: Context window usage indicator

### MCP Servers

#### `mcp_servers/servers/demo/server.py` (67 lines)
**Reference implementation**: `add(a, b)`, `divide(a, b)`

#### `mcp_servers/servers/filesystem/server.py` (255 lines)
**File system tools** with path-traversal protection:
- `list_directory`, `read_file`, `write_file`, `create_folder`, `move_file`, `rename_file`
- `_get_safe_path()`: Validates paths against `BASE_PATH`

#### `mcp_servers/servers/websearch/server.py` (145 lines)
**Web search + page reading**:
- `search_web_pages(query)`: DuckDuckGo search returning URLs + snippets
- `read_website(url)`: Async crawl4ai with stealth mode (rotating UAs, noise reduction, randomized timing)
- Falls back to trafilatura for content extraction

#### `mcp_servers/servers/terminal/server.py`
**Terminal command execution** (reference only — NOT spawned as subprocess):
- All terminal tools are registered inline via `register_inline_tools()` and intercepted at the handler layer
- The MCP server file exists for reference and standalone testing but is never connected in production
- `run_command(command, cwd, timeout)`: Executes via subprocess.run with blocklist check, PATH injection protection, 120s hard timeout cap
- `get_environment()`: Returns OS, shell, cwd, and installed tool versions
- `find_files(pattern, directory)`: Glob-based file search
- `request_session_mode(reason)` / `end_session_mode()`: Session mode lifecycle (auto-expires after each turn)
- Captures `_ORIGINAL_PATH` at startup to prevent PATH injection

#### `mcp_servers/servers/terminal/blocklist.py`
**Defense-in-depth command filtering**:
- `check_blocklist(command)`: Blocks destructive commands (format, mkfs, dd, reg delete, rm -rf /, rd /s /q C:\Windows)
- `check_path_injection(env)`: Detects PATH manipulation via suspicious additions
- OS-specific path protection (System32, /etc/shadow, ~/.ssh, etc.)

#### `mcp_servers/servers/gmail/server.py` (523 lines)
**Gmail Integration**:
- Search, read, send, reply, trash, labels, drafts
- Requires Google Auth (token injected via env)

#### `mcp_servers/servers/calendar/server.py` (470 lines)
**Google Calendar Integration**:
- Events (list, search, create, update, delete)
- Free/busy check, quick add
- Requires Google Auth

#### Placeholder servers: `discord/`, `canvas/` (skeleton files)

## Development Commands

```bash
npm run dev                # Full dev mode (all services in parallel)
npm run dev:react          # Vite dev server (port 5123)
npm run dev:electron       # Electron app
npm run dev:pyserver       # Python FastAPI (via uv run)
npm run build              # Full build (Python exe + React + Electron)
npm run dist:win           # Windows installer (NSIS + portable)
npm run install:python     # Install Python deps via UV
uv sync --group dev        # Install all Python deps (fast!)
uv add <package>           # Add a new Python dependency
```

## MCP (Model Context Protocol) Integration

**Purpose**: Give LLM access to external tools via stdio child processes (JSON-RPC).

### How Tool Calls Work

**Ollama models:**
1. User query -> Phase 1: non-streamed call (`think=False`) to detect tool requests
2. If tool calls detected: execute via `McpToolManager`, broadcast `tool_call`/`tool_result` to frontend
3. Phase 2: follow-up response is **streamed in real-time** — the model's commentary appears live between tool rounds
4. Loop continues (up to 30 rounds); `pre_computed_response = {already_streamed: True}` signals completion
5. Images are included in detection calls so the model can analyze visual content when picking tools

**Cloud models (Anthropic / OpenAI / Gemini):**
1. `router.py` calls `retrieve_relevant_tools()` to select relevant tool names for the query
2. `stream_cloud_chat()` is called with `allowed_tool_names` — tools are handled **inline during streaming**
3. Text is broadcast in real-time; when a tool call appears, it is executed and results fed back immediately
4. Loop continues (up to 30 rounds) until the model produces a response with no tool calls
5. The user sees the entire process (text → tool → text → tool → text) as one interleaved flow

### Adding New MCP Tools (3 Steps)

**Step 1**: Create `mcp_servers/servers/<name>/server.py`
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ToolName")

@mcp.tool()
def function_name(param: str) -> str:
    """LLM-visible description of when to use this tool."""
    return f"Result: {param}"

if __name__ == "__main__":
    mcp.run()
```

**Step 2**: Register in `source/main.py` -> `_init_mcp_servers()`
```python
await _mcp_manager.connect_server(
    "tool_name",
    sys.executable,
    [str(PROJECT_ROOT / "mcp_servers" / "servers" / "tool_name" / "server.py")]
)
```

**Step 3**: Add to `mcp_servers/config/servers.json` and restart app

### Current Servers
- **demo**: add, divide (reference implementation)
- **filesystem**: list_directory, read_file, write_file, create_folder, move_file, rename_file
- **websearch**: search_web_pages, read_website
- **terminal**: run_command, get_environment, find_files, request_session_mode, end_session_mode
- Placeholders: gmail, calendar, discord, canvas

### Debugging
- Check `[MCP]` logs in console for server registration
- Test standalone: `python -m mcp_servers.servers.demo.server`
- Tool calls show as cards in UI with arguments, results, and server name

## WebSocket Protocol

The WebSocket connection at `ws://localhost:8000/ws` uses JSON messages with `type` and `content` fields.

### Client -> Server Messages

```json
{"type": "submit_query", "content": "Your question", "model": "qwen3-vl:8b-instruct"}
{"type": "clear_context"}
{"type": "stop_streaming"}
{"type": "set_capture_mode", "mode": "fullscreen | precision | none"}
{"type": "remove_screenshot", "screenshot_id": "ss_1"}
{"type": "get_conversations", "limit": 50, "offset": 0}
{"type": "load_conversation", "conversation_id": "uuid-string"}
{"type": "resume_conversation", "conversation_id": "uuid-string"}
{"type": "search_conversations", "query": "search terms"}
{"type": "delete_conversation", "conversation_id": "uuid-string"}
{"type": "stop_recording"}
{"type": "terminal_approval_response", "request_id": "...", "approved": true, "remember": false}
{"type": "terminal_session_response", "approved": true}
{"type": "terminal_stop_session"}
{"type": "terminal_set_ask_level", "level": "always | on-miss | off"}
```

### Server -> Client Messages

```json
{"type": "ready", "content": "Server ready..."}
{"type": "screenshot_start", "content": "Screenshot capture starting"}
{"type": "screenshot_added", "content": "{\"id\": \"ss_1\", \"name\": \"...\", \"thumbnail\": \"data:image/png;base64,...\"}"}
{"type": "screenshot_removed", "content": "{\"id\": \"ss_1\"}"}
{"type": "screenshots_cleared", "content": ""}
{"type": "query", "content": "User's question"}
{"type": "thinking_chunk", "content": "...partial thinking..."}
{"type": "thinking_complete", "content": ""}
{"type": "response_chunk", "content": "...partial response..."}
{"type": "response_complete", "content": ""}
{"type": "tool_call", "content": "{\"name\": \"...\", \"arguments\": {...}, \"server\": \"...\"}"}
{"type": "tool_result", "content": "{\"name\": \"...\", \"result\": \"...\", \"server\": \"...\"}"}
{"type": "tool_calls_summary", "content": "[...]"}
{"type": "context_cleared", "content": "Context cleared..."}
{"type": "conversation_saved", "content": "{\"conversation_id\": \"uuid\"}"}
{"type": "conversations_list", "content": "[...]"}
{"type": "conversation_loaded", "content": "{...}"}
{"type": "conversation_resumed", "content": "{...}"}
{"type": "conversation_deleted", "content": "{\"conversation_id\": \"uuid\"}"}
{"type": "token_update", "content": "{\"input\": 123, \"output\": 456, \"total\": 579}"}
{"type": "transcription_result", "content": "Transcribed text"}
{"type": "error", "content": "Error message"}
{"type": "terminal_approval_request", "content": "{\"request_id\": \"...\", \"command\": \"...\", \"cwd\": \"...\"}"}
{"type": "terminal_session_request", "content": "{\"reason\": \"...\"}"}
{"type": "terminal_session_started", "content": ""}
{"type": "terminal_session_ended", "content": ""}
{"type": "terminal_output", "content": "{\"request_id\": \"...\", \"output\": \"...\"}"}
{"type": "terminal_command_complete", "content": "{\"request_id\": \"...\", \"exit_code\": 0, \"duration_ms\": 1234}"}
{"type": "terminal_running_notice", "content": "{\"request_id\": \"...\", \"command\": \"...\", \"elapsed_seconds\": 15}"}
```

## Database Schema

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,              -- UUID
    title TEXT,                       -- Auto-generated from first message
    created_at REAL,
    updated_at REAL,                  -- Updated on every new message
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0
);

CREATE TABLE messages (
    num_messages INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,             -- FK to conversations.id
    role TEXT,                        -- 'user' or 'assistant'
    content TEXT,                     -- Message text
    images TEXT,                      -- JSON array of base64 strings
    model TEXT,                       -- Model used for this response
    created_at REAL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT                        -- JSON-serialized value
);

CREATE TABLE terminal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,             -- FK to conversations.id
    message_index INTEGER,            -- Position in chat_history
    command TEXT,                      -- Executed command
    exit_code INTEGER,                -- Process exit code (-1 if denied)
    output TEXT,                      -- First 50KB of output
    cwd TEXT,                         -- Working directory
    duration_ms INTEGER DEFAULT 0,    -- Execution time
    pty INTEGER DEFAULT 0,            -- Reserved for Phase 2
    background INTEGER DEFAULT 0,     -- Reserved for Phase 2
    timed_out INTEGER DEFAULT 0,      -- Whether command hit timeout
    denied INTEGER DEFAULT 0,         -- Whether user denied command
    created_at REAL                   -- Timestamp
);
```

## Common Development Tasks

### Add New UI Page
1. Create `src/ui/pages/<PageName>.tsx`
2. Add route in `src/ui/main.tsx` using `createHashRouter`
3. Add CSS in `src/ui/CSS/<PageName>.css`

### Add New WebSocket Message Type
1. Backend: Add handler method in `source/api/handlers.py` (MessageHandler class)
2. Backend: Add routing case in `source/api/websocket.py`
3. Frontend: Add case in `App.tsx` WebSocket message handler

### Add New REST Endpoint
1. Backend: Add route in `source/api/http.py`
2. Frontend: Add client method in `src/ui/services/api.ts`

### Add New MCP Tool
See MCP section above and `docs/mcp-guide.md`.

### Modify Database Schema
1. Edit `_init_db()` in database.py
2. Add migration: `try: cursor.execute("ALTER TABLE...") except sqlite3.OperationalError: pass`
3. Update read/write methods
4. Update `src/ui/types/index.ts` if frontend is affected

### Change Ollama Model
1. `ollama pull model-name`
2. Update `DEFAULT_MODEL` in `source/config.py`
3. Verify tool support (not all models support function calling)
4. Test with images if using a vision model

## Architecture Decisions (Critical for LLMs)

**Why `check_same_thread=False` in SQLite?**
FastAPI uses thread pools; SQLite needs multi-thread access.

**Why refs in React hooks?**
WebSocket callbacks capture stale state; refs ensure current values in async operations.

**Why `server_loop_holder`?**
Windows Proactor loop can't be accessed from other threads; we schedule coroutines via `asyncio.run_coroutine_threadsafe()`.

**Why stdio transport for MCP?**
Standard MCP protocol; enables child process isolation and language-agnostic servers.

**Why PyInstaller?**
Bundles Python + deps into single exe for production distribution.

**Why Electron `screen-saver` level?**
Ensures always-on-top even above full-screen apps.

**Why DPI scaling in ss.py?**
Windows multi-monitor setups require coordinate transformation via ctypes for accurate region selection.

**Why include images in tool detection calls?**
The model needs to see image content to make informed tool-calling decisions. For example, if a user sends a screenshot of a URL and asks "read this", the model must see the image to extract the URL and call `read_website`. The non-streamed tool detection call includes images alongside tool definitions, and `think=False` keeps the call fast.

**Why producer-consumer pattern in ollama_provider.py?**
Ollama's synchronous generator runs in a background thread; the main async thread consumes chunks via an asyncio queue for non-blocking streaming.

**Why non-streamed initial call for tool detection?**
Streaming responses can't reliably indicate tool calls (Ollama bug #10976: `think+tools=empty output`); a quick non-streamed Phase 1 check determines if tools are needed. Once detected, Phase 2 follow-up calls are fully **streamed** so the user sees the model's intermediate reasoning in real-time. For cloud providers, tool calls are handled entirely inline during streaming — no separate detection phase is needed.

**Why does terminal approval live in the FastAPI process, not the MCP server?**
asyncio.Event can't cross process boundaries. The MCP terminal server runs as a stdio child process, so approval blocking must happen in the parent FastAPI process. The MCP server provides defense-in-depth via blocklist only.

**Why 4 security layers for terminal?**
Layer 1 (invisible): OS path blocklist in MCP server. Layer 2 (invisible): PATH injection protection. Layer 3 (invisible): 120s hard timeout ceiling. Layer 4 (visible): User-facing approval prompts with configurable ask level. Invisible layers are never shown to the user or LLM to prevent social engineering around them.

**Why inline registration for terminal tools instead of an MCP subprocess?**
Every terminal tool call was intercepted at the handler layer before reaching the MCP server — the subprocess was a "ghost process" doing nothing. `register_inline_tools()` registers tool schemas directly in the manager without spawning a child process, saving memory and startup time. The MCP server file stays for reference/standalone testing.

**Why RequestContext instead of raw flags?**
A single `RequestContext` object replaces scattered `stream_lock + is_streaming + stop_streaming` flags with a proper lifecycle: `cancel()`, `mark_done()`, `on_cancel(callback)`. This prevents state inconsistencies and makes cleanup deterministic (e.g. terminal kill on cancellation).

**Why auto-expire session mode?**
LLMs reliably request session mode but almost never call `end_session_mode` to release it. Auto-expiring in the `finally` block of `submit_query` guarantees cleanup without depending on LLM behavior. The explicit tool still works for early opt-out.

**Why a unified terminal executor?**
Both `handlers.py` (Ollama) and `cloud_provider.py` (cloud providers, handling tools inline) need identical terminal logic — approval, PTY execution, notice tasks, DB persistence. `terminal_executor.py` is the single source of truth, called from both the Ollama streaming loop and the inline cloud provider streaming loops.

**Why inline tool calling for cloud providers instead of a separate detection phase?**
The old approach ran a silent pre-streaming `handle_cloud_tool_calls()` phase, then streamed the response separately. This produced a delay with no user feedback, and tool context was injected as an awkward "system summary" message rather than proper API tool-result messages. Moving tool execution inline gives the user full visibility — text, tool calls, and results appear as one interleaved stream using each SDK's native tool-calling format (`tools=` for Anthropic/OpenAI, `function_declarations` for Gemini).

**Why a background asyncio Task for MCP server lifecycle in manager.py?**
The `stdio_client` and `ClientSession` context managers must be exited in the **same asyncio Task** that entered them (anyio requirement). The previous approach called `__aenter__`/`__aexit__` from different tasks, causing a "cancel scope in a different task" `RuntimeError` during shutdown. A dedicated background Task holds both context managers open indefinitely, and a `shutdown_event` signals it to exit cleanly.

---

*Last updated: February 21 2026 | Version: 0.3.0*
