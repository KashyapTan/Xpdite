# Getting Started

This guide covers installing and running Xpdite for both end users and developers.

## End User Installation

### Prerequisites

1. **Ollama** - Local LLM runtime (Optional if using Cloud Models)
   - Download from [ollama.com](https://ollama.ai/)
   - Pull the default vision model:
     ```bash
     ollama pull qwen3-vl:8b-instruct
     ```
2. **Cloud API Keys** (Optional)
   - Anthropic (Claude)
   - OpenAI (GPT-4o, o1)
   - Google Gemini
3. **Google Account** (Optional)
   - Required for Gmail and Calendar integration
4. **Windows 10/11** (macOS support planned)

### Quick Install

Download the latest installer:

[![Download Xpdite](https://img.shields.io/badge/Download_Xpdite-blue?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/KashyapTan/xpdite/releases/latest/download/XpditeSetup.exe)

Or download from the [Releases](https://github.com/KashyapTan/xpdite/releases) page.

> **Windows Security Notice:** You may see a SmartScreen warning because the app is not yet code-signed. Click "More info" then "Run anyway". The app is safe to install.

### Basic Usage

1. Launch Xpdite -- a small floating window appears
2. Take a screenshot with `Alt + .` (period)
3. Type a question or press Enter to ask about your screenshot
4. The AI responds in real-time with streaming text

### Features at a Glance

| Feature | How to Use |
|---------|-----------|
| Screenshot (region) | Press `Alt + .`, then click and drag |
| Chat without image | Just type and press Enter |
| New conversation | Click the "New Chat" button in the title bar |
| Browse history | Navigate to the History page |
| Mini mode | Click the Xpdite logo to minimize to 52x52 |
| **Multi-tab** | Open multiple independent AI conversations with the tab bar |
| **Cloud Models** | Go to Settings > Models to add API keys for Claude, GPT, or Gemini |
| **Google Integration** | Go to Settings > Connections to link your Google account (Gmail + Calendar) |
| Model selection | Toggle models in Settings > Models |
| Stop streaming | Click stop while the AI is responding |
| **Slash Commands / Skills** | Type `/` followed by a command (e.g., `/fs`, `/terminal`) to force-inject a skill |
| **Inline Terminal** | Terminal command tool calls execute inline in the chat; approve, deny, or allow-always |
| **Meeting Recorder** | Navigate to Recorder page to capture + transcribe meetings with AI analysis |
| **Response Retry/Edit** | Hover a message to retry or edit it; browse alternate responses with ←/→ arrows |
| Web search | Ask questions that trigger web search tools |

---

## Developer Setup

### Prerequisites

- **Node.js** 18+ and **Bun** (package manager) — [Install Bun](https://bun.sh/)
- **Python** 3.13+
- **UV** (Python package manager) - [Install UV](https://docs.astral.sh/uv/getting-started/installation/)
- **Ollama** running locally (optional)
- **Git**

### Clone and Install

```bash
# Clone the repository
git clone https://github.com/KashyapTan/xpdite.git
cd xpdite

# Install JavaScript dependencies
bun install

# Install Python dependencies (uses UV)
bun run install:python
# or directly:
uv sync --group dev
```

### Running in Development

```bash
# Start everything (React + Electron + Python server + Ollama)
bun run dev
```

This runs three services in parallel:
- **React dev server** on port 5123 (hot reload)
- **Python FastAPI server** on port 8000 (auto-detected)
- **Electron app** loading from the dev server

You can also run services individually:

```bash
bun run dev:react      # Vite dev server only
bun run dev:pyserver   # Python backend only (via uv run)
bun run dev:electron   # Electron shell only
```

### Building for Production

```bash
# Full build (Python exe + React + Electron)
bun run build

# Package Windows installer
bun run dist:win
```

The build process:
1. Bundles Python backend into `dist-python/main.exe` via PyInstaller
2. Builds React frontend into `dist-react/`
3. Compiles TypeScript for Electron into `dist-electron/`
4. Packages everything with electron-builder

### Project Structure

```
xpdite/
  src/
    electron/         # Electron main process
    ui/               # React frontend
      pages/          # Route components
      components/     # Reusable UI components
      hooks/          # Custom React hooks
      services/       # API clients
      types/          # TypeScript interfaces
      CSS/            # Stylesheets
  source/             # Python backend
    api/              # WebSocket + REST endpoints
    core/             # State, connections, lifecycle, thread pool
    services/         # Business logic (conversations, skills, tab manager, meeting recorder, terminal…)
    llm/              # Ollama + Cloud Providers (Claude, OpenAI, Gemini via LiteLLM)
    mcp_integration/  # MCP server management + semantic retrieval
    skills_seed/      # Builtin skills (terminal, filesystem, websearch, gmail, calendar, browser)
  mcp_servers/        # MCP tool server implementations
    servers/          # Individual server modules (gmail, calendar, etc.)
    client/           # Standalone bridge client
    config/           # Server configuration
  docs/               # Documentation
  user_data/          # Runtime data (DB, screenshots, tokens)
```

### Verifying Your Setup

1. Ensure Ollama is running: `ollama list` should show installed models
2. Start the dev server: `bun run dev`
3. The Xpdite window should appear and show "ready" in the console
4. Take a screenshot with `Alt + .` and ask a question

### Troubleshooting

| Issue | Solution |
|-------|---------|
| Python server won't start | Ensure Python 3.13+ is installed and `uv` is available |
| Port already in use | The server auto-probes ports 8000-8009; kill stale processes |
| Ollama not responding | Run `ollama serve` and verify with `ollama list` |
| Google Auth fails | Check internet connection; ensure `client_config.json` is embedded |
| MCP tools missing | Verify `bun run install:python` installed all deps including `mcp` |
| WebSocket disconnects | Check the Python server console for error logs |
