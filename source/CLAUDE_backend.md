# source/ — Python Backend

## Architecture

```
source/
├── main.py                               # Entry point: boot markers, port discovery, uvicorn startup
├── bootstrap/
│   ├── __init__.py
│   └── app_factory.py                    # FastAPI factory + startup/shutdown wiring
├── infrastructure/
│   ├── __init__.py
│   ├── config.py                         # Paths, defaults, OAuth config, shared constants
│   ├── database.py                       # DatabaseManager — sole gateway to SQLite
│   └── screenshot_runtime.py             # ScreenshotService + screenshot utility helpers
│
├── core/
│   ├── __init__.py
│   ├── connection.py                     # ConnectionManager + tab-aware broadcast helpers
│   ├── lifecycle.py                      # Signal handlers + graceful shutdown
│   ├── request_context.py                # Per-request lifecycle, cancellation, model ContextVars
│   ├── state.py                          # AppState singleton
│   └── thread_pool.py                    # run_in_thread helper
│
├── api/
│   ├── __init__.py
│   ├── websocket.py                      # WS endpoint + protocol reference docstring
│   ├── handlers.py                       # MessageHandler (_handle_<type> per WS message)
│   ├── http.py                           # Main REST endpoints (models, keys, skills, settings)
│   ├── terminal.py                       # REST: terminal settings + approval history controls
│   └── mobile_internal.py                # Internal REST API for channel bridge
│
├── llm/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── router.py                     # parse_provider() + route_chat()
│   │   ├── key_manager.py                # Encrypted API key storage/retrieval
│   │   ├── prompt.py                     # build_system_prompt()
│   │   └── types.py                      # ChatResult + provider-neutral types
│   └── providers/
│       ├── __init__.py
│       ├── ollama_provider.py            # AsyncClient streaming + Ollama tool loop integration
│       └── cloud_provider.py             # Unified Anthropic/OpenAI/Gemini via LiteLLM
│
├── mcp_integration/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── manager.py                    # McpToolManager: connect/discover/register tools
│   │   ├── handlers.py                   # Ollama MCP tool loop + shared retrieval helper
│   │   ├── retriever.py                  # ToolRetriever (semantic + BM25 + cache)
│   │   ├── skill_injector.py             # Two-phase skill injection (manifest + contextual)
│   │   └── tool_args.py                  # Tool argument normalization/sanitization
│   └── executors/
│       ├── __init__.py
│       ├── terminal_executor.py          # Inline terminal tools (approval + PTY + DB persist)
│       ├── video_watcher_executor.py     # Inline video watcher tool execution
│       ├── skills_executor.py            # Inline skills tools (list_skills/use_skill)
│       ├── memory_executor.py            # Inline memory tools (memlist/memread/memcommit)
│       └── scheduler_executor.py         # Inline scheduler tools
│
├── services/
│   ├── __init__.py
│   ├── chat/
│   │   ├── __init__.py
│   │   ├── conversations.py              # ConversationService.submit_query()
│   │   ├── query_queue.py                # Per-tab queue runtime
│   │   ├── tab_manager.py                # TabState/TabSession/TabManager
│   │   ├── tab_manager_instance.py       # Lazy singleton + queue->conversation bridge
│   │   └── ollama_global_queue.py        # Global local-Ollama request serializer
│   ├── filesystem/
│   │   ├── __init__.py
│   │   └── file_browser.py               # @ file picker browse/search + index refresh
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── external_connectors.py        # External MCP connector lifecycle
│   │   ├── google_auth.py                # OAuth2 flow for Gmail/Calendar
│   │   └── mobile_channel.py             # Mobile channel session + relay orchestration
│   ├── media/
│   │   ├── __init__.py
│   │   ├── screenshots.py                # ScreenshotHandler lifecycle + tab routing
│   │   ├── file_extractor.py             # File extraction/parsing helpers
│   │   ├── video_watcher.py              # YouTube captions/transcription flow
│   │   ├── transcription.py              # Voice transcription service
│   │   ├── meeting_recorder.py           # Meeting recording + post-processing pipeline
│   │   └── gpu_detector.py               # CUDA/CPU detection for Whisper planning
│   ├── memory_store/
│   │   ├── __init__.py
│   │   └── memory.py                     # Filesystem-backed long-term memory service
│   ├── scheduling/
│   │   ├── __init__.py
│   │   ├── scheduler.py                  # APScheduler-backed jobs runtime
│   │   └── notifications.py              # Notification persistence + delivery helpers
│   ├── shell/
│   │   ├── __init__.py
│   │   ├── terminal.py                   # TerminalService + PTY session lifecycle
│   │   └── approval_history.py           # Persisted allow-and-remember approvals
│   └── skills_runtime/
│       ├── __init__.py
│       ├── skills.py                     # SkillManager (filesystem-backed skills)
│       └── sub_agent.py                  # spawn_agent execution + tier resolution
│
└── skills_seed/                           # Builtin skill folders shipped with the app
    ├── terminal/                         # Each folder contains: skill.json + SKILL.md
    ├── filesystem/
    ├── websearch/
    ├── youtube/
    ├── gmail/
    ├── calendar/
    └── browser/                          # Browser automation via playwright-cli
```

---

## Key File Responsibilities

