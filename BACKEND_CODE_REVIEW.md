# Backend Code Review — `source/`

> **Date:** February 22, 2026
> **Scope:** All files under `source/` (~25 files across 6 subdirectories)
> **Goal:** Production-quality code + excellent open-source DX

## How to Use This Document

Each issue has a checkbox. Work through them in phase order (Critical → High → Medium → Low).
Mark issues `[x]` as you fix them. Issues are grouped by phase, then by file.

**Severity counts:**

| Severity | Count |
|----------|-------|
| Critical | 5 |
| High | 14 |
| Medium | 33 |
| Low | 30 |

---

## Phase 1 — Critical Issues (crashes, data corruption)

### C1. `_clear_folder` crashes on subdirectories
- [x] **File:** `source/core/lifecycle.py` — Lines 78–82
- **Problem:** `os.remove(file_path)` is called on every match from `glob.glob(os.path.join(folder_path, "*"))`. If the folder contains subdirectories, this raises `PermissionError` (Windows) or `IsADirectoryError` (POSIX), crashing cleanup.
- **Fix:**
```python
def _clear_folder(folder_path):
    """Remove all files (not subdirectories) from a folder."""
    for file_path in glob.glob(os.path.join(folder_path, "*")):
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                print(f"Warning: Could not remove {file_path}: {e}")
```

### C2. `OPENAI_FALLBACK` and `GEMINI_FALLBACK` defined twice — second silently overwrites first
- [x] **File:** `source/api/http.py`
- **Problem:** Both lists are assigned twice. The second definitions (older, less accurate lists) overwrite the first.
  - `OPENAI_FALLBACK` first: Line 243 `["o3-mini", "o1", "gpt-4o", "gpt-4o-mini", "o1-mini"]`
  - `OPENAI_FALLBACK` second (wins): Line 262 `["gpt-4o", "gpt-4o-mini", "o1-preview", "o1-mini", "gpt-4-turbo"]`
  - `GEMINI_FALLBACK` first: Line 251 `["gemini-2.0-flash", "gemini-2.0-pro-exp-0505", "gemini-1.5-pro", "gemini-1.5-flash"]`
  - `GEMINI_FALLBACK` second (wins): Line 270 `["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b"]`
- **Fix:** Delete the second (duplicate) definition of each. Keep the first (more current) lists. The duplicate definitions and any surrounding dead code (lines ~260–298) should be removed entirely.

### C3. `call_tool()` crashes when `session` is `None` (inline tools)
- [x] **File:** `source/mcp_integration/manager.py` — Lines 224–230
- **Problem:** Inline tools (terminal) have `session=None` by design (registered via `register_inline_tools` at line 187). If the handler layer fails to intercept, `session.call_tool()` raises `AttributeError`.
- **Fix:** Add a guard at the top of `call_tool()`:
```python
if session is None:
    return f"Error: Tool '{tool_name}' is an inline tool (server '{entry['server_name']}') and cannot be called via MCP session. It must be handled by the inline tool executor."
```

### C4. Return type mismatch across entire LLM module (3-tuple declared, 4-tuple returned)
- [x] **Files & lines:**
  - `source/llm/router.py` Line 35 — declares 3-tuple
  - `source/llm/ollama_provider.py` Line 50 — declares 3-tuple
  - `source/llm/cloud_provider.py` Lines 133, 394, 684, 924 — all declare 3-tuple
  - Early returns that return 3-tuples (crash when caller unpacks 4): cloud_provider.py Lines 166, 430, 722
- **Problem:** Every streaming function declares `tuple[str, Dict, List]` but actually returns `(text, stats, tool_calls, interleaved_blocks)`. The early-return paths return 3-tuples causing **unpacking errors**.
- **Fix:** 
  1. Define a `NamedTuple` in a shared location (e.g., `source/llm/__init__.py` or a new `source/llm/types.py`):
     ```python
     from typing import NamedTuple, Dict, List, Any, Optional
     
     class ChatResult(NamedTuple):
         response_text: str
         token_stats: Dict[str, int]
         tool_calls: List[Dict[str, Any]]
         interleaved_blocks: Optional[List[Dict[str, Any]]] = None
     ```
  2. Update all function signatures to return `ChatResult`.
  3. Fix the 3 early returns (lines 166, 430, 722 of cloud_provider.py) to include `None` as the 4th element (or use `ChatResult(..., interleaved_blocks=None)`).

### C5. `TranscriptionService.stop_recording()` blocks the event loop
- [x] **File:** `source/services/transcription.py` — Line 65
- **Problem:** `self.recording_thread.join()` is blocking. Additionally, `_load_model()` (Whisper model loading) is heavy CPU/IO.
- **Context:** The handler at `source/api/handlers.py` Lines 203–208 correctly uses `run_in_thread` for `stop_recording`, so the event loop isn't actually blocked at the current call site. However, `start_recording` at Line 200 does NOT use `run_in_thread`. 
- **Fix (2 parts):**
  1. Wrap `start_recording` in `run_in_thread` at `source/api/handlers.py` Line 200:
     ```python
     await run_in_thread(app_state.transcription_service.start_recording)
     ```
  2. Also fix the other `transcription.py` issues (see M23, L22, L23 below).

---

## Phase 2 — High-Severity Issues

### H1. `RequestContext.cancelled` never checked in tool/streaming loops
- [x] **Files & locations:**
  - `source/mcp_integration/handlers.py` — tool loop (~Lines 130–270)
  - `source/mcp_integration/cloud_tool_handlers.py` — all 3 provider tool loops
  - `source/llm/cloud_provider.py` — all 3 streaming functions
  - `source/services/conversations.py` — `submit_query` post-processing
