# API Reference

Xpdite exposes:

- **WebSocket** for real-time chat and streaming: `/ws`
- **REST API** for configuration/data operations: `/api/*`
- **Internal mobile API** for Channel Bridge integration: `/internal/mobile/*`

Base host defaults to loopback (`127.0.0.1`) and backend port is auto-selected in `8000-8009`.

Host binding is configurable through `XPDITE_SERVER_HOST`. Binding to non-loopback expands the trust boundary and requires additional external network controls.

## Conventions

- REST requests/responses use JSON unless noted.
- Error shape from FastAPI handlers is typically:

```json
{
  "detail": "Human-readable error message"
}
```

- Artifact endpoints are loopback-gated and may require `X-Xpdite-Server-Token` when runtime token protection is enabled.

## REST API

### Health

- `GET /api/health`
- `GET /api/health/session`

Returns backend health status.

Example response:

```json
{
  "status": "healthy"
}
```

### Models and Keys

- `GET /api/models/ollama`
- `GET /api/models/ollama/info/{model_name}`
- `GET /api/models/enabled`
- `PUT /api/models/enabled`
- `GET /api/models/anthropic`
- `GET /api/models/openai`
- `GET /api/models/gemini`
- `GET /api/models/openrouter`
- `GET /api/keys`
- `PUT /api/keys/{provider}`
- `DELETE /api/keys/{provider}`

### Artifacts

All artifact routes require loopback access. When server token is set, include `X-Xpdite-Server-Token`.

- `GET /api/artifacts`
- `GET /api/artifacts/conversation/{conversation_id}`
- `GET /api/artifacts/{artifact_id}`
- `POST /api/artifacts`
- `PUT /api/artifacts/{artifact_id}`
- `DELETE /api/artifacts/{artifact_id}`

List query parameters:

- `query` (string)
- `type` (`code` | `markdown` | `html`)
- `status` (`ready` | `deleted`)
- `page` (int, default `1`)
- `page_size` (int, default `50`)

Create request example:

```json
{
  "type": "markdown",
  "title": "Release Notes Draft",
  "content": "# v1.2.0\n...",
  "language": "markdown",
  "conversation_id": "conv_abc123",
  "message_id": "msg_abc123"
}
```

Destructive operation note:

- Artifact delete operations are irreversible for API consumers.

### Memory

- `GET /api/memory`
- `GET /api/memory/file`
- `PUT /api/memory/file`
- `DELETE /api/memory/file`
- `DELETE /api/memory`

`PUT /api/memory/file` request example:

```json
{
  "path": "profile/user.md",
  "title": "User Profile",
  "category": "profile",
  "importance": 0.9,
  "tags": ["identity", "preferences"],
  "abstract": "Stable user preferences and context.",
  "body": "- Prefers concise responses\n- Uses Windows"
}
```

Destructive operation note:

- `DELETE /api/memory` clears all memory files and recreates default folders.

### Settings and MCP

- `GET /api/settings/tools`
- `PUT /api/settings/tools`
- `GET /api/settings/sub-agents`
- `PUT /api/settings/sub-agents`
- `GET /api/settings/memory`
- `PUT /api/settings/memory`
- `GET /api/settings/system-prompt`
- `PUT /api/settings/system-prompt`
- `GET /api/mcp/servers`

### Skills

- `GET /api/skills`
- `GET /api/skills/{name}/content`
- `POST /api/skills`
- `PUT /api/skills/{name}`
- `PATCH /api/skills/{name}/toggle`
- `DELETE /api/skills/{name}`
- `POST /api/skills/{name}/references`

### Google Integration

- `GET /api/google/status`
- `POST /api/google/connect`
- `POST /api/google/disconnect`

### External Connectors

- `GET /api/external-connectors`
- `POST /api/external-connectors/{name}/connect`
- `POST /api/external-connectors/{name}/disconnect`

### Mobile Channel Settings (Public)

- `GET /api/mobile-channels/config`
- `PUT /api/mobile-channels/config/{platform_id}`

### Scheduled Jobs

- `GET /api/scheduled-jobs`
- `GET /api/scheduled-jobs/conversations`
- `GET /api/scheduled-jobs/{job_id}`
- `POST /api/scheduled-jobs`
- `PUT /api/scheduled-jobs/{job_id}`
- `DELETE /api/scheduled-jobs/{job_id}`
- `POST /api/scheduled-jobs/{job_id}/pause`
- `POST /api/scheduled-jobs/{job_id}/resume`
- `POST /api/scheduled-jobs/{job_id}/run-now`
- `GET /api/scheduled-jobs/{job_id}/conversations`

`POST /api/scheduled-jobs` request example:

```json
{
  "name": "Daily Standup Summary",
  "cron_expression": "0 9 * * 1-5",
  "instruction": "Summarize yesterday's progress and blockers.",
  "timezone": "America/New_York",
  "model": "qwen3-vl:8b-instruct",
  "delivery_platform": "telegram",
  "delivery_sender_id": "123456789",
  "is_one_shot": false
}
```

Destructive operation note:

- `DELETE /api/scheduled-jobs/{job_id}` permanently removes job definitions.

### Notifications

- `GET /api/notifications`
- `GET /api/notifications/count`
- `DELETE /api/notifications/{notification_id}`
- `DELETE /api/notifications`

Destructive operation note:

- Notification delete operations are irreversible.

### Terminal Settings

