# Architecture

This document provides a detailed overview of the Xpdite system architecture, covering the three main layers (Electron, React, Python) and how they communicate.

## High-Level Overview

Xpdite is a desktop application built on three independent layers that communicate through well-defined interfaces:

```
+---------------------------+
|        Electron           |  Window management, Python lifecycle, IPC bridge
|     (src/electron/)       |
+---------------------------+
          |          |
          v          v
+-------------+  +------------------+
|   React UI  |  |  Python Backend  |
| (src/ui/)   |  |  (source/)       |
+-------------+  +------------------+
     |  WebSocket (ws://localhost:8000/ws)  |
     +<----------------------------------->+
                                |
                    +-----------+-----------+
                    |           |           |
                    v           v           v
                 LLMs       SQLite      MCP Servers
            (Ollama/Cloud)    (DB)      (child processes)
                                        (Terminal handled inline)
```

## Layer Details

### 1. Electron Layer (`src/electron/`)

The Electron layer manages the desktop application shell:

| File | Responsibility |
|------|---------------|
| `main.ts` | Window creation, IPC handlers, Python server lifecycle |
| `preload.ts` | Secure bridge exposing `electronAPI` to the renderer |
| `pythonApi.ts` | Python process management (start, stop, port discovery, cleanup) |
| `pcResources.ts` | Resource path resolution for production builds |
| `utils.ts` | Environment detection (`isDev()`) |

**Window Configuration:**
- Frameless, transparent window (`frame: false`, `transparent: true`)
- Always-on-top at `screen-saver` level (stays above full-screen apps)
- Content protection enabled (`setContentProtection(true)`) - prevents screen recording
- Normal mode: 550×550 | Mini mode: 52×52
- `skipTaskbar: true` for minimal desktop footprint
- `setDisplayMediaRequestHandler` auto-approves WASAPI loopback for meeting audio

**IPC Channels:**
- `set-mini-mode` - Toggles between normal and mini window sizes
- `set-hidden` - Hides window content (opacity: 0) during screenshot capture
- `get-python-port` - Returns the Python backend port (production only)

**Python Lifecycle (Production):**
1. On `app.whenReady()`, spawns the bundled Python executable
2. Monitors stdout for "Application startup complete"
3. Performs health check on the discovered port
4. On `app.quit()`, terminates the Python process and cleans up orphaned processes

### 2. React Frontend (`src/ui/`)

The frontend follows a modular architecture with custom hooks for state management:

