<div align="center">
  <a href="https://github.com/KashyapTan/xpdite">
    <img alt="xpdite" width="240" src="./assets/xpdite-logo-github-bg.svg">
  </a>
</div>
<h3 align="center">Your AI Assistant and Agent Harness with Xpdite.</h3>
<h4 align="center">| Free | Easy | Open Source | Private |</h4>

---

# Xpdite

An AI assistant and agent harness that is truly **yours**. It runs your desktop using any model provider (local or cloud), is completely open-source, 100% customizable, and built for everyone (technical or not).

## Key Features

- **Screenshot + Vision AI** -- Capture any region of your screen (Alt+.) and ask questions about it
- **Multi-Model Support** -- Local Ollama models + cloud (Claude, GPT, Gemini, OpenRouter) from one UI
- **Streaming Responses** -- Real-time token-by-token display with thinking/reasoning visibility
- **Multi-Tab** -- Multiple independent AI conversations running in parallel
- **MCP Tool Integration** -- File ops, web search, Gmail, Calendar, and terminal via Model Context Protocol
- **Inline Terminal** -- AI-commanded shell execution with approval flow inline in the chat
- **Skills / Slash Commands** -- Type `/terminal`, `/filesystem`, `/websearch` etc. to force-inject expert instruction sets
- **Meeting Recorder** -- System audio capture + AI transcription (WhisperX + diarization) + action extraction
- **Response Retry / Edit** -- Re-generate any response or edit past messages; browse alternate versions with arrows
- **Cloud Models** -- Anthropic (Claude), OpenAI (GPT / o-series), Google Gemini, and OpenRouter via LiteLLM
- **Gmail & Calendar** -- Read, send emails and manage calendar events via your Google account
- **Web Search** -- DuckDuckGo-powered search and web page reading through MCP tools
- **Voice Input** -- Voice-to-text transcription via faster-whisper
- **Chat History** -- SQLite-backed conversation persistence with full-text search (FTS5)
- **Token Tracking** -- Context window usage monitoring per conversation
- **Always-on-Top** -- Frameless, transparent floating window that stays above all apps (including fullscreen)
- **Mini Mode** -- Collapse to a 52×52 widget when not in use

## Getting Started

### Prerequisites

- **Ollama** -- Download from [ollama.com](https://ollama.com/) and pull a model:
  ```bash
  ollama pull qwen3.5:9b
  ```

### Quick Install

Xpdite is currently in deveopment, however, the beta will be released very soon.

### Usage

1. Launch Xpdite
2. Take a screenshot with `Alt + .` (period)
3. Type a question.
4. Get streaming AI responses in real-time

## Custom MCP Tools

Xpdite allows your model to take action. It can read files, search the web, send emails, manage your calendar, and run terminal commands — all from within the chat.

| Server | What it can do | Status |
|--------|---------------|--------|
| **Filesystem** | Read, write, move, rename files and folders | Active |
| **Web Search** | Search DuckDuckGo, read any web page as clean text | Active |
| **Gmail** | Search, read, send, reply, draft, trash, label emails | Available after Google connect |
| **Calendar** | List, search, create, update, delete events; check free/busy | Available after Google connect |
| **Terminal** | Run shell commands inline in chat with per-command approval | Active |
| Discord | Message operations | In Progress |
| Canvas | LMS integration | In Progress |

Adding new tools is straightforward -- see the [MCP Guide](./docs/mcp-guide.md).

## Feature Inventory

For the complete, up-to-date feature catalog, see `docs/features-overview.md`.

## Documentation

| Document | Description |
|----------|-------------|
| [Documentation Index](./docs/README.md) | Full docs map and recommended reading paths |
| [Getting Started](./docs/getting-started.md) | Installation, setup, and first run |
| [Architecture](./docs/architecture.md) | System design and data flow |
| [Development](./docs/development.md) | Developer guide, conventions, and common tasks |
| [API Reference](./docs/api-reference.md) | WebSocket and REST API docs |
| [MCP Guide](./docs/mcp-guide.md) | Tool integration guide |
| [Configuration](./docs/configuration.md) | All configurable settings |
| [Features Overview](./docs/features-overview.md) | Canonical map of all app features |
| [Artifacts](./docs/artifacts.md) | Artifact lifecycle, storage, and APIs |
| [Chat and Tabs](./docs/chat-and-tabs.md) | Core chat, tab isolation, and queue behavior |
| [Meeting Recorder](./docs/meeting-recorder.md) | Recording, transcript, and analysis flows |
| [Models and Providers](./docs/models-and-providers.md) | Local/cloud model handling and provider APIs |
| [Memory](./docs/memory.md) | Long-term memory model and APIs |
| [Skills](./docs/skills.md) | Builtin/user skills and slash-command injection |
| [Terminal](./docs/terminal.md) | Terminal approval model and real-time command flow |
| [Scheduled Jobs](./docs/scheduled-jobs.md) | Task automation lifecycle and APIs |
| [Notifications](./docs/notifications.md) | Notification events, storage, and APIs |
| [Mobile Bridge](./docs/mobile-bridge.md) | Remote messaging bridge architecture |
| [Operations Guide](./docs/operations.md) | Runtime operations, health checks, and recovery |
| [Security Overview](./docs/security.md) | Security controls and hardening guidance |
| [Troubleshooting](./docs/troubleshooting.md) | Common issues and fixes |
| [Contributing](./docs/contributing.md) | How to contribute |

## Development

See the [Getting Started guide](./docs/getting-started.md) for dev setup and the [Development guide](./docs/development.md) for conventions, common tasks, and how to add new features.

## Contributing

See [Contributing Guide](./docs/contributing.md) for details.

## License

[MIT](./LICENSE)
