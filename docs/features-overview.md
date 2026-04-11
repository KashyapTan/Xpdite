# Features Overview

This document is the canonical feature map for Xpdite.

Use this as the product-level index, then jump to dedicated docs for architecture and implementation details.

## Core Experience

- Multi-tab chat workspace with independent sessions.
- Streaming responses with reasoning and tool-call visibility.
- Screenshot-first assistant workflow (`Alt + .`).
- Per-message model selection across local and cloud providers.

## AI Model Support

- Local Ollama models.
- Cloud providers: Anthropic, OpenAI, Gemini, OpenRouter.
- Local and cloud model availability/configuration in settings.

## Tooling and MCP

- MCP subprocess servers for filesystem/search/web and external connectors.
- Inline tools for terminal, sub-agents, memory, scheduler, skills, and video watcher.
- Semantic tool retrieval with configurable `always_on` and `top_k`.

## Artifacts

- Detects structured generated artifact blocks from model streams.
- Persists metadata to SQLite and content to DB/filesystem by artifact type.
- Supports listing, retrieval, update, and soft-delete via guarded APIs.

## Long-Term Memory

- Filesystem-backed memory store under `user_data/memory/`.
- Structured metadata front matter + markdown body model.
- Path safety and atomic write protections.
- Memory MCP tools for listing/reading/writing knowledge.

## Skills System

- Builtin and user-defined skills with toggle management.
- Slash command activation flow.
- Builtin seeded skills include terminal, filesystem, websearch, gmail, calendar, browser, and youtube.

## Terminal Integration

- Inline terminal tool with approval controls.
- Session mode, PTY interaction, and output streaming.
- Terminal settings and approval history controls via API.

## Scheduled Jobs

- Cron and one-shot scheduled AI tasks.
- Execution through normal conversation pipeline in isolated scheduled-job tab contexts.
- Pause/resume/run-now controls and run history.

## Notifications

- Global async notification inbox for job outcomes and background completions.
- WebSocket event broadcasting + REST query/dismiss operations.

## Meeting Recorder

- Meeting recording lifecycle and transcript capture.
- Analysis generation and action execution flows.
- Recording library and settings management.

## Mobile Channel Bridge

- Messaging integration for Telegram, Discord, and WhatsApp.
- Pairing-code onboarding and per-sender session management.
- Inbound command/message routing and outbound streaming relay.

## External Integrations

- Google OAuth connection for Gmail/Calendar tool access.
- Extensible external connector lifecycle management.

## History and Search

- Persistent conversation storage with search.
- Resume, load, and delete conversation workflows.

## Files and Attachments

- File browser search endpoint for attachment selection.
- Attachment-aware query submission flow.

## Related Docs

- `docs/api-reference.md`
- `docs/mcp-guide.md`
- `docs/architecture.md`
- `docs/configuration.md`
