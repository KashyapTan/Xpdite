# Terminal

This document describes terminal execution features exposed through Xpdite.

## Capability Summary

- Run shell commands through inline terminal tools.
- Interactive PTY session support.
- Approval-based execution controls.
- Streaming output and completion events.

## Approval Model

- Ask levels determine approval strictness (`always`, `on-miss`, `off`).
- Approval history can be cleared.

Terminal settings API:

- `GET /api/terminal/settings`
- `PUT /api/terminal/settings/ask-level`
- `DELETE /api/terminal/approvals`

## WebSocket Interaction

Inbound control messages:

- `terminal_approval_response`
- `terminal_session_response`
- `terminal_stop_session`
- `terminal_kill_command`
- `terminal_set_ask_level`
- `terminal_resize`

Outbound events:

- `terminal_approval_request`
- `terminal_session_request`
- `terminal_session_started`
- `terminal_session_ended`
- `terminal_running_notice`
- `terminal_output`
- `terminal_command_complete`

## Safety Notes

- Terminal execution should remain approval-gated in untrusted prompt contexts.
- Output truncation and command safety controls protect UI/runtime stability.

## Related Docs

- `docs/api-reference.md`
- `docs/security.md`
- `docs/features-overview.md`