- **`state.py`** is a simple mutable singleton — it is *not* thread-safe for writes. All mutations happen inside the asyncio event loop from WS handler tasks, which is sufficient. `server_loop_holder["loop"]` stores the running asyncio event loop so that non-async threads (screenshot, lifecycle) can schedule coroutines via `asyncio.run_coroutine_threadsafe()`. Required because the Windows Proactor loop is not accessible from threads spawned outside uvicorn. It also tracks `active_tab_id` and a global `screenshot_counter` (ID generation only). Screenshots themselves are no longer stored globally.
- **`connection.py`** — `wrap_with_tab_ctx(tab_id, coro)` wraps a coroutine so that `_current_tab_id` is set for its duration. Used whenever scheduling a broadcast from a background thread (e.g., precision-mode screenshot capture) back to the event loop via `call_soon_threadsafe` or `run_coroutine_threadsafe`. Without this wrapper, new tasks lose the contextvar and broadcast messages arrive without `tab_id`, routing them to the wrong tab on the frontend. Also provides `broadcast_to_tab(tab_id, message_type, content)` — an explicit tab-scoped broadcast helper for scenarios where you want to target a specific tab directly rather than rely on the contextvar (e.g., Ollama queue status updates from the global queue). See the "Why `wrap_with_tab_ctx`" architecture decision below.
- **`request_context.py`** replaces the old `stop_streaming` boolean. Every subsystem that loops (tool rounds, PTY streaming, approval wait) must check `ctx.cancelled` to unblock cleanly when the user clicks Stop. Provides `ContextVar`-based `set_current_request()` / `is_current_request_cancelled()` for per-task cancellation, and `set_current_model()` / `get_current_model()` so the LLM layer picks up the correct model per-request without reading the global `app_state.selected_model`. `RequestContext` also carries a `forced_skills: list` field (set from `QueuedQuery.forced_skills` by the slash command parser) and supports `on_cancel(callback)` to register cleanup callbacks that fire on cancellation; `mark_done()` clears them on normal completion.
- **`query_queue.py`** — `ConversationQueue`: per-tab `asyncio.Queue(maxsize=5)` with a lazy consumer task. Supports `stop_current()`, `cancel_item()`, `drain()`, and `get_snapshot()`. Errors during processing are broadcast and the queue continues; `CancelledError` exits the consumer gracefully. On `QueueFullError`, the handler broadcasts `queue_full` (not `error`). Each enqueued item broadcasts `query_queued` to the frontend. `QueuedQuery` carries `item_id`, `forced_skills`, `llm_query`, `action` (`"submit"` / `"retry"` / `"edit"`), and `target_message_id` for retry/edit flows. `resolved_conversation_id` on the queue allows subsequent items to inherit the conversation started by the first.
- **`tab_manager.py`** — `TabState` dataclass holds per-tab mutable state (chat_history, screenshot_list, conversation_id, current_request, stop_streaming). Includes `add_screenshot()` and `remove_screenshot()` methods that use the global `screenshot_counter` for unique IDs across tabs. `TabSession` groups a `TabState` + `ConversationQueue`. `TabManager` enforces `MAX_TABS=10`, creates/closes/lists tabs. `lifecycle.py` calls `tab_manager.close_all()` during graceful shutdown.
- **`ollama_global_queue.py`** — singleton `OllamaGlobalQueue` serializes local Ollama requests across tabs (GPU can only serve one at a time). Cloud provider requests and Ollama cloud models (`-cloud`) bypass this and run concurrently. `remove_tab()` unblocks waiting callers with `CancelledError`. Uses a `result_holder[0]` pattern via an inner `_wrapper` coroutine to propagate return values back to `run()` callers. `set_broadcast_fn(fn)` injects the broadcast function after startup to avoid circular imports.
- **`services/chat/tab_manager_instance.py`** — lazy singleton initialized from `bootstrap/app_factory.py` startup hooks. The `_process_fn` bridges `QueuedQuery → ConversationService.submit_query`, setting the tab_id contextvar and routing only local Ollama models through the global queue. `init_tab_manager()` also wires the Ollama queue's broadcast function and creates the default tab.
- **`bootstrap/app_factory.py` startup hooks** — besides tab/session restoration, startup now also syncs `USER_DATA_DIR/mobile_channels_config.json` from DB by calling `_write_mobile_channels_config_file()` via `run_in_thread(...)` so Channel Bridge always gets a fresh config snapshot after backend boot.
- **Startup performance guardrails** — keep package `__init__.py` exports lazy (`api/`, `core/`, `llm/`, `mcp_integration/`, `services/`) so importing a narrow module does not eagerly pull in the full LLM/tool stack. `api/handlers.py` should only import heavyweight services lazily inside handlers/helpers, `core/state.py` must not import `infrastructure/screenshot_runtime.py` just for typing, and `mcp_integration/core/retriever.py` should only import `sentence_transformers` if the Ollama embedding backend is unavailable. Regressing these patterns adds multiple seconds to dev startup before the first boot marker appears.
- **`api/mobile_internal.py`** — Internal HTTP API called by `channel-bridge` service. Exposes `/internal/mobile/*` endpoints to handle message routing, command execution (`/new`, `/stop`), device pairing, and connection sync for mobile apps like WhatsApp.
- **`services/integrations/mobile_channel.py`** — `MobileChannelService`: Coordinates communication between the Channel Bridge and Xpdite. Manages session states (mapping mobile user IDs to Xpdite tab IDs), pushes mobile messages into the Conversation Queue, and acts as the webhook callback dispatcher. Also broadcasts AI typing and message edits (streams via chunk accumulation) back to the bridge.
- **`services/integrations/external_connectors.py`** — `ExternalConnectorService`: Manages external out-of-process MCP servers (like Figma or Slack) running via `npx` or `uvx` directly. Persists enabled states in DB so they auto-reconnect on boot.
- **`llm/core/types.py`** — `ChatResult`: Unified return signature for all Provider streams (text output, token stats, tools, interleaved blocks).
- **`thread_pool.py → run_in_thread`** is mandatory for anything that calls a synchronous SDK (e.g., `google-auth`, `Pillow`, screenshots). Calling them directly will block uvicorn's single event loop. Note: Ollama now uses `AsyncClient` natively and no longer needs `run_in_thread`.
- **`terminal_executor.py`** handles terminal tools *inline* — it never calls the MCP subprocess for terminal actions. The `terminal` MCP server's `server.py` exists only as a schema/description source. Supported inline tools: `run_command`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process`, `get_environment`. `run_command` accepts optional `background=True` and `yield_ms` parameters. A per-command `_notice_checker` asyncio task fires a notice broadcast if the command runs longer than 10 seconds.
- **`services/skills_runtime/sub_agent.py`** — Sub-agent execution service. `execute_sub_agent()` is the entry point called by the `spawn_agent` tool interceptor (in both `cloud_provider.py` and `handlers.py`). Accepts `instruction`, `model_tier` (fast/smart/self), and `agent_name`. Resolves tier to a model via `_resolve_tier_model()` (checks DB setting `sub_agent_tier_<tier>`, falls back to current model). Tools are retrieved via `_get_sub_agent_tools()` which uses semantic retrieval minus `_EXCLUDED_TOOLS` (terminal tools + spawn_agent). Cloud calls use LiteLLM non-streaming with a tool loop; Ollama calls use AsyncClient non-streaming. A global `_concurrency_semaphore` (cap 5) prevents overwhelming APIs/GPU. `execute_sub_agents_parallel()` checks if *any* call resolves to local Ollama — if so, all run sequentially; otherwise parallel with `asyncio.gather(return_exceptions=True)`. Ollama cloud tags `:cloud` and `-cloud` are treated as remote (parallel-safe). Broadcasts `tool_call` status messages with `server: "sub_agent"` for UI progress. Settings: `sub_agent_tier_fast` and `sub_agent_tier_smart` in the `settings` DB table, exposed via `GET/PUT /api/settings/sub-agents`.
- **`infrastructure/screenshot_runtime.py`** calls `SetProcessDpiAwarenessContext(-4)` (per-monitor V2) at import time via ctypes. Without this, Tkinter reports logical coordinates while the capture API uses physical pixels, causing misaligned region selection on scaled or multi-monitor Windows setups. Also exposes `copy_image_to_clipboard(image, dpi_scale=None)` (copies PIL Image to Windows clipboard via `CF_DIB` with retry loop for busy clipboard) and `copy_file_to_clipboard(filepath)` (uses PowerShell `Set-Clipboard -Path`). `ScreenshotService` has a `start_callback` field for when capture starts (used for window hiding) and a 1.5s debounce via `_last_trigger_time`.
- **`services/shell/approval_history.py`** persists "Allow & Remember" approvals to `user_data/exec-approvals.json`. `_normalize_command()` extracts program + first 2 args for fuzzy matching; stored as SHA256 hash so the file contains no sensitive command text. Uses an in-memory `_approvals_cache` dict protected by `threading.Lock` to avoid repeated file reads.
- **`services/media/transcription.py`** — `TranscriptionService`: records 16kHz mono audio via `pyaudio` into a queue, transcribes on `stop_recording` using `faster-whisper` (`base.en`), broadcasts `transcription_result` via WebSocket. `_recording_error: str | None` attribute surfaces audio errors back to the caller.
- **`services/chat/conversations.py`** — `submit_query` orchestrates the full turn and now requires a concrete `tab_state` (global screenshot fallback removed). Supports `action` parameter (`"submit"` / `"retry"` / `"edit"`) and `target_message_id` for retry/edit flows. When the user cancels mid-generation (`ctx.cancelled`), the method still persists the user prompt and partial assistant response (with `[Response interrupted]` appended) to the DB, creates a conversation record if needed, and broadcasts `conversation_saved`. Tool calls and content blocks executed before cancellation are preserved in the saved message. Screenshots consumed during a turn are always cleared in the `finally` block (covers normal, cancelled, and exception paths). Slash command extraction (`extract_skill_slash_commands`) uses a background thread to parse `/skill-name` tokens via regex `(?<!\S)/([a-zA-Z0-9_-]+)(?=\s|$)` and returns `(forced_skills, llm_query_without_commands)`.