- `GET /api/terminal/settings`
- `PUT /api/terminal/settings/ask-level`
- `DELETE /api/terminal/approvals`

`PUT /api/terminal/settings/ask-level` request body:

```json
{
  "level": "on-miss"
}
```

Allowed values: `always`, `on-miss`, `off`.

### Marketplace

- `GET /api/marketplace/sources`
- `POST /api/marketplace/sources`
- `DELETE /api/marketplace/sources/{source_id}`
- `POST /api/marketplace/sources/{source_id}/refresh`
- `GET /api/marketplace/catalog`
- `GET /api/marketplace/installs`
- `POST /api/marketplace/install`
- `POST /api/marketplace/install-package`
- `POST /api/marketplace/install-repo`
- `POST /api/marketplace/installs/{install_id}/enable`
- `POST /api/marketplace/installs/{install_id}/disable`
- `POST /api/marketplace/installs/{install_id}/update`
- `DELETE /api/marketplace/installs/{install_id}`
- `PUT /api/marketplace/installs/{install_id}/secrets`

Requires local-api-access.

### File Browser

- `GET /api/files/browse`

### Internal Mobile API (`/internal/mobile/*`)

These endpoints are intended for Channel Bridge integration.

Security boundary:

- Treat `/internal/mobile/*` as local integration APIs, not public internet APIs.
- Keep backend bound to loopback interfaces.
- Do not expose these routes through external reverse proxies.
- Assume local-trust posture; these routes are intended for the local Channel Bridge process.
- Internal mobile endpoints are unauthenticated by design and rely on loopback/network boundary controls.

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

## WebSocket Protocol (`/ws`)

Message envelope:

```json
{
  "type": "message_type",
  "content": "...",
  "tab_id": "default"
}
```

`tab_id` is required for tab-scoped operations.

Client message example:

```json
{
  "type": "submit_query",
  "tab_id": "default",
  "content": "Summarize this screenshot",
  "capture_mode": "precision",
  "model": "qwen3-vl:8b-instruct"
}
```

Server stream example:

```json
{
  "type": "response_chunk",
  "tab_id": "default",
  "content": "Here is a concise summary..."
}
```

### Client -> Server Types

- Tab lifecycle: `tab_created`, `tab_closed`, `tab_activated`
- Chat flow: `submit_query`, `retry_message`, `edit_message`, `set_active_response`
- Conversation management: `clear_context`, `resume_conversation`, `load_conversation`, `delete_conversation`, `get_conversations`, `search_conversations`
- Queue/cancellation: `stop_streaming`, `cancel_queued_item`
- Screenshots: `remove_screenshot`
- Capture mode: `set_capture_mode`
- Legacy voice transcription: `start_recording`, `stop_recording`
- Terminal approvals/control: `terminal_approval_response`, `terminal_session_response`, `terminal_stop_session`, `terminal_kill_command`, `terminal_set_ask_level`, `terminal_resize`
- YouTube fallback approval: `youtube_transcription_approval_response`
- Meeting recording: `meeting_start_recording`, `meeting_stop_recording`, `meeting_audio_chunk`, `get_meeting_recordings`, `load_meeting_recording`, `delete_meeting_recording`, `search_meeting_recordings`, `meeting_get_status`, `meeting_get_compute_info`, `meeting_get_settings`, `meeting_update_settings`, `meeting_generate_analysis`, `meeting_execute_action`
- Ollama model pull: `ollama_pull_model`, `ollama_cancel_pull`

### Server -> Client Events

- Readiness/base: `ready`, `error`
- Screenshots: `screenshot_start`, `screenshot_added`, `screenshot_removed`, `screenshots_cleared`, `screenshot_ready`
- Chat streaming: `query`, `thinking_chunk`, `thinking_complete`, `response_chunk`, `response_complete`, `token_usage`
- Tooling/artifacts: `tool_call`, `tool_calls_summary`, `artifact_start`, `artifact_chunk`, `artifact_complete`, `artifact_deleted`
- Conversation/history: `context_cleared`, `conversation_saved`, `conversations_list`, `conversation_loaded`, `conversation_deleted`, `conversation_resumed`
- Queue: `queue_full`, `query_queued`, `queue_updated`, `ollama_queue_status`
- Terminal: `terminal_approval_request`, `terminal_session_request`, `terminal_session_started`, `terminal_session_ended`, `terminal_running_notice`, `terminal_output`, `terminal_command_complete`
- YouTube fallback: `youtube_transcription_approval`
- Meeting: `transcription_result`, `meeting_recording_started`, `meeting_recording_stopped`, `meeting_transcript_chunk`, `meeting_recordings_list`, `meeting_recording_loaded`, `meeting_recording_deleted`, `meeting_recording_status`, `meeting_recording_error`, `meeting_processing_progress`, `meeting_compute_info`, `meeting_settings`, `meeting_analysis_started`, `meeting_analysis_complete`, `meeting_analysis_error`, `meeting_action_result`
- Notifications: `notification_added`, `notification_dismissed`, `notifications_cleared`
- Ollama pull: `ollama_pull_progress`, `ollama_pull_complete`, `ollama_pull_error`, `ollama_pull_cancelled`
- Mobile stop acknowledgement: `generation_stopped`

## Notes

- Some event payloads intentionally contain stringified JSON for compatibility.
- Keep this document and `source/api/websocket.py` protocol docstring in sync when adding/removing message types.
