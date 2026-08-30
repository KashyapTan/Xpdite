<div align="center">
  <a href="https://github.com/KashyapTan/xpdite">
    <img alt="xpdite" width="240" src="./assets/xpdite-logo-github-bg.svg">
  </a>
</div>

<h3 align="center">Xpdite - Your AI Assistant and Agent Harness</h3>

<p align="center">
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/github/license/KashyapTan/xpdite?style=for-the-badge&label=License"></a>
  <a href="https://github.com/KashyapTan/xpdite/releases"><img alt="Release" src="https://img.shields.io/github/v/release/KashyapTan/xpdite?include_prereleases&style=for-the-badge&label=Release"></a>
  <a href="https://github.com/KashyapTan/xpdite/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/KashyapTan/xpdite?style=for-the-badge&label=Stars"></a>
</p>

<p align="center">
  <a href="./docs/getting-started.md"><img alt="Get Started" src="https://img.shields.io/badge/Get%20Started-0f172a?style=for-the-badge&logo=bookstack&logoColor=white"></a>
  <a href="./docs/README.md"><img alt="Documentation" src="https://img.shields.io/badge/Documentation-1d4ed8?style=for-the-badge&logo=gitbook&logoColor=white"></a>
  <a href="./docs/contributing.md"><img alt="Contributing" src="https://img.shields.io/badge/Contributing-0f766e?style=for-the-badge&logo=github&logoColor=white"></a>
</p>

---

## Xpdite

An AI assistant and agent harness that is truly **yours**. It runs your desktop using any model provider, is completely open-source, 100% customizable, and built for everyone.
Use it as a desktop copilot, then continue the same experience from mobile channels through WhatsApp, Telegram, or Discord.

---

## Why Xpdite

- **Agent harness, not just chat** -- Supports multi-step execution with approval-aware actions and structured task flows.
- **Desktop-first workflow** -- Always-on-top app, screenshot-first interaction (`Alt + .`), and fast context switching.
- **Model flexibility** -- Use local Ollama models and/or cloud providers from a single interface.
- **Parallel context** -- Multi-tab chat with isolated session state and per-tab queueing.
- **Remote continuity** -- Mobile Channel Bridge keeps conversations accessible from messaging apps.
- **Extensible by design** -- Built for customization, integrations, and long-term evolution.

---

## Core Features

- **Comprehensive execution timeline UI** -- Beautiful in-chat thinking and tool-call rendering that shows model steps, live tool progress, terminal output, and completion states in a single readable flow.
- **Claude-style inline artifacts** -- Models can generate inline artifacts (code, markdown, and HTML) that are persisted, searchable, and easy to revisit from chat history.
- **`@` file attachments like a coding harness** -- Attach files instantly with `@<file_name>` from the input, then send mixed text + file context in one prompt.
- **Broad file intelligence** -- Reads and extracts content from code files, PDFs, Office documents, ODF/RTF formats, ZIP listings, and image files so context loading stays frictionless.
- **Advanced custom tool ecosystem** -- Includes high-capability web search, YouTube video watcher flows, an approval-aware terminal/bash runtime, and many more MCP/inline tools.
- **Mobile + desktop continuity** -- Start on desktop and continue from WhatsApp, Telegram, or Discord with paired session routing.

---

## Demo

Xpdite in action:


https://github.com/user-attachments/assets/412d2da8-ccba-4825-a47d-f1c6fca3d81f


https://github.com/user-attachments/assets/956f8147-c917-4aa2-bc60-771742cbdc9b

---

## Getting Started

### Connecting a provider