- **Problem:** The CLAUDE.md rule says: *"Don't skip `RequestContext.cancelled` checks inside long-running loops."* Currently only the global `app_state.stop_streaming` is checked, meaning cancelling one request cancels ALL concurrent requests.
- **Fix:** In every tool execution loop and streaming loop, add checks like:
```python
if ctx and ctx.cancelled:
    break
```
Where `ctx` is the current `RequestContext`. Also check after `route_chat` returns in `conversations.py` `submit_query` (~Line 159): `if ctx.cancelled: return`.

### H2. `cleanup_resources()` runs twice on shutdown
- [x] **File:** `source/core/lifecycle.py` — Lines 85–88 (signal handler) and Line 96 (atexit)
- **Problem:** Signal handler calls `cleanup_resources()` then `sys.exit(0)`. `atexit.register(cleanup_resources)` fires during `sys.exit`. MCP cleanup is not idempotent.
- **Fix:** Add an idempotency guard:
```python
_cleanup_done = False

def cleanup_resources():
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    # ... rest of cleanup
```

### H3. Thread pool executor never shut down
- [x] **File:** `source/core/thread_pool.py` — Line 21
- **Problem:** `_app_executor` (ThreadPoolExecutor with `max_workers=4`) is never shut down during cleanup. Worker threads block process exit.
- **Fix:**
  1. Add a `shutdown_thread_pool()` function:
     ```python
     def shutdown_thread_pool():
         _app_executor.shutdown(wait=False, cancel_futures=True)
     ```
  2. Call it from `cleanup_resources()` in `lifecycle.py`.

### H4. Fire-and-forget `asyncio.create_task` with no error handling
- [x] **File:** `source/api/handlers.py` — Line 98
- **Problem:** `asyncio.create_task(ConversationService.submit_query(...))` — if `submit_query` raises, user gets no error feedback. Produces only a `Task exception was never retrieved` warning.
- **Fix:** Wrap in a safe helper:
```python
async def _safe_submit_query(self, *args, **kwargs):
    try:
        await ConversationService.submit_query(*args, **kwargs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await self.websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Query failed: {str(e)[:200]}"
            }))
        except Exception:
            pass

# Then in _handle_submit_query:
asyncio.create_task(self._safe_submit_query(...))
```

### H5. `chat_history.copy()` is shallow — shared references corrupt state
- [x] **File:** `source/services/conversations.py` — Line 159
- **Problem:** `.copy()` on a list of dicts gives a shallow copy. If `route_chat` mutates any inner dict (e.g., pops `images`), it corrupts `app_state.chat_history`.
- **Fix:**
```python
import copy
# Line 159: change
history_copy = copy.deepcopy(app_state.chat_history)
```

### H6. Blocking Ollama embedding calls on event loop
- [x] **File:** `source/mcp_integration/retriever.py` — Lines 95–123
- **Problem:** `_get_embedding()` calls `ollama.embeddings(...)` synchronously. Each `embed_tools()` call does N blocking HTTP requests during server connection.
- **Fix:** The callers of `embed_tools()` and `retrieve_tools()` should use `run_in_thread`:
```python
# In manager.py where embed_tools is called:
await run_in_thread(retriever.embed_tools, tools_data)

# In handlers.py where retrieve_tools is called:
tools = await run_in_thread(retriever.retrieve_tools, query, ...)
```
Alternatively, make the retriever methods async internally.

### H7. Key derivation uses single SHA-256 pass
- [x] **File:** `source/llm/key_manager.py` — Line 67
- **Problem:** `hashlib.sha256(salt + material).digest()` is fast and brute-forceable.
- **Fix:**
```python
import hashlib
# Replace:
#   key = hashlib.sha256(salt + material).digest()
# With:
key = hashlib.pbkdf2_hmac('sha256', material, salt, iterations=100_000)
```
> **Note:** This is a breaking change — existing encrypted keys won't decrypt. Either add a migration path or document that existing API keys must be re-entered after this update.

### H8. Error text from LLM SDK stored as chat response
- [x] **Files:** `source/llm/cloud_provider.py` (Lines ~312, ~600, ~900), `source/llm/ollama_provider.py` (Line ~288)
- **Problem:** When an API call fails, the error string (which may contain API keys in URL, internal details) is returned as `response_text` and saved to the DB as an assistant message.
- **Fix:** Return empty string for `response_text`, and broadcast the error separately:
```python
except Exception as e:
    error_msg = f"LLM API error: {type(e).__name__}"
    await broadcast_message(websocket, "error", error_msg)
    print(f"[LLM] Full error: {e}")  # or use logging
    return "", total_token_stats, tool_calls_list, interleaved_blocks
```

### H9. No timeouts on cloud API streaming calls
- [x] **File:** `source/llm/cloud_provider.py`
- **Problem:** If Anthropic/OpenAI/Gemini hangs mid-stream, the connection blocks indefinitely.
- **Fix:** Pass timeout configuration to each client:
```python
# Anthropic
client = anthropic.AsyncAnthropic(api_key=api_key, timeout=httpx.Timeout(300.0, connect=10.0))

# OpenAI
client = openai.AsyncOpenAI(api_key=api_key, timeout=httpx.Timeout(300.0, connect=10.0))
```
Or wrap the streaming in `asyncio.wait_for(stream_call, timeout=300)`.

### H10. `send_input` decodes arbitrary escape sequences from LLM
- [x] **File:** `source/services/terminal.py` — Line 806
- **Problem:** `.encode("raw_unicode_escape").decode("unicode_escape")` allows the LLM to inject arbitrary control characters into the PTY.
- **Fix:** Replace with explicit whitelist:
```python
def _decode_safe_escapes(text: str) -> str:
    """Only decode known-safe escape sequences."""
    replacements = {
        r'\n': '\n',
        r'\r': '\r',
        r'\t': '\t',
        r'\x03': '\x03',  # Ctrl-C
        r'\x1b': '\x1b',  # ESC
        r'\x04': '\x04',  # Ctrl-D / EOF
    }
    result = text
    for escaped, actual in replacements.items():
        result = result.replace(escaped, actual)
    return result

# In send_input:
decoded = _decode_safe_escapes(text)
```

