# source/ — Python Backend

## Architecture

```
source/
├── main.py              # Entry point: port discovery, uvicorn startup, MCP init hook
├── app.py               # FastAPI factory: CORS, WS route, HTTP routers
├── config.py            # All constants (ports, paths, model defaults, Google OAuth config)
├── database.py          # DatabaseManager — sole gateway to SQLite
├── ss.py                # ScreenshotService (OS-level capture + thumbnail generation)
│
├── core/
│   ├── state.py         # AppState singleton (screenshot list, model selection, chat history)
│   ├── connection.py    # ConnectionManager + broadcast_message helper
│   ├── request_context.py  # Per-request lifecycle and cancellation
│   ├── thread_pool.py   # run_in_thread — offload blocking calls from event loop
│   └── lifecycle.py     # Signal handlers, graceful shutdown
│
├── api/
│   ├── websocket.py     # WS endpoint + full protocol docstring
│   ├── handlers.py      # MessageHandler — one _handle_<type> per WS message
│   ├── http.py          # REST: models, API keys, MCP info, skills, Google auth, settings
│   └── terminal.py      # REST: terminal settings (shell path, timeout, approval mode)
│
├── llm/
│   ├── router.py        # parse_provider() + route_chat() — Ollama vs cloud dispatch
│   ├── ollama_provider.py  # stream_ollama_chat: 2-phase tool detect + streaming loop
│   ├── cloud_provider.py   # stream_cloud_chat: Anthropic / OpenAI / Gemini inline streaming
│   ├── key_manager.py   # Encrypted API key storage/retrieval
│   └── prompt.py        # build_system_prompt, accepts skills_block + optional template
│
├── mcp_integration/
│   ├── manager.py       # McpToolManager: spawn servers, discover tools, route calls
│   ├── handlers.py      # handle_mcp_tool_calls (Ollama path) + retrieve_relevant_tools
│   ├── cloud_tool_handlers.py  # Cloud path: parallel execute + result injection
│   ├── retriever.py     # ToolRetriever: semantic search over tool descriptions
│   ├── skill_injector.py   # Inject skills into system prompt based on active tools
│   ├── terminal_executor.py  # INLINE terminal execution (approval + PTY + DB persist)
│   └── default_skills.py   # Seed data for the skills table
│
└── services/
    ├── conversations.py # ConversationService.submit_query — orchestrates the full turn
    ├── screenshots.py   # ScreenshotHandler — manage screenshot lifecycle + state
    ├── terminal.py      # TerminalService — PTY sessions, approval queue, history
    ├── google_auth.py   # OAuth2 flow for Gmail/Calendar
    └── transcription.py # Audio transcription (if enabled)
```

---

## Key File Responsibilities

- **`state.py`** is a simple mutable singleton — it is *not* thread-safe for writes. All mutations happen inside the asyncio event loop from WS handler tasks, which is sufficient. `server_loop_holder["loop"]` stores the running asyncio event loop so that non-async threads (screenshot, lifecycle) can schedule coroutines via `asyncio.run_coroutine_threadsafe()`. Required because the Windows Proactor loop is not accessible from threads spawned outside uvicorn.
- **`request_context.py`** replaces the old `stop_streaming` boolean. Every subsystem that loops (tool rounds, PTY streaming, approval wait) must check `ctx.cancelled` to unblock cleanly when the user clicks Stop.
- **`thread_pool.py → run_in_thread`** is mandatory for anything that calls a synchronous SDK (e.g., `ollama.chat`, `ollama.list`). Calling them directly will block uvicorn's single event loop.
- **`terminal_executor.py`** handles terminal tools *inline* — it never calls the MCP subprocess for terminal actions. The `terminal` MCP server's `server.py` exists only as a schema/description source.
- **`ss.py`** calls `SetProcessDpiAwarenessContext(-4)` (per-monitor V2) at import time via ctypes. Without this, Tkinter reports logical coordinates while the capture API uses physical pixels, causing misaligned region selection on scaled or multi-monitor Windows setups.
- **`services/approval_history.py`** persists "Allow & Remember" approvals to `user_data/exec-approvals.json`. `_normalize_command()` extracts program + first 2 args for fuzzy matching; stored as SHA256 hash so the file contains no sensitive command text.
- **`services/transcription.py`** — `TranscriptionService`: records 16kHz mono audio via `pyaudio` into a queue, transcribes on `stop_recording` using `faster-whisper` (`base.en`), broadcasts `transcription_result` via WebSocket.
- **`services/conversations.py`** — `submit_query` orchestrates the full turn. When the user cancels mid-generation (`ctx.cancelled`), the method still persists the user prompt and partial assistant response (with `[Response interrupted]` appended) to the DB, creates a conversation record if needed, and broadcasts `conversation_saved`. Tool calls and content blocks executed before cancellation are preserved in the saved message.
- **`services/terminal.py`** — terminal events that fire before the first assistant message (no `conversation_id` yet) are queued via `queue_terminal_event()` and flushed to the DB after the conversation record is created via `flush_pending_events(conversation_id)`. Without this, tool calls on message 1 would be orphaned.