1. Choose how you want to run models:
   - **Local with Ollama (recommended)**: Download and install Ollama from [ollama.com/download](https://ollama.com/download).
   - **Cloud providers**: Bring your own API key (Anthropic, OpenAI, Gemini, or OpenRouter).
   - **ChatGPT subscription**: Connect your ChatGPT account through the bundled OpenAI Codex runtime using browser OAuth or device code; available models follow your account entitlements.
2. If you install Ollama, open Xpdite and go to **Settings -> Models** to pull models directly from the UI.
3. Browse available local models at [ollama.com/search](https://ollama.com/search).

### End users

1. Install the latest published build for your platform:
   Windows x64:
   ```bash
   irm https://kashyaptan.com/Xpdite/install.ps1 | iex
   ```
   macOS (Apple Silicon or Intel):
   ```bash
   curl -fsSL https://kashyaptan.com/Xpdite/install.sh | bash
   ```
   Manual downloads remain available on [Releases](https://github.com/KashyapTan/xpdite/releases) (recommended for windows).
2. Launch Xpdite and wait for startup checks to finish.
3. Press `Alt + .` to capture a screenshot and ask your question.

See [docs/getting-started.md](./docs/getting-started.md) for full setup details and optional channel pairing.

### Developers

Requirements: Bun, Python 3.13+, UV, Git. macOS audio builds also require Homebrew PortAudio.

```bash
git clone https://github.com/KashyapTan/xpdite.git
cd xpdite
bun install
bun run install:python
bun run dev
```

`install:python` selects the native dependency profile. Apple Silicon, Windows,
and Linux x64 use the full profile; Intel macOS uses the transcription profile.
Intel retains dictation, meeting transcription, and YouTube transcription while
WhisperX alignment, speaker diarization, and bundled Sentence Transformers are
unavailable. A configured Ollama embedding model and BM25 tool retrieval continue
to work on Intel.

Useful checks:

```bash
bun run lint
bun run test:frontend
uv run python -m pytest tests/ -v
bun run build
```

---

### Architecture Diagram

**System Overview** — the five major processes and how they connect:



```mermaid

graph LR

  classDef electron fill:#4f46e5,stroke:#3730a3,color:#fff

  classDef react fill:#0ea5e9,stroke:#0284c7,color:#fff

  classDef python fill:#059669,stroke:#047857,color:#fff

  classDef bridge fill:#e11d48,stroke:#be123c,color:#fff

  classDef external fill:#475569,stroke:#334155,color:#fff



  Electron["Electron Host\nWindow · IPC · Lifecycle"]:::electron

  ReactUI["React UI\nChat · Tabs · Settings"]:::react

  Backend["Python Backend\nFastAPI · Services · SQLite"]:::python

  Bridge["Channel Bridge\nWhatsApp · Telegram · Discord"]:::bridge

  External["External Services\nOllama · Cloud LLMs · Google OAuth"]:::external



  Electron <-->|IPC| ReactUI

  Electron -->|spawns| Backend

  Electron -->|spawns| Bridge

  ReactUI <-->|"WebSocket + REST"| Backend

  Backend <-->|"/internal/mobile/*"| Bridge

  Backend -->|"LLM calls"| External

  Bridge <-->|"messages"| External

```



**Backend Request Flow** — how a chat message moves through the Python process:



```mermaid

graph LR

  classDef input fill:#4f46e5,stroke:#3730a3,color:#fff

  classDef llm fill:#7c3aed,stroke:#6d28d9,color:#fff

  classDef mcp fill:#d97706,stroke:#b45309,color:#fff

  classDef tools fill:#be185d,stroke:#9d174d,color:#fff

  classDef store fill:#059669,stroke:#047857,color:#fff



  Input["WebSocket Handler\n+ Tab Queue"]:::input

  Conv["Conversation Service\nsubmit_query()"]:::input

  LLM["LLM Router\nOllama or Cloud LLM"]:::llm

  MCP["MCP Tool Manager\nSemantic retrieval · Skill injection"]:::mcp

  Inline["Inline Tools\nterminal · memory · sub_agent\nvideo_watcher · skills · scheduler"]:::tools

  Subprocess["Subprocess Servers\nfilesystem · websearch · gmail · calendar"]:::tools

  DB[("SQLite\nMessages · History · Events")]:::store



  Input --> Conv

  Conv --> LLM

  LLM -->|"tool calls"| MCP

  MCP --> Inline

  MCP --> Subprocess

  LLM -->|"stream response"| Input

  Conv --> DB

  Inline --> DB

```



---

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

---

## Contributing

Contributions are welcome. Read [docs/contributing.md](./docs/contributing.md) before opening a PR.

---

## License

[MIT](./LICENSE)

---

## Sponsor

<a href="https://github.com/sponsors/KashyapTan">
  <img src="https://img.shields.io/badge/Sponsor-%E2%9D%A4-ea4aaa?style=for-the-badge&logo=github-sponsors&logoColor=white" alt="Sponsor KashyapTan">
</a>