```
src/ui/
  main.tsx                    # createHashRouter setup (/, /settings, /history, /album, /recorder, /recording/:id)
  pages/
    App.tsx                   # Main chat interface — tab routing, WS dispatch, retry/edit
    ChatHistory.tsx           # Conversation browser with full-text search
    Settings.tsx              # Tabbed settings (models, connections, tools, skills, meeting, system-prompt)
    MeetingRecorder.tsx       # Live meeting recording UI
    MeetingAlbum.tsx          # Past recordings list (grouped by date)
    MeetingRecordingDetail.tsx# Recording detail + AI analysis + calendar/email action execution
  components/
    Layout.tsx                # App shell; manages mini/hidden state via Outlet context
    TitleBar.tsx              # Custom title bar: new-chat button, nav icons, mini-mode toggle
    TabBar.tsx                # Multi-tab strip (hidden when 1 tab open)
    chat/
      ChatMessage.tsx         # Message with inline edit, retry, response version navigation
      ThinkingSection.tsx     # Collapsible reasoning/thinking display
      ToolCallsDisplay.tsx    # ToolChainTimeline (primary) + legacy flat view
      InlineTerminalBlock.tsx # Inline xterm.js PTY / ansi-to-html terminal in chat flow
      CodeBlock.tsx           # Syntax-highlighted code blocks
      ResponseArea.tsx        # Scrollable message list (dynamic topInset/bottomInset)
      SlashCommandMenu.tsx    # Skill autocomplete menu used by QueryInput
      LoadingDots.tsx         # Typing indicator
    input/
      QueryInput.tsx          # Chip-aware contentEditable div with slash command chips
      ModeSelector.tsx        # Screenshot mode selector (precision / fullscreen / meeting)
      ScreenshotChips.tsx     # Screenshot thumbnail chips
      QueueDropdown.tsx       # Per-tab conversation queue display
      TokenUsagePopup.tsx     # Context window usage indicator
    settings/
      SettingsModels.tsx      # Ollama + cloud model enable/disable toggles
      SettingsApiKey.tsx      # API key management (Anthropic/OpenAI/Gemini)
      SettingsConnections.tsx # Google OAuth connection (Gmail + Calendar)
      SettingsTools.tsx       # Semantic tool retrieval config (topK, always-on)
      SettingsSystemPrompt.tsx# Custom system prompt template editor
      SettingsSkills.tsx      # Full CRUD for user skills and builtin overrides
      MeetingRecorderSettings.tsx # Whisper model, diarization, audio retention
    terminal/
      InlineTerminalBlock.tsx # (also under chat/) — approval, PTY, ansi output
      TerminalCard.tsx        # Past terminal event in chat history
      ApprovalCard.tsx        # Legacy standalone approval prompt
      SessionBanner.tsx       # Autonomous session status
  hooks/
    useChatState.ts           # Chat history, streaming, terminal block management
    useScreenshots.ts         # Screenshot context + meetingRecordingMode flag
    useTokenUsage.ts          # Token tracking
    useAudioCapture.ts        # System audio capture (WASAPI loopback + mic mix)
  services/
    api.ts                    # REST API client (18+ endpoints) + WS command factory
    portDiscovery.ts          # Concurrent port probe (8000-8009)
  types/
    index.ts                  # TypeScript interfaces (ChatMessage, ContentBlock, TerminalCommandBlock, TabSnapshot, ResponseVariant…)
  contexts/
    WebSocketContext.tsx      # Single WS connection, pub/sub, exponential backoff
    TabContext.tsx            # Tab list and active tab (pure UI state)
    MeetingRecorderContext.tsx# Recording state (persists across routes)
  utils/
    chatMessages.ts           # Message mapping, merging, retry/edit reconciliation
  CSS/                        # Per-component stylesheets
```

**State Management Pattern:**
- Custom hooks (`useChatState`, `useScreenshots`, `useTokenUsage`) manage domain-specific state
- `useRef` is used alongside `useState` to avoid stale closures in WebSocket callbacks
- No external state library (Redux, Zustand) -- hooks and context are sufficient

**Communication:**
- Real-time operations (chat, streaming, history) use WebSocket
- Configuration operations (model management, keys, auth) use REST API
- Electron IPC for window management only

### 3. Python Backend (`source/`)

The backend is a FastAPI application serving both WebSocket and REST endpoints:

```
source/
  main.py                     # Entry point: service init, Uvicorn launch
  app.py                      # FastAPI app factory with CORS
  config.py                   # Centralized constants (ports, models, limits)
  database.py                 # SQLite operations (thread-safe), FTS5 search, response versioning
  ss.py                       # Screenshot capture (hotkey, overlay, DPI, clipboard copy)
  api/
    websocket.py              # /ws endpoint, message routing to MessageHandler
    http.py                   # /api/* REST endpoints
    handlers.py               # MessageHandler: _handle_<type> per WS message
    terminal.py               # Terminal-specific REST endpoints
  core/
    state.py                  # AppState singleton + server_loop_holder + active_tab_id
    request_context.py        # RequestContext: cancellation, forced_skills, on_cancel callbacks
    connection.py             # ConnectionManager, broadcast_message, broadcast_to_tab, wrap_with_tab_ctx
    lifecycle.py              # Graceful shutdown, tab_manager.close_all()
    thread_pool.py            # run_in_thread — offload blocking calls from event loop
  services/
    conversations.py          # submit_query: full turn orchestration, retry/edit, slash extraction
    screenshots.py            # Screenshot lifecycle (per-tab, hotkey, blur window)
    transcription.py          # Voice-to-text (pyaudio + faster-whisper base.en)
    google_auth.py            # Google OAuth 2.0 (InstalledAppFlow)
    terminal.py               # TerminalSession, PTY, kill_process_tree, resize_all_pty
    approval_history.py       # SHA256-hashed "Allow & Remember" persistence
    skills.py                 # SkillManager: filesystem-backed skill CRUD, cache, references
    query_queue.py            # Per-tab ConversationQueue (maxsize=5, lazy consumer task)
    tab_manager.py            # TabState, TabSession, TabManager (MAX_TABS=10)
    tab_manager_instance.py   # Lazy singleton + _process_fn bridging queue → ConversationService
    ollama_global_queue.py    # Global serializer for Ollama (GPU single-tenant)
    meeting_recorder.py       # MeetingRecorderService: live Tier 1 + full Tier 2 pipeline
    gpu_detector.py           # CUDA vs CPU detection, compute_type, VRAM info
  llm/
    router.py                 # parse_provider() + route_chat()
    ollama_provider.py        # 2-phase tool detect + streaming via AsyncClient
    cloud_provider.py         # Unified Anthropic/OpenAI/Gemini via LiteLLM
    key_manager.py            # Fernet-encrypted API key storage
    prompt.py                 # build_system_prompt with skills_block + template
    types.py                  # Shared LLM type definitions
  mcp_integration/
    manager.py                # McpToolManager: spawn servers, discover tools, route calls
    handlers.py               # Ollama tool loop + retrieve_relevant_tools
    retriever.py              # Semantic tool retrieval (cosine sim, embedding cache)
    skill_injector.py         # Two-phase skill injection (manifest + full SKILL.md)
    terminal_executor.py      # Inline terminal execution (approval, PTY, DB persist)
  skills_seed/                # Builtin skills shipped with app (seeded to user_data on startup)
    terminal/, filesystem/, websearch/, gmail/, calendar/, browser/
```

**Key Patterns:**
- **Multi-Tab Isolation**: Each tab has its own `TabState` (chat history, screenshots, conversation_id, current request). `TabManager` (max 10 tabs) and per-tab `ConversationQueue` ensure requests are queued and isolated. Active tab is tracked by `MessageHandler` on every incoming WS message.
- **ContextVars for per-request state**: `set_current_request()`, `set_current_model()`, `set_tab_id()` use Python `ContextVar` so that per-tab model and cancellation state are isolated across concurrent async tasks on the same event loop. Never read `app_state.selected_model` from LLM layers.
- `AppState` (singleton) holds process-level shared state (server loop, active_tab_id, screenshot service).
- `RequestContext` manages per-request lifecycle: `cancelled` flag, `forced_skills` list, `on_cancel()` callbacks, `mark_done()` cleanup.
- `server_loop_holder` stores the asyncio event loop for cross-thread scheduling (hotkey thread → WebSocket broadcast).
- `wrap_with_tab_ctx(tab_id, coro)` stamps `_current_tab_id` on coroutines scheduled from background threads (e.g., precision screenshot hotkey) so `broadcast_message()` routes to the correct tab.
- `find_available_port()` probes ports 8000-8009 to avoid conflicts.
- Thread-safe SQLite with `check_same_thread=False`, WAL mode, `busy_timeout=5000`.
- **Skill System**: Skills are filesystem-backed folders under `user_data/skills/`. Builtin skills live under `user_data/skills/builtin/` (seeded from `source/skills_seed/` on every startup). `skill_injector.py` uses two-phase injection: a compact manifest always in the system prompt, and full `SKILL.md` content when the skill is triggered.
- **Ollama Global Queue**: `OllamaGlobalQueue` serializes local Ollama requests across tabs (single local GPU). Cloud requests and Ollama cloud models (`-cloud`) bypass this and run concurrently.
- **Inline LLM routing via LiteLLM**: All cloud providers (Anthropic, OpenAI, Gemini) use `litellm.acompletion()` with `litellm.modify_params=True`. Tool definitions use OpenAI format; LiteLLM translates to native formats.

## Data Flow

### Chat Query Flow

