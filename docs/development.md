# Development Guide

This guide covers local workflows, coding standards, and common implementation patterns.

## Local Development

### Install

```bash
bun install
bun run install:python
```

### Run

```bash
bun run dev
```

Useful targeted commands:

```bash
bun run dev:react
bun run dev:electron
bun run dev:pyserver
bun run dev:ollama
```

### Build and Validate

```bash
bun run lint
bun run test:frontend
bun run build:react
uv run python -m pytest tests/ -v
uv run ruff check .
```

## Core Engineering Conventions

### Python Backend

- Use relative imports within `source/`.
- Keep business logic in `services/`, not `api/` handlers.
- Route blocking and CPU-heavy work through `run_in_thread()`.
- Use request/tab/model ContextVars helpers for per-request state.
- Do not access global mutable request state from deep provider/tool layers.
- Use `broadcast_message()` / `broadcast_to_tab()` instead of raw manager broadcast calls.

### Database

- Database access should go through `DatabaseManager` methods.
- Do not open ad-hoc sqlite connections outside database manager patterns.
- Schema evolution uses additive migration blocks in `_init_db()` with safe exception handling.

### React Frontend

- Use function components and hooks only.
- For streaming callbacks, pair `useState` with `useRef` when needed to avoid stale closures.
- Use typed interfaces from `src/ui/types/index.ts`.
- Send WebSocket messages via `createApiService(send)` methods.

### MCP Integration

- Register subprocess servers in `source/mcp_integration/core/manager.py`.
- Register inline tools through `register_inline_tools(...)`.
- Inline tools must be intercepted in both:
  - `source/mcp_integration/core/handlers.py` (Ollama path)
  - `source/llm/providers/cloud_provider.py` (cloud path)

## Common Tasks

### Add a New UI Page

1. Add component under `src/ui/pages/`.
2. Add route in `src/ui/main.tsx`.
3. Add styles under `src/ui/CSS/pages/` if needed.
4. Add navigation entry in layout/title UI.

### Add a REST Endpoint

1. Add route in `source/api/http.py` (or relevant API module).
2. Add frontend client method in `src/ui/services/api.ts`.
3. Add tests in `tests/` for backend behavior.

### Add a WebSocket Message Type

1. Add handler method in `source/api/handlers.py` (`_handle_<type>`).
2. Update websocket protocol documentation in `source/api/websocket.py` docstring.
3. Add sender helper in `src/ui/services/api.ts` where applicable.
4. Update frontend event handling/state flow.

### Add a DB Column

1. Add migration block in `source/infrastructure/database.py` `_init_db()`.
2. Update read/write methods and type contracts.
3. Add regression tests.

### Add a New MCP Server

Follow `docs/mcp-guide.md` for full steps.

### Add a New Inline Tool

1. Define tool schema under `mcp_servers/servers/<name>/inline_tools.py`.
2. Register in `init_mcp_servers()`.
3. Add intercept/execute logic in both Ollama and cloud tool loops.
4. Add tests for tool definition and execution.

## Testing Expectations

Add or update tests when:

- changing business logic,
- adding endpoints,
- modifying queueing, scheduling, memory, or tool execution behavior,
- fixing a bug (include regression coverage).

Thin glue-only UI or pass-through handler changes may skip tests if behavior is unchanged.

## Code Review Checklist

- Correctness: request context, cancellation, tab routing, and error handling.
- Security: loopback boundaries, token checks, command safety, path normalization.
- Performance: avoid blocking event loop and redundant heavy work.
- Stability: preserve backward-compatible payload shapes where required.

## Related Docs

- `docs/architecture.md`
- `docs/api-reference.md`
- `docs/configuration.md`
- `docs/contributing.md`
