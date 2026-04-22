# Architecture

This document describes Xpdite's runtime architecture, key boundaries, and data flows.

## System Overview

Xpdite is a desktop-first system composed of four cooperating runtimes:

1. **Electron host** (`src/electron/`)
2. **React renderer** (`src/ui/`)
3. **Python backend** (`source/`)
4. **Mobile Channel Bridge** (`src/channel-bridge/`)

```text
Electron Main Process
  -> manages Python process lifecycle
  -> manages Channel Bridge process lifecycle
  -> exposes secure IPC to renderer

React Renderer <-> Python Backend (/ws + /api/*)

Python Backend <-> MCP servers (subprocess stdio + inline tools)

Channel Bridge <-> Python Backend (/internal/mobile/* and bridge callbacks)
```

## Runtime Layers

### 1) Electron Layer (`src/electron/`)

Responsibilities:

- Own window lifecycle and always-on-top behavior.
- Launch and monitor Python backend.
- Launch and monitor Channel Bridge after backend readiness.
- Expose minimal IPC surface via preload.

Key behaviors:

- Boot-state events are driven by structured `XPDITE_BOOT` stdout markers plus backend health checks.
- Backend readiness is confirmed by HTTP health probe (`/api/health`), not stdout alone.
- Renderer receives server port and session token through IPC.

### 2) React Renderer (`src/ui/`)

Responsibilities:

- Chat UX, streaming rendering, artifact rendering, settings, and history.
- Tabbed sessions multiplexed over one WebSocket connection.
- Frontend currently caps open tabs at 10, while backend tab infrastructure supports up to 50.
- REST calls for configuration and data retrieval.

Routing highlights (`src/ui/main.tsx`):

- `/` main chat
- `/settings`
- `/history`
- `/album`, `/recorder`, `/recording/:id`
- `/scheduled-jobs`

### 3) Python Backend (`source/`)

Responsibilities:

- FastAPI REST + WebSocket APIs.
- Conversation orchestration and queueing.
- LLM routing (local Ollama + cloud providers).
- MCP tool execution (subprocess and inline).
- Persistence (SQLite + filesystem-backed memory/artifacts).
- Scheduler and notification services.
- Marketplace platform for discovering and installing community extensions, skills, and prompts.
- Claude-compatible hooks runtime for pre/post generation modification.

Core architecture patterns:

- **ContextVars request scoping**: request, model, and tab identity flow through deep layers without global mutable coupling.
- **Per-tab isolation**: tab manager + conversation queue per tab (`MAX_TABS=50`, queue size `5`).
- **Ollama global serialization**: local GPU requests are serialized to avoid contention.
- **Thread-pool boundary**: blocking operations run through app-owned `run_in_thread()`.

### 4) Mobile Channel Bridge (`src/channel-bridge/`)

Responsibilities:

- Maintain adapters for Telegram, Discord, and WhatsApp.
- Forward inbound messages/commands to Python internal mobile endpoints.
- Relay outbound responses from Python to messaging platforms.

Bridge process notes:

- Bridge exposes local HTTP endpoints (`/health`, `/status`, `/outbound`, `/outbound/edit`, `/outbound/typing`).
- Python writes `mobile_channels_config.json` to share runtime configuration with the bridge.

## Boot Sequence

1. Electron creates lightweight boot shell.
2. Electron starts Python process.
3. Python emits staged boot markers.
4. Electron probes `http://127.0.0.1:{8000..8009}/api/health`.
5. Once healthy, Electron starts Channel Bridge in background.
6. Renderer loads and begins normal operation.

## Chat and Tool Flow

### User Request Path

1. Renderer sends `submit_query` over `/ws` with `tab_id`.
2. Backend enqueues request in tab queue.
3. Conversation service builds prompt + context.
4. Provider runtime streams model output.
5. Tool calls are executed and interleaved with streaming.
6. Renderer receives chunks/events and updates UI state.

### Tool Execution Modes

- **Subprocess MCP servers**: invoked over stdio JSON-RPC.
- **Inline tools**: intercepted and executed in-process (terminal, sub-agent, memory, skills, scheduler, video watcher).

## Data and Persistence

### SQLite

Primary state lives in `user_data/xpdite_app.db` (WAL mode, thread-safe connection management via database manager).

Major domains:

- Conversations/messages + response versions
- Artifacts metadata
- Scheduled jobs and notifications
- Mobile paired devices and sessions
- Settings and encrypted provider keys

### Filesystem-backed Data

- `user_data/artifacts/` for code/markdown artifact files
- `user_data/memory/` for long-term memory markdown files
- `user_data/skills/` for builtin/user skills and preferences
- `user_data/screenshots/` for captured and temporary images

## Security Model (Local-First)

- Server binds loopback by default.
- Sensitive artifact routes require loopback origin plus server token header.
- Electron preload bridge runs with `contextIsolation` and `nodeIntegration` disabled in renderer.
- Terminal execution is gated by approval policy and command safety checks.

## Concurrency and Isolation

- WebSocket events are tab-scoped and stamped with `tab_id`.
- Long-running loops check request cancellation context.
- Background work uses thread pool wrappers and explicit lifecycle cleanup.

## Scalability Constraints

- Designed for single-user local desktop runtime.
- Throughput constrained by model provider and local hardware.
- Local Ollama requests are intentionally serialized for stability.

## Related Docs

- `docs/development.md`
- `docs/api-reference.md`
- `docs/mcp-guide.md`
- `docs/mobile-bridge.md`
