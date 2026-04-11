# Getting Started

This guide covers initial setup for both end users and contributors.

## Choose Your Path

- **Use Xpdite**: follow [End User Setup](#end-user-setup).
- **Develop Xpdite**: follow [Developer Setup](#developer-setup).

## End User Setup

### Prerequisites

1. **Windows 10/11**
2. **Ollama** (optional, required for local models)
   - Install from [ollama.com](https://ollama.ai/)
   - Pull a default model:
     ```bash
     ollama pull qwen3-vl:8b-instruct
     ```
3. **Cloud API keys** (optional)
   - Anthropic, OpenAI, Gemini, or OpenRouter
4. **Google account** (optional)
   - Needed only for Gmail and Calendar tools

### Install

Download the latest installer from the [Releases](https://github.com/KashyapTan/xpdite/releases) page.

If SmartScreen warns because the app is not code-signed yet, choose **More info** and **Run anyway**.

Safety checks before bypassing SmartScreen:

- Download only from the official GitHub releases page.
- Verify repository owner and release tag before running installer.
- If checksums are published for a release, verify file integrity before install.

### First Run

1. Launch Xpdite.
2. Wait for the boot screen to finish backend startup checks.
3. Press `Alt + .` to capture a screenshot.
4. Enter a prompt and submit.

### Verify Core Health

- Chat responses stream in real time.
- `Alt + .` capture inserts a screenshot into the active tab.
- Settings load successfully (models, tools, connections).

### Common Optional Setup

- Add provider keys in Settings for cloud models.
- Connect Google in Settings > Connections for Gmail/Calendar tools.
- Pair mobile channels in Settings > Mobile if you want remote chat.

## Developer Setup

### Prerequisites

- **Bun** (JavaScript package manager and task runner)
- **Python 3.13+**
- **UV** (Python dependency manager)
- **Git**

### Install Dependencies

```bash
git clone https://github.com/KashyapTan/xpdite.git
cd xpdite
bun install
bun run install:python
```

### Run in Development

```bash
bun run dev
```

This starts:

- Vite renderer (`127.0.0.1:5123`)
- Electron main process
- Python backend (first free port in `8000-8009`)
- Ollama startup helper

Channel Bridge starts after backend health checks pass.

### Run Individual Services

```bash
bun run dev:react
bun run dev:electron
bun run dev:pyserver
```

### Build

```bash
bun run build
```

For packaged Windows output:

```bash
bun run dist:win
```

## Repository Layout

```text
xpdite/
  src/
    electron/          # Electron process and IPC bridge
    ui/                # React frontend
    channel-bridge/    # Mobile messaging bridge service
  source/              # FastAPI backend and services
  mcp_servers/         # MCP server implementations
  docs/                # Product and engineering docs
  tests/               # Backend pytest suite
  user_data/           # Local runtime data (dev)
```

## Next Steps

- Read `docs/architecture.md` for system design.
- Read `docs/development.md` for implementation patterns.
- Read `docs/api-reference.md` for contracts.