### Screenshot Tab Routing (No Global Fallback)

- Precision screenshot capture (`Alt+.`) always routes to a concrete tab.
- `MessageHandler.handle()` updates `active_tab_id` for most tab-scoped messages, but intentionally skips overwriting it for `tab_closed` so closing a background tab cannot hijack screenshot routing.
- `MessageHandler._handle_tab_closed()` now reassigns `active_tab_id` only when the currently active tab is closed, selecting a remaining tab (or `default`).
- `ScreenshotHandler` resolves target tab via contextvar first, then `active_tab_id`, and finally coerces to `default` session if needed.
- Screenshot add/remove/clear broadcasts are explicitly tab-scoped via `broadcast_to_tab(...)`; no “global screenshot tab” behavior remains.
- Destructive remove flow now fails closed: `_handle_remove_screenshot()` returns early if `tab_id` does not resolve to a live tab state.
- **`services/shell/terminal.py`** — `TerminalSession` class tracks running processes with fields `session_id`, `request_id`, `command`, `process`, `output_buffer`, `text_buffer`, `reader_task`, `exit_code`. `wait_for_completion(timeout)` is async-safe. `get_recent_output(lines=50)` returns ANSI-stripped output via `_ANSI_RE`. `_kill_process_tree(pid)` uses `taskkill /F /T /PID` on Windows, process-group kill on Unix. `kill_running_command()` and `resize_all_pty(cols, rows)` are available (triggered by `terminal_kill_command` and `terminal_resize` WS messages). Terminal events that fire before the first assistant message (no `conversation_id` yet) are queued via `queue_terminal_event()` and flushed to the DB after the conversation record is created via `flush_pending_events(conversation_id)`.
- **`services/media/meeting_recorder.py`** — `MeetingRecorderService` manages one active recording at a time. Audio arrives as base64 PCM chunks via WS, written to `user_data/meeting_audio/<recording_id>.wav` (16kHz, mono, 16-bit). Live Tier 1 transcription runs via `faster-whisper` in a background thread with 5-second chunks and 1-second overlap. Silence detection uses RMS < 50 threshold. `recover_interrupted_recordings()` is called at startup for crash recovery. `PostProcessingPipeline` runs a sequential worker thread with steps: `transcribing → aligning → diarizing → merging → generating_title → saving`, using `faster-whisper large-v3`, WhisperX for alignment, and SpeechBrain for diarization.
- **`services/media/gpu_detector.py`** — `detect_compute_backend()` returns `'cuda'` or `'cpu'`. `get_compute_info()` returns `{backend, device_name, vram_gb, compute_type}` — `float16` if VRAM ≥ 4 GB, else `int8`. `get_estimated_processing_time(audio_duration_seconds)` returns `0.15×` for CUDA, `1.5×` for CPU. Results are cached in a module-level `_cached_backend` singleton.
- **`services/integrations/google_auth.py`** — `GoogleAuthService` manages Google OAuth 2.0 lifecycle. `start_oauth_flow()` runs `InstalledAppFlow.run_local_server(port=0)`, saves `token.json` to `user_data/google/`. `disconnect()` attempts token revocation then deletes the file. `get_status()` returns `{connected, email, auth_in_progress}`. The OAuth client credentials are embedded in `infrastructure/config.py` — this is the Google-recommended pattern for native desktop apps (client_secret is not confidential for installed apps).
- **`services/filesystem/file_browser.py`** — `FileBrowserService` powers the `@` attachment picker. Search reads from a persisted SQLite index (`user_data/file_browser_index.db`) keyed by root path; when an index is missing it falls back to a bounded recursive scan and schedules background indexing. Ranking uses command-palette heuristics (exact > starts-with > contains > compact subsequence) so best matches appear first. File changes are tracked with an event-driven watchdog observer (with queue coalescing) so index refreshes are incremental. The app starts/stops the file indexer + observer from `bootstrap/app_factory.py` startup/shutdown events.
- **`services/skills_runtime/skills.py`** — `SkillManager` caches skill content lazily on `Skill` instances; `invalidate_content_cache()` clears it. `_validate_safe_name(value, label)` enforces `^[a-zA-Z0-9_-]+$` pattern to prevent path traversal. `add_reference_file(name, filename, content)` writes a `.md` file to `skill_folder/references/` (enforces `.md` extension). Skills with `references/` subdirectories have their reference files available to inject as additional context. `get_all_skills_with_overrides()` returns overridden builtins first (greyed out) followed by all active skills.
- **`services/media/video_watcher.py`** — `VideoWatcherService` handles `watch_youtube_video`: normalize URL, extract metadata, prefer native YouTube captions, and fallback to Whisper transcription when captions are unavailable. Fallback path emits a `youtube_transcription_approval` request, waits up to 180s for user approval (`resolve_transcription_approval`), then runs download/transcription in thread pool. Output is bounded to `MAX_TOOL_RESULT_LENGTH` with truncation metadata.
- **`mcp_integration/executors/skills_executor.py`** — inline executor for `list_skills` and `use_skill` tools. `list_skills` returns active skill catalog and usage guidance; `use_skill` resolves one skill and returns full prompt content without spawning MCP subprocesses.
- **`mcp_integration/executors/video_watcher_executor.py`** — inline executor for `video_watcher/watch_youtube_video`, routing args to `VideoWatcherService` and returning user-facing errors (`VideoWatcherError`) as tool results.
- **`mcp_integration/core/tool_args.py`** — `normalize_tool_args(raw_args)` centralizes tool-argument parsing for dict/string/invalid payloads so cloud and Ollama tool loops share the same validation path and error text.