---

## DB Schema

| Table | Key Columns | Notes |
|---|---|---|
| `conversations` | `id` (UUID), `title`, `created_at`, `updated_at`, `total_input_tokens`, `total_output_tokens` | Sort sidebar by `updated_at` |
| `messages` | `num_messages` (autoincrement PK), `conversation_id`, `role`, `content`, `images` (JSON), `model`, `content_blocks` (JSON) | `images` is a JSON-serialized list of file paths |
| `settings` | `key`, `value` | Key-value store for all user preferences |
| `terminal_events` | `id`, `conversation_id`, `command`, `exit_code`, `output_preview`, `full_output`, `cwd`, `duration_ms`, `timed_out`, `denied`, `pty`, `background` | Full audit trail of executed commands |
| `skills` | `skill_name` (UNIQUE), `slash_command` (UNIQUE), `content`, `is_default`, `enabled` | Seeded from `default_skills.py` via `INSERT OR IGNORE` |

**Migration rule:** New columns use `ALTER TABLE … ADD COLUMN` inside `try/except OperationalError` in `_init_db()`. Never alter the original `CREATE TABLE` statement — it would break existing databases.

---

## WebSocket Protocol Reference

### Client → Server

| `type` | Key fields | Handler |
|---|---|---|
| `submit_query` | `content`, `capture_mode`, `model` | `_handle_submit_query` |
| `clear_context` | — | `_handle_clear_context` |
| `remove_screenshot` | `id` | `_handle_remove_screenshot` |
| `set_capture_mode` | `mode` (`fullscreen`/`precision`/`none`) | `_handle_set_capture_mode` |
| `stop_streaming` | — | `_handle_stop_streaming` |
| `get_conversations` | `limit`, `offset` | `_handle_get_conversations` |
| `load_conversation` | `conversation_id` | `_handle_load_conversation` |
| `delete_conversation` | `conversation_id` | `_handle_delete_conversation` |
| `search_conversations` | `query` | `_handle_search_conversations` |
| `resume_conversation` | `conversation_id` | `_handle_resume_conversation` |
| `stop_recording` | — | `_handle_stop_recording` |
| `terminal_approval_response` | `request_id`, `approved`, `remember` | `_handle_terminal_approval_response` |
| `terminal_session_response` | `approved` | `_handle_terminal_session_response` |
| `terminal_stop_session` | — | `_handle_terminal_stop_session` |
| `terminal_set_ask_level` | `level` (`always`/`on-miss`/`off`) | `_handle_terminal_set_ask_level` |

### Server → Client

| `type` | When sent |
|---|---|
| `ready` | On new WS connect |
| `screenshot_start` / `screenshot_added` / `screenshot_removed` / `screenshots_cleared` | Screenshot lifecycle |
| `thinking_chunk` / `thinking_complete` | Streaming reasoning tokens |
| `response_chunk` / `response_complete` | Streaming response tokens |
| `tool_call` | Each MCP tool invocation (includes result when done) |
| `tool_calls_summary` | After tool loop ends |
| `query` | Echo of submitted query |
| `token_usage` | After response completes |
| `context_cleared` | After `clear_context` completes |
| `conversation_saved` / `conversations_list` / `conversation_loaded` / `conversation_deleted` / `conversation_resumed` | Conversation management |
| `screenshot_ready` | Legacy — kept for backwards compatibility |
| `transcription_result` | After `stop_recording` completes |
| `terminal_approval_request` | Command needs user approval (includes `request_id`, `command`, `cwd`) |
| `terminal_session_request` | LLM requests session mode (includes `reason`) |
| `terminal_session_started` / `terminal_session_ended` | Session mode lifecycle |
| `terminal_output` | PTY output chunks during execution |
| `terminal_command_complete` | Command finished (`exit_code`, `duration_ms`) |
| `terminal_running_notice` | Broadcast 10s after command starts if still running |
| `error` | Any unhandled exception |

---

## MCP Integration — How Tool Calls Work

