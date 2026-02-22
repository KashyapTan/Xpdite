# src/ — Frontend & Electron

## Directory Structure

```
src/
├── electron/
│   ├── main.ts          # Electron entry: window creation, IPC handlers, Python lifecycle
│   ├── preload.ts       # contextBridge: exposes electronAPI to renderer (minimal surface)
│   ├── pythonApi.ts     # Python server spawn/kill logic (dev vs prod differs significantly)
│   ├── pcResources.ts   # Resource path resolution for packaged app
│   └── utils.ts         # isDev() — checks NODE_ENV === 'development'
│
└── ui/
    ├── main.tsx         # React entry, router, WebSocketProvider wrap
    ├── pages/
    │   ├── App.tsx      # Main chat page (query input, response, tool calls, screenshots)
    │   ├── Settings.tsx # Settings page (models, API keys, MCP, skills, system prompt)
    │   ├── ChatHistory.tsx  # Past conversations browser
    │   └── MeetingAlbum.tsx # Screenshot/meeting album view
    ├── components/
    │   ├── Layout.tsx        # Shell with nav, page routing slot
    │   ├── TitleBar.tsx      # Draggable custom title bar + mini-mode toggle
    │   ├── WebSocketContext.tsx  # Global WS context (window hide for screenshots, ready state)
    │   ├── chat/             # Message rendering (thinking blocks, tool calls, markdown)
    │   ├── input/            # Query input bar, model selector, capture mode controls
    │   ├── settings/         # Settings panel sub-components (per-tab components)
    │   └── terminal/         # Terminal approval UI, PTY output renderer
    ├── hooks/
    │   ├── useWebSocket.ts   # Low-level WS hook: connect, reconnect, send
    │   ├── useChatState.ts   # All in-flight and history chat state
    │   ├── useScreenshots.ts # Screenshot list management
    │   └── useTokenUsage.ts  # Token count display
    ├── services/
    │   └── api.ts        # createApiService (WS helpers) + singleton `api` (HTTP helpers)
    ├── types/            # Shared TypeScript interfaces (ChatMessage, ToolCall, ContentBlock…)
    └── utils/            # Misc helpers
```

---

## Key Patterns

### WebSocket — two layers, different purposes
- **`useWebSocket` hook** (`hooks/useWebSocket.ts`) — reconnecting WS connection used by the main chat page. Returns `send`, `isConnected`, and `wsRef`. Each page that needs WS creates its own via this hook.
- **`WebSocketContext`** — a second, always-open WS connection used for global concerns only: hiding the window during screenshot capture (`isHidden`), tracking `canSubmit`, and propagating `ready`. Kept separate so screenshot hiding works even when the chat page is unmounted.

Never call `ws.send()` directly. Use `createApiService(send)` to build a typed message sender.

### Streaming state — state + refs dual pattern
`useChatState` holds every field in both `useState` (drives re-renders) **and** `useRef` (for mutation inside async callbacks mid-stream). The refs are the source of truth during a stream; state is synced from them. On response complete, refs are read to commit to `chatHistory`, then both are reset.

This is intentional: mutating React state inside a streaming callback causes stale-closure bugs. The refs guarantee you always read the latest accumulated text regardless of how many renders have fired.

### Content blocks — interleaved rendering
The `contentBlocks: ContentBlock[]` array interleaves `{ type: 'text' }`, `{ type: 'tool_call' }`, and `{ type: 'terminal_command' }` entries to render tool calls inline between text segments. Do not use a flat `response` string for display when tool calls are present — use `contentBlocks`.

### `createApiService` vs `api` singleton
- `createApiService(send)` — wraps the WS `send` function into typed helpers. Use for any real-time action.
- `api` singleton in `api.ts` — plain `fetch` calls for one-shot HTTP operations (settings, model lists, API key management). Import `api` directly; don't create new instances.

---

## Electron-Specific Notes

### Window
- Frameless, transparent, 450×450, `alwaysOnTop: true` at `screen-saver` level.
- **Mini mode** (52×52): saves `normalBounds` before shrinking; restores on exit. Triggered via `ipcMain.handle('set-mini-mode', …)`.
- `minimizable: false`, `maximizable: false`, `skipTaskbar: true` — intentional for overlay UX.

### IPC surface (preload.ts)
Only two methods are exposed via `contextBridge`:
- `window.electronAPI.setMiniMode(mini: boolean)`
- `window.electronAPI.focusWindow()`

Do not add IPC channels without updating both `preload.ts` (expose) and `main.ts` (handle).

### Python server lifecycle
- **Dev:** Electron does *not* start Python. `dev:pyserver` runs it independently. `isDev()` guards this.
- **Prod:** Electron spawns `resources/python-server/xpdite-server.exe` (PyInstaller bundle) from `pythonApi.ts → startPythonServer()`. The exe path differs between packaged and unpackaged builds — `pythonApi.ts` resolves `process.resourcesPath` at runtime.
- **Port detection:** Both sides scan 8000-8009. The Python side picks first available; the frontend hardcodes `:8000`. If you move off 8000, you need to pass the chosen port from Python → Electron → renderer (currently not done — port 8000 is assumed free).

---

## How to Add Things

### New page
1. Create `src/ui/pages/MyPage.tsx`
2. Add a `<Route>` in `src/ui/main.tsx`
3. Add a nav entry in `src/ui/components/Layout.tsx`

### New settings tab
Add a component under `src/ui/components/settings/` and render it conditionally inside `src/ui/pages/Settings.tsx`.

### New WS message type (server → client)
Handle the new `type` string inside the `onMessage` callback in the relevant hook or page. Update `websocket.py`'s protocol docstring on the Python side.

### New HTTP endpoint call
Add a method to the `api` singleton at the bottom of `src/ui/services/api.ts`. Use the existing `fetch` + error handling pattern already there.