```
User types message
       |
       v
React (App.tsx) --[WS: submit_query]--> Python (websocket.py)
       |                                        |
       |                                        v
       |                              handlers.py: _handle_submit_query
       |                                        |
       |                                        v
       |                              conversations.py: submit_query
       |                                (Creates RequestContext)
       |                                        |
       |                                        v
       |                              router.py: route_chat
       |                               /              \
       |                       (Ollama)                (Cloud: Anthropic/OpenAI/Gemini)
       |                          |                        |
       |                          v                        v
       |                 ollama_provider.py          cloud_provider.py
       |            Phase 1: non-streamed detect    (inline tool calling)
       |                          |                        |
       |                          v                        v
       |                 MCP Manager / Handlers    Tool Execution inline
       |            Phase 2: streaming follow-up   (MCP / Terminal)
       |                          |                        |
       |                          v                        v
       |                     Tool Execution          Stream Response
       |                   (MCP / Terminal)          (interleaved)
       |                          |
       |                          v
       |                   Stream Response
       |                    (interleaved)
       |                          |
       |                          +-----------+------------+
       |                                      |
       |                                      v
       |                              Save to SQLite
       |                              Auto-expire terminal session
       |                              Finalize RequestContext
       |                                      |
       v                                      v
React receives WS messages:         Broadcast results
  - thinking_chunk                   - conversation_saved
  - response_chunk                   - tool_calls_summary
  - tool_call / tool_result          - token_update
  - response_complete
```

### Terminal Tool Flow

```
LLM returns terminal tool_call (e.g., run_command)
       |
       v
mcp_integration/handlers.py (Ollama) or cloud_provider.py (cloud models)
       |
       v
mcp_integration/terminal_executor.py
       |
       v
services/terminal.py: check_approval
  - Blocks via asyncio.Event
  - Broadcasts "terminal_approval_request"
       |
       v
User approves in UI (App.tsx) --[WS: terminal_approval_response]--> websocket.py
       |                                                           |
       |                                                           v
       +<----------------------------------------------------------+
       |
       v
terminal.py: execute_command (PTY or Sync)
  - Broadcasts live output via "terminal_output"
  - Handles 10s running notices
  - Obeys RequestContext cancellation
       |
       v
Save event to terminal_events table
       |
       v
Return result to LLM
```

### Screenshot Flow

```
User presses Alt+. (or UI trigger)
       |
       v
ss.py: ScreenshotService (background thread)
       |
       v
RegionSelector (Tkinter overlay)
  - DPI-aware coordinate transform
  - Click-drag rectangle selection
       |
       v
Capture image, generate thumbnail
       |
       v
screenshots.py: on_screenshot_captured
  - Add to app_state.screenshot_list
  - Schedule WS broadcast via server_loop_holder
       |
       v
React receives: screenshot_added
  - Display thumbnail chip in input area
```

### MCP Tool Call Flow

**Ollama path:**

```
Phase 1: Non-streamed detection call (think=False)
  - LLM returns tool_calls list (or empty — falls through to normal streaming)
       |
       v
handlers.py: handle_mcp_tool_calls()
  - Broadcasts "tool_call" for each detected tool
  - Executes via mcp_manager.call_tool() or terminal_executor
  - Broadcasts "tool_result"
  - Appends tool exchange to messages
       |
       v
Phase 2: _stream_tool_follow_up()
  - Follow-up response streamed in real-time (text + possible further tool calls)
  - Loop continues (up to MAX_MCP_TOOL_ROUNDS)
  - Returns {already_streamed: True} when done
```

**Cloud path (Anthropic / OpenAI / Gemini):**

```
router.py: retrieve_relevant_tools() -> allowed_tool_names set
       |
       v
cloud_provider.py: stream_cloud_chat(allowed_tool_names=...)
  - Streams text in real-time
  - When tool calls detected mid-stream, executes them inline
  - Broadcasts "tool_call" + "tool_result" to frontend
  - Appends results to messages and loops
  - Loop continues (up to MAX_MCP_TOOL_ROUNDS)
  - User sees text → tool → text → tool → text as one continuous flow
```

## Database Schema