### H11. `GoogleAuthService.start_oauth_flow()` blocks event loop
- [x] **File:** `source/services/google_auth.py` — Lines 130–150
- **Problem:** `flow.run_local_server()` starts an HTTP server and waits for browser callback — entirely blocking.
- **Fix:** The call site (in `source/api/http.py`) must wrap this in `run_in_thread`:
```python
result = await run_in_thread(google_auth.start_oauth_flow)
```
Check the HTTP endpoint that calls this and wrap it.

### H12. WebSocket protocol docstring is stale — missing 16+ message types
- [x] **File:** `source/api/websocket.py` — Lines 18–52
- **Problem:** Violates the rule: *"Don't add a new WS message type without updating the protocol docstring."* Missing client→server types: `start_recording`, `stop_recording`, `terminal_approval_response`, `terminal_session_response`, `terminal_stop_session`, `terminal_kill_command`, `terminal_set_ask_level`, `terminal_resize`. Missing server→client types: `terminal_approval_request`, `terminal_session_request`, `terminal_session_started`, `terminal_session_ended`, `terminal_running_notice`, `terminal_output`, `terminal_command_complete`, `transcription_result`.
- **Fix:** Update the docstring to match reality. Cross-reference with `source/api/handlers.py` for all `_handle_*` methods and with all `broadcast_message` calls throughout the codebase.

### H13. `broadcast()` iterates directly over `active_connections`
- [x] **File:** `source/core/connection.py` — Line 41
- **Problem:** The list is iterated directly. While disconnects are deferred, a concurrent `connect()` call from another coroutine could modify the list mid-iteration.
- **Fix:** Iterate over a snapshot:
```python
for connection in list(self.active_connections):
```

### H14. `asyncio.Lock()`/`asyncio.Event()` created outside running loop
- [x] **Files:**
  - `source/core/state.py` — Lines 32, 39 (`asyncio.Lock()`)
  - `source/core/request_context.py` — Line 40 (`asyncio.Event()`)
