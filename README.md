<div align="center">
  <a href="https://github.com/KashyapTan/xpdite">
    <img alt="xpdite" width="240" src="./assets/xpdite-logo-github-color.png">
  </a>
</div>
<h3 align="center">Answers for anything on your screen with Xpdite.</h3>
<h4 align="center">| Free | Easy | Fast | Private |</h4>

---

# Xpdite

A free, private, AI-powered desktop assistant that sees your screen. Take screenshots of anything, ask questions in natural language, and get instant answers -- all running locally on your machine with Ollama.

## Key Features

- **Screenshot + Vision AI** -- Capture any region of your screen (Alt+.) and ask questions about it
- **Multi-Model Support** -- Local Ollama models + cloud (Claude, GPT, Gemini, OpenRouter) from one UI
- **Streaming Responses** -- Real-time token-by-token display with thinking/reasoning visibility
- **Multi-Tab** -- Multiple independent AI conversations running in parallel
- **MCP Tool Integration** -- File ops, web search, Gmail, Calendar, and terminal via Model Context Protocol
- **Inline Terminal** -- AI-commanded shell execution with approval flow inline in the chat
- **Skills / Slash Commands** -- Type `/terminal`, `/fs`, `/websearch` etc. to force-inject expert instruction sets
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

- **Ollama** -- Download from [ollama.com](https://ollama.ai/) and pull a model:
  ```bash
  ollama pull qwen3-vl:8b-instruct
  ```

### Quick Install

<div>
  <a href="https://github.com/KashyapTan/xpdite/releases/latest/download/XpditeSetup.exe">
    <img src="https://img.shields.io/badge/Download Xpdite-blue?style=for-the-badge&logo=windows&logoColor=white" alt="Download Xpdite Setup">
  </a>
</div>

**Alternative:** Download from the [Releases](https://github.com/KashyapTan/xpdite/releases) page

> **Windows Security Notice:** You may see a SmartScreen warning because the app is not yet code-signed. Click "More info" then "Run anyway".

### Usage

1. Launch Xpdite
2. Take a screenshot with `Alt + .` (period)
3. Type a question or just press Enter
4. Get streaming AI responses in real-time

## Demo

### Video Demo

<div align="center">
  <img src="./assets/xpdite-demo.gif" alt="Xpdite Demo - Animated Preview" width="720">
</div>

<div>
  <h1>Watch on Youtube:</h1>
  <a href="https://www.youtube.com/watch?v=wrrfFeGoSt0">
    <img src="https://img.youtube.com/vi/wrrfFeGoSt0/maxresdefault.jpg" alt="Watch Full Demo on YouTube" width="200">
  </a>
</div>

### Screenshots

| Step | Screenshot |
|------|-----------|
| 1. Launch & capture | <img alt="Launch" src="./assets/demo-1.png" width="300"> |
| 2. Enter a prompt | <img alt="Prompt" src="./assets/demo-2.png" width="300"> |
| 3. Real-time response | <img alt="Response" src="./assets/demo-3.png" width="300"> |
| 4. Final result | <img alt="Result" src="./assets/demo-4.png" width="300"> |

## MCP Tools

Xpdite gives the AI hands. It can read files, search the web, send emails, manage your calendar, and run terminal commands — all from within the chat.

| Server | What it can do | Status |
|--------|---------------|--------|
| **Filesystem** | Read, write, move, rename files and folders | Active |
| **Web Search** | Search DuckDuckGo, read any web page as clean text | Active |
| **Gmail** | Search, read, send, reply, draft, trash, label emails | Active |
| **Calendar** | List, search, create, update, delete events; check free/busy | Active |
| **Terminal** | Run shell commands inline in chat with per-command approval | Active |
| Discord | Message operations | In Progress |
| Canvas | LMS integration | In Progress |

Adding new tools is straightforward -- see the [MCP Guide](./docs/mcp-guide.md).

## What's Changed

Every feature that exists in Xpdite today:

**Vision & Chat**
- Screenshot any region of your screen with `Alt + .` and ask questions about it
- Fullscreen and meeting-mode screenshot capture
- Real-time streaming responses with thinking/reasoning visible as it happens
- Stop any response mid-generation
- Edit any past message and re-generate from that point
- Retry any AI response to get a different answer; browse all versions with ← → arrows
- Voice-to-text input transcribed locally via faster-whisper

**Multi-Tab**
- Up to 10 independent AI conversations open at the same time, each with their own history, screenshots, and model
- Queue multiple questions per tab (up to 5) — they run back-to-back while you keep typing
- Ollama GPU requests are serialized globally so tabs never fight over the GPU

**AI Models**
- Any locally installed Ollama model (default: `qwen3-vl:8b-instruct`)
- Anthropic Claude (all tiers, including latest Sonnet and Opus)
- OpenAI GPT-4o, GPT-4.1, and o-series reasoning models
- Google Gemini (all tiers)
- OpenRouter models (tool-compatible models from multiple upstream providers)
- Switch models per-message; each conversation tracks which model generated each response

**Tools & Skills**
- File operations, web search, Gmail, Calendar, and terminal accessible via natural language
- Semantic tool retrieval — only the tools relevant to your query are sent to the model (no context bloat)
- Always-on tool overrides configurable in Settings
- 6 builtin skills: `terminal`, `filesystem`, `websearch`, `gmail`, `calendar`, `browser`
- Slash commands: type `/terminal`, `/fs`, `/websearch` etc. to force-inject an expert skill for that turn
- Full skill editor — create, edit, delete, and reset skills in Settings

**Inline Terminal**
- The AI can run shell commands directly in the chat flow
- Every command shows an approval card — approve once, deny, or "Allow & Remember" to skip future prompts for that command
- Full PTY support for interactive programs
- Background sessions for long-running processes
- Every command is logged with exit code, output, duration, and working directory

**Meeting Recorder**
- Captures system audio (WASAPI loopback) and microphone simultaneously
- Live transcription during the meeting (Tier 1, fast)
- Full post-processing after recording ends: WhisperX large-v3 + speaker diarization (SpeechBrain)
- AI generates a summary, title, and a list of action items from the transcript
- Action items link directly to Calendar and Gmail — schedule meetings and send follow-ups in one click
- View all past recordings grouped by date; each has the full transcript and AI analysis

**Gmail & Calendar**
- Connect your Google account in Settings > Connections with one click (OAuth, no password stored)
- Gmail: search, read, send, reply, create drafts, trash emails, manage labels, check unread count
- Calendar: list events, search, create, update, delete, quick-add from natural language, check free/busy

**History & Search**
- All conversations saved automatically to a local SQLite database
- Full-text search across every conversation title and message (FTS5 — fast even with thousands of entries)
- Resume any past conversation with full state restored (messages, screenshots, token count)
- Delete conversations individually

**Customization**
- Custom system prompt template — write your own instructions that apply to every conversation
- Settings > Skills — manage which skills are active and what their instructions say
- Settings > Tools — tune how many tools the AI sees per query and which are always active
- Settings > Models — enable/disable any installed local or cloud model

**Privacy & Security**
- Runs entirely on your machine — nothing is sent anywhere except to your chosen model provider
- API keys are encrypted at rest with Fernet (per-install encryption key)
- Terminal commands require explicit approval (configurable)
- Content protection prevents other apps from capturing the Xpdite window

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](./docs/getting-started.md) | Installation, setup, and first run |
| [Architecture](./docs/architecture.md) | System design and data flow |
| [Development](./docs/development.md) | Developer guide, conventions, and common tasks |
| [API Reference](./docs/api-reference.md) | WebSocket and REST API docs |
| [MCP Guide](./docs/mcp-guide.md) | Tool integration guide |
| [Configuration](./docs/configuration.md) | All configurable settings |
| [Contributing](./docs/contributing.md) | How to contribute |

## Development

See the [Getting Started guide](./docs/getting-started.md) for dev setup and the [Development guide](./docs/development.md) for conventions, common tasks, and how to add new features.

## Contributing

See [Contributing Guide](./docs/contributing.md) for details.

## License

[MIT](./LICENSE)
