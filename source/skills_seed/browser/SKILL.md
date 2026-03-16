---
name: browser
description: Guidance for browser automation using Playwright CLI.
trigger-servers: []
---

# Browser Automation Skill

You automate browsers by running `playwright-cli` commands through the **terminal MCP server's `run_command` tool**. Pass each command as the `command` argument to `run_command`. Always run the `request_session_mode` command first to get approval for multiple commands in a row without user prompts.

## Setup

Before first use, install the CLI globally:
```bash
npm install -g @playwright/cli
```
This provides the `playwright-cli` binary. Do NOT confuse with `npx playwright open` — that is a different tool (interactive codegen) that blocks the terminal.

## How It Works

`playwright-cli` is a **daemon-based CLI** (NOT a TUI). It works like this:
- `playwright-cli open` spawns a background browser daemon, opens the browser, and **returns** with a snapshot. The command exits — it does NOT block.
- Subsequent commands (`click`, `fill`, `snapshot`, etc.) talk to the daemon, print output, and exit.
- `playwright-cli close` stops the daemon and closes the browser.

Because each command is short-lived: use regular `run_command` — **no PTY or background mode needed**.

**Headed vs headless:** The browser is **headless by default** (invisible). Always pass `--headed` to `open` so the user can see the browser:
```bash
playwright-cli open [https://example.com](https://example.com) --headed
```
Use `playwright-cli show` to open a visual dashboard of all running sessions.

## Critical Workflow

1. **Execute via `run_command`** — pass each `playwright-cli` command as the `command` argument. Never suggest the user paste commands manually.
2. **Read the snapshot via `read_file`** — after `open`, `goto`, `click` (that navigates), or calling `playwright-cli snapshot`, a page snapshot is generated. **You must call the `read_file` MCP tool to read the snapshot before moving on to your next command.** This file contains the current URL, page title, and an accessibility tree of interactive elements labeled with **ref IDs** (e.g. `e1`, `e5`, `e12`). You MUST use these ref IDs for subsequent interactions.
3. **Snapshot after navigation** — run `playwright-cli snapshot` any time you need a fresh view or after a page change, then immediately follow up with `read_file` to parse the state.
4. **One command at a time** — run a single `playwright-cli` command per `run_command` call, use `read_file` to check the output, then decide the next action. Never chain multiple commands.
5. **Always close** when done — `playwright-cli close` or `playwright-cli close-all`.

## Quick Start

Each line below is a separate step in your workflow:
```bash
playwright-cli open [https://example.com](https://example.com) --headed
# → Call `read_file` to read the snapshot output: e1 [link "More information..."], etc.

playwright-cli click e1
# → Call `read_file` to read the new snapshot after navigation

playwright-cli snapshot
# → Explicitly get current page state if needed
# → Call `read_file` to read the fresh snapshot

playwright-cli close
```

## Typing into Inputs & Search Bars

This is the most common source of errors for small models. Follow this exact pattern for any input field on any page:

**Step 1:** Open the page and read the snapshot carefully using `read_file`.
```bash
playwright-cli open [https://example.com](https://example.com) --headed
```
Read the file containing the snapshot with element refs. Find the input you need — look for `[searchbox]`, `[combobox]`, `[textbox]`, or `[input]` entries with a ref ID.

**Step 2:** Click the input first to focus it, then fill it.
```bash
playwright-cli click e5
# → e5 is the ref ID of the input found in the snapshot
```

**Step 3:** Fill the input with your text. Use `fill` (NOT `type`) — it clears the field first.
```bash
playwright-cli fill e5 "your text here"
```

**Step 4:** Press Enter to submit, or click a submit button if one exists.
```bash
playwright-cli press Enter
# OR: playwright-cli click e8   (if there's a submit/search button)
```

**Key rules for inputs:**
- **Always use the ref ID** from the snapshot — never guess or hardcode a ref.
- **`fill <ref> "text"`** targets a specific input field (clears first, then types). Use this for any search bar, form field, text input, etc.
- **`type "text"`** types into whatever is currently focused — less reliable. Avoid unless `fill` does not apply.
- If a snapshot doesn't show the element you expect, call `playwright-cli snapshot` again and read the new file — the page may still be loading dynamically.

