# Security Overview

This document summarizes the core security controls in Xpdite's local-first architecture.

## Threat Model Scope

Xpdite is primarily a single-user local desktop app.

Primary risks:

- Unauthorized local process access to sensitive APIs
- Unsafe tool execution
- Credential leakage
- Path traversal / filesystem escape

## Core Controls

### API Surface Restrictions

- Backend defaults to loopback host binding.
- Sensitive artifact routes enforce loopback and session token checks.
- Internal mobile endpoints are intended only for local bridge integration.
- Internal mobile endpoints are unauthenticated and depend on loopback-only exposure.
- Non-loopback binding (`XPDITE_SERVER_HOST`) requires explicit external hardening.

### Session Token Protection

- Electron generates a random server token per runtime session.
- Token is required by guarded artifact routes via `X-Xpdite-Server-Token` header when configured.

Coverage note:

- Session-token enforcement is currently applied to guarded artifact APIs.
- Other local APIs rely primarily on loopback binding and local process trust boundaries.

### Electron Renderer Isolation

- Renderer Node integration is disabled.
- Context isolation is enabled.
- Access to privileged operations is mediated through preload IPC.

### Credential Handling

- Provider API keys are encrypted before persistence.
- Google OAuth tokens are stored in user data directory and managed by backend integration flows.

Current limitation:

- Mobile channel tokens are currently stored in SQLite settings and propagated to `mobile_channels_config.json` for bridge runtime use.
- Treat user data storage as sensitive local secret material and apply OS account isolation and disk encryption.

### Filesystem Safety

- Memory service normalizes and validates relative paths.
- Absolute paths, traversal, and invalid extensions are rejected for memory operations.
- Artifact and memory writes use controlled storage roots.

### Tool Execution Safety

- Terminal tool execution requires approval flow based on configured ask-level.
- Tool outputs are sanitized/truncated for stability and leakage reduction.
- Inline tool interceptors centralize execution controls.

## Recommended Hardening Practices

- Keep app and dependencies updated.
- Do not run with elevated OS privileges unless necessary.
- Restrict local machine access and protect user profile data.
- Regularly rotate/revoke cloud provider keys when needed.

## Reporting

For vulnerability handling process and disclosure policy, also review `SECURITY.md` at repository root.

## Related Docs

- `docs/api-reference.md`
- `docs/operations.md`
- `docs/configuration.md`
