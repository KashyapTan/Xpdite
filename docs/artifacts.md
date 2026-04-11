# Artifacts

Artifacts are structured generated outputs captured during model responses.

## Purpose

Artifacts provide persistent, standalone renderable units for generated content.

Supported types:

- `code`
- `markdown`
- `html`

## Lifecycle

1. Artifact parser detects artifact blocks during stream processing.
2. Metadata is written to SQLite artifact records.
3. Content storage strategy:
   - `html`: inline in DB
   - `code` and `markdown`: stored as files under `user_data/artifacts/<type>/`
4. Artifact can be linked to origin conversation/message IDs.

## Data Model

Artifact metadata includes:

- `id`, `type`, `title`, `language`
- `size_bytes`, `line_count`
- `status`
- `conversation_id`, `message_id`
- timestamps

## API

- `GET /api/artifacts`
- `GET /api/artifacts/conversation/{conversation_id}`
- `GET /api/artifacts/{artifact_id}`
- `POST /api/artifacts`
- `PUT /api/artifacts/{artifact_id}`
- `DELETE /api/artifacts/{artifact_id}`

## Security

- Artifact API access is loopback-restricted.
- When runtime server token is set, `X-Xpdite-Server-Token` is required.

## Operational Notes

- Artifact deletion is modeled as soft-delete in lifecycle events.
- Artifact text is indexed for search where configured.

## Related Docs

- `docs/api-reference.md`
- `docs/features-overview.md`
