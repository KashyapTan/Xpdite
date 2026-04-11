# Mobile Bridge

The Mobile Bridge is a standalone TypeScript process that connects messaging platforms to Xpdite.

## Supported Platforms

- Telegram
- Discord
- WhatsApp

## High-Level Flow

Inbound:

1. Platform adapter receives message.
2. Bridge normalizes/deduplicates payload.
3. Bridge forwards to backend internal mobile API.
4. Backend enqueues message in mobile session context.

Outbound:

1. Backend emits relay callbacks for mobile-originated sessions.
2. Bridge sends new message and optionally edits for streaming updates.

## Pairing and Sessions

- Pairing uses `/pair <code>` verification.
- Paired devices are persisted in backend DB.
- Sessions map sender identity to stable tab context.

## Bridge Endpoints

- `GET /health`
- `GET /status`
- `POST /outbound`
- `POST /outbound/edit`
- `POST /outbound/typing`

## Backend Internal Mobile API

- `POST /internal/mobile/message`
- `POST /internal/mobile/command`
- `POST /internal/mobile/pair/verify`
- `POST /internal/mobile/pair/check`
- `POST /internal/mobile/pair/generate`
- `GET /internal/mobile/devices`
- `DELETE /internal/mobile/devices/{device_id}`
- `POST /internal/mobile/whatsapp/connection`
- `GET /internal/mobile/sessions`
- `GET /internal/mobile/session/{platform}/{sender_id}`
- `DELETE /internal/mobile/session/{platform}/{sender_id}`
- `GET /internal/mobile/health`
- `POST /internal/mobile/cleanup`

## Commands

- `/pair <code>`
- `/new`
- `/stop`
- `/status`
- `/model <name>`
- `/default <name>`
- `/help`

## Security and Deployment Notes

- Keep bridge and internal mobile endpoints on loopback interfaces.
- Do not expose internal mobile routes to external networks.
- Use local firewall restrictions where applicable.
- Bridge HTTP endpoints are trust-local and currently do not enforce endpoint authentication.
- Keep browser access to bridge ports restricted to trusted local contexts only.
- Disable or stop Channel Bridge when mobile channels are not in use.

## Related Docs

- `docs/api-reference.md`
- `docs/scheduled-jobs.md`
- `docs/notifications.md`
