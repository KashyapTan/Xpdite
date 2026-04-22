# Notifications

Notifications provide global visibility for asynchronous events.

## Purpose

- Surface completion/failure of background work.
- Provide quick navigation context to related conversations/jobs.

## Typical Notification Types

- `job_complete`
- `job_error`
- `tab_completed`

## Data and Delivery

- Persisted in SQLite `notifications` table.
- Broadcast to renderer through WebSocket events.

WebSocket events:

- `notification_added`
- `notification_dismissed`
- `notifications_cleared`

## API

- `GET /api/notifications`
- `GET /api/notifications/count`
- `DELETE /api/notifications/{notification_id}`
- `DELETE /api/notifications`

## UX Notes

- Frontend can maintain unread count and badge state from API + events.

## Related Docs

- `docs/scheduled-jobs.md`
- `docs/api-reference.md`