---

## DB Schema

| Table | Key Columns | Notes |
|---|---|---|
| `conversations` | `id` (UUID), `title`, `created_at`, `updated_at`, `total_input_tokens`, `total_output_tokens` | Sort sidebar by `updated_at`; indexed on `updated_at DESC` |
| `messages` | `num_messages` (autoincrement PK), `conversation_id` (NOT NULL), `role` (NOT NULL), `content`, `images` (JSON), `model`, `content_blocks` (JSON), `message_id` (UUID, unique index), `turn_id` (UUID), `active_response_index`, `mobile_origin` (JSON) | `message_id` is the stable per-message identifier used by retry/edit flows; `turn_id` groups a user + assistant pair; indexed on `(conversation_id, created_at)` and `(conversation_id, turn_id, created_at)` |
| `message_response_versions` | `id` (UUID PK), `assistant_message_id` (TEXT, FK→messages.message_id), `response_index` (INTEGER), `content`, `model`, `content_blocks` (JSON), `created_at` | Unique constraint on `(assistant_message_id, response_index)`; stores alternate assistant responses for the same turn; `messages.active_response_index` points at the visible variant |
| `settings` | `key`, `value` | Key-value store for all user preferences including `enabled_models`, `system_prompt_template` |
| `terminal_events` | `id`, `conversation_id` (NOT NULL), `message_index`, `command`, `exit_code`, `output_preview`, `full_output`, `cwd`, `duration_ms`, `timed_out`, `denied`, `pty`, `background` | Full audit trail of executed commands; `pty` and `background` are boolean flags |
| `meeting_recordings` | `id` (UUID PK), `title`, `started_at` (REAL), `ended_at` (REAL), `duration_seconds` (REAL), `status` (TEXT: `recording`/`processing`/`completed`/`failed`), `audio_file_path`, `tier1_transcript` (TEXT), `tier2_transcript_json` (JSON), `ai_summary` (TEXT), `ai_actions_json` (JSON), `ai_title_generated` (INTEGER bool) | Indexed on `started_at DESC` |
| `mobile_paired_devices` | `id` (PK), `platform`, `sender_id`, `display_name`, `paired_at`, `last_active` | Unique on `(platform, sender_id)`. Stores platforms that completed pairing |
| `mobile_sessions` | `id` (PK), `platform`, `sender_id`, `tab_id`, `conversation_id`, `model_override` | Unique on `(platform, sender_id)`. Maps mobile users to Xpdite tabs |
| `mobile_pairing_codes` | `code` (PK), `created_at`, `expires_at`, `claimed` | Short-lived codes for device pairing |
| `conversations_fts` | Virtual FTS5 table: `conversation_id`, `title` | `unicode61` tokenizer; kept in sync by `conversations_fts_ai` / `_au` / `_ad` triggers |
| `messages_fts` | Virtual FTS5 table: `conversation_id`, `content` | `unicode61` tokenizer; kept in sync by `messages_fts_ai` / `_au` / `_ad` triggers; `messages_fts_au` trigger fires on `UPDATE OF content` |

Skills are **no longer in the database** — they are filesystem-backed folders under `user_data/skills/` managed by `SkillManager` in `source/services/skills_runtime/skills.py`. Preferences (enabled/disabled) are stored in `user_data/skills/preferences.json`.

**FTS5 search:** `search_conversations(search_term)` uses `_fts5_phrase(term)` to wrap the query in FTS5 double-quote phrase syntax (internal `"` doubled). Falls back to `LIKE` search with `ESCAPE '\\'` if the FTS virtual tables are missing.

**Migration pattern for new message columns:** `_backfill_message_metadata(cursor)` runs on every `_init_db()` call to assign `message_id`/`turn_id`/`active_response_index` to all existing messages and create their corresponding `message_response_versions` row. This is idempotent — rows that already have IDs are skipped.

**Connection pattern:** All methods use the `_connect()` context manager which ensures cleanup on exit and explicit rollback on error. `_get_connection()` sets PRAGMAs (WAL, foreign_keys, busy_timeout, cache_size, synchronous) on every connection.

**Migration rule:** New columns use `ALTER TABLE … ADD COLUMN` inside `try/except OperationalError` in `_init_db()`. Never alter the original `CREATE TABLE` statement — it would break existing databases.

