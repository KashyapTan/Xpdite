# Xpdite — CLAUDE.md

Xpdite is an **always-on-top Electron desktop app** that wraps a React UI and a Python FastAPI backend to deliver an AI chat assistant with screenshot OCR, MCP tool calling, and multi-provider LLM support (Ollama, Anthropic, OpenAI, Gemini). Python dependencies are managed with **UV**; frontend with **Bun**.

---

## Workflow

### Sub-agents for Information Gathering
Spawn as many sub-agents as you need for any read-only task that just needs a result — reading files, searching for patterns, exploring the directory structure, checking how something is implemented. The goal is to keep the main context window clean and focused. Do NOT use sub-agents when the reasoning process itself is needed in the main context.

### Sub-agents for Self-Review
After finishing any coding task, spawn a fresh sub-agent(s) to review the work before considering it done. The reviewer should:
The reviewer sub-agent(s) should read and follow the CODE_REVIEW_GUIDE.md for its review.
Incorporate the reviewer's findings before responding. The goal is production-ready output on the first pass.

### Post review action
Read the testing section and see if new tests are needed based on the changes made.
Once you finish your entire task, make sure to update any relevalant claude and documentation files with the changes made. 

### Read more than less
Its always better to read more than less. Make sure to read all relevant and connected files so you have a comprehensive understanding of how things work before writing new code.

### Freedom and direction
You are extremly knowledgeable so dont be afraid to use that. If you have any concers, suggestions, or imporvements, dont be afraid to let me know. I am open to discussion and would prefer if we discussed things and clarified to get to the best possible end goal.

### Planning
Enter plan mode for non trivial tasks. Its important to get the correct info and details of a task by planning for it before you execute. For trivial tasks, this is unnecessary, dont over-engineer things.

---

## Dev Commands

```bash
bun run dev              # start everything: React (Vite), Electron, Python server, Ollama (GPU via scripts/start-ollama.mjs)
bun run dev:react        # Vite only (port 5123)
bun run dev:pyserver     # Python FastAPI server only
bun run build            # full production build (PyInstaller → tsc → Vite)
bun run lint             # ESLint
bun run install:python   # uv sync --group dev (always run after pulling)
bun run transpile:electron  # tsc for Electron main process only

# Python (run from project root with .venv active)
.venv\Scripts\python.exe -m source.main      # start Python server directly
uv sync --group dev                           # install / update Python deps
uv add <pkg>                                  # add a new Python package
uv run <file_name>                            # run python files for testing
```

**Ports:** Python server starts on 8000 (scans up to 8009 if busy). React dev server is on port 5123. WebSocket and HTTP share python's port.

