# src/channel-bridge/ — Mobile Integration

## Architecture

```
src/channel-bridge/
├── index.ts              # Runtime orchestrator: adapter lifecycle, dedup, inbound routing, status emission
├── server.ts             # Loopback HTTP API for Python -> platform outbound relay
├── pythonClient.ts       # Loopback HTTP client for bridge -> Python internal mobile API
├── messageUtils.ts       # Text/timestamp normalization + WhatsApp outbound echo suppression helpers
├── types.ts              # Shared bridge contracts (platforms, statuses, payloads, IPC message shapes)
│
├── adapters/
│   ├── discord.ts        # Chat SDK Discord adapter wiring
│   ├── telegram.ts       # Chat SDK Telegram adapter wiring (polling)
│   └── whatsapp.ts       # Chat SDK Baileys adapter wiring (pairing-code linked-device)
│
├── commands/
│   └── handler.ts        # Slash command interception (/new, /stop, /status, /model, /default, /help, /pair)
│
└── config/
    ├── loader.ts         # Watches mobile_channels_config.json and triggers hot-reload
    └── types.ts          # Config-file schema + parser into runtime adapter config
```

The Channel Bridge is a standalone TypeScript service spawned by Electron after Python is healthy. It binds loopback-only HTTP (default 9000), connects Telegram/Discord/WhatsApp via Chat SDK adapters, and bridges messages bidirectionally with Python internal mobile endpoints.

---

## Runtime Responsibilities

- `index.ts` is the real runtime entrypoint: starts `BridgeServer`, creates `PythonClient`, loads config, (re)builds adapters, initializes Chat SDK, wires inbound handlers (`onNewMention`, `onSubscribedMessage`, `onNewMessage`), and emits structured stdout messages (`CHANNEL_BRIDGE_MSG {...}`) consumed by Electron.
- Inbound dedup + safety live in `index.ts`: message-id TTL cache, startup grace window, WhatsApp self-chat-only filtering (using both the paired account's PN and LID identities so self-chat works on LID-addressed accounts), canonical self-chat thread normalization for outbound relay/editing, outbound-echo suppression, and per-user unpaired-response cooldown.
- `commands/handler.ts` intercepts supported commands before LLM submission: `/new`, `/stop`, `/status`, `/model`, `/default`, `/help`, `/pair`.
- `server.ts` exposes Python-facing loopback relay endpoints: `POST /outbound`, `POST /outbound/typing`, `POST /outbound/edit`, legacy `POST /send`, plus `GET /status` and `GET /health`.
- `pythonClient.ts` calls Python `/internal/mobile/*` endpoints with timeout guards; primary paths are `/message`, `/command`, `/pair/verify`, `/pair/check`, and `/health`.

---

## Message Flow

Inbound (platform -> bridge -> Python):
1. Adapter callback receives a platform message event.
2. `index.ts` normalizes text/sender/timestamps (`toInboundMessage`) and applies dedup + stale-event checks. For WhatsApp, it only accepts self-authored messages in the paired account's self-chat and ignores all other threads.
3. If command, `commands/handler.ts` executes locally by calling Python internal command/pair endpoints.
4. If non-command, bridge posts to `/internal/mobile/message`.
5. On success, bridge reacts with thumbs-up and starts typing; on queue backlog, sends queue-position acknowledgment.
6. On pairing errors, bridge sends "pair first" response with cooldown protection.

Outbound (Python -> bridge -> platform):
1. Python posts to bridge `/outbound` (or `/outbound/edit` for streaming edits).
2. `server.ts` validates payload and routes to `sendToPlatform` / `editPlatformMessage`.
3. WhatsApp outbound IDs are tracked so Baileys echo events are ignored on re-ingest.

---

## Config & Hot Reload

- Source of truth is `mobile_channels_config.json` under Electron `userData`.
- `config/loader.ts` watches the config directory and debounces reloads.
- Discord config is only considered complete when `botToken`, `publicKey`, and `applicationId` are all present. The settings modal pre-fills the non-secret Discord identifiers and preserves an existing saved bot token unless the user explicitly replaces it.
- Reload path (`applyConfig()` in `index.ts`) tears down/rebuilds adapters safely; WhatsApp may be preserved across reloads when already connected and `forcePairing` is not requested.
- `forcePairing: true` triggers fresh WhatsApp auth-state cleanup under `XPDITE_USER_DATA_DIR/whatsapp_auth` before reconnect.

---

## Security Boundaries

- Bridge HTTP server listens on `127.0.0.1` only and is intended for local Python caller usage.
- Python internal mobile endpoints are also loopback-scoped internal APIs (`/internal/mobile/*`), not public cloud-facing contracts.
- Secrets/tokens are persisted by Python settings storage; bridge receives only needed runtime config and should not invent alternate credential stores.