---

## WebSocket Protocol Reference

### Client → Server

| `type` | Key fields | Handler |
|---|---|---|
| `submit_query` | `content`, `capture_mode`, `model`, `tab_id` | `_handle_submit_query` |
| `retry_message` | `message_id`, `tab_id` | `_handle_retry_message` |
| `edit_message` | `message_id`, `content`, `tab_id` | `_handle_edit_message` |
| `set_active_response` | `message_id`, `response_index`, `tab_id` | `_handle_set_active_response` |
| `clear_context` | `tab_id` | `_handle_clear_context` |
| `remove_screenshot` | `id` | `_handle_remove_screenshot` |
| `set_capture_mode` | `mode` (`fullscreen`/`precision`/`none`) | `_handle_set_capture_mode` |
| `stop_streaming` | `tab_id` | `_handle_stop_streaming` |
| `get_conversations` | `limit`, `offset` | `_handle_get_conversations` |
| `load_conversation` | `conversation_id` | `_handle_load_conversation` |
| `delete_conversation` | `conversation_id` | `_handle_delete_conversation` |
| `search_conversations` | `query` | `_handle_search_conversations` |
| `resume_conversation` | `conversation_id`, `tab_id` | `_handle_resume_conversation` |
| `start_recording` | — | `_handle_start_recording` |
| `stop_recording` | — | `_handle_stop_recording` |
| `terminal_approval_response` | `request_id`, `approved`, `remember` | `_handle_terminal_approval_response` |
| `terminal_session_response` | `approved` | `_handle_terminal_session_response` |
| `terminal_stop_session` | — | `_handle_terminal_stop_session` |
| `terminal_set_ask_level` | `level` (`always`/`on-miss`/`off`) | `_handle_terminal_set_ask_level` |
| `terminal_kill_command` | — | `_handle_terminal_kill_command` |
| `terminal_resize` | `cols`, `rows` (validated: 0 < cols ≤ 500, 0 < rows ≤ 200) | `_handle_terminal_resize` |
| `tab_created` | `tab_id` | `_handle_tab_created` |
| `tab_closed` | `tab_id` | `_handle_tab_closed` |
| `tab_activated` | `tab_id` | `_handle_tab_activated` |
| `cancel_queued_item` | `tab_id`, `item_id` | `_handle_cancel_queued_item` |
| `meeting_start_recording` | `title` | `_handle_meeting_start_recording` |
| `meeting_stop_recording` | `recording_id` | `_handle_meeting_stop_recording` |
| `meeting_cancel_recording` | `recording_id` | `_handle_meeting_cancel_recording` |
| `meeting_get_recordings` | `limit`, `offset` | `_handle_meeting_get_recordings` |
| `meeting_get_recording` | `recording_id` | `_handle_meeting_get_recording` |
| `meeting_delete_recording` | `recording_id` | `_handle_meeting_delete_recording` |
| `meeting_search_recordings` | `query` | `_handle_meeting_search_recordings` |
| `meeting_analyze_recording` | `recording_id` | `_handle_meeting_analyze_recording` |
| `meeting_regenerate_analysis` | `recording_id`, `instructions` | `_handle_meeting_regenerate_analysis` |
| `meeting_get_analysis` | `recording_id` | `_handle_meeting_get_analysis` |
| `meeting_audio_chunk` | `recording_id`, `data` (base64 PCM) | `_handle_meeting_audio_chunk` |
| `meeting_execute_action` | `recording_id`, `action_type` (`create_event`/`create_draft`), `action_data` | `_handle_meeting_execute_action` |
| `youtube_transcription_approval_response` | `request_id`, `approved` | `_handle_youtube_transcription_approval_response` |

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
| `conversation_saved` / `conversations_list` / `conversation_loaded` / `conversation_deleted` / `conversation_resumed` | Conversation management (`conversation_saved` now includes the persisted turn payload used to reconcile retry/edit results on the frontend) |
| `screenshot_ready` | Legacy — kept for backwards compatibility |
| `transcription_result` | After `stop_recording` completes |
| `terminal_approval_request` | Command needs user approval (includes `request_id`, `command`, `cwd`) |
| `terminal_session_request` | LLM requests session mode (includes `reason`) |
| `terminal_session_started` / `terminal_session_ended` | Session mode lifecycle |
| `terminal_output` | PTY output chunks during execution |
| `terminal_command_complete` | Command finished (`exit_code`, `duration_ms`) |
| `terminal_running_notice` | Broadcast 10s after command starts if still running |
| `queue_updated` | Queue items changed for a tab (`tab_id`, `items`) |
| `query_queued` | Broadcast when a query is successfully enqueued (`tab_id`, `item_id`, `position`) |
| `queue_full` | Broadcast when `QueueFullError` is raised (queue already at max 5 items) |
| `ollama_queue_status` | Ollama global queue position broadcast |
| `error` | Any unhandled exception |
| `meeting_recordings_list` | Response to `meeting_get_recordings` |
| `meeting_recording_detail` | Response to `meeting_get_recording` or `meeting_stop_recording` completion |
| `meeting_recording_started` | Recording successfully created and started |
| `meeting_recording_stopped` | Recording stopped; includes `recording_id` and `duration_seconds` |
| `meeting_recording_cancelled` | Recording cancelled before saving |
| `meeting_recording_deleted` | Recording deleted |
| `meeting_recordings_search` | FTS/LIKE search results |
| `meeting_tier1_transcript_chunk` | Live transcript text during recording |
| `meeting_processing_status` | Tier 2 pipeline step progress (`transcribing` → `aligning` → `diarizing` → `merging` → `generating_title` → `saving`) |
| `meeting_processing_complete` | Tier 2 pipeline finished; includes final recording detail |
| `meeting_processing_error` | Tier 2 pipeline failed |
| `meeting_analysis_result` | AI summary + actions after `meeting_analyze_recording` |
| `meeting_action_executed` | Calendar event or email draft created via `meeting_execute_action` |
| `meeting_error` | Meeting-specific error (not generic `error`) |
| `youtube_transcription_approval` | User confirmation request for fallback YouTube audio transcription (includes metadata and estimates) |

**Note:** All server→client messages include a `tab_id` field stamped automatically by `broadcast_message()` via the `_current_tab_id` contextvar.

---

## MCP Integration — How Tool Calls Work

