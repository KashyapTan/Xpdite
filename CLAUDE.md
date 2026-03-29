# Xpdite — CLAUDE.md

Xpdite is an **always-on-top Electron desktop app** that wraps a React UI and a Python FastAPI backend to deliver an AI chat assistant with screenshot OCR, MCP tool calling, and multi-provider LLM support (Ollama, Anthropic, OpenAI, Gemini, OpenRouter). Python dependencies are managed with **UV**; frontend with **Bun**.

---

## Workflow

### Sub-agents for Information Gathering
Spawn as many sub-agents as you need **in parallel** for any read-only task that just needs a result — reading files, searching for patterns, exploring the directory structure, checking how something is implemented. The goal is to keep the main context window clean and focused. Do NOT use sub-agents when the reasoning process itself is needed in the main context.

### Sub-agents for Self-Review — Best-of-N + Parallel + De-dup

After finishing any coding task, run a **three-stage review pipeline** before considering it done. This produces near-zero false-negatives and filters out noise. For non-trivial changes this is mandatory; for trivial one-liners (renaming a variable, fixing a typo) a single quick pass is fine.

---

#### Stage 1 — Parallel Focused Reviewers (run all three simultaneously)

Spawn **three independent sub-agent reviewers in parallel**, each with a *single narrow focus*. Provide each agent the changed files + the `CODE_REVIEW_GUIDE.md`. Give each a different lens:

| Agent | Focus | Checklist Phases |
|---|---|---|
| **Reviewer A — Correctness & Logic** | Logic bugs, edge cases, async errors, wrong return types, mutation bugs | Phase 1 (Correctness) |
| **Reviewer B — Security & Resilience** | Injection, hardcoded secrets, missing auth, unhandled errors, resource leaks, timeouts | Phase 2 (Security) + Phase 3 (Error Handling) |
| **Reviewer C — Performance & Quality** | N+1 queries, O(n²) loops, dead code, naming, complexity, missing tests | Phase 4 (Performance) + Phase 5–7 (Simplification, Style, Testability) |

Each reviewer produces a raw findings list in the `CODE_REVIEW_GUIDE.md` report format. They work completely independently and must **not** see each other's output.

---

#### Stage 2 — Best-of-N Synthesis (optional but recommended for large diffs)

For large or high-risk changes (new services, DB migrations, auth flows), spawn **two additional Reviewer A agents** (correctness is the highest-value check) and pick the best / most complete findings across all three correctness reports. This is "best of N" — independent runs of the same task surface different bugs.

---

#### Stage 3 — De-dup Judge Agent

Spawn a **single judge sub-agent** that receives all raw reports from Stage 1 (and Stage 2 if run). The judge must:

1. **Merge** all findings into a single ranked list (Critical → High → Medium → Low).
2. **De-duplicate** — if multiple reviewers flag the same issue, keep one entry with a note that N reviewers flagged it (higher confidence).
3. **Resolve contradictions** — if Reviewer A says something is fine and Reviewer B flags it, the judge investigates and decides.
4. **Filter false positives** — mark any finding as a false positive if it flags intentional, correct behavior (e.g. flagging `check_same_thread=False` on SQLite as a bug when it's required by our DB pattern).
5. **Produce the final `CODE_REVIEW_GUIDE.md` report** with a clear Production Readiness Verdict.

---

#### Stage 4 — Fix & Verify

- Incorporate all Critical and High findings before responding.
- Fix all problems found Critical first, then High, then medium, then low.
- If any findings require human review, flag it and mention in review document.
- After fixes, spawn a **final lightweight verification agent** to confirm the fixes are correct and didn't introduce regressions.
- Make sure to create a code_review_[topic of review].md file after the review stating all the problems found and how they were fixed.

---

### Post-Review Action
Read the Testing section and determine if new tests are needed based on the changes made. Once the entire task is complete, update any relevant CLAUDE and documentation files to reflect the changes.
After every code implementation, run all lint checks and tests and fix all issues before considering the task complete.

### Read More Than Less
Always read all relevant and connected files before writing new code. It is always better to over-read than to miss context.

### Freedom and Direction
You are extremely knowledgeable — don't be afraid to use that. If you have concerns, suggestions, or improvements, raise them. Discussion and clarification lead to the best possible outcome.

### Planning
Enter plan mode for non-trivial tasks. Get the correct info and details before executing. For trivial tasks this is unnecessary — don't over-engineer.

---

## Dev Commands

```bash
bun run dev              # start everything: React (Vite), Electron, Python server, Ollama (GPU via scripts/start-ollama.mjs)
bun run dev:react        # Vite only (port 5123)
bun run dev:electron     # transpile Electron tsc + launch in dev mode
bun run dev:pyserver     # Python FastAPI server only
bun run test:ollama      # verify Ollama is running (curl probe to port 11434)
bun run build            # full production build (PyInstaller → tsc → Vite)
bun run build:react      # Vite build only
bun run build:python     # Python build via scripts/build-python.mjs (without PyInstaller exe)
bun run build:python-exe # PyInstaller via scripts/build-python-exe.py (used by prebuild hook)
bun run preview          # preview the Vite production build locally
bun run lint             # ESLint
bun run install:python   # uv sync --group dev (always run after pulling)
bun run install:uv       # install the UV tool itself (first-time setup)
bun run transpile:electron  # tsc for Electron main process only
bun run dist:win         # full production package for Windows (x64)
bun run dist:mac         # full production package for macOS (arm64)
bun run dist:linux       # full production package for Linux (x64)

# Python (run from project root with .venv active)
.venv\Scripts\python.exe -m source.main      # start Python server directly
uv sync --group dev                           # install / update Python deps
uv add <pkg>                                  # add a new Python package
uv run <file_name>                            # run python files for testing
```

**Requires Python 3.13+** (`requires-python = ">=3.13"` in `pyproject.toml`).

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
- All DB methods use `with self._connect() as conn:` context manager — never open/close connections manually
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

**New MCP tool server** → see `mcp_servers/CLAUDE_mcp.md` → "How to Add a New MCP Server". If tool calls from that server should render nicely in chat, also update `src/ui/components/chat/toolCallUtils.ts` (and its summary helper usage in `ToolCallsDisplay.tsx`) with badge/text mappings for the new tools.

**New builtin skill** → create a folder under `source/skills_seed/<name>/` with `skill.json` (name, description, slash_command, trigger_servers, version) and `SKILL.md` (prompt content). It will be auto-seeded to `user_data/skills/builtin/` on every app startup.

**New inline tool (like terminal or sub_agent)** → register via `mcp_manager.register_inline_tools("server_name", [...])` in `init_mcp_servers()` (see `manager.py`). Add interception in both `cloud_provider.py` (`_execute_and_broadcast_tool`) and `handlers.py` (Ollama tool loop) with `elif fn_name == "tool_name" and server_name == "server_name"`. Implement execution logic in `source/services/`. Current inline servers include `terminal`, `sub_agent`, `video_watcher`, and `skills`.

**YouTube analysis flow (`watch_youtube_video`)** → The `video_watcher` inline tool first tries native YouTube captions; if captions are unavailable it emits a `youtube_transcription_approval` content block in chat, waits for `youtube_transcription_approval_response`, then (if approved) downloads audio and transcribes with Whisper using detected compute backend (`cuda`/`cpu`) and estimated timing metadata.

**Boot system** → The Electron window loads instantly, showing a boot screen overlay (`src/ui/components/boot/BootScreen.tsx` + `BootContext.tsx`) while the Python backend starts. Boot progress is communicated via structured `XPDITE_BOOT {"phase":"...","message":"...","progress":N}` markers on stdout (emitted by `_emit_boot_marker()` in `source/main.py`), parsed in `pythonApi.ts`, and relayed to the renderer via the `boot-state` IPC channel. The backend is only considered ready after a successful HTTP health-check response — not from stdout markers alone. In dev mode (no Electron), `BootContext` falls back to polling `/api/health` on ports 8000–8009.
In dev mode, Electron also prewarms the Vite renderer by probing the real entry/module URLs before swapping away from the boot shell. Keep the initial renderer shell lightweight (`Layout.css` is intentionally separated from the heavier chat styles), and avoid moving markdown / syntax-highlighting / terminal-heavy imports back onto the boot-critical path unless they are behind a deliberate lazy boundary.

---

## Testing & Linting

### Frontend (React + Electron)
```bash
bun run test:frontend                       # run frontend Vitest suite
bun run test:frontend:watch                 # run frontend Vitest in watch mode
bun run test:frontend:coverage              # run frontend tests with coverage
bun run lint                                # ESLint (frontend + electron TS/JS)
bun run build:react                         # production build sanity-check
```

**Vitest vs coverage runs**
- `bun run test:frontend` gives fast pass/fail feedback for local iteration.
- `bun run test:frontend:coverage` runs the same tests with instrumentation and emits coverage metrics (lines/branches/functions), so it is slower but better for pre-merge confidence.

### Backend (FastAPI + Python)
```bash
uv run python -m pytest tests/ -v          # run all backend tests
uv run python -m pytest tests/test_foo.py  # run a single test file
uv run --with pytest-cov python -m pytest tests/ -q --cov=source --cov-report=term --cov-report=json:backend-coverage.json  # backend coverage report
uv run ruff check .                        # backend lint/static checks
```

Frontend test files are organized under `src/ui/test/**` (components, contexts, hooks, services, utils) and run in a `jsdom` environment via `vitest.config.ts`.

**`asyncio_mode = "auto"`** is set in `pyproject.toml` — all `async def test_*` functions are automatically treated as asyncio tests. No `@pytest.mark.asyncio` decorator is needed (though some legacy tests retain it; both styles work).

### When to add tests
Always add tests when:
- Adding or changing frontend logic (hooks, utilities, state transforms, non-trivial component behavior)
- Adding a new public method or utility function to `source/` (pure logic, algorithms, data transforms)
- Adding a new DB method to `DatabaseManager`
- Fixing a bug — add a test that would have caught it before writing the fix

You can skip tests for very thin glue code (simple delegating WS/HTTP handlers or presentational-only UI), unless behavior changed.

### Backend test file conventions
- One file per source module: `source/services/terminal.py` → `tests/test_terminal.py`
- Class-per-concern inside the file: `class TestMyFeature:`
- Fixtures live in `tests/conftest.py`; keep them minimal — one `db_manager` fixture backed by `tmp_path` covers all DB tests

### The circular-import problem (backend pytest)
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
| `src/channel-bridge/CLAUDE_mobile.md` | Mobile messenger (WhatsApp/Telegram/Discord) integration architecture, messaging flow, and platform adapters |
