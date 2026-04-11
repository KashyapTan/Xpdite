# Skills

Skills are reusable instruction bundles that can be injected into model context.

## Skill Types

- Builtin skills seeded from repository.
- User-created skills persisted in user data.

## Builtin Skills

Current seeded builtin skills include:

- `terminal`
- `filesystem`
- `websearch`
- `gmail`
- `calendar`
- `browser`
- `youtube`

## Skill Lifecycle

- List all skills
- Read skill content
- Create/update/delete user skills
- Toggle enabled state
- Add reference files to user skills

## API

- `GET /api/skills`
- `GET /api/skills/{name}/content`
- `POST /api/skills`
- `PUT /api/skills/{name}`
- `PATCH /api/skills/{name}/toggle`
- `DELETE /api/skills/{name}`
- `POST /api/skills/{name}/references`

## Runtime Integration

- Skills can be injected via slash-command flow.
- Skills are also exposed via inline tools for model-driven retrieval/injection.

## Related Docs

- `docs/api-reference.md`
- `docs/mcp-guide.md`
- `docs/features-overview.md`
