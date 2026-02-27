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
    ├── main.tsx         # React entry, router, TabProvider wrap
    ├── pages/
    │   ├── App.tsx      # Main chat page (query input, response, tool calls, screenshots, tab routing)
    │   ├── Settings.tsx # Settings page (models, API keys, MCP, skills, system prompt)
    │   ├── ChatHistory.tsx  # Past conversations browser
    │   ├── MeetingRecorder.tsx # Live meeting recording UI
    │   ├── MeetingAlbum.tsx   # Past meeting recordings list
    │   └── MeetingRecordingDetail.tsx # Individual recording detail + AI analysis
    ├── components/
    │   ├── Layout.tsx        # Shell with nav, WebSocketProvider + MeetingRecorderProvider wrap
    │   ├── TitleBar.tsx      # Draggable custom title bar + mini-mode toggle
    │   ├── TabBar.tsx        # Tab strip (hidden when 1 tab), create/close/switch
    │   ├── chat/             # Message rendering (thinking blocks, tool calls, markdown)
    │   ├── input/            # Query input bar, model selector, capture mode controls
    │   ├── settings/         # Settings panel sub-components (per-tab components)
    │   └── terminal/         # Terminal approval UI, PTY output renderer
    ├── contexts/
    │   ├── WebSocketContext.tsx  # Single WS connection provider (send, subscribe, isConnected)
    │   ├── MeetingRecorderContext.tsx # Recording state (persists across routes)
    │   └── TabContext.tsx    # TabProvider: tab list, active tab, switch/close/create with callbacks
    ├── hooks/
    │   ├── useChatState.ts   # All in-flight and history chat state (+ getSnapshot/restoreSnapshot)
    │   ├── useScreenshots.ts # Screenshot list management (+ getSnapshot/restoreSnapshot)
    │   ├── useAudioCapture.ts # System audio capture for meeting recording
    │   └── useTokenUsage.ts  # Token count display (+ getSnapshot/restoreSnapshot)
    ├── services/
    │   └── api.ts        # createApiService (WS helpers) + singleton `api` (HTTP helpers)
    ├── types/            # Shared TypeScript interfaces (ChatMessage, ToolCall, ContentBlock, TabSnapshot…)
    ├── CSS/
    │   └── TabBar.css    # Dark theme tab bar styles (28px height)
    └── utils/            # Misc helpers
```

---

## Key Patterns

### WebSocket — single provider, pub/sub dispatch
- **`WebSocketProvider`** (`contexts/WebSocketContext.tsx`) manages the one and only WebSocket connection. It lives in `Layout.tsx` so the connection survives route changes (e.g., navigating from `/` to `/recorder`).
- **API**: `send(msg)` sends raw JSON; `subscribe(handler)` returns an unsubscribe function. Every subscriber receives every message — each consumer filters by `data.type`.
- **Pseudo-messages**: `{ type: '__ws_connected' }` and `{ type: '__ws_disconnected' }` are dispatched by the provider so subscribers can react to connection lifecycle events.
- **`App.tsx`** subscribes and handles chat / screenshot / queue messages. It wraps the raw `send` with `tab_id` injection as `wsSend`.
- **`MeetingRecorderContext`** subscribes directly for `meeting_recording_*` messages. Meeting pages (Album, Detail, Settings) each subscribe for their own message types.

Never call `ws.send()` directly in a component — go through `useWebSocket().send`.

### Multi-Tab Architecture
- **TabContext** (`contexts/TabContext.tsx`) manages the list of open tabs, active tab ID, and per-tab queue items. Pure UI state — no chat/token/screenshot data here.
- **State registry** (`App.tsx → tabRegistryRef`) is a `Map<string, TabSnapshot>` held in a ref. On tab switch, the outgoing tab's state is snapshot'ed (via hook `.getSnapshot()` methods) and the incoming tab's state is restored (via `.restoreSnapshot()`).
- **Three-tier WS routing** in `App.tsx`:
  1. **Global messages** (e.g., `screenshot_start`, `ready`, `screenshot_ready`) — applied regardless of tab
  2. **Active tab messages** — routed to live React state via hooks (includes `screenshot_added`, `screenshot_removed`, `screenshots_cleared`)
  3. **Background tab messages** — applied to the registry via `applyToBackgroundTab()` mini-reducer (handles `screenshot_added`, `screenshot_removed`, `screenshots_cleared` in the snapshot)
- **`wsSend`** helper auto-injects `tab_id: activeTabIdRef.current` as a default, but explicit `tab_id` fields in the message object override it (spread order: `{ tab_id: default, ...msg }`).
- **Tab lifecycle**: `TabBar` creates/closes tabs; `TitleBar`'s "new chat" button creates a new tab. Max 10 tabs. Tabs are ephemeral (don't survive app restart). TabBar is hidden when only 1 tab is open.
- **Cleanup**: When a tab is closed, `registerOnTabClosed` fires a callback that deletes the tab's snapshot from `tabRegistryRef`.

### Stale closure prevention — ref-based WS handler
`App.tsx` subscribes to the WebSocket via `wsSubscribe` with an empty-ish dependency array to avoid re-subscribing on every render. To prevent stale closures, a `handleWebSocketMessageRef` is kept in sync with the latest `handleWebSocketMessage` on every render. The subscription callback calls `handleWebSocketMessageRef.current(data)` instead of the stale closure. The same pattern is used by `MeetingRecorderContext` via `handlersRef`.

Similarly, `handleSubmit` displays the user query optimistically via `chatState.startQuery(queryText)` when `canSubmit` is true (non-queued). A guard in `handleActiveTabMessage`'s `query` case prevents the WS echo from calling `startQuery` again (which would reset in-flight tool calls / content blocks).

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
Handle the new `type` string inside a `subscribe()` callback in the relevant context or page component. Update `websocket.py`'s protocol docstring on the Python side.

### New HTTP endpoint call
Add a method to the `api` singleton at the bottom of `src/ui/services/api.ts`. Use the existing `fetch` + error handling pattern already there.
