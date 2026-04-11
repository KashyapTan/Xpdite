# Xpdite Documentation

This directory is organized by audience entry points and domain guides.

## 1) Product and Feature Docs

- [`getting-started.md`](./getting-started.md) — install and first-run guide
- [`features-overview.md`](./features-overview.md) — canonical feature map across the app

## 2) System and Engineering Docs

- [`architecture.md`](./architecture.md) — runtime architecture and data flow
- [`development.md`](./development.md) — coding conventions and implementation workflows
- [`configuration.md`](./configuration.md) — runtime settings, limits, and data layout
- [`api-reference.md`](./api-reference.md) — REST/WebSocket/internal mobile API contracts
- [`mcp-guide.md`](./mcp-guide.md) — MCP integration model and extension workflow

## 3) Feature Domain Docs

- [`artifacts.md`](./artifacts.md)
- [`chat-and-tabs.md`](./chat-and-tabs.md)
- [`meeting-recorder.md`](./meeting-recorder.md)
- [`models-and-providers.md`](./models-and-providers.md)
- [`memory.md`](./memory.md)
- [`scheduled-jobs.md`](./scheduled-jobs.md)
- [`notifications.md`](./notifications.md)
- [`mobile-bridge.md`](./mobile-bridge.md)
- [`skills.md`](./skills.md)
- [`terminal.md`](./terminal.md)

## 4) Operations, Reliability, and Security

- [`operations.md`](./operations.md)
- [`security.md`](./security.md)
- [`troubleshooting.md`](./troubleshooting.md)

## 5) Contribution Process

- [`contributing.md`](./contributing.md)

## Recommended Reading Paths

### End Users

1. [`getting-started.md`](./getting-started.md)
2. [`features-overview.md`](./features-overview.md)
3. [`troubleshooting.md`](./troubleshooting.md)

### New Engineers

1. [`getting-started.md`](./getting-started.md)
2. [`architecture.md`](./architecture.md)
3. [`development.md`](./development.md)
4. [`configuration.md`](./configuration.md)
5. [`api-reference.md`](./api-reference.md)
6. [`features-overview.md`](./features-overview.md)

### Integrations / Platform Engineers

1. [`architecture.md`](./architecture.md)
2. [`api-reference.md`](./api-reference.md)
3. [`mcp-guide.md`](./mcp-guide.md)
4. [`mobile-bridge.md`](./mobile-bridge.md)
5. [`operations.md`](./operations.md)
6. [`security.md`](./security.md)

## Documentation Rules

- Keep one source of truth per domain to avoid duplicate feature descriptions.
- Avoid combining unrelated feature domains in one file.
- Update docs and contracts in the same PR as behavior changes.
