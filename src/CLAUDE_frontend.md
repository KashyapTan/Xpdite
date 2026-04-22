# src/ — Frontend & Electron

## Directory Structure

```
src/
├── channel-bridge/           # Mobile messenger (WhatsApp/Telegram/Discord) integration (see CLAUDE_mobile.md)
├── electron/
│   ├── main.ts               # Electron entry: window creation, IPC handlers, Python lifecycle
│   ├── preload.ts            # contextBridge: exposes electronAPI to renderer (minimal surface)
│   ├── pythonApi.ts          # Python server spawn/kill logic + killProcessesOnPorts() pre-spawn cleanup
│   ├── channelBridgeApi.ts   # Inter-process communication for channel-bridge service lifecycle
│   ├── bootShellHtml.ts      # HTML payload for the early startup boot screen overlay
│   ├── pcResources.ts        # Resource path resolution for packaged app
│   └── utils.ts              # isDev() — checks NODE_ENV === 'development'
│
└── ui/
    ├── main.tsx              # React entry, createHashRouter (7 routes), TabProvider wrap
    ├── pages/
    │   ├── App.tsx                  # Main chat page (query input, response, tool calls, screenshots, tab routing)
    │   ├── Settings.tsx             # Settings page (models, tools, marketplace, skills, memory, artifacts, tasks, mobile, providers, prompt)
    │   ├── ChatHistory.tsx          # Past conversations browser with full-text search
    │   ├── MeetingRecorder.tsx      # Live meeting recording UI
    │   ├── MeetingAlbum.tsx         # Past meeting recordings list (grouped by date)
    │   ├── MeetingRecordingDetail.tsx  # Individual recording detail + AI analysis + action execution
    │   └── ScheduledJobsResults.tsx # History browser for scheduled-job run results
    ├── components/
    │   ├── Layout.tsx        # Shell; manages mini/hidden state; passes {setMini,setIsHidden} via Outlet context
    │   ├── TitleBar.tsx      # Custom title bar: new-chat button, nav icons, mini-mode toggle
    │   ├── TabBar.tsx        # Tab strip (hidden when 1 tab), switch/close
    │   ├── MobilePlatformBadge.tsx # UI component to render platform icons (WhatsApp, Telegram, etc.)
    │   ├── boot/
    │   │   └── BootScreen.tsx    # Early startup loading screen overlay component
    │   ├── icons/
    │   │   ├── AppIcons.tsx      # Shared inline SVG icon components used across the UI
    │   │   ├── ProviderLogos.tsx # Shared React components for AI provider brand logos
    │   │   └── iconPaths.ts      # Shared SVG path constants for React and DOM-built icons
    │   ├── chat/
    │   │   ├── ChatMessage.tsx          # User + assistant message; inline edit, retry, response version nav
    │   │   ├── CodeBlock.tsx            # Syntax-highlighted code block with copy button
    │   │   ├── InlineTerminalBlock.tsx  # Inline terminal (xterm.js PTY or ansi-to-html); approval buttons
    │   │   ├── InlineYouTubeApprovalBlock.tsx  # Inline approval UI for fallback YouTube transcription
    │   │   ├── LoadingDots.tsx          # Three-dot loading animation
    │   │   ├── ResponseArea.tsx         # Scrollable message list; renders streaming + historical blocks and passes scroll container refs
    │   │   ├── SlashCommandMenu.tsx     # Autocomplete skill menu (used by QueryInput)
    │   │   ├── SubAgentTranscript.tsx   # Structured sub-agent transcript renderer
    │   │   ├── ThinkingSection.tsx      # Collapsible thinking/reasoning block
    │   │   ├── ToolCallsDisplay.tsx     # ToolChainTimeline (primary) + legacy flat ToolCallsDisplay
    │   │   ├── DeferredChatHistory.tsx  # Virtualized history renderer (pretext estimate + measured correction)
    │   │   ├── toolCallUtils.ts         # getHumanReadableDescription() for tool calls
    │   │   └── index.ts
    │   ├── input/
    │   │   ├── ModeSelector.tsx         # Precision / fullscreen / meeting audio mode selector
    │   │   ├── QueryInput.tsx           # Chip-aware contentEditable div with slash command autocomplete
    │   │   ├── QueueDropdown.tsx        # Collapsed per-tab queue list above input
    │   │   ├── ScreenshotChips.tsx      # Screenshot thumbnail chips
    │   │   ├── SlashCommandChips.tsx    # ⚠️ LEGACY — superseded by QueryInput chip rendering; not imported
    │   │   ├── TokenUsagePopup.tsx      # Token count popup with context-window progress bar
    │   │   └── index.ts
    │   ├── settings/
    │   │   ├── MeetingRecorderSettings.tsx  # Whisper model, diarization, audio retention (WS-based)
    │   │   ├── SettingsApiKey.tsx           # API key entry per provider
    │   │   ├── SettingsConnections.tsx      # Google OAuth + external MCP connectors
    │   │   ├── SettingsArtifacts.tsx        # Artifact browser/editor settings panel
    │   │   ├── SettingsMemory.tsx           # Long-term memory settings + file management
    │   │   ├── SettingsMobileChannels.tsx   # Mobile platform setup (tokens + WhatsApp pairing code)
    │   │   ├── SettingsModels.tsx           # Ollama + cloud model enable/disable toggles
    │   │   ├── SettingsScheduledJobs.tsx    # Scheduled task management (pause/resume/run-now/delete)
    │   │   ├── SettingsSkills.tsx           # Full CRUD for user skills and builtin overrides
    │   │   ├── SettingsSubAgents.tsx        # Tier model mapping for sub-agent fast/smart modes
    │   │   ├── SettingsSystemPrompt.tsx     # Editable system prompt template
    │   │   └── SettingsTools.tsx            # Always-on tools, topK slider, per-tool toggles
    │   └── terminal/
    │       ├── ApprovalCard.tsx         # Standalone approval prompt (legacy — now inside InlineTerminalBlock)
    │       ├── SessionBanner.tsx        # Session mode active/request banner
    │       ├── TerminalCard.tsx         # Past terminal event in chat history
    │       └── TerminalPanel.tsx        # ⚠️ Fully implemented but NOT rendered in App.tsx; supplanted by InlineTerminalBlock
    ├── contexts/
    │   ├── BootContext.tsx           # Boot sequence initialization, readiness state
    │   ├── WebSocketContext.tsx      # Single WS connection provider (send, subscribe, isConnected)
    │   ├── MeetingRecorderContext.tsx # Recording state (persists across routes)
    │   └── TabContext.tsx             # TabProvider: tab list, active tab, switch/close/create with callbacks
    ├── hooks/
    │   ├── useChatState.ts    # All in-flight and history chat state + terminal block management
    │   ├── useScreenshots.ts  # Screenshot list + meetingRecordingMode flag
    │   ├── useAudioCapture.ts # System audio capture for meeting recording (WASAPI + mic mix)
    │   ├── useTokenUsage.ts   # Token count display
    │   └── index.ts
    ├── services/
    │   ├── api.ts             # singleton `api` (HTTP helpers)
    │   ├── portDiscovery.ts   # Dynamic server port discovery (IPC-first, then probe 8000–8009)
    │   └── index.ts
    ├── types/
    │   └── index.ts           # ChatMessage, ContentBlock, TerminalCommandBlock, TabSnapshot, ResponseVariant, Electron API bridge types…
    ├── CSS/                   # Theme + stylesheets grouped by feature (base, boot, components, chat, input, pages, settings, terminal)
    ├── assets/                # App icons, provider SVGs, logos
    ├── test/                  # Vitest frontend behavioral & unit tests (matches ui structure)
    └── utils/
        ├── chatMessages.ts    # Message mapping, merging, retry/edit reconciliation utilities
        ├── clipboard.ts       # copyToClipboard helper
        ├── modelDisplay.ts    # Model name formatting tools for UI display
        ├── perfLogger.ts      # Renderer perf logger; forwards metrics to Electron terminal via IPC
        ├── pretextMessageLayout.ts # pretext-based message height estimation + cache utilities for virtualization
        ├── providerLogos.ts   # Resolves logos based on API provider string
        └── index.ts
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
- **TabContext** (`contexts/TabContext.tsx`) manages the list of open tabs, active tab ID, per-tab queue items, and a persistent `Map<string, TabSnapshot>` registry that survives route changes.
- **State registry** is accessed by `App.tsx` through `getTabSnapshot()` / `setTabSnapshot()`. On tab switch, the outgoing tab's state is snapshot'ed (via hook `.getSnapshot()` methods) and the incoming tab's state is restored (via `.restoreSnapshot()`). `App.tsx` also saves the active tab during unmount so navigating to Settings / History does not blank tabs.
- **Three-tier WS routing** in `App.tsx`:
  1. **Global messages** (e.g., `screenshot_start`, `ready`, `screenshot_ready`) — applied regardless of tab
  2. **Active tab messages** — routed to live React state via hooks (includes `screenshot_added`, `screenshot_removed`, `screenshots_cleared`)
  3. **Background tab messages** — applied to the registry via `applyToBackgroundTab()` mini-reducer (handles `screenshot_added`, `screenshot_removed`, `screenshots_cleared` in the snapshot)
- **`wsSend`** helper auto-injects `tab_id: activeTabIdRef.current` as a default, but explicit `tab_id` fields in the message object override it (spread order: `{ tab_id: default, ...msg }`).
- **Tab lifecycle**: `TabBar` creates/closes tabs; `TitleBar`'s "new chat" button and `ChatHistory.tsx` both create a new tab before navigating back to the chat route. Max 10 tabs. Tabs are ephemeral (don't survive app restart). TabBar is hidden when only 1 tab is open.
- **Cleanup**: When a tab is closed, `registerOnTabClosed` fires a callback that deletes the tab's persisted snapshot from `TabContext`.

### Stale closure prevention — ref-based WS handler
`App.tsx` subscribes to the WebSocket via `wsSubscribe` with an empty-ish dependency array to avoid re-subscribing on every render. To prevent stale closures, a `handleWebSocketMessageRef` is kept in sync with the latest `handleWebSocketMessage` on every render. The subscription callback calls `handleWebSocketMessageRef.current(data)` instead of the stale closure. The same pattern is used by `MeetingRecorderContext` via `handlersRef`.

Similarly, `handleSubmit` displays the user query optimistically via `chatState.startQuery(queryText)` when `canSubmit` is true (non-queued). A guard in `handleActiveTabMessage`'s `query` case prevents the WS echo from calling `startQuery` again (which would reset in-flight tool calls / content blocks).

Retry/edit flows are different from brand-new submits: `response_complete` still ends the stream, but `conversation_saved` is the source of truth for patching the existing turn in `chatHistory`. Keep turn-aware reconciliation logic in `src/ui/utils/chatMessages.ts` instead of duplicating it inside components.

### Streaming state — state + refs dual pattern
`useChatState` holds every field in both `useState` (drives re-renders) **and** `useRef` (for mutation inside async callbacks mid-stream). The refs are the source of truth during a stream; state is synced from them. On response complete, refs are read to commit to `chatHistory`, then both are reset.

This is intentional: mutating React state inside a streaming callback causes stale-closure bugs. The refs guarantee you always read the latest accumulated text regardless of how many renders have fired.

### Chat history virtualization (pretext + measured correction)
- `DeferredChatHistory.tsx` virtualizes when history length passes a threshold (currently 20 rows).
- Row heights are estimated up front by `utils/pretextMessageLayout.ts` using `@chenglou/pretext`, then corrected with real DOM measurements via `ResizeObserver`.
- The list uses top/bottom spacer divs plus overscan to render only the visible window.
- Cache reset rules are explicit: width changes and large conversation swaps trigger estimate/measured cache rebuilds.
- Performance telemetry is emitted from the renderer (`[chat-performance] ...`) and includes DOM reduction and cycle timing fields.

### Content blocks — interleaved rendering
The `contentBlocks: ContentBlock[]` array interleaves `{ type: 'text' }`, `{ type: 'tool_call' }`, `{ type: 'terminal_command' }`, `{ type: 'thinking' }`, `{ type: 'youtube_transcription_approval' }`, and `{ type: 'artifact' }` entries to render tool calls, artifacts, and approval UI inline between text segments. Do not use a flat `response` string for display when tool calls or artifacts are present — use `contentBlocks`.

### Shared inline icons
Reuse `src/ui/components/icons/AppIcons.tsx` for UI iconography instead of pasted Unicode glyphs or ad-hoc SVG duplication. If a non-React DOM builder needs the same icon (for example `QueryInput.tsx` chip rendering), reuse `src/ui/components/icons/iconPaths.ts` so the SVG path data stays centralized.

### Chat message metadata and footer actions
`ChatMessage` now carries stable `messageId`, `turnId`, `timestamp`, `activeResponseIndex`, and `responseVersions`. `components/chat/ChatMessage.tsx` owns footer UI (copy, retry, timestamp, and user-only edit); `ResponseArea.tsx` just wires callbacks from `App.tsx`.

### Retry / Edit flow
`App.tsx` tracks in-flight retry/edit operations via `pendingTurnActionsRef: Map<string, PendingTurnAction>` (keyed by `tabId`):
```ts
type PendingTurnAction = { type: 'retry' | 'edit'; messageId: string; editedContent?: string }
```
When the user clicks Retry or saves an edit:
1. `handleRetryMessage` / `handleEditMessage` stores a `PendingTurnAction` and sends `retry_message` / `edit_message` to the server.
2. After `conversation_saved` arrives (with `operation: 'retry' | 'edit'`), `App` automatically sends `resume_conversation` to reload the full updated history.
3. `applySavedTurnToHistory(history, turn, operation, localPatch)` in `chatMessages.ts` performs the reconciliation — slices history at the affected turn and rebuilds it with server metadata.

Retry/edit is disabled for messages that don't yet have a server-assigned `messageId` (`canPersistActions = !!message.messageId`).

### Response versioning
Each assistant `ChatMessage` carries `responseVersions: ResponseVariant[]` and `activeResponseIndex`. Users navigate versions with left/right arrow buttons in `ChatMessage.tsx`. `applyResponseVariant(message, index)` switches the visible content without re-fetching.

```ts
interface ResponseVariant {
  content: string
  model?: string
  timestamp?: number
  contentBlocks?: ContentBlock[]
}
```

### `QueryInput` — chip-aware contentEditable
`QueryInput` is **not a `<textarea>`**. It is a `contentEditable` div that renders slash command tokens as non-editable chip spans inline:
- `normalizeQuerySegments(query, commandMap)` — parses text into `QuerySegment[]` (`text` or `chip`).
- `buildChipNode(command, label)` — creates `<span data-slash-chip="true">` with an `×` remove button.
- `getSlashTrigger(node)` — detects partial `/command` typed by the user and opens `SlashCommandMenu`.
- `getSelectionOffset()` / `restoreSelectionOffset()` — custom cursor tracking that survives DOM mutations.
- `COMMAND_TOKEN_PATTERN = /(?<!\S)\/([a-zA-Z0-9_-]+)(?=\s|$)/g`
- On mount, fetches `api.skillsApi.getAll()` to build the command map.

### `ToolChainTimeline` — primary tool display
`ToolCallsDisplay.tsx` exports **`ToolChainTimeline`** (new) in addition to the legacy flat `ToolCallsDisplay`. `ToolChainTimeline` separates content blocks into:
- `chainBlocks` — thinking tokens, tool calls, terminal commands (interleaved, collapsible).
- `responseBlocks` — trailing text after all tools complete.

Timeline item kinds: `thinking_tokens` (collapsible `ChainThinkingItem`), `thinking` (plain), `tool` (wrench+check), `terminal` (renders `InlineTerminalBlock`), `done` (final check marker). Auto-expands while any tool is running.

`src/ui/components/chat/toolCallUtils.ts` is the source of truth for human-readable tool-call badges, per-tool descriptions, and server summary fragments. When adding new MCP servers or tools, update that file (and keep `ToolCallsDisplay.tsx` wired to its helpers) so chat tool calls stay polished.

### `InlineTerminalBlock` — embedded terminal in chat
Filepath: `src/ui/components/chat/InlineTerminalBlock.tsx`

Replaces `TerminalPanel` for in-flow terminal I/O. Two rendering paths:
- **PTY mode** (`isPty=true`): xterm.js with `FitAddon`; `writtenChunksRef` prevents replay on re-render.
- **Non-PTY mode**: `ansi-to-html` with VSCode Dark+ compatible ANSI color theme.

Status: `pending_approval` (yellow + Allow/Deny/Allow&Remember buttons) → `running` (spinner) → `completed` (green/red) / `denied` (red). `ResizeObserver` keeps xterm fitted and calls `onTerminalResize(cols, rows)` to sync the PTY.

### `InlineYouTubeApprovalBlock` — approval block in chat
Filepath: `src/ui/components/chat/InlineYouTubeApprovalBlock.tsx`

Renders `youtube_transcription_approval` content blocks inline with metadata returned from backend fallback planning (title/channel/duration, no-captions reason, download/transcription/total estimate, whisper model, compute backend). Sends approval/deny through `onRespond(requestId, approved)` and the app forwards it as `youtube_transcription_approval_response`.

### `SubAgentTranscript` — structured nested transcript renderer
Filepath: `src/ui/components/chat/SubAgentTranscript.tsx`

Renders serialized sub-agent step JSON (text/tool steps) into an in-message transcript view. Tool steps support collapsible result panes and running states, so nested sub-agent work stays readable inside a single assistant response.

### Settings tabs (full list)
`Settings.tsx` renders the following tabs in order:
`models → connections → tools → marketplace → skills → memory → artifacts → scheduled-jobs → meeting → sub-agents → mobile → system-prompt → ollama (placeholder) → anthropic → gemini → openai → openrouter`

- **`marketplace`** → `<MarketplaceSettings>` — Community extension manager for skills, prompts, and server installs.
- **`connections`** → `<SettingsConnections>` — Google OAuth for Gmail + Calendar plus external MCP connector toggles. Shows email and service badges when connected.
- **`meeting`** → `<MeetingRecorderSettings>` — Whisper model selector, diarization toggle, keep-audio toggle. Communicates via WS (`meeting_get_compute_info`, `meeting_get_settings`, `meeting_update_settings`).
- **`mobile`** → `<SettingsMobileChannels>` — Connects WhatsApp, Telegram, and Discord to the unified backend via the channel-bridge daemon. WhatsApp uses phone-number + pairing-code linked-device auth. Discord setup requires bot token, application ID, and public key; reconnect keeps the saved token unless the user replaces it.
- **`sub-agents`** → `<SettingsSubAgents>` — Tier mapping for sub-agent `fast_model` and `smart_model`; blank values fall back to the currently active model.
- **`scheduled-jobs`** → `<SettingsScheduledJobs>` — Scheduled task controls (toggle, run-now, delete, per-job forwarding targets).
- **`system-prompt`** → `<SettingsSystemPrompt>` — Editable system prompt template with Save/Reset. Placeholders: `current_datetime`, `os_info`, `skills_block`, `memory_block`, `artifacts_block`, `user_profile_block`.

### `api` singleton
- The `api` object provides typed HTTP helpers.
- Use `useWebSocket().send` for real-time actions.
- `api` singleton in `api.ts` — plain `fetch` calls for one-shot HTTP operations. Import `api` directly; don't create new instances.

`QueryInput` uses `api.browseFiles(query?)` for the `@` file picker. Backend responses are relevance-ranked globally from the home subtree (no folder navigation), so the top suggestion is the closest match for the typed token.

**`api` HTTP methods** (partial list — see `api.ts` for full surface):
```ts
// Models
api.getOllamaModels()            → GET /api/models/ollama
api.getEnabledModels()           → GET /api/models/enabled
api.setEnabledModels(models)     → PUT /api/models/enabled
api.getProviderModels(provider)  → GET /api/models/{provider}   // CloudModel[]

