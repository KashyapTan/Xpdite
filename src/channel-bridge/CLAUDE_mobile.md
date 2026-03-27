# src/channel-bridge/ — Mobile Integration

## Architecture

```
src/channel-bridge/
├── index.ts              # Entry point: initializes adapters, deduplicates messages, orchestrates components
├── server.ts             # BridgeServer: HTTP endpoints for the Python backend to send outbound messages
├── pythonClient.ts       # HTTP client connecting to Python's /internal/mobile/* endpoints
├── messageUtils.ts       # Parses messy metadata (timestamps, text extraction, WhatsApp JIDs)
├── types.ts              # Shared interfaces (Platform, InboundMessage, CommandResponse, etc.)
│
├── adapters/
│   ├── discord.ts        # Chat SDK Discord wrapper (WebSocket Gateway)
│   ├── telegram.ts       # Chat SDK Telegram wrapper (Polling mode)
│   └── whatsapp.ts       # Chat SDK Baileys wrapper (Pairing code auth)
│
├── commands/
│   └── handler.ts        # Intercepts slash commands (e.g. /new, /stop, /pair)
│
└── config/
    ├── loader.ts         # ConfigLoader: watches mobile_channels_config.json for live reloads
    └── types.ts          # Config interfaces and default configurations
```

The Channel Bridge is a standalone **TypeScript service** spawned by Electron (on port 9000 by default), running alongside the Python backend. Its purpose is to connect to messaging platforms (Telegram, Discord, WhatsApp) using the Chat SDK and bridge messages to and from the Python backend.

---

## Key File Responsibilities

- **`index.ts`** is the main entry point. It instantiates the HTTP server, Python client, config watcher, and platform adapters. It deduplicates incoming messages (protecting against multiple event fires), handles outbound message echoes from WhatsApp, rate-limits "unpaired" error responses, and wires together inbound platform messages with `pythonClient.submitMessage()`. It applies configuration on-the-fly when `mobile_channels_config.json` changes by disconnecting and reconnecting adapters.
- **`server.ts`** exposes an HTTP server (port 9000) for the Python backend to call. Endpoints include:
  - `POST /outbound` — Relay final text or status messages back to a platform thread.
  - `POST /outbound/typing` — Start a typing indicator.
  - `POST /outbound/edit` — Edit an existing message (used for streaming token updates).
  - `POST /send` — Legacy endpoint for sending messages.
  - `GET /health` & `GET /status` — Return platform connection statuses.
- **`pythonClient.ts`** wraps HTTP calls targeting the Python server (port ~8000). Standard message submission goes to `/internal/mobile/message`. Command execution routes to `/internal/mobile/command`. Device pairing logic targets `/internal/mobile/pair/verify` and `/internal/mobile/pair/check`.
- **`commands/handler.ts`** intercepts predefined slash commands (`/new`, `/stop`, `/status`, `/model`, `/help`, `/pair`) before they ever reach the LLM. It forwards them to Python via `pythonClient`. `/pair` is handled particularly here by submitting a 6-digit code to link the mobile user to the desktop.
- **`messageUtils.ts`** is a suite of parsing tools. Mobile platform webhooks (especially WhatsApp via Baileys) yield deeply nested message structures. This file includes `extractTextFromWhatsAppMessage`, timestamp parsers to standard `ms` time, and WhatsApp outbound trackers to silence echoing bugs when we send outbound messages.

---

## Platform Adapters (`adapters/`)

The bridge uses the `Chat SDK` standard interface (from `@chat-adapter/*` packages) but wraps them with dedicated orchestrators in `src/channel-bridge/adapters/`:

1. **Telegram (`telegram.ts`)**: Uses polling mode (`longPolling: { timeout: 30 }`) which is optimal for a desktop application (no public webhook IP required).
2. **Discord (`discord.ts`)**: Requires `Message Content Intent` enabled in the Discord dev portal. Starts a Gateway WebSocket listener to receive direct messages and mentions.
3. **WhatsApp (`whatsapp.ts`)**: Wraps the unofficial `Baileys` library. This is the most complex adapter since WhatsApp lacks a simple Official Bot API for personal use. It relies on the "Linked Devices" mechanism. It handles auth state by writing to `XPDITE_USER_DATA_DIR/whatsapp_auth` using Baileys' `useMultiFileAuthState`. It emits the temporary pairing code as an IPC message (`whatsapp_pairing_code`) which Electron routes to the UI.

---

## Message Flow Workflow

**Inbound (User -> Platform -> Bridge -> Python):**
1. Platform adapter emits an inbound event.
2. `index.ts` normalizes it via `toInboundMessage` and deduplicates using `shouldProcessMessage` (`processedMessageIds`).
3. If it's a command (`/pair`, `/new`), `commands/handler.ts` takes over execution natively and responds via `sendToPlatform`.
4. Otherwise, it calls `pythonClient.submitMessage(inboundMessage)`.
5. If the Python backend indicates the user is unpaired, the bridge replies with "You need to pair first" (rate-limited via `UNPAIRED_RESPONSE_COOLDOWN_MS`).
6. If successfully queued, the bridge immediately calls `reactToMessage('✅')` to acknowledge reception, followed by `startTypingIndicator()`.

**Outbound (Python -> Bridge -> Platform):**
1. Python submits HTTP POST to `/outbound` (or `/outbound/edit` for streaming).
2. `server.ts` maps this to `sendToPlatform` or `editPlatformMessage`.
3. If WhatsApp is the target, `whatsappOutboundTracker.remember(...)` is invoked so that when Baileys immediately echoes the message back to us as a new inbound event, it is silently ignored.

---

## Config & Live Reload (`config/`)

The application's connection details are kept in `mobile_channels_config.json` inside Electron's `userData` directory. The `config/loader.ts` file sets up an `fs.watch` AbortController process on this file. When the configuration is saved from Xpdite's frontend, the watcher triggers `applyConfig()` inside `index.ts`. Next:
- Old platform adapters are gracefully halted (e.g. `adapter.stopPolling()`), except WhatsApp which is selectively preserved if no re-pairing is requested, to avoid login races.
- The platform configuration interfaces are rebuilt and updated connection state is logged.

Because WhatsApp connections are brittle, a full disconnect/reconnect cycle is avoided unless `forcePairing: true` is set, in which case the `whatsapp_auth` folder is wiped for a clean start.