## Understanding Snapshots

When you use `read_file` after a command, the snapshot structure looks like:
```text
### Page
- Page URL: [https://example.com/](https://example.com/)
- Page Title: Example Domain
### Snapshot
- [document] Example Domain
  - [heading] "Example Domain"
  - [paragraph] "This domain is for use in illustrative examples..."
  - [link e1] "More information..."
```
The **ref IDs** (e1, e2, …) are your handles for interacting with elements. Always read the snapshot file to find the correct ref before clicking, filling, or interacting.

## Command Reference

### Open & Close
```bash
playwright-cli open --headed                  # open browser (visible to user)
playwright-cli open [https://example.com](https://example.com) --headed  # open and navigate
playwright-cli open --browser=chrome --headed # specific browser (chrome/firefox/webkit/msedge)
playwright-cli open --persistent --headed     # persistent profile on disk
playwright-cli show                           # open visual dashboard of all sessions
playwright-cli close                          # close browser
playwright-cli close-all                      # close all sessions
playwright-cli kill-all                       # force-kill all processes
```

### Navigation
```bash
playwright-cli goto [https://playwright.dev](https://playwright.dev)
playwright-cli go-back
playwright-cli go-forward
playwright-cli reload
```

### Element Interaction (use ref IDs from snapshot)
```bash
playwright-cli click e3                       # click
playwright-cli dblclick e7                    # double-click
playwright-cli fill e5 "user@example.com"     # clear + type into input
playwright-cli type "search query"            # type into focused element
playwright-cli select e9 "option-value"       # select dropdown
playwright-cli check e12 / uncheck e12        # checkbox
playwright-cli hover e4                       # hover
playwright-cli drag e2 e8                     # drag and drop
playwright-cli upload ./document.pdf          # file upload
```

### Snapshots & Screenshots
```bash
playwright-cli snapshot                       # generate accessibility tree (read via read_file next!)
playwright-cli screenshot                     # full page screenshot
playwright-cli screenshot e5                  # element screenshot
playwright-cli screenshot --filename=page.png # named screenshot
playwright-cli pdf --filename=page.pdf        # PDF export
```

### Keyboard & Mouse
```bash
playwright-cli press Enter
playwright-cli press ArrowDown
playwright-cli keydown Shift / keyup Shift
playwright-cli mousemove 150 300
playwright-cli mousedown / mouseup
playwright-cli mousewheel 0 100
```

### JavaScript, Dialogs & Window
```bash
playwright-cli eval "document.title"
playwright-cli eval "el => el.textContent" e5
playwright-cli dialog-accept / dialog-dismiss
playwright-cli resize 1920 1080
```

### Tabs
```bash
playwright-cli tab-list
playwright-cli tab-new [https://example.com](https://example.com)
playwright-cli tab-select 0
playwright-cli tab-close 2
```

### Named Sessions (parallel isolated browsers)
```bash
playwright-cli -s=auth open [https://app.example.com/login](https://app.example.com/login) --headed
playwright-cli -s=auth fill e1 "user@example.com"
playwright-cli -s=auth close
playwright-cli list                           # list all sessions
```

### Storage, Network & DevTools (see references for details)
```bash
playwright-cli state-save auth.json / state-load auth.json
playwright-cli cookie-list / cookie-set name value
playwright-cli localstorage-get key / localstorage-set key value
playwright-cli route "**/api/*" --body='{"mock":true}' / unroute
playwright-cli console / network
playwright-cli tracing-start / tracing-stop
playwright-cli video-start / video-stop out.webm
playwright-cli run-code "async page => { ... }"
```

## Reference Docs

For advanced usage, read the reference files in the `references/` subfolder:
- [references/request-mocking.md](references/request-mocking.md) — intercept & mock network requests
- [references/running-code.md](references/running-code.md) — run arbitrary Playwright code
- [references/session-management.md](references/session-management.md) — parallel browser sessions
- [references/storage-state.md](references/storage-state.md) — cookies, localStorage, sessionStorage
- [references/test-generation.md](references/test-generation.md) — generate Playwright test files
- [references/tracing.md](references/tracing.md) — capture execution traces
- [references/video-recording.md](references/video-recording.md) — record browser sessions