```sql
-- Conversations index
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,                    -- UUID v4
    title TEXT,
    created_at REAL,
    updated_at REAL,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0
);

-- Messages with versioning support
CREATE TABLE messages (
    num_messages INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,                     -- 'user' or 'assistant'
    content TEXT,
    images TEXT,                            -- JSON array of base64 image strings
    model TEXT,
    content_blocks TEXT,                    -- JSON array of ContentBlock
    message_id TEXT UNIQUE,                 -- Stable UUID for retry/edit targeting
    turn_id TEXT,                           -- Groups a user+assistant pair
    active_response_index INTEGER DEFAULT 0,-- Which response variant is visible
    created_at REAL
);

-- Response variants (retry/edit creates new versions)
CREATE TABLE message_response_versions (
    id TEXT PRIMARY KEY,
    assistant_message_id TEXT,              -- FK → messages.message_id
    response_index INTEGER,
    content TEXT,
    model TEXT,
    content_blocks TEXT,                    -- JSON
    created_at REAL,
    UNIQUE(assistant_message_id, response_index)
);

-- Terminal command audit trail
CREATE TABLE terminal_events (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_index INTEGER,
    command TEXT,
    exit_code INTEGER,
    output_preview TEXT,
    full_output TEXT,
    cwd TEXT,
    duration_ms INTEGER,
    timed_out INTEGER,
    denied INTEGER,
    pty INTEGER,
    background INTEGER,
    created_at REAL
);

-- Meeting recordings
CREATE TABLE meeting_recordings (
    id TEXT PRIMARY KEY,
    title TEXT,
    started_at REAL,
    ended_at REAL,
    duration_seconds REAL,
    status TEXT,                            -- 'recording'|'processing'|'completed'|'failed'
    audio_file_path TEXT,
    tier1_transcript TEXT,
    tier2_transcript_json TEXT,             -- JSON (WhisperX aligned + diarized)
    ai_summary TEXT,
    ai_actions_json TEXT,
    ai_title_generated INTEGER DEFAULT 0
);

-- FTS5 virtual tables for full-text search
CREATE VIRTUAL TABLE conversations_fts USING fts5(conversation_id, title, tokenize='unicode61');
CREATE VIRTUAL TABLE messages_fts USING fts5(conversation_id, content, tokenize='unicode61');
-- Auto-updated by triggers: *_ai (after insert), *_au (after update), *_ad (after delete)

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

**Key Settings Stored:**
- `enabled_models`: List of active models
- `api_key_anthropic` / `api_key_openai` / `api_key_gemini`: Fernet-encrypted API keys
- `encryption_salt`: Per-install salt for key encryption
- `tool_always_on`: List of tool names to always include in context
- `tool_retriever_top_k`: Number of semantic matches for tool retrieval
- `system_prompt_template`: Custom system prompt template string

**Skills** are no longer stored in the DB — they are filesystem-backed folders under `user_data/skills/`. Enabled/disabled state is in `user_data/skills/preferences.json`.

## Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Desktop** | Electron 37+, frameless transparent 550×550 window |
| **Frontend** | React 19, TypeScript 5.8, Vite 6, React Router 7, xterm.js, ansi-to-html |
| **Backend** | Python 3.13+, FastAPI, Uvicorn, asyncio |
| **LLM (Local)** | Ollama via `ollama.AsyncClient` (default: qwen3-vl:8b-instruct) |
| **LLM (Cloud)** | Anthropic (Claude), OpenAI (GPT/o-series), Google (Gemini) via LiteLLM |
| **Database** | SQLite3 (WAL mode, FTS5 full-text search, response versioning) |
| **Security** | Fernet encryption (`cryptography`) for API keys; SHA256-hashed approval history |
| **MCP** | Model Context Protocol SDK, stdio transport, semantic tool retrieval |
| **Screenshots** | pynput (hotkeys), Pillow (images), tkinter (overlay), SetProcessDpiAwarenessContext |
| **Transcription** | faster-whisper (base.en for live), pyaudio, WhisperX (large-v3 for meetings) |
| **Diarization** | SpeechBrain, torchaudio |
| **Auth** | Google OAuth 2.0 (`InstalledAppFlow`) for Gmail/Calendar |
| **Web Search** | DuckDuckGo Search (ddgs), crawl4ai (stealth Playwright), trafilatura |
| **Build** | PyInstaller (Python), electron-builder (desktop), UV (Python pkg manager), Bun (JS) |