### Ollama path (two-phase)
1. **Detection phase** — non-streaming call with `think=False` and the retrieved tool list. Returns either tool calls or nothing. `think=False` is a workaround for Ollama bug #10976 where `think=True` + tools produces empty output.
2. **Streaming loop** — if tools were requested, enters a `MAX_MCP_TOOL_ROUNDS` loop: execute tools → append results → streaming call for next response. Each intermediate text chunk is broadcast live so the user sees the model's reasoning between tool calls.
3. If no tools were detected in phase 1, the caller falls through to normal streaming (with thinking enabled).

### Cloud path (inline)
Tools are handled inside a single streaming session. When a tool_use block is detected mid-stream, execution is paused, the tool runs, and the result is injected before streaming resumes. No separate detection phase.

### Tool Retrieval
`ToolRetriever` embeds tool descriptions and user query using Ollama (`nomic-embed-text`) or `sentence-transformers`. Top-K most similar tools are passed to the LLM, reducing context noise. "Always on" tools bypass the filter (configured in Settings → Tools).

### Skill Injection
`skill_injector.py` appends behavioral guidance to the system prompt. Forced skills come from `/slash` commands; auto-detected skills come from the dominant tool server in the retriever output. Skills are stored in the `skills` DB table and editable from Settings.

### Adding a New MCP Server (end-to-end)

1. **Create** `mcp_servers/servers/<name>/server.py` with `@mcp.tool()` functions.
2. **Connect** in `source/mcp_integration/manager.py`'s `init_mcp_servers()`:
   ```python
   await mcp_manager.connect_server(
       "your_name",
       sys.executable,
       [str(PROJECT_ROOT / "mcp_servers" / "servers" / "your_name" / "server.py")]
   )
   ```
3. **Optionally update** `mcp_servers/config/servers.json` with metadata (used by the Settings UI; not read by the backend).
4. **Optionally add a skill** in `source/mcp_integration/default_skills.py` so the model gets context-specific guidance when your tools are active.
5. Tools are auto-discovered, indexed by the retriever, and available immediately.

---

## Architecture Decisions

**Why `check_same_thread=False` on every SQLite connection?**
FastAPI runs handlers on different threads in its thread pool. A per-call `_get_connection()` pattern creates a new connection for every DB call, avoiding cross-thread reuse while staying compatible with asyncio.

**Why does the Ollama tool-detection call use `think=False`?**
Ollama bug #10976: models with thinking enabled return empty `tool_calls` even when they intend to call tools. The detection phase disables thinking specifically to surface tool calls correctly; thinking is re-enabled in the streaming follow-up.

**Why is terminal execution handled inline rather than via the MCP subprocess?**
Terminal commands need approval UI, PTY streaming, cancellation, and DB persistence — all of which require access to the app's WebSocket connection and state. Routing through a subprocess would require a separate approval protocol. Inline execution makes the approval/streaming/audit pipeline a first-class part of the app.

**Why is `RequestContext` separate from `AppState`?**
`AppState` is long-lived (entire process). `RequestContext` is per-request and garbage-collected after each turn. This makes cancellation scoping clean — cancelling the current request doesn't corrupt state for the next one.

**Why does `McpToolManager.connect_server` use a background asyncio Task?**
`anyio` (used by `mcp`) requires that `stdio_client` and `ClientSession` context managers enter and exit on the *same* task. Using a dedicated background task per server avoids the "cancel scope in a different task" RuntimeError when disconnecting from an HTTP handler.

**Why does `ollama_provider.py` use a producer thread + asyncio queue?**
Ollama's Python SDK returns a synchronous generator that blocks the calling thread. It runs in a `daemon=True` background thread and pushes chunks into an `asyncio.Queue`. The event loop consumes the queue without blocking. Calling `ollama.chat(stream=True)` directly on the event loop thread would freeze uvicorn.

**Why does terminal approval live in the FastAPI process, not the MCP subprocess?**
`asyncio.Event` can't cross process boundaries. The MCP terminal server runs as a stdio child process, so blocking until the user confirms must happen in the parent FastAPI process where the WebSocket connection lives.

**Why are 3 of the 4 terminal security layers invisible?**
Layer 1 (blocklist), Layer 2 (PATH injection detection), Layer 3 (120s hard timeout) are never surfaced to the user or LLM. Exposing them would allow social engineering ("just disable the blocklist first"). Only Layer 4 (approval prompts) is visible.

**Why does session mode auto-expire in `submit_query`'s `finally` block?**
LLMs reliably call `request_session_mode` but almost never call `end_session_mode`. Auto-expiring on turn end guarantees cleanup regardless of how the turn ends (completion, cancellation, error).

**Why are images included in the Ollama tool-detection call?**
The model needs to see image content to make informed tool-calling decisions — e.g., a screenshot containing a URL where the user asks "read this" requires the model to extract the URL *from the image* before it can call `read_website`. The non-streamed detection call includes images alongside tool definitions.
