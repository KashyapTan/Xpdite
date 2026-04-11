# Operations Guide

This guide covers local runtime operations, observability, and incident response basics for Xpdite deployments.

## Runtime Components

- Electron host process
- Python backend (FastAPI)
- Channel Bridge process
- Optional local Ollama daemon

## Health Endpoints

- Backend: `GET /api/health`
- Mobile internal health: `GET /internal/mobile/health`
- Bridge: `GET http://127.0.0.1:<bridge_port>/health`

## Startup Behavior

- Backend chooses first available port in `8000-8009`.
- Bridge defaults to `9000` and may increment if occupied.
- Electron waits for backend health before marking app ready.

## Logs and Diagnostics

- Python emits structured boot markers: `XPDITE_BOOT {...}`.
- Electron emits optional boot profiling entries when enabled.
- Bridge emits structured messages prefixed with `CHANNEL_BRIDGE_MSG`.
- Optional verbose mobile logs via `XPDITE_MOBILE_DEBUG_LOGS=1`.

### Where Logs Appear

- Development: Python, Electron, and bridge logs appear in the terminals running `bun run dev` processes.
- Packaged desktop runs: process logs are emitted through app runtime console streams; if launching from a terminal, inspect that terminal output first.

## Data Locations

`XPDITE_USER_DATA_DIR` (or Electron `userData` in production) contains:

- `xpdite_app.db`
- `artifacts/`
- `memory/`
- `screenshots/`
- `skills/`
- `mobile_channels_config.json`
- Google token data when connected

## Routine Checks

1. Confirm backend health endpoint is reachable.
2. Confirm expected model providers appear in settings/API.
3. Confirm scheduler starts and jobs show expected next-run metadata.
4. Confirm bridge status and platform states if mobile channels are enabled.

## Common Failure Modes

- **Port conflicts**: backend/bridge auto-probe alternative ports.
- **Provider key failures**: key validation endpoint returns explicit errors.
- **Tool server startup issues**: degraded tool availability, core app remains usable.
- **Bridge adapter auth failures**: platform-specific status shows `error`.

## Recovery Actions

- Restart app to reset process topology.
- Re-save mobile platform config to regenerate bridge config file.
- Reconnect OAuth providers if token state is stale.
- Re-run dependency install if local environment drifted.

## Security Incident Recovery

If endpoint exposure or credential compromise is suspected:

1. Revoke and rotate provider API keys.
2. Reconnect Google integrations to refresh token state.
3. Revoke and re-pair mobile devices.
4. Verify backend and bridge remain loopback-bound.

## Security Notes

- Keep APIs bound to loopback host.
- Do not expose internal mobile endpoints externally.
- Treat user data directory as sensitive local data.

## Related Docs

- `docs/configuration.md`
- `docs/api-reference.md`
- `docs/mobile-bridge.md`