**Ollama GPU (AMD/Vulkan):** `dev:ollama` runs via `scripts/start-ollama.mjs` which first checks if ollama is already running (HTTP probe to `127.0.0.1:11434`) and skips launch if so. Otherwise it auto-detects the GPU: NVIDIA (via `nvidia-smi`) → AMD (via `HIP_PATH` env var) → CPU fallback. For AMD it explicitly sets `OLLAMA_GPU_DRIVER=vulkan` and clears conflicting HIP/ROCm device vars (`HIP_VISIBLE_DEVICES`, `HSA_OVERRIDE_GFX_VERSION`). The process runs with `stdio: 'inherit'` so ollama is visible in the terminal and system tray. Performance env vars are set automatically: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MAX_LOADED_MODELS=1`.

---

## Code Style

**TypeScript / React**
- Functional components only, hooks for all stateful logic
- Streaming state uses **both** React state (for renders) and refs (for mutations mid-stream) — never mutate state directly during streaming
- All WS messages sent via `createApiService(send)` — never call `ws.send()` directly in a component
- Import order: React → third-party → internal (use path aliases, not `../../`)
- Never use `any` unless bridging an untyped external API; prefer `unknown` + narrow

**Python**
- All modules inside `source/` use **relative imports** (`from ..config import ...`) — never absolute `from source.xxx`
- Every async handler runs in the uvicorn event loop; CPU-heavy or blocking-IO work goes through `run_in_thread` (see `source/core/thread_pool.py`)
- Never call `sqlite3.connect()` outside `DatabaseManager._get_connection()` — and always pass `check_same_thread=False`
- New DB columns: ADD via `ALTER TABLE ... ADD COLUMN` inside a `try/except OperationalError` migration block in `_init_db()`, not by changing the CREATE TABLE statement
- Never put business logic in `api/` layer — it belongs in `services/`
- Tests are in the tests folder
- **Multi-tab state isolation**: per-request state (model, cancellation) uses ContextVars (`set_current_request()`, `set_current_model()`). Never read `app_state.stop_streaming` or `app_state.selected_model` from LLM/MCP layers — use `is_current_request_cancelled()` and `get_current_model()` instead.

**Never do**
- Don't add a new WS message type on the Python side without updating the client → server or server → client reference in `source/api/websocket.py`'s docstring
- Don't hardcode ports — use `find_available_port()` on the Python side
- Don't skip `RequestContext.cancelled` checks inside long-running loops (streaming, tool loops)
- Don't call `manager.broadcast()` directly in service code — always use `broadcast_message()` from `core.connection`. `manager.broadcast()` sends raw JSON with no `tab_id`, so the frontend routes the message to the `'default'` tab regardless of which tab is active. `broadcast_message()` reads `_current_tab_id` from the ContextVar and stamps it automatically.

---

## Common Tasks

**New page in the UI** → add a file under `src/ui/pages/`, register a route in `src/ui/main.tsx`, add a nav link in `src/ui/components/Layout.tsx`.

**New WebSocket message type (client → server)** → add `_handle_<type>` method to `MessageHandler` in `source/api/handlers.py`; add the send helper to `createApiService` in `src/ui/services/api.ts`.

**New REST endpoint** → add a route to `source/api/http.py` (or `terminal.py` for terminal-related settings); add the fetch call to the `api` singleton in `src/ui/services/api.ts`.

**New DB column** → add an `ALTER TABLE … ADD COLUMN` migration block inside `_init_db()` in `source/database.py`. Never modify the original `CREATE TABLE` statement.

**New MCP tool server** → see `source/CLAUDE.md` → "Adding a new MCP server".

**New builtin skill** → create a folder under `source/skills_seed/<name>/` with `skill.json` (name, description, slash_command, trigger_servers, version) and `SKILL.md` (prompt content). It will be auto-seeded to `user_data/skills/builtin/` on every app startup.

---

## Testing

### When to add tests
Always add tests when:
- Adding a new public method or utility function to `source/` (pure logic, algorithms, data transforms)
- Adding a new DB method to `DatabaseManager`
- Fixing a bug — add a test that would have caught it before writing the fix

Skip tests for thin glue code (WS handlers that just call a service, REST endpoints that just delegate, UI components).

### How to run tests
```bash
uv run python -m pytest tests/ -v          # run all tests
uv run python -m pytest tests/test_foo.py  # run a single file
```

### Test file conventions
- One file per source module: `source/services/terminal.py` → `tests/test_terminal.py`
- Class-per-concern inside the file: `class TestMyFeature:`
- Fixtures live in `tests/conftest.py`; keep them minimal — one `db_manager` fixture backed by `tmp_path` covers all DB tests

### The circular-import problem
`source/` has a circular import involving `mcp_integration.handlers` → `services` → `llm` → `mcp_integration.handlers`. This would crash pytest collection.

**`tests/conftest.py` breaks the cycle** by pre-stubbing `source.mcp_integration.handlers` in `sys.modules` before any test file is collected. The stub is a `MagicMock` with `handle_mcp_tool_calls` set. The real package (`source.mcp_integration`) and all other real submodules (`retriever`, `manager`, etc.) remain importable normally.

**Rule**: if you add a test file that imports a module deep in the source tree and pytest crashes at collection with an `ImportError`, check whether the module chains into the circular path. If yes, add a targeted `sys.modules.setdefault(...)` stub in `conftest.py` for the specific module causing the problem — **never** stub entire packages.

### DB tests — fixture pattern
```python
import pytest

@pytest.fixture()
def db_manager(tmp_path):
    db_path = str(tmp_path / "test.db")
    from source.database import DatabaseManager
    mgr = DatabaseManager(database_path=db_path)
    return mgr
```
The fixture is already defined in `conftest.py` — just accept `db_manager` as a parameter.

---

## Sub-file Index

| File | Contents |
|---|---|
| `source/CLAUDE_backend.md` | Python backend architecture, DB schema, WS protocol, MCP integration, architecture decisions |
| `src/CLAUDE_frontend.md` | Frontend + Electron patterns, state management, IPC, how to add pages/components |
| `mcp_servers/CLAUDE_mcp.md` | MCP server directory, per-server purpose, how to add a new server |