// API Keys
api.getApiKeyStatus()            → GET /api/keys
api.saveApiKey(provider, key)    → PUT /api/keys/{provider}
api.deleteApiKey(provider)       → DELETE /api/keys/{provider}

// Google OAuth
api.getGoogleStatus()            → GET /api/google/status
api.connectGoogle()              → POST /api/google/connect
api.disconnectGoogle()           → POST /api/google/disconnect

// MCP / Tools
api.getMcpServers()              → GET /api/mcp/servers
api.getToolsSettings()           → GET /api/settings/tools
api.setToolsSettings(alwaysOn, topK) → PUT /api/settings/tools

// Sub-Agents
api.getSubAgentSettings()        → GET /api/settings/sub-agents
api.setSubAgentSettings(settings)→ PUT /api/settings/sub-agents

// System Prompt
api.getSystemPrompt()            → GET /api/settings/system-prompt
api.setSystemPrompt(template)    → PUT /api/settings/system-prompt

// Skills (sub-object)
api.skillsApi.getAll()           → GET /api/skills
api.skillsApi.getContent(name)   → GET /api/skills/{name}/content
api.skillsApi.create(skill)      → POST /api/skills
api.skillsApi.update(name, u)    → PUT /api/skills/{name}
api.skillsApi.toggle(name, en)   → PATCH /api/skills/{name}/toggle
api.skillsApi.delete(name)       → DELETE /api/skills/{name}
```

---

## Electron-Specific Notes

### Window
- Frameless, transparent, **420×420**, `alwaysOnTop: true` at `screen-saver` level.
- **Mini mode** (52×52): saves `normalBounds` before shrinking; `setResizable(true)` called before `setSize()` to allow shrinking below minimum; restores on exit. Triggered via `ipcMain.handle('set-mini-mode', …)`.
- `minimizable: false`, `maximizable: false`, `skipTaskbar: true` — intentional for overlay UX.
- `setDisplayMediaRequestHandler` — auto-approves `getDisplayMedia` with `{ video: { source: tab-capture-stream } }` for WASAPI loopback audio capture; required by `useAudioCapture`.

### IPC surface (preload.ts)
Several key methods are exposed via `contextBridge`:
- `window.electronAPI.setMiniMode(mini: boolean)`
- `window.electronAPI.focusWindow()`
- `window.electronAPI.getServerPort()` — returns the port the Python backend is listening on (production only)
- `window.electronAPI.getServerToken()` — loopback auth token for protected local endpoints (artifact API)
- `window.electronAPI.getBootState()` / `onBootState` — Boot initialization communication
- `window.electronAPI.retryBoot()`
- `window.electronAPI.perfLog(message)` — writes renderer-side perf metrics into Electron main-process terminal output
- `window.electronAPI.getChannelBridgePort()` / `getChannelBridgeStatus` / `onChannelBridgeStatus` — Channel Bridge daemon RPC
- `window.electronAPI.onWhatsAppPairingCode` — Receives Baileys WhatsApp OTP codes

Do not add IPC channels without updating both `preload.ts` (expose) and `main.ts` (handle).

### `pythonApi.ts` extras
- **`killProcessesOnPorts()`** — runs before every Python spawn; parses `netstat -ano -p tcp` for listeners on 8000–8009, inspects process metadata (including command lines), and kills only owned backend processes with `taskkill /F /T`. Prevents stale-port collisions without killing unrelated services.
- **Injected env vars:** `XPDITE_USER_DATA_DIR` (production path wiring) and `XPDITE_SERVER_TOKEN` (loopback auth token for protected internal endpoints).
- **Boot marker parsing:** stdout `XPDITE_BOOT {...}` lines are parsed and forwarded to Electron boot state handlers (`onBootMarker`).

### Python server lifecycle
- **Dev:** Electron does *not* start Python. `dev:pyserver` runs it independently. `isDev()` guards this.
- **Prod:** Electron spawns `resources/python-server/xpdite-server.exe` (PyInstaller bundle) from `pythonApi.ts → startPythonServer()`. The exe path differs between packaged and unpackaged builds — `pythonApi.ts` resolves `process.resourcesPath` at runtime.
- **Port discovery:** The Python backend binds to the first available port in 8000–8009. The renderer discovers the port automatically via `portDiscovery.ts`:
  1. **IPC path (production):** `window.electronAPI.getServerPort()` returns the port detected by Electron's stdout parsing. The IPC-provided port is validated with a `/api/health` check before trusting it (guards against stale default when the Python server binds to a different port).
  2. **Probe fallback (dev / no IPC):** Concurrent `GET /api/health` requests to ports 8000–8009; first 200 wins.
  3. `WebSocketContext` calls `discoverServerPort()` before each connection (and `resetDiscovery()` on disconnect so a server restart on a new port is handled).
  4. Every `api.*` HTTP method internally calls `await baseUrl()`, which awaits `discoverServerPort()` (cached after first resolution). This eliminates race conditions — no separate sync step is needed.
- **Never hardcode `localhost:8000`** in frontend code — always use `getWsBaseUrl()` / `getHttpBaseUrl()` from `portDiscovery.ts`, or the `api` singleton which calls them internally.

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

---

## Frontend Testing (Vitest)

- **Runner:** Vitest + Testing Library in `jsdom` mode (`vitest.config.ts`).
- **Test location:** `src/ui/test/**` (grouped by `components`, `contexts`, `hooks`, `services`, `utils`).
- **Global setup:** `src/ui/test/setup.ts` for browser API shims (`matchMedia`, `ResizeObserver`, `IntersectionObserver`, `scrollIntoView`).

### Commands
```bash
bun run test:frontend
bun run test:frontend:watch
bun run test:frontend:coverage
```

### Conventions
- Prefer behavior-level tests for user-visible UI and state transitions.
- Keep mocks constructor-compatible for classes instantiated with `new` (for example `WebSocket`, `Terminal`, `FitAddon`, `AnsiToHtml`).
- For modules with import-time singleton state (for example `portDiscovery.ts`), use `vi.resetModules()` and dynamic imports per test to isolate state.

---

## Key `chatMessages.ts` Utilities

These are the primary reconciliation utilities used by `App.tsx` to keep local state consistent with server-persisted data:

| Function | Purpose |
|---|---|
| `mapConversationMessagePayload(msg)` | Maps server conversation message payload → `ChatMessage`; handles camelCase + snake_case |
| `mapConversationContentBlock(block)` | Maps persisted DB block payload to frontend `ContentBlock` union type |
| `mergeMessageMetadata(local, persisted)` | Merges in-flight local state with server data; local wins for content, persisted wins for IDs |
| `applyResponseVariant(message, index)` | Switches active response variant; clears thinking/toolCalls for variants with contentBlocks |
| `applySavedTurnToHistory(history, turn, operation, localPatch?)` | Applies a server-saved turn to local history for submit/retry/edit operations |
| `serializeMessageForCopy(msg)` | Serializes full message to plain text for clipboard, using contentBlocks when present |
| `normalizeTimestamp(ts)` | Converts Unix seconds to milliseconds if `ts < 1_000_000_000_000`; keeps values at/above threshold as milliseconds |
| `formatMessageTimestamp(ts)` | Returns locale time string (HH:MM AM/PM) |

```ts
interface LocalTurnPatch {
  user?: ChatMessage
  assistant?: ChatMessage
}
```
