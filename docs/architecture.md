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
- Content protection enabled (`setContentProtection(true)`)
- Normal mode: 450x450 | Mini mode: 52x52
- `skipTaskbar: true` for minimal desktop footprint

**IPC Channels:**
- `set-mini-mode` - Toggles between normal and mini window sizes
- `focus-window` - Programmatically brings the window to foreground

**Python Lifecycle (Production):**
1. On `app.whenReady()`, spawns the bundled Python executable
2. Monitors stdout for "Application startup complete"
3. Performs health check on the discovered port
4. On `app.quit()`, terminates the Python process and cleans up orphaned processes

### 2. React Frontend (`src/ui/`)

The frontend follows a modular architecture with custom hooks for state management:

```
src/ui/
  main.tsx                    # HashRouter setup (/, /settings, /history, /album)
  pages/
    App.tsx                   # Main chat interface
    ChatHistory.tsx           # Conversation browser with search
    Settings.tsx              # Tabbed settings interface
    MeetingAlbum.tsx          # Place holder for meeting recorder transcriptions
  components/
    Layout.tsx                # App shell with mini mode transitions
    TitleBar.tsx              # Custom draggable title bar
    WebSocketContext.tsx      # WebSocket provider
    chat/
      ChatMessage.tsx         # Individual message rendering
      ThinkingSection.tsx     # Collapsible reasoning display
      ToolCallsDisplay.tsx    # MCP tool execution cards
      CodeBlock.tsx           # Syntax-highlighted code blocks
      ResponseArea.tsx        # Chat history display area
      SlashCommandMenu.tsx    # Contextual skills menu
      LoadingDots.tsx         # Typing indicator
    input/
      QueryInput.tsx          # User input with attachments
      ModeSelector.tsx        # Screenshot mode selector
      ScreenshotChips.tsx     # Screenshot thumbnail chips
      SlashCommandChips.tsx   # Active skill indicators
      TokenUsagePopup.tsx     # Context window usage indicator
    settings/
      SettingsModels.tsx      # Model toggle UI
      SettingsApiKey.tsx      # API key management (Anthropic/OpenAI/Gemini)
      SettingsConnections.tsx # Google OAuth connection card
      SettingsTools.tsx       # Semantic tool retrieval configuration
      SettingsSystemPrompt.tsx# Custom system prompt configuration
      SettingsSkills.tsx       # Skill editor and manager
    terminal/
      TerminalPanel.tsx       # Integrated xterm.js terminal
      TerminalCard.tsx        # Inline command execution view
      ApprovalCard.tsx        # Security approval prompts
      SessionBanner.tsx       # Autonomous mode status
  hooks/
    useChatState.ts           # Chat history, streaming, status
    useScreenshots.ts         # Screenshot context management
    useTokenUsage.ts          # Token tracking
  services/
    api.ts                    # REST API client + WS command factory
  types/
    index.ts                  # TypeScript interfaces
  CSS/                        # Component stylesheets
    App.css
    ChatHistory.css
    Settings.css
    SettingsApiKey.css
    SettingsConnections.css
    SettingsModels.css
    SettingsTools.css
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
  database.py                 # SQLite operations (thread-safe)
  ss.py                       # Screenshot capture (hotkey, overlay, DPI)
  api/
    websocket.py              # /ws endpoint, message routing
    http.py                   # /api/* REST endpoints
    handlers.py               # WebSocket message handler logic
    terminal.py               # Terminal-specific WebSocket handlers
  core/
    state.py                  # Global mutable state (AppState)
    request_context.py        # Request lifecycle (RequestContext class)
    connection.py             # WebSocket connection registry
    lifecycle.py              # Graceful shutdown & cleanup
    thread_pool.py            # Async execution helper
  services/
    conversations.py          # Chat flow orchestration (lifecycle + streaming)
    screenshots.py            # Screenshot lifecycle management
    transcription.py          # Voice-to-text (faster-whisper)
    google_auth.py            # Google OAuth 2.0 flow manager
    terminal.py               # Terminal approval flow, PTY, notice tracking
    approval_history.py       # Persistence for "remember" approvals
  llm/
    router.py                 # Routes requests to Ollama or Cloud providers
    ollama_provider.py        # Ollama streaming bridge with tool support
    cloud_provider.py         # Anthropic/OpenAI/Gemini streaming with inline tool calling
    key_manager.py            # Encrypted API key storage
    prompt.py                 # System prompt builder with variable interpolation
  mcp_integration/
    manager.py                # MCP server process management + inline tools
    retriever.py              # Semantic tool retrieval (Top-K selection)
    handlers.py               # Tool call routing loop (up to 30 rounds)
    cloud_tool_handlers.py    # Legacy cloud tool handler (superseded by inline tool calling in cloud_provider.py)
    skill_injector.py         # Dynamic skill injection based on category
    default_skills.py         # Hardcoded system instructions for tools
    terminal_executor.py      # Unified terminal tool execution logic
```

