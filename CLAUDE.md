# Xpdite — CLAUDE.md

Xpdite is an **always-on-top Electron desktop app** that wraps a React UI and a Python FastAPI backend to deliver an AI chat assistant with screenshot OCR, MCP tool calling, and multi-provider LLM support (Ollama, Anthropic, OpenAI, Gemini). Python dependencies are managed with **UV**; frontend with npm.

---

## Workflow

### Sub-agents for Information Gathering
Spawn a sub-agent for any read-only task that just needs a result — reading files, searching for patterns, exploring the directory structure, checking how something is implemented. The goal is to keep the main context window clean and focused. Do NOT use sub-agents when the reasoning process itself is needed in the main context.

### Sub-agents for Self-Review
After finishing any coding task, spawn a fresh sub-agent to review the work before considering it done. The reviewer should:
Read the CODE_REVIEW_GUIDE.md and follow that file for its review.
Incorporate the reviewer's findings before responding. The goal is production-ready output on the first pass.

### Read more than less
Its always better to read more than less. Make sure to read all relevant and connected files so you have a comprehensive understanding of how things work before writing new code.

### Freedom and direction
You are extremly knowledgeable so dont be afraid to use that. If you have any concers, suggestions, or imporvements, dont be afraid to let me know. I am open to discussion and would prefer if we discussed things and clarified to get to the best possible end goal.

### Planning
Enter plan mode for non trivial tasks. Its important to get the correct info and details of a task by planning for it before you execute. For trivial tasks, this is unnecessary, dont over-engineer things.

---

## Dev Commands

```bash
npm run dev              # start everything: React (Vite), Electron, Python server, Ollama watcher
npm run dev:react        # Vite only (port 5123)
npm run dev:pyserver     # Python FastAPI server only
npm run build            # full production build (PyInstaller → tsc → Vite)
npm run lint             # ESLint
npm run install:python   # uv sync --group dev (always run after pulling)
npm run transpile:electron  # tsc for Electron main process only

# Python (run from project root with .venv active)
.venv\Scripts\python.exe -m source.main      # start Python server directly
uv sync --group dev                           # install / update Python deps
uv add <pkg>                                  # add a new Python package
uv run <file_name>                            # run python files for testing
```

**Ports:** Python server starts on 8000 (scans up to 8009 if busy). React dev server is on port 5123. WebSocket and HTTP share python's port.

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

**Never do**
- Don't add a new WS message type on the Python side without updating the client → server or server → client reference in `source/api/websocket.py`'s docstring
- Don't hardcode ports — use `find_available_port()` on the Python side
- Don't skip `RequestContext.cancelled` checks inside long-running loops (streaming, tool loops)

---

## Common Tasks

**New page in the UI** → add a file under `src/ui/pages/`, register a route in `src/ui/main.tsx`, add a nav link in `src/ui/components/Layout.tsx`.

**New WebSocket message type (client → server)** → add `_handle_<type>` method to `MessageHandler` in `source/api/handlers.py`; add the send helper to `createApiService` in `src/ui/services/api.ts`.

**New REST endpoint** → add a route to `source/api/http.py` (or `terminal.py` for terminal-related settings); add the fetch call to the `api` singleton in `src/ui/services/api.ts`.

**New DB column** → add an `ALTER TABLE … ADD COLUMN` migration block inside `_init_db()` in `source/database.py`. Never modify the original `CREATE TABLE` statement.

**New MCP tool server** → see `source/CLAUDE.md` → "Adding a new MCP server".

---

## Sub-file Index

| File | Contents |
|---|---|
| `source/CLAUDE_backend.md` | Python backend architecture, DB schema, WS protocol, MCP integration, architecture decisions |
| `src/CLAUDE_frontend.md` | Frontend + Electron patterns, state management, IPC, how to add pages/components |
| `mcp_servers/CLAUDE_mcp.md` | MCP server directory, per-server purpose, how to add a new server |
