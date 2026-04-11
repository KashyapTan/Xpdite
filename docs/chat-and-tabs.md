# Chat and Tabs

This document describes core chat behavior, tab/session isolation, and queue semantics.

## Core Chat Flow

1. Frontend sends `submit_query` over WebSocket with `tab_id`.
2. Backend enqueues request for that tab.
3. Provider stream emits thinking/response/tool events.
4. Frontend updates chat UI in real time.

## Tab Model

- Frontend currently allows up to 10 open tabs.
- Backend tab manager supports up to 50 tabs.
- Each tab has isolated chat state and screenshot context.

## Queue Model

- Each tab has its own queue.
- Per-tab queue size is 5.
- Queue state events:
  - `query_queued`
  - `queue_updated`
  - `queue_full`

## Conversation Operations

WebSocket request types:

- `submit_query`
- `retry_message`
- `edit_message`
- `set_active_response`
- `stop_streaming`
- `cancel_queued_item`
- `clear_context`
- `resume_conversation`
- `load_conversation`
- `delete_conversation`
- `get_conversations`
- `search_conversations`

Conversation events:

- `conversation_saved`
- `conversations_list`
- `conversation_loaded`
- `conversation_resumed`
- `conversation_deleted`

## Screenshot Context

- Capture hotkey flow is integrated with chat submission.
- Screenshot events:
  - `screenshot_start`
  - `screenshot_added`
  - `screenshot_removed`
  - `screenshots_cleared`

## History and Search

- Conversation history persists in SQLite.
- Search and listing operations are available from WebSocket conversation commands.

## Related Docs

- `docs/api-reference.md`
- `docs/architecture.md`
- `docs/features-overview.md`