**Key Patterns:**
- `AppState` (singleton) holds all mutable state, shared across threads
- `RequestContext` replaces raw boolean flags for managing request lifecycles (cancellation, cleanup).
- `server_loop_holder` stores the asyncio event loop for cross-thread scheduling (hotkey thread -> WebSocket thread)
- `find_available_port()` probes ports 8000-8009 to avoid conflicts
- Thread-safe SQLite with `check_same_thread=False`
- **Hybrid LLM Support**: Routes requests between local Ollama and cloud APIs (Anthropic, OpenAI, Gemini). Cloud providers handle tool execution inline during streaming — the user sees text, tool calls, and results interleaved in real-time.
- **Skills and Slash Commands**: Dynamic behavioral guidance injected into the system prompt.
- **Unified Terminal Executor**: Centralizes all terminal tool logic (approval, PTY, notice tracking, DB) in a single module.
- **Ghost Process Prevention**: Terminal tools are registered inline; no background process is spawned.

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
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,                    -- UUID v4
    title TEXT,                             -- Auto-generated from first message
    created_at REAL,                        -- Unix timestamp
    updated_at REAL,                        -- Updated on each new message
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0
);

CREATE TABLE messages (
    num_messages INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,                   -- FK to conversations.id
    role TEXT,                              -- 'user' or 'assistant'
    content TEXT,                           -- Message text
    images TEXT,                            -- JSON array of base64 image strings
    model TEXT,                             -- Model used for this message
    created_at REAL                         -- Unix timestamp
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,                   -- Setting identifier
    value TEXT                              -- JSON-serialized value
);
```

**Key Settings Stored:**
- `enabled_models`: List of active models
- `api_key_anthropic`: Encrypted API key
- `api_key_openai`: Encrypted API key
- `api_key_gemini`: Encrypted API key
- `encryption_salt`: Per-install salt for key encryption
- `tool_always_on`: List of tool names to always include in context
- `tool_retriever_top_k`: Number of semantic matches for tool retrieval
- `system_prompt_template`: Custom system prompt template string

## Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Desktop** | Electron 37+, frameless transparent window |
| **Frontend** | React 19, TypeScript 5.8, Vite 6, React Router 7, react-markdown |
| **Backend** | Python 3.13+, FastAPI, Uvicorn, asyncio |
| **LLM (Local)** | Ollama (default: qwen3-vl:8b-instruct) |
| **LLM (Cloud)** | Anthropic (Claude), OpenAI (GPT/o1), Google (Gemini) |
| **Database** | SQLite3 (thread-safe) |
| **Security** | Fernet encryption (cryptography) for API keys |
| **MCP** | Model Context Protocol SDK, stdio transport |
| **Screenshots** | pynput (hotkeys), Pillow (images), tkinter (overlay) |
| **Transcription** | faster-whisper, pyaudio |
| **Auth** | Google OAuth 2.0 (Gmail/Calendar integration) |
| **Web Search** | DuckDuckGo Search (ddgs), crawl4ai, trafilatura |
| **Build** | PyInstaller (Python), electron-builder (desktop), UV (package manager) |