### Ollama path (two-phase)
1. **Detection phase** — non-streaming call with `think=False` and the retrieved tool list. Returns either tool calls or nothing. `think=False` is a workaround for Ollama bug #10976 where `think=True` + tools produces empty output.
2. **Streaming loop** — if tools were requested, enters a `MAX_MCP_TOOL_ROUNDS` loop: execute tools → append results → streaming call for next response. Each intermediate text chunk is broadcast live so the user sees the model's reasoning between tool calls.
3. If no tools were detected in phase 1, the caller falls through to normal streaming (with thinking enabled).
4. **Duplicate retrieval removal** — `route_chat()` now passes its already-retrieved tool list into the Ollama provider/handler path, so `retrieve_relevant_tools(...)` is not run twice for the same request. This trims avoidable startup latency before first token.

### Cloud path (inline via LiteLLM)
All cloud providers (Anthropic, OpenAI, Gemini) use a single unified implementation via `litellm.acompletion()`. `litellm.modify_params = True` is set globally — required for Anthropic thinking+tools to work correctly. The API key is passed directly as a kwarg (not via `os.environ`) for thread safety. Tool definitions use OpenAI format for all providers — LiteLLM translates to native formats. When accumulated tool call deltas are detected after a streaming round ends, tools are executed and results fed back in a multi-round loop (up to `MAX_MCP_TOOL_ROUNDS`). The presence of `pending_tool_calls` is the trigger — not `finish_reason` — because providers like Gemini may use a non-standard finish reason (e.g. `"stop"` instead of `"tool_calls"`). After the tool budget is exhausted, one final summarisation round runs without tools so the model can synthesise its answer. Thinking/reasoning tokens are broadcast via `thinking_chunk`; thinking state (`thinking_tokens`, `thinking_complete_sent`) is **reset per round** so multi-round tool loops get fresh thinking broadcasts. Reasoning/thinking capability and `max_output_tokens` are both derived from a single `litellm.get_model_info()` call cached once per request — no redundant queries and no hardcoded token limits. If the model is not in litellm's registry, `max_tokens` is omitted (except for Anthropic, which requires it — a 16384 fallback is used). If supported, `reasoning_effort` (configurable via `REASONING_EFFORT` in `infrastructure/config.py`) is passed and LiteLLM translates it to each provider's native format (Anthropic → `thinking`, Gemini → `thinkingConfig`/`thinking_level`, OpenAI → native `reasoning_effort`). Malformed tool call JSON is reported back to the model as a tool-result error so it can self-correct. Cancellation during tool execution properly exits both the inner tool loop and the outer streaming loop. On exceptions, partial accumulated text and tool calls are preserved (not discarded). Providers that omit `tool_call_id` (e.g. Gemini) receive synthetic fallback IDs. `_sanitize_tool_args(value)` scrubs sensitive keys (`api_key`, `token`, `secret`, `password`, `authorization`, `cookie`, `session`, `key`) from tool arguments before logging/broadcasting — replaces values with `"[REDACTED]"`.

### Tool Retrieval
`ToolRetriever` embeds tool descriptions and user query using Ollama (`nomic-embed-text`) or `sentence-transformers`. Top-K most similar tools are passed to the LLM, reducing context noise. Similarity is gated by `MIN_SIMILARITY_THRESHOLD = 0.3` — tools below this floor are excluded even if in the top-K. Embeddings are cached to `user_data/cache/tool_embeddings.npz` keyed by `sha256(model_name|description)`, with `user_data/cache/tool_embedding_index.json` tracking the latest key per tool so stale embeddings are pruned when descriptions change or tools are removed. "Always on" tools bypass the filter (configured in Settings → Tools). `retrieve_relevant_tools` is shared between the Ollama and cloud paths — both call it to build `allowed_tool_names`.

### `McpToolManager` — Key Methods
- `register_inline_tools(server_name, tools)` — registers tool schemas for inline (non-subprocess) tools like terminal tools. No subprocess is spawned.
- `get_tools()` — returns OpenAI-format tool list, strips `additionalProperties`. `get_openai_tools` is a backward-compat alias.
- `call_tool(...)` — has a 3-minute `asyncio.wait_for` timeout ceiling.
- `connect_google_servers()` / `disconnect_google_servers()` — start/stop Gmail and Calendar MCP servers on demand.
- Startup batching rule: when connecting multiple MCP servers in parallel during app boot, pass `skip_embed=True` to `connect_server(...)` and perform one final `refresh_tool_embeddings()` after the batch. Re-embedding after every individual server connection causes repeated retrieval-index rebuilds and noticeably slows startup.

### Skill Injection
`skill_injector.py` uses a two-phase injection strategy:
1. **Compact manifest** — a one-liner-per-skill list always present in the system prompt so the agent knows what capabilities exist. The manifest includes the skills directory path and each skill's folder path.
2. **Full injection** — the complete `SKILL.md` content, injected only when triggered by a `/slash` command or auto-detected dominant MCP server.

Skills are managed by `SkillManager` in `source/services/skills_runtime/skills.py`. Builtin skills live in `user_data/skills/builtin/` (seeded from `source/skills_seed/` on every startup). User skills live in `user_data/skills/user/`. A `preferences.json` file stores enabled/disabled state so builtin overwrites never reset user toggles. Skills can have a `references/` subdirectory with `.md` files for supplemental context.

### Terminal Tools (Inline)
Terminal tools are handled inline by `source/mcp_integration/executors/terminal_executor.py`, never via the MCP subprocess. Full set: `run_command`, `request_session_mode`, `end_session_mode`, `send_input`, `read_output`, `kill_process`, `get_environment`. `run_command` accepts `background=True` and `yield_ms` params.

### Additional Inline Tool Executors
- **Video watcher (`video_watcher`)**: `watch_youtube_video` is registered as inline and intercepted before MCP subprocess routing. Execution is delegated to `source/mcp_integration/executors/video_watcher_executor.py` / `source/services/media/video_watcher.py`, including the user-approval fallback path (`youtube_transcription_approval` → `youtube_transcription_approval_response`) when no captions are available.
- **Skills (`skills`)**: `list_skills` and `use_skill` are inline tools executed by `source/mcp_integration/executors/skills_executor.py`. Unlike terminal/sub_agent/video_watcher registrations, these are indexed for semantic retrieval (`skip_embed=False`) so models can discover skill-loading tools contextually.

