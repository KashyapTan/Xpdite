# Getting Started

This guide covers initial setup for both end users and contributors.

## Choose Your Path

- **Use Xpdite**: follow [End User Setup](#end-user-setup).
- **Develop Xpdite**: follow [Developer Setup](#developer-setup).

## Connecting a Provider

1. Choose how you want to run models:
   - **Local with Ollama (recommended)**: download and install from [ollama.com/download](https://ollama.com/download).
   - **Cloud providers**: bring your own API key (Anthropic, OpenAI, Gemini, or OpenRouter).
2. After installing Ollama, open Xpdite and go to **Settings -> Models**.
3. Pull models directly from the UI in the Models tab.
4. Find models at [ollama.com/search](https://ollama.com/search).

## End User Setup

### Prerequisites

1.  **OS**: Windows 10/11 or macOS (11.0+)
    - Current beta installers are published for Windows x64 and Apple Silicon macOS only.
2.  **System Dependencies (macOS only)**:
    - Install [Homebrew](https://brew.sh)
    - Install PortAudio for audio features:
      ```bash
      brew install portaudio
      ```
3.  **Ollama** (optional, required for local models or ollama cloud models)
    - Install from [ollama.com/download](https://ollama.com/download)
    - Pull models from **Settings -> Models** inside Xpdite
4.  **Cloud API keys** (optional)
    - Anthropic, OpenAI, Gemini, or OpenRouter
5.  **Google account** (optional)
    - Needed only for Gmail and Calendar tools

### Install

Install the latest published build from the terminal:

Windows x64:

```powershell
irm https://kashyaptan.com/Xpdite/install.ps1 | iex
```

macOS Apple Silicon:

```bash
curl -fsSL https://kashyaptan.com/Xpdite/install.sh | bash
```

Manual downloads remain available on the [Releases](https://github.com/KashyapTan/xpdite/releases) page (recommended for windows).

If SmartScreen warns because the app is not code-signed yet, choose **More info** and **Run anyway**.

Safety checks before bypassing SmartScreen:

- Download only from the official GitHub releases page.
- Verify repository owner and release tag before running installer.
- For manual downloads, verify file integrity against the published `SHA256SUMS.txt` asset before install.

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
- Add your Hugging Face token in Settings > Meeting if you want speaker diarization.
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

`bun run build` now does all packaging prerequisites:

- regenerates the Electron app icons from `assets/xpdite-logo-black-bg.svg`
- builds the PyInstaller backend executable
- copies the Python runtime and MCP server sources into `dist-python-runtime/`
- writes a packaged Google OAuth env file that includes only `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
- compiles the channel bridge, Electron process, and React UI

Packaging is host-specific:

- `bun run dist:win` must be run on Windows.
- `bun run dist:mac` must be run on macOS. This repo targets Apple Silicon (`arm64`) for beta DMG builds.

For packaged Windows output:

```bash
bun run dist:win
```

For packaged macOS output:

```bash
bun run dist:mac
```

### Packaged Google OAuth

Local development can continue to read Google OAuth credentials from the repo `.env`.

Packaged builds do not read the repo `.env` at runtime. Instead, the build step writes `dist-runtime-config/google-oauth.env` with only:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

That runtime env file is bundled into the app and passed explicitly to the packaged Python backend. The Google OAuth desktop flow still uses loopback redirect handling with PKCE.

### GitHub Beta Releases

GitHub Actions now has two packaging workflows:

- `CI`: runs frontend tests, backend pytest, Electron transpile, and channel-bridge compile on pull requests and pushes to `main`
- `Beta Release`: builds unsigned prerelease assets only on `v*` tags or manual dispatch

The beta workflow expects repository secrets named:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Manual dispatch requires a beta version string and can optionally include a custom release name and release notes.
Each beta release now also publishes `SHA256SUMS.txt` so manual downloads and install scripts can verify asset integrity.

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
