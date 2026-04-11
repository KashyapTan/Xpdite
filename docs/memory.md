# Memory

Xpdite memory is a filesystem-backed long-term knowledge layer.

## Purpose

Memory preserves durable user/project context across sessions while remaining editable and transparent.

## Storage Model

- Root directory: `user_data/memory/`
- File format: markdown file with metadata front matter + body.
- Default taxonomy:
  - `profile/`
  - `semantic/`
  - `episodic/`
  - `procedural/`

## Safety Model

Memory path handling enforces:

- relative paths only
- no absolute/drive-prefixed paths
- no traversal (`..`)
- `.md` extension requirement
- root escape prevention after resolution

Writes use lock + atomic replace semantics to reduce corruption risk under concurrency.

## Runtime Behavior

- Memory can be listed, read, updated, deleted, or fully reset via APIs.
- Profile memory auto-injection behavior is controlled by settings.

## API

- `GET /api/memory`
- `GET /api/memory/file`
- `PUT /api/memory/file`
- `DELETE /api/memory/file`
- `DELETE /api/memory`
- `GET /api/settings/memory`
- `PUT /api/settings/memory`

## Memory MCP Tools

- `memlist`
- `memread`
- `memcommit`

## Related Docs

- `docs/api-reference.md`
- `docs/configuration.md`
- `docs/features-overview.md`