- **Problem:** On Python < 3.10, creating these outside an async context raises or warns. While 3.10+ is likely the floor, it's fragile.
- **Fix (state.py):** Create locks lazily:
```python
self._request_lock: Optional[asyncio.Lock] = None
self._stream_lock: Optional[asyncio.Lock] = None

@property
def request_lock(self) -> asyncio.Lock:
    if self._request_lock is None:
        self._request_lock = asyncio.Lock()
    return self._request_lock
```
**Fix (request_context.py):** `RequestContext` is always instantiated inside an async function, so add a comment documenting this requirement. Or use a `threading.Event` (which doesn't have the loop issue) since `mark_done`/`wait_done` cross thread boundaries.

---

## Phase 3 — Medium-Severity Issues

### M1. Business logic (slash command parsing) in API layer
- [x] **File:** `source/api/handlers.py` — Lines 18–49 (`extract_skill_slash_commands`) and Lines 88–95
- **Problem:** Per project rules: *"Never put business logic in `api/` layer."* Slash command extraction should be in `services/`.
- **Fix:** Move `extract_skill_slash_commands` to `source/services/conversations.py` (or a new `source/services/skills.py`). Have `ConversationService.submit_query` handle the parsing internally.

### M2. Double JSON serialization in handler responses
- [x] **File:** `source/api/handlers.py` — Lines 145, 158, 174, 188
- **Problem:** `json.dumps({"type": ..., "content": json.dumps(data)})` forces the frontend to `JSON.parse()` twice.
- **Fix:** Pass data directly: `json.dumps({"type": "conversations_list", "content": conversations})`. This requires matching frontend changes in the websocket message handlers.

### M3. `set_ask_level` returns error as 200 instead of HTTPException
- [x] **File:** `source/api/terminal.py` — Lines 39–42
- **Problem:** `return {"error": "Invalid ask level..."}` with 200 status. Frontend probably doesn't check for `error` key in 200 responses.
- **Fix:**
```python
from fastapi import HTTPException
raise HTTPException(status_code=400, detail="Invalid ask level. Must be 'always', 'on-miss', or 'off'")
```
Also update `AskLevelRequest` (Line 22) to use `Literal`:
```python
from typing import Literal
level: Literal['always', 'on-miss', 'off']
```

### M4. Double DB write for default skill updates
- [x] **File:** `source/api/http.py` — Lines 694–705
- **Problem:** `db.upsert_skill(...)` at Line 694 already writes the new content, then `db.update_skill_content(skill_name, body.content)` at Line 705 writes it again. Redundant second write.
- **Fix:** Remove the `db.update_skill_content(...)` call since `upsert_skill` already handles the content update. Alternatively, consolidate the `is_modified` tracking into `upsert_skill`.

### M5. Hardcoded model for Anthropic key validation
- [x] **File:** `source/api/http.py` — Line 159 (approximately)
- **Problem:** `model="claude-3-haiku-20240307"` is hardcoded. If this model is deprecated by Anthropic, all key validation fails.
- **Fix:** Use a lightweight validation approach that doesn't depend on a specific model, or catch model-not-found and fall back to another model.

### M6. Sync DB call (`db.get_all_skills()`) on event loop
- [x] **File:** `source/api/handlers.py` — Lines 18–49
- **Problem:** `extract_skill_slash_commands` calls `db.get_all_skills()` synchronously on the event loop. Per rules: *"blocking-IO work goes through `run_in_thread`."*
- **Fix:** Once moved to services (M1), make it async with `run_in_thread`. For SQLite with small tables, this is low-risk but violates the pattern.

### M7. `start_recording()` likely blocking on event loop
- [x] **File:** `source/api/handlers.py` — Line 200
- **Problem:** `app_state.transcription_service.start_recording()` called directly (not via `run_in_thread`), unlike `stop_recording` which correctly uses `run_in_thread` at Lines 203–208.
- **Fix:**
```python
await run_in_thread(app_state.transcription_service.start_recording)
```

### M8. `_truncate_result` duplicated across two files
- [x] **Files:**
  - `source/mcp_integration/handlers.py` — Line 68
  - `source/mcp_integration/cloud_tool_handlers.py` — Line ~710
- **Problem:** Identical function with same magic number (100000).
- **Fix:** Keep one copy (in `handlers.py` or extract to a shared utils module like `source/mcp_integration/utils.py`). Import from the other file. Also extract `100000` to a named constant `MAX_TOOL_RESULT_LENGTH = 100_000` in `config.py`.

### M9. `retrieve_relevant_tools` logic duplicated in cloud handlers
- [x] **Files:**
  - `source/mcp_integration/handlers.py` — Line 30 (shared helper)
  - `source/mcp_integration/cloud_tool_handlers.py` — Lines 48–76 (reimplemented inline)
- **Problem:** Same logic for getting always-on tools, calling retriever, etc. is copy-pasted.
- **Fix:** Have `cloud_tool_handlers.py` import and use `retrieve_relevant_tools` from `handlers.py`.

### M10. `safe_schedule` uses fire-and-forget `create_task` from thread
- [x] **File:** `source/mcp_integration/handlers.py` — Lines ~310–350
- **Problem:** `loop.call_soon_threadsafe(asyncio.create_task, coro)` — if broadcast fails, exception is silently lost.
- **Fix:**
```python
def safe_schedule(coro):
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        pass  # Loop closed
```

### M11. Bare `except:` clauses
- [x] **Files & lines:**
  - `source/api/http.py` Line 570 — `except:` in `get_tools_settings`
  - `source/mcp_integration/cloud_tool_handlers.py` Line ~62
- **Fix:** Change to `except Exception:` (or more specific types like `except json.JSONDecodeError:`).

### M12. Message converters skip `tool` role — latent bug
- [x] **File:** `source/mcp_integration/cloud_tool_handlers.py` — Line ~259
- **Problem:** All three `_to_*_messages()` converters skip `role == "tool"` messages. If the messages list is ever re-converted (e.g., in a future refactor), tool results would be stripped.
- **Fix:** Add a comment explaining the assumption that conversion happens only once, or better — convert only messages up to the current index.

### M13. `max_tokens` hardcoded in multiple places
- [x] **Files:**
  - `source/mcp_integration/cloud_tool_handlers.py` Lines ~131, ~244 — `max_tokens=4096`
  - `source/llm/cloud_provider.py` Line ~166 — `max_tokens: 16384`
  - `source/llm/ollama_provider.py` Line ~137 — `"num_ctx": 32768`
- **Fix:** Extract to `source/config.py`:
```python
CLOUD_MAX_TOKENS = 16384
OLLAMA_CTX_SIZE = 32768
CLOUD_TOOL_MAX_TOKENS = 4096
```

### M14. `np.zeros(1)` fallback breaks cosine similarity
- [x] **File:** `source/mcp_integration/retriever.py` — Lines 105, 123
- **Problem:** When embedding fails, `np.zeros(1)` (1-dimensional) is returned. Real embeddings are e.g. 768-dimensional. Shape mismatch causes the tool to always be skipped.
- **Fix:** Return `None` on failure and handle `None` explicitly:
```python
def _get_embedding(self, text: str):
    # ... 
    except Exception:
        return None

# In retrieve_tools:
if embedding is None:
    continue
```

### M15. `find_files` has no path traversal protection
- [x] **File:** `source/mcp_integration/terminal_executor.py` — Lines 268–285
- **Problem:** The LLM-supplied `directory` parameter is used directly in `glob.glob()`. Since `find_files` "never requires approval," there's no user gate against filesystem enumeration (e.g., `directory="C:\"`).
- **Fix:** Validate that `directory` resolves within the CWD or an allowed root:
```python
import os
resolved = os.path.realpath(directory)
cwd = os.path.realpath(os.getcwd())
if not resolved.startswith(cwd):
    return "Error: find_files is restricted to the current working directory tree."
```

### M16. `shell=True` in subprocess calls
- [x] **File:** `source/mcp_integration/terminal_executor.py` — Line 237
- **Problem:** `subprocess.run(cmd, shell=True, ...)` — commands are hardcoded today but `shell=True` is an anti-pattern.
- **Fix:** Use `shlex.split(cmd)` with `shell=False`:
```python
import shlex
subprocess.run(shlex.split(cmd), shell=False, capture_output=True, text=True, timeout=10)
```

### M17. Sync subprocess/glob calls block event loop
- [x] **File:** `source/mcp_integration/terminal_executor.py` — Lines ~70, ~230, ~279
- **Problem:** `_handle_get_environment()` runs multiple `subprocess.run` calls and `_handle_find_files()` runs `glob.glob(recursive=True)` — both synchronous, called from async `execute_terminal_tool`.
- **Fix:** Wrap in `run_in_thread`:
```python
result = await run_in_thread(_handle_get_environment)
result = await run_in_thread(_handle_find_files, directory, pattern)
```
Since `execute_terminal_tool` is already async, this is straightforward.

### M18. Duplicate shutdown logic in `cleanup()` vs `disconnect_server()`
- [x] **File:** `source/mcp_integration/manager.py` — Lines ~349 and ~424
- **Problem:** `cleanup()` reimplements the same shutdown-event + task-cancel pattern as `disconnect_server()`.
- **Fix:** Have `cleanup()` call `disconnect_server()` in a loop:
```python
async def cleanup(self):
    for name in list(self._connections):
        await self.disconnect_server(name)
```

### M19. `_initialized` flag set but never checked
- [x] **File:** `source/mcp_integration/manager.py` — Lines 54, 671
- **Problem:** Set to `False` in `__init__`, set to `True` at end of `init_mcp_servers()`, but never read anywhere.
- **Fix:** Either use it (guard against double-init or use-before-init) or remove it.

### M20. `resume_conversation` blocks event loop with thumbnail generation
- [x] **File:** `source/services/conversations.py` — Lines 56–58
- **Problem:** `create_thumbnail()` is called inside a loop for every image — synchronous image I/O blocks the event loop.
- **Fix:** `await run_in_thread(create_thumbnail, img_path)` or batch all thumbnails.

### M21. `cancel_all_pending` uses `.kill()` instead of `_kill_process_tree()`
- [x] **File:** `source/services/terminal.py` — Line 985
- **Problem:** `self._active_process.kill()` only kills the immediate process, not children. Leaves orphan child processes on Windows.
- **Fix:** `_kill_process_tree(self._active_process.pid)`

### M22. Token file not deleted on refresh failure
- [x] **File:** `source/services/google_auth.py` — Lines 88–95
- **Problem:** `_load_credentials` returns `None` if token refresh fails but doesn't delete the expired/invalid token file. `has_token()` still returns `True`, creating a "connected but broken" state.
- **Fix:** Delete the token file on refresh failure, or return a more descriptive status.

### M23. Transcription service: resource leak + missing error handling
- [x] **File:** `source/services/transcription.py`
- **Problem (3 parts):**
  1. **Line 116:** `pyaudio.PyAudio().get_sample_size(self.FORMAT)` creates a second PyAudio instance that is never terminated (resource leak).
  2. **Lines 30–32:** If `_load_model()` fails, `self.model` stays `None`. `_transcribe_audio` then crashes with `AttributeError` on Line ~97.
  3. **Lines 74–80:** `_record_audio` catches exceptions silently — if the microphone is unavailable, `stop_recording` returns empty transcription with no error indication.
- **Fix:**
  1. Replace with a class constant: `SAMPLE_WIDTH = 2  # pyaudio.paInt16 is always 2 bytes`
  2. After `_load_model()`, check `if self.model is None: return "Error: Transcription model failed to load"`
  3. Set an error flag in `_record_audio` that `stop_recording` checks and returns to the user.

### M24. Approval history reads file on every command check
- [x] **File:** `source/services/approval_history.py` — Lines 68–72, 82–86
- **Problem:** `_load_approvals()` reads and parses the entire JSON file from disk on every call. During a session with many terminal commands, this causes repeated file I/O.
- **Fix:** Cache approvals in memory after first load. Invalidate/reload only on `remember_approval` or `clear_approvals`:
```python
_approvals_cache: list | None = None

def _load_approvals():
    global _approvals_cache
    if _approvals_cache is not None:
        return _approvals_cache
    # ... read from disk ...
    _approvals_cache = data
    return data

def remember_approval(command):
    global _approvals_cache
    # ... append + write ...
    _approvals_cache = None  # invalidate
```

### M25. Approval history race condition on concurrent writes
- [x] **File:** `source/services/approval_history.py` — Lines 82–96
- **Problem:** `remember_approval` does load → check → append → save without file locking. Two concurrent writes could overwrite each other.
- **Fix:** Add a `threading.Lock` around the read-modify-write cycle.

### M26. `delete_conversation` doesn't delete `terminal_events`
- [x] **File:** `source/database.py` — Lines 324–338
- **Problem:** Only deletes from `messages` and `conversations`. Orphaned `terminal_events` rows accumulate.
- **Fix:** Add before the messages delete:
```python
cursor.execute("DELETE FROM terminal_events WHERE conversation_id = ?", (conversation_id,))
```

### M27. Thinking model detection is fragile
- [x] **File:** `source/llm/cloud_provider.py`
  - Anthropic Line 186: `any(kw in model for kw in ("opus", "sonnet"))` — matches ALL Opus/Sonnet models
  - Gemini Line 729: `"thinking" in model or "2.5" in model` — matches all "2.5" models
- **Fix:** Use a configuration list of known thinking-capable model identifiers, or better — check the model's capabilities via the API if available.

### M28. Lifecycle uses `call_soon_threadsafe` + `ensure_future` instead of `run_coroutine_threadsafe`
- [x] **File:** `source/core/lifecycle.py` — Line 50
- **Problem:** The manual pattern is fragile during shutdown races.
- **Fix:** Use `asyncio.run_coroutine_threadsafe(coro, loop)` which returns a `concurrent.futures.Future` you can wait on directly.

### M29. `mark_done()` doesn't clear `_cancel_callbacks`
- [x] **File:** `source/core/request_context.py` — Line 61
- **Problem:** If someone calls `cancel()` on a completed context, stale callbacks fire.
- **Fix:** Have `mark_done()` clear the callbacks list: `self._cancel_callbacks.clear()`

### M30. `broadcast_json` content parameter semantics
- [x] **File:** `source/core/connection.py` — Line 50
- **Problem:** `content: str` parameter — callers often pass JSON strings that get double-encoded by `json.dumps`. If content is already JSON, downstream consumers must `JSON.parse` twice.
- **Fix:** Accept `content: Any` and let `json.dumps` handle serialization, or document clearly that `content` is always a plain string.

### M31. Redundant inline `from ..database import db` imports
- [x] **File:** `source/services/conversations.py` — Lines 47, 164, 172, 224
- **Problem:** `db` is already imported at Line 17 (top-level). The 4 inline re-imports are redundant.
- **Fix:** Delete the inline `from ..database import db` statements.

### M32. `_APPROVALS_FILE` uses relative path
- [x] **File:** `source/services/approval_history.py` — Line 16
- **Problem:** `os.path.join("user_data", "exec-approvals.json")` — resolution depends on CWD.
- **Fix:** Use an absolute path from `config.py`:
```python
from ..config import PROJECT_ROOT
_APPROVALS_FILE = os.path.join(PROJECT_ROOT, "user_data", "exec-approvals.json")
```

### M33. OS info in system prompt exposes home directory to cloud providers
- [x] **File:** `source/llm/prompt.py` — Lines 55, 62, 65, 68
- **Problem:** `Path.home()` is included in OS info sent to Anthropic/OpenAI/Gemini on every request, leaking PII (username in path).
- **Fix:** Remove home directory from OS info, or only include it for local (Ollama) models by checking the provider.

---

## Phase 4 — Low-Severity Issues

### L1. Outdated module docstring in `main.py`
- [x] **File:** `source/main.py` — Lines 1–29
- **Problem:** References `mcp/` (should be `mcp_integration/`), `llm/ollama.py` (should be `ollama_provider.py`), and omits most service files.
- **Fix:** Update docstring to match the actual directory structure.

### L2. Polling loop for server readiness (race condition)
- [x] **File:** `source/main.py` — Lines 162–167
- **Problem:** `for _ in range(50): time.sleep(0.1)` is a race condition.
- **Fix:** Use `threading.Event`:
```python
# In state.py:
self.server_ready = threading.Event()

# In start_server():
app_state.server_ready.set()

# In main():
app_state.server_ready.wait(timeout=5.0)
```

### L3. Incomplete `__all__` exports
- [x] **Files:** `source/core/__init__.py` (Line 8), `source/llm/__init__.py` (Lines 4–6), `source/services/__init__.py` (Lines 4–5)
- **Fix:** Either make `__all__` exhaustive or remove it entirely.

### L4. `import traceback` inside loop body
- [x] **File:** `source/api/websocket.py` — Line 83
- **Fix:** Move to top-level imports.

### L5. Malformed JSON silently swallowed
- [x] **File:** `source/api/websocket.py` — Line 79
- **Problem:** `except Exception: continue` discards unparseable messages with no logging.
- **Fix:** Add `print(f"[WS] Ignoring malformed message: {raw[:200]}")`.

### L6. Redundant `terminal_service` import
- [x] **File:** `source/api/handlers.py` — Line 132
- **Fix:** Remove the inline `from ..services.terminal import terminal_service` — already imported at Line 14.

### L7. No upper-bound validation on terminal resize
- [x] **File:** `source/api/handlers.py` — Lines 245–249
- **Fix:** Add: `0 < cols <= 500 and 0 < rows <= 200`.

### L8. Bare `except:` in http.py
- [x] Already covered in M11. (This entry is a cross-reference.)

### L9. Accessing private `_tool_registry`
- [x] **File:** `source/api/http.py` — Line 549
- **Fix:** Add a public method to `mcp_manager`: `get_server_tools() -> dict[str, list[str]]`.

### L10. `body.dict()` deprecated in Pydantic v2
- [x] **File:** `source/api/http.py` — Line 588
- **Fix:** Replace with `body.model_dump()`.

### L11. Empty list vs error on Ollama failure
- [x] **File:** `source/api/http.py` — Lines 81–82
- **Fix:** Return `{"models": [], "error": "Ollama not reachable"}` or similar.

### L12. Inconsistent import placement
- [x] **File:** `source/api/http.py` — throughout
- **Problem:** Some imports at top, some deferred inside function bodies, with no comments explaining why.
- **Fix:** Move to top-level where possible. Where circular imports force deferral, add `# deferred: circular import` comment.

### L13. `import os` inside `get_image_paths`
- [x] **File:** `source/core/state.py` — Line 82
- **Fix:** Move to top-level imports.

### L14. Type annotation inconsistency (`Optional[X]` vs `X | None`)
- [x] **File:** `source/core/state.py` — Lines 30, 47 (`Optional`) vs Lines 50–53 (`X | None`)
- **Fix:** Pick one style consistently. `Optional[X]` is safer for broader Python version support.

### L15. `screenshot_list` and `screenshot_counter` lack shape documentation
- [x] **File:** `source/core/state.py` — Lines 27–28
- **Fix:** Add: `# List of {"id": str, "path": str, "thumbnail": str}`

### L16. `remove_screenshot` uses indexed loop with `pop(i)`
- [x] **File:** `source/core/state.py` — Line 87
- **Fix:** Consider list comprehension for clarity (but note: need to keep the True/False return).

### L17. Deferred import of `DEFAULT_MODEL` without comment
- [x] **File:** `source/core/state.py` — Line 44
- **Fix:** Add: `# deferred: avoid circular import with config.py`

### L18. `cancel()` callback errors silently swallowed
- [x] **File:** `source/core/request_context.py` — Line 58
- **Fix:** Add: `import logging; logging.getLogger(__name__).debug("Cancel callback failed", exc_info=True)`

### L19. `forced_skills` uses lowercase `list[dict]` syntax
- [x] **File:** `source/core/request_context.py` — Line 41
- **Fix:** Use `List[Dict[str, Any]]` for consistency, or add `from __future__ import annotations`.

### L20. `run_in_thread` lacks type hints
- [x] **File:** `source/core/thread_pool.py` — Line 25
- **Fix:**
```python
from typing import TypeVar, Callable, Any
T = TypeVar('T')

async def run_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
```

### L21. `max_workers=4` is a magic number
- [x] **File:** `source/core/thread_pool.py` — Line 21
- **Fix:** Extract to config: `THREAD_POOL_SIZE = int(os.environ.get("XPDITE_THREAD_POOL_SIZE", "4"))`

### L22. Unused `numpy` import in transcription.py
- [x] **File:** `source/services/transcription.py` — Line 7
- **Fix:** Delete `import numpy as np`.

### L23. No docstrings or type hints in transcription.py
- [x] **File:** `source/services/transcription.py` — entire file
- **Fix:** Add module docstring, class docstring, and type hints on all public methods.

### L24. Dead `import json` in screenshots.py
- [x] **File:** `source/services/screenshots.py` — Line 103
- **Fix:** Remove.

### L25. `clear_screenshots` reassigns list instead of `.clear()`
- [x] **File:** `source/services/screenshots.py` — Lines 105–110
- **Fix:** Use `app_state.screenshot_list.clear()` to avoid orphaning references.

### L26. `mask_key` doesn't handle None input
- [x] **File:** `source/llm/key_manager.py` — Line 104
- **Fix:** Add guard: `if not plaintext: return "****"`

### L27. `get_api_key_status` decrypts all keys just to mask them
- [x] **File:** `source/llm/key_manager.py` — Line 145
- **Fix:** Consider storing the masked version alongside the encrypted key, or only check `has_key` status without decrypting.

### L28. `copy_image_to_clipboard` fallback is a no-op
- [x] **File:** `source/ss.py` — Lines ~133–139
- **Problem:** The PowerShell fallback is `pass` — effectively dead code.
- **Fix:** Either implement the fallback or remove the block.

### L29. `retriever = ToolRetriever()` instantiated at import time
- [x] **File:** `source/mcp_integration/retriever.py` — Line 223
- **Problem:** Calls `ollama.list()` during import, adding startup latency even if Ollama isn't running.
- **Fix:** Lazy instantiation on first use.

### L30. No similarity threshold on tool retrieval
- [x] **File:** `source/mcp_integration/retriever.py` — Lines ~200–204
- **Problem:** Always picks top-K regardless of score — even near-zero similarity tools are included.
- **Fix:** Add a minimum threshold (e.g., `0.3`) and filter results below it.

---

## Phase 5 — Cross-Cutting Improvements (not bugs, but important for open-source quality)

### X1. Replace all `print()` with structured logging
- [x] **Scope:** All files under `source/`
- **Problem:** The entire backend uses `print()` statements. For an open-source project, `logging.getLogger(__name__)` with proper log levels is essential.
- **Fix:** At the top of each module:
```python
import logging
logger = logging.getLogger(__name__)
```
Replace `print(f"...")` with `logger.info(...)`, `logger.debug(...)`, `logger.warning(...)`, or `logger.error(...)` as appropriate. Configure logging in `main.py`.

### X2. Add type hints to all public function signatures
- [x] **Scope:** `thread_pool.py`, `transcription.py`, `connection.py`, `prompt.py`
- **Fix:** Add return type annotations and parameter types to all public-facing functions.

### X3. Centralize magic numbers in `config.py`
- [x] **Values to extract:**
  - `32768` → `OLLAMA_CTX_SIZE`
  - `100000` → `MAX_TOOL_RESULT_LENGTH`
  - `16384` / `4096` → `CLOUD_MAX_TOKENS` / `CLOUD_TOOL_MAX_TOKENS`
  - `4` → `THREAD_POOL_SIZE`
  - `50 * 1024` → `TERMINAL_MAX_OUTPUT_SIZE`

### X4. Deduplicate cloud provider code (~400+ lines removable)
- [x] **File:** `source/llm/cloud_provider.py` (954→734 lines, ~236 lines removed)
- **Problem:** The three `_build_*_messages` functions (~250 lines), three tool execution blocks (~120 lines), and broadcasting patterns are near-identical across providers.
- **Fix:** Extracted:
  1. `_build_chat_messages(history, query, images, format_image_fn)` — generic message builder used by Anthropic + OpenAI (Gemini stays separate due to `types.Content` SDK objects)
  2. `_format_anthropic_image()` / `_format_openai_image()` — thin image-format callbacks
  3. `_execute_and_broadcast_tool(fn_name, fn_args, provider_label, ...)` — shared tool execution + broadcast + recording (was ~30 identical lines × 3 providers)

### X5. Deduplicate `cloud_tool_handlers.py` similarly
- [ ] **File:** `source/mcp_integration/cloud_tool_handlers.py`
- **Problem:** Same pattern: `_to_*_messages()` x3, tool execution x3.
- **Fix:** Same approach as X4.

### X6. Skill query result mapping is duplicated 6+ times
- [x] **File:** `source/database.py` — skill operation methods
- **Problem:** The same `SELECT ... FROM skills` column list and `row → dict` mapping is repeated in `get_all_skills`, `get_skill_by_name`, `get_skill_by_slash_command`.
- **Fix:** Extract a `_row_to_skill(row) -> dict` helper.

### X7. Add basic test coverage
- [x] **67 tests across 6 test files — all passing.**
- **Test files created in `tests/`:**
  1. `test_database.py` — DatabaseManager CRUD: conversations, messages, tokens, settings, search (14 tests)
  2. `test_router.py` — `parse_provider` parsing + `route_chat` dispatch to Ollama/cloud/missing-key (9 tests)
  3. `test_request_context.py` — `RequestContext` cancellation lifecycle, idempotency, callback semantics (10 tests)
  4. `test_approval_history.py` — `_normalize_command` for prefixed/non-prefixed/edge cases (15 tests)
  5. `test_retriever.py` — `ToolRetriever` similarity scoring, threshold, top-k, always-on (6 tests)
  6. `test_terminal.py` — `_decode_safe_escapes` for `\n`, `\r`, `\t`, `\\`, hex escapes, edge cases (13 tests)
- **Infrastructure:** `pytest + pytest-asyncio` added to dev dependencies, `asyncio_mode = "auto"` configured in `pyproject.toml`.

### X8. CORS `allow_origins=["*"]` should be documented
- [x] **File:** `source/app.py`
- **Fix:** Add a comment: `# Intentionally permissive: this is a local desktop app, not a web service.`

---

## Summary by File

| File | Critical | High | Medium | Low |
|------|----------|------|--------|-----|
| `main.py` | - | - | - | 2 |
| `app.py` | - | - | - | 1 |
| `config.py` | - | - | - | - |
| `database.py` | - | - | 1 | - |
| `ss.py` | - | - | - | 1 |
| `core/state.py` | - | 1 | - | 5 |
| `core/connection.py` | - | 1 | 1 | - |
| `core/request_context.py` | - | - | 1 | 2 |
| `core/thread_pool.py` | - | 1 | - | 2 |
| `core/lifecycle.py` | 1 | 1 | 1 | - |
| `api/websocket.py` | - | 1 | - | 2 |
| `api/handlers.py` | - | 1 | 3 | 2 |
| `api/http.py` | 1 | - | 2 | 4 |
| `api/terminal.py` | - | - | 1 | - |
| `llm/router.py` | 1* | - | - | - |
| `llm/ollama_provider.py` | 1* | - | 1 | - |
| `llm/cloud_provider.py` | 1* | 2 | 2 | - |
| `llm/key_manager.py` | - | 1 | - | 2 |
| `llm/prompt.py` | - | - | 1 | - |
| `mcp_integration/manager.py` | 1 | - | 2 | - |
| `mcp_integration/handlers.py` | - | 1 | 3 | - |
| `mcp_integration/cloud_tool_handlers.py` | - | 1 | 3 | - |
| `mcp_integration/retriever.py` | - | 1 | 1 | 2 |
| `mcp_integration/terminal_executor.py` | - | - | 3 | - |
| `services/conversations.py` | - | 1 | 3 | - |
| `services/screenshots.py` | - | - | 1 | 2 |
| `services/terminal.py` | - | 1 | 1 | - |
| `services/google_auth.py` | - | 1 | 1 | - |
| `services/transcription.py` | 1 | - | 1 | 2 |
| `services/approval_history.py` | - | - | 3 | - |

*\* C4 spans multiple files (counted once total)*

---

## Remaining Work

**All deferred backend issues are now resolved.**

| Issue | Status |
|-------|--------|
| **X1** — Replace `print()` with structured logging | ✅ Complete — All 18 source files migrated. `logging.basicConfig()` in `main.py`, `logger = logging.getLogger(__name__)` in each module. Only `main_old.py` (dead legacy file) retains `print()`. |
| **X4** — Deduplicate cloud provider code | ✅ Complete — `cloud_provider.py` reduced from 970→734 lines (~236 lines removed). Extracted `_build_chat_messages()` (shared Anthropic/OpenAI message builder), `_format_anthropic_image()`/`_format_openai_image()`, and `_execute_and_broadcast_tool()` (shared tool execution + broadcast). |
| **X5** — Deduplicate `cloud_tool_handlers.py` | N/A — File was deleted (confirmed unused). |
| **X7** — Add basic test coverage | ✅ Complete — 67 tests across 6 files, all passing. Covers: DatabaseManager CRUD, `parse_provider`/`route_chat`, `RequestContext` cancellation, `_normalize_command`, `ToolRetriever` scoring, `_decode_safe_escapes`. |

### Frontend Changes Required

These backend fixes changed wire-format or behaviour and need matching frontend updates:

1. **M2 — Double JSON serialization removed** ✅ Complete
   - **What changed:** `source/api/handlers.py` — the inner `json.dumps()` was removed from 4 WebSocket responses: `conversations_list`, `conversation_messages`, `skills_list`, `skill_content`.
   - **Fixed:** `src/ui/pages/ChatHistory.tsx` — removed `JSON.parse(data.content)` on `conversations_list` and `conversation_deleted` handlers. The page was stuck on "Loading conversations..." because the double-parse threw an error before `setLoading(false)` could run.
   - **Already safe:** `src/ui/pages/App.tsx` uses the defensive pattern `typeof data.content === 'string' ? JSON.parse(data.content) : data.content` for all its handlers — no changes needed there.
   - **Verified:** No other active pages/components do a raw `JSON.parse(data.content)` on `conversation_messages`, `skills_list`, or `skill_content`. These message types are only handled in `App.tsx` (already guarded). `App_old.tsx` has 3 unguarded calls but is a dead legacy file — not in use.

2. **L11 — Ollama failure now returns error key** ✅ Complete
   - **What changed (backend):** `source/api/http.py` — when Ollama is unreachable, the response is now `{"models": [], "error": "Ollama is not running..."}` instead of just `{"models": []}`.
   - **What changed (frontend):** `src/ui/services/api.ts` — `getOllamaModels()` now returns `{ models, error? }` instead of a plain array. `src/ui/components/settings/SettingsModels.tsx` — displays the Ollama error string as a warning under the Ollama section header when present.

3. **M3 — Terminal ask level returns 400 on invalid input**
   - **What changed:** `source/api/terminal.py` — invalid `level` values now raise HTTP 400 instead of returning `{"error": ...}` with status 200.
   - **What the frontend needs:** Handle 400 status from the `PUT /api/terminal/ask-level` endpoint (likely already handled if using standard fetch error handling).

- `source/mcp_integration/cloud_tool_handlers.py` was **deleted** — it was entirely unused dead code. Issues M8 (partial), M9, M11 (partial), M12, M13 (partial) that referenced it were resolved by deletion.
- A **critical bug** was found and fixed in `source/core/state.py` that was NOT in this review: several `__init__` assignments (`selected_model`, `chat_history`, `conversation_id`, service references) were placed after a `return` statement inside the `stream_lock` property, making them unreachable. These were moved into `__init__` before the property definitions.
