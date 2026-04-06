# Development Guide

This guide covers common development tasks, code patterns, and conventions used in Xpdite.

## Development Commands

| Command | Description |
|---------|-------------|
| `bun run dev` | Full dev mode (React + Electron + Python + Ollama) |
| `bun run dev:react` | Vite dev server on port 5123 |
| `bun run dev:electron` | Electron app (expects React dev server) |
| `bun run dev:pyserver` | Python FastAPI server via UV |
| `bun run build` | Production build (Python exe + React + Electron) |
| `bun run dist:win` | Windows installer via electron-builder |
| `bun run install:python` | Install Python deps via UV (`uv sync --group dev`) |
| `uv sync --group dev` | Install all Python deps including dev tools |
| `uv add <package>` | Add a new Python dependency |
| `uv run python -m pytest tests/ -v` | Run all tests |

## Code Conventions

### Python Backend

- **Async-first**: All API handlers are async. Blocking or CPU-heavy work uses `run_in_thread()` from `source/core/thread_pool.py` — never `asyncio.to_thread()` directly.
- **Lifecycle Management**: Every user query is wrapped in a `RequestContext` (`source/core/request_context.py`). Use `ctx.on_cancel()` to register cleanup handlers (e.g., killing processes). Check `is_current_request_cancelled()` inside long-running loops.
- **Multi-tab state isolation**: Per-request state (model, cancellation, tab id) uses Python `ContextVar` via `set_current_request()`, `set_current_model()`, `set_tab_id()`. Never read `app_state.selected_model` from LLM layers — use `get_current_model()` instead.
- **State management**: Process-level shared state lives in `AppState` (singleton in `source/core/state.py`).
- **Thread safety**: Use `app_state.server_loop_holder` to schedule coroutines from non-async threads. Use `wrap_with_tab_ctx(tab_id, coro)` when scheduling from background threads so the correct tab context is stamped.
- **Broadcasting**: Always use `broadcast_message()` from `core.connection` (not `manager.broadcast()` directly) — it auto-stamps `tab_id` from the ContextVar.
- **Unified Terminal Logic**: Use `execute_terminal_tool()` from `source/mcp_integration/executors/terminal_executor.py` for any shell-related tool calls.
- **Skills**: Builtin skills live in `source/skills_seed/<name>/`. They are seeded to `user_data/skills/builtin/` on every startup by `SkillManager`. Never hardcode skill content in Python code.
- **Logging**: Use `print()` with `[MODULE]` prefixes (e.g., `[MCP]`, `[WS]`, `[SS]`).
- **Constants**: All magic numbers and defaults live in `source/infrastructure/config.py`.
- **Security**: Never commit secrets. Use `KeyManager` for sensitive user data.

### React Frontend

- **Hooks over classes**: All components are functional with hooks.
- **Ref pattern**: Use `useRef` alongside `useState` for values accessed in WebSocket callbacks to avoid stale closures.
- **Modular components**: Keep components focused; delegate to sub-components.
- **CSS-per-component**: Each major component has a corresponding CSS file.
- **Type safety**: All interfaces live in `src/ui/types/index.ts`.

### Naming Conventions

| Item | Convention | Example |
|------|-----------|---------|
| Python files | `snake_case.py` | `ollama_provider.py` |
| Python classes | `PascalCase` | `AppState`, `McpToolManager` |
| Python functions | `snake_case` | `submit_query()` |
| React components | `PascalCase.tsx` | `ChatMessage.tsx` |
| React hooks | `use*.ts` | `useChatState.ts` |
| CSS files | `PascalCase.css` | `ChatHistory.css` |
| WebSocket types | `snake_case` | `submit_query`, `response_chunk` |

## Common Tasks

### Adding a New UI Page

1. Create the component in `src/ui/pages/NewPage.tsx`
2. Add the route in `src/ui/main.tsx`:
   ```tsx
   import NewPage from './pages/NewPage'
   // In the router:
   { path: '/new-page', element: <NewPage /> }
   ```
3. Create the stylesheet in `src/ui/CSS/NewPage.css`
4. Add navigation link in `TitleBar.tsx` if needed

### Adding a New WebSocket Message Type

**Backend (Python):**