### Adding a New MCP Server (end-to-end)

1. **Create** `mcp_servers/servers/<name>/server.py` with `@mcp.tool()` functions.
2. **Connect** in `source/mcp_integration/core/manager.py`'s `init_mcp_servers()`:
   ```python
   await mcp_manager.connect_server(
       "your_name",
       sys.executable,
       [str(PROJECT_ROOT / "mcp_servers" / "servers" / "your_name" / "server.py")]
   )
   ```
3. **Optionally update** `mcp_servers/config/servers.json` with metadata (used by the Settings UI; not read by the backend).
4. **Optionally add a skill** by creating a folder under `source/skills_seed/<your_name>/` with a `skill.json` and `SKILL.md` file. The skill will be auto-seeded to `user_data/skills/builtin/` on startup.
5. If the new server's tool calls should render cleanly in the chat timeline, update `src/ui/components/chat/toolCallUtils.ts` (and the summary helper used by `ToolCallsDisplay.tsx`) with badge/text mappings for the new server and its tools.
6. Tools are auto-discovered, indexed by the retriever, and available immediately.

---

## REST API Reference

All endpoints are in `source/api/http.py` unless noted.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/models` | Ollama models list |
| `GET` | `/api/cloud-models` | All enabled cloud models per provider |
| `GET` | `/api/keys` | Provider API key status (present/absent) |
| `POST` | `/api/keys/{provider}` | Save encrypted API key; triggers model list refresh |
| `DELETE` | `/api/keys/{provider}` | Delete key; also removes that provider's models from `enabled_models` |
| `GET` | `/api/models/enabled` | User's enabled model list |
| `PUT` | `/api/models/enabled` | Save enabled model list |
| `POST` | `/api/keys/{provider}/validate` | Validate API key with a test request. Anthropic tries `["claude-sonnet-4-20250514", "claude-3-haiku-20240307"]` with fallback |
| `GET` | `/api/mcp/servers` | Sorted list of connected MCP servers + their tool names |
| `GET` | `/api/skills` | All skills (with overrides) |
| `POST` | `/api/skills` | Create a user skill |
| `GET` | `/api/skills/{name}` | Get a single skill |
| `PATCH` | `/api/skills/{name}` | Update skill fields (uses `_UNSET` sentinel for `slash_command` to distinguish "not sent" from null) |
| `DELETE` | `/api/skills/{name}` | Delete a user skill |
| `PUT` | `/api/skills/{name}/toggle` | Enable/disable a skill |
| `GET` | `/api/skills/{name}/content` | Return full `SKILL.md` text |
| `POST` | `/api/skills/{name}/references` | Add a `.md` reference file to a skill; enforces `.md` extension (`ReferenceFileCreate`: `filename`, `content`) |
| `GET` | `/api/google/status` | Google OAuth connection status |
| `POST` | `/api/google/connect` | Start OAuth flow (opens browser) |
| `POST` | `/api/google/disconnect` | Revoke + delete token |
| `GET` | `/api/settings/system-prompt` | Returns template text + `is_custom: bool` (returns `_BASE_TEMPLATE` if no custom set) |
| `PUT` | `/api/settings/system-prompt` | Save custom template; send null/empty to reset to base |
| `GET` | `/api/terminal/settings` | Terminal settings | `source/api/terminal.py` |
| `PUT` | `/api/terminal/settings/ask-level` | Set approval level | `source/api/terminal.py` |
| `DELETE` | `/api/terminal/approvals` | Clear remembered approvals | `source/api/terminal.py` |
| `POST` | `/internal/mobile/message` | Mobile message entrypoint | `source/api/mobile_internal.py` |
| `POST` | `/internal/mobile/command` | Execute `/new`, `/stop` mobile commands | `source/api/mobile_internal.py` |
| `POST` | `/internal/mobile/pair/verify` | Verify pairing code | `source/api/mobile_internal.py` |
| `POST` | `/internal/mobile/pair/generate` | Generate pairing code | `source/api/mobile_internal.py` |
| `GET` | `/internal/mobile/devices` | Get paired devices | `source/api/mobile_internal.py` |
| `DELETE` | `/internal/mobile/devices/{device_id}` | Revoke device | `source/api/mobile_internal.py` |
| `POST` | `/internal/mobile/whatsapp/connection` | Update WhatsApp conn status | `source/api/mobile_internal.py` |
| `GET` | `/internal/mobile/sessions` | List active sessions | `source/api/mobile_internal.py` |
| `GET` | `/api/files/browse` | Browse/search files for `@` attachments | `source/api/http.py` |

**Model filtering rules:**
- **Gemini**: Skips models containing `"embedding"`, `"aqa"`, `"bison"`, `"gecko"`; strips `"models/"` prefix from names.
- **OpenAI**: Includes models starting with `"gpt-"`, `"o1"`, `"o3"`, `"o4"`, `"chatgpt-"`, `"gpt-5"`; excludes names containing `"search"`.

---

## Skills Seed Directory

| Skill | `slash_command` | `trigger_servers` | Notes |
|---|---|---|---|
| `terminal` | `terminal` | `["terminal"]` | PTY + approval flow |
| `filesystem` | `filesystem` | `["filesystem", "glob", "grep"]` | Read/write files plus dedicated structured search servers |
| `websearch` | `websearch` | `["websearch"]` | Web search |
| `gmail` | `gmail` | `["gmail"]` | Gmail MCP server |
| `calendar` | `calendar` | `["calendar"]` | Google Calendar MCP server |
| `browser` | `browser` | `[]` | Playwright-CLI automation; NOT server-backed. Uses `run_command` via terminal tools to interact with a playwright-cli daemon. `--headed` always. Has a `references/` subdirectory. Empty `trigger_servers` means never auto-injects — only activated by `/browser` slash command. |

---

## Config Constants

Key constants from `infrastructure/config.py` (also re-exported by `source/infrastructure/config.py`):

| Constant | Value | Notes |
|---|---|---|
| `DEFAULT_MODEL` | `"qwen3-vl:8b-instruct"` | Default Ollama model |
| `OLLAMA_CTX_SIZE` | `32768` | Context window size passed as `num_ctx` |
| `MAX_TOOL_RESULT_LENGTH` | `100_000` | Truncation limit for MCP tool result strings |
| `TERMINAL_MAX_OUTPUT_SIZE` | `50 * 1024` (50 KB) | Max bytes stored in `terminal_events.full_output` |
| `THREAD_POOL_SIZE` | env `XPDITE_THREAD_POOL_SIZE` or default | Override thread pool size |
| `XPDITE_USER_DATA_DIR` env var | — | Electron sets this in production to point to the correct user data dir |

---

## Architecture Decisions

**Why `check_same_thread=False` on every SQLite connection?**
FastAPI runs handlers on different threads in its thread pool. A per-call `_get_connection()` pattern creates a new connection for every DB call, avoiding cross-thread reuse while staying compatible with asyncio. Each connection is wrapped in the `_connect()` context manager for exception-safe cleanup. WAL mode is enabled for concurrent reads during writes, and `busy_timeout=5000` prevents instant lock failures.

**Why does the Ollama tool-detection call use `think=False`?**
Ollama bug #10976: models with thinking enabled return empty `tool_calls` even when they intend to call tools. The detection phase disables thinking specifically to surface tool calls correctly; thinking is re-enabled in the streaming follow-up.

**Why is terminal execution handled inline rather than via the MCP subprocess?**
Terminal commands need approval UI, PTY streaming, cancellation, and DB persistence — all of which require access to the app's WebSocket connection and state. Routing through a subprocess would require a separate approval protocol. Inline execution makes the approval/streaming/audit pipeline a first-class part of the app.

**Why is `RequestContext` separate from `AppState`?**
`AppState` is long-lived (entire process). `RequestContext` is per-request and garbage-collected after each turn. This makes cancellation scoping clean — cancelling the current request doesn't corrupt state for the next one.

**Why use ContextVars for request context and model instead of passing them as parameters?**
The call chain from `submit_query` → `route_chat` → `stream_ollama_chat` → `handle_mcp_tool_calls` is deep, and some callsites (MCP tool detection, Ollama fallback) would need threading the model/request through 4+ function signatures. ContextVars provide implicit per-async-task scoping without changing any function signatures, and they naturally isolate concurrent tabs running on the same event loop.

**Why does the Ollama global queue exist?**
Local Ollama on a single GPU can only serve one inference request at a time. Without serialization, concurrent tabs sending local Ollama requests would cause GPU contention, timeouts, and garbled responses. Cloud providers (Anthropic, OpenAI, Gemini) and Ollama cloud models (`-cloud`) don't have this limitation and run concurrently.

**Why does `McpToolManager.connect_server` use a background asyncio Task?**
`anyio` (used by `mcp`) requires that `stdio_client` and `ClientSession` context managers enter and exit on the *same* task. Using a dedicated background task per server avoids the "cancel scope in a different task" RuntimeError when disconnecting from an HTTP handler.

**Why does `ollama_provider.py` use `AsyncClient` instead of the sync `Client`?**
Ollama's Python SDK (v0.4+) provides `ollama.AsyncClient` with an identical API to the sync `Client`. The async client returns native async iterators from `chat(stream=True)`, allowing direct `async for chunk in stream:` consumption on the event loop — no background threads, no `asyncio.Queue`, no `wrap_with_tab_ctx`. This matches the pattern used by the cloud providers (Anthropic, OpenAI, Gemini) and eliminates the threading complexity that previously existed.

**Why `wrap_with_tab_ctx` in `connection.py`?**
Python's `contextvars.ContextVar` propagates automatically through `await` chains on the same task, but does NOT carry over when scheduling a new task from a background thread via `loop.call_soon_threadsafe(asyncio.create_task, coro)` or `asyncio.run_coroutine_threadsafe(coro, loop)`. The new task gets the event loop's root context, which has no `_current_tab_id`. This matters for the precision-mode screenshot hotkey, which fires from a native `pynput` listener thread and schedules `broadcast_message()` back to the loop. `wrap_with_tab_ctx` captures the tab_id before entering the thread and applies it as a thin wrapper around every coroutine scheduled back. All LLM providers (including Ollama via `AsyncClient`) are now fully async and don't cross a thread boundary, so they don't need this wrapper.

**Why are screenshots stored per-tab instead of globally?**
Each tab is an independent conversation. Screenshots attached in one tab should not appear in another tab's context. `ScreenshotHandler` writes to `tab_state.screenshot_list` (resolved via explicit parameter, `_current_tab_id` contextvar, or `app_state.active_tab_id` fallback). The `active_tab_id` is tracked by `MessageHandler.handle()` on every incoming WS message. For precision-mode hotkey captures (background thread), `process_screenshot` snapshots `active_tab_id` at schedule time and wraps the event-loop coroutine with `wrap_with_tab_ctx` so both the contextvar and the active-tab lookup resolve correctly.

**Why is fullscreen screenshot capture done in the handler, not in `submit_query`?**
Fullscreen auto-capture (first message of a new conversation in fullscreen mode) runs in `_handle_submit_query` *before* the query is enqueued. This is intentional: if it ran inside `submit_query`, it would be serialized behind the Ollama global queue — meaning tab 2's screenshot could be blocked for minutes while tab 1's LLM response is generating. By capturing in the handler, the screenshot runs immediately on the event loop regardless of queue state. The blocking `take_fullscreen_screenshot` call is offloaded via `run_in_thread` to avoid stalling the event loop.
`asyncio.Event` can't cross process boundaries. The MCP terminal server runs as a stdio child process, so blocking until the user confirms must happen in the parent FastAPI process where the WebSocket connection lives.

**Why are 3 of the 4 terminal security layers invisible?**
Layer 1 (blocklist), Layer 2 (PATH injection detection), Layer 3 (120s hard timeout) are never surfaced to the user or LLM. Exposing them would allow social engineering ("just disable the blocklist first"). Only Layer 4 (approval prompts) is visible.

**Why does session mode auto-expire in `submit_query`'s `finally` block?**
LLMs reliably call `request_session_mode` but almost never call `end_session_mode`. Auto-expiring on turn end guarantees cleanup regardless of how the turn ends (completion, cancellation, error).

**Why are images included in the Ollama tool-detection call?**
The model needs to see image content to make informed tool-calling decisions — e.g., a screenshot containing a URL where the user asks "read this" requires the model to extract the URL *from the image* before it can call `read_website`. The non-streamed detection call includes images alongside tool definitions.
