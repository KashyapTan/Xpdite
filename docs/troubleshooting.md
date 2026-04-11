# Troubleshooting

Use this guide to diagnose common local issues.

## App Does Not Finish Booting

Checks:

1. Confirm backend health on `http://127.0.0.1:8000/api/health` (or nearby ports up to 8009).
2. Confirm Python 3.13+ and dependencies are installed.
3. Restart app to clear stale processes.

Useful commands:

```bash
bun run dev:pyserver
bun run dev:react
bun run dev:electron
```

## Ollama Models Not Available

- Ensure Ollama daemon is running.
- Verify `ollama pull <model>` succeeds.
- Retry model refresh in settings.

## Cloud Models Fail to Load

- Re-save provider API key in settings.
- Verify `/api/keys` reports `has_key=true` for provider.
- Check network access to provider endpoints.

## Tool Calls Not Triggering

- Verify tools in `/api/mcp/servers`.
- Check retrieval settings (`always_on`, `top_k`).
- Confirm expected tools are enabled/reachable.

## Mobile Pairing or Delivery Issues

- Verify bridge health and status endpoints.
- Regenerate pairing code and retry `/pair`.
- Re-save platform config in settings to regenerate bridge config.
- Enable `XPDITE_MOBILE_DEBUG_LOGS=1` for diagnostic output.

## Scheduled Jobs Not Running

- Confirm scheduler service started (app boot logs).
- Verify job is enabled and cron/timezone are valid.
- Use `run-now` endpoint to validate job execution path.

## Artifacts API Access Errors

- Ensure request is loopback-originated.
- Include `X-Xpdite-Server-Token` header when required.
- Confirm Electron can read and pass runtime server token.

## Data or State Corruption Suspicions

- Backup `user_data/` first.
- Inspect SQLite and memory files for malformed content.
- Reproduce issue in development with focused logs/tests.

## Last-Resort Reset

If you need a clean local state, back up and then remove `user_data/` for the target environment.

Warning: this removes local history, artifacts, memories, and settings.

After reset, follow `docs/getting-started.md` for first-run setup and `docs/configuration.md` for data layout expectations.