1. Add the message type handler in `source/api/handlers.py` as a method on `MessageHandler`. The framework automatically dispatches `msg_type` to `_handle_<msg_type>`:
   ```python
   async def _handle_new_message(self, data: dict) -> None:
       # Process the message
       result = await some_operation()
       await broadcast_message("new_message_response", result)
   ```

   > No registration needed — naming the method `_handle_<type>` is sufficient. Update the WS protocol docstring in `source/api/websocket.py`.

**Frontend (React):**

2. Handle the response in `App.tsx`'s WebSocket message handler:
   ```tsx
   case 'new_message_response':
       // Update state
       break;
   ```

3. Add the send helper to `createApiService` in `src/ui/services/api.ts`.

### Adding a New REST API Endpoint

1. Add the endpoint in `source/api/http.py`:
   ```python
   @router.get("/api/new-endpoint")
   async def new_endpoint():
       return {"data": "value"}
   ```

2. Add the client method in `src/ui/services/api.ts`:
   ```typescript
   async getNewData(): Promise<any> {
       const response = await fetch(`${this.baseUrl}/api/new-endpoint`);
       return response.json();
   }
   ```

### Adding a New MCP Tool Server

See the dedicated [MCP Guide](./mcp-guide.md) for detailed instructions.

### Modifying the Database Schema

1. Edit `_init_db()` in `source/infrastructure/database.py` to add the new table or column
2. Add a migration for existing databases:
   ```python
   try:
       cursor.execute("ALTER TABLE conversations ADD COLUMN new_field TEXT DEFAULT ''")
   except sqlite3.OperationalError:
       pass  # Column already exists
   ```
3. Update the corresponding read/write methods
4. If the change affects the frontend, update `src/ui/types/index.ts`

### Adding a Builtin Skill

1. Create a folder under `source/skills_seed/<name>/` with:
   - `skill.json` — `{ name, description, slash_command, trigger_servers, version }`
   - `SKILL.md` — the full prompt content injected when the skill is triggered
2. The skill is automatically seeded to `user_data/skills/builtin/<name>/` on the next app startup (existing user customizations are preserved).

### Adding a Cloud Provider

1. Implement streaming logic in `source/llm/providers/cloud_provider.py`
2. Update `source/llm/core/router.py` to handle the new provider prefix
3. Add API key management support in `source/api/http.py` and `SettingsApiKey.tsx`
4. Register available models in `source/api/http.py`

## Google OAuth Setup

The app uses an embedded OAuth client configuration for Google authentication.
The configuration is loaded from `GOOGLE_CLIENT_CONFIG` in `source/infrastructure/config.py`.

To update the OAuth client:
1. Download `client_secret_*.json` from Google Cloud Console
2. Update the `GOOGLE_CLIENT_CONFIG` dictionary in `source/infrastructure/config.py`
3. Ensure scopes in `GOOGLE_SCOPES` match the required permissions

## Architecture Patterns

### Cross-Thread Communication

The hotkey listener runs in a dedicated thread, but needs to trigger WebSocket broadcasts on the asyncio event loop:

```python
# In the hotkey thread (ss.py):
loop = app_state.server_loop_holder
if loop:
    asyncio.run_coroutine_threadsafe(
        broadcast_screenshot(data),
        loop
    )
```

### Streaming Response Handling

**Ollama (Local):**
Uses a producer-consumer pattern with a background thread reading the synchronous iterator and an asyncio queue for the main loop.

**Cloud Providers:**
Use native async streaming APIs directly in the main event loop (no background threads needed).

### WebSocket Ref Pattern (React)

```tsx
// State for rendering
const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
// Ref for WebSocket callbacks (avoids stale closure)
const chatHistoryRef = useRef(chatHistory);

useEffect(() => {
    chatHistoryRef.current = chatHistory;
}, [chatHistory]);

// In WebSocket handler:
const currentHistory = chatHistoryRef.current; // Always current
```

## Build and Packaging

### PyInstaller Build

The Python backend is bundled into a single executable:

```bash
bun run build:python-exe
```

Output goes to `dist-python/main.exe`, which is included as an extra resource in the Electron package.

### Electron Builder

Configuration in `electron-builder.json`:
- Bundles `dist-electron/` (compiled TypeScript) and `dist-react/` (built frontend)
- Copies `dist-python/` as `python-server/` extra resource
- Targets: NSIS installer and portable for Windows x64
