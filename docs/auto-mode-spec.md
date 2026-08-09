# Auto Mode (Instant Answer) — Implementation Specification

> Status: Implemented
> Scope: Auto Mode plus the bundled mini-mode toggle hotkey

## 1. Goal

Auto Mode turns one global hotkey press into a hands-off workflow:

1. Hide Xpdite from the capture.
2. Capture the full desktop.
3. Submit the saved prompt and fresh screenshot.
4. Stream the answer in Xpdite without taking operating-system focus.

The user does not select a region, type, click, or confirm after pressing the
hotkey.

## 2. Trigger and lifecycle

Auto Mode is controlled in **Settings → General**. It repurposes the existing
screenshot hotkey:

- macOS: `Control+.`
- Windows and Linux: `Alt+.`
- Auto Mode off: the hotkey retains the normal precision-capture behavior.
- Auto Mode on: the hotkey runs the full Auto Mode pipeline.

The persisted enable flag is restored before the listener starts and updates
immediately when the setting changes.

By default, each trigger creates a fresh, persistent chat tab and uses the normal
enqueue, stream, token-accounting, and history-persistence flow. The optional
**Keep context** setting targets the current tab instead. A keep-context trigger is
rejected while that tab is busy. If a fresh tab cannot be created because the tab
limit has been reached, Auto Mode reports an error and does not fall back to or
mutate the active conversation.

## 3. Model selection

The optional pinned model is used when it remains enabled. Otherwise Auto Mode uses
the model currently selected in chat. The renderer synchronizes model changes to
the backend so hotkeys fired from another route still use the latest selection.

The selected model must support images. Provider failures, including a model that
does not support vision, use the normal assistant-style chat error UI.

## 4. Capture correctness

The backend owns the capture immediately before queueing the request:

- A failed capture is a hard stop; no text-only request is enqueued.
- Auto Mode rejects a busy destination before clearing or capturing anything.
- An idle keep-context tab clears stale screenshots before taking a fresh capture.
- Xpdite remains hidden until `screenshot_added` or an error restores it.
- The optional flash starts only after `screenshot_added`, so it cannot appear in
  the screenshot.
- Windows capture passes Pillow's `all_screens=True` so monitors with negative
  virtual-desktop coordinates are included. macOS and Linux keep their native
  Pillow call.

## 5. Focus and cross-platform behavior

Auto Mode must never call the focus/activate path. Electron shows the main overlay
with `showInactive()` and switches only Xpdite's in-app tab.

Electron does not support `BrowserWindow.showInactive()` on Linux Wayland. Because
focus preservation is a hard requirement, Auto Mode is reported as unsupported and
cannot be enabled in a Wayland session. Linux X11, Windows, and macOS use the normal
non-activating path. This is a deliberate fail-closed behavior rather than a
best-effort fallback that could steal focus.

## 6. Privacy and tool safety

A full-screen capture may contain passwords, messages, financial information, or
other private data. Auto Mode therefore applies two additional controls:

- Local Ollama models can be used immediately. Sending Auto Mode screenshots to a
  cloud or Ollama-cloud model requires the separate **Allow cloud screenshots**
  opt-in. Without it, the trigger is blocked before capture.
- Tool discovery and tool execution are disabled for every Auto Mode turn,
  including stop-hook continuations. Screen text is untrusted input and must not be
  able to turn a hands-off capture into terminal, memory, scheduler, sub-agent, or
  other MCP actions.

These controls do not make screen capture harmless; users should leave Auto Mode
off when they do not intend to capture the current desktop.

## 7. Settings

| Setting | Purpose | Default |
|---|---|---|
| Auto Mode enabled | Switches the screenshot hotkey into Auto Mode | Off |
| Prompt | Text submitted with every capture | “Answer the question on my screen concisely.” |
| Pinned model | Optional model override | Current chat model |
| Keep context | Append to the current idle tab | Off |
| Flash on trigger | Flash after capture succeeds | Off |
| Allow cloud screenshots | Permit full-screen images to leave the machine | Off |

Prompts are length-capped before persistence. A pinned model that is later disabled
falls back to the synchronized current model.

## 8. Architecture

The native listener schedules `AutoModeHandler.on_auto_mode_trigger` on the server
event loop. After capability and cloud-consent checks, it broadcasts a global
`auto_mode_trigger` containing the prompt, resolved model, keep-context flag, and
flash flag.

`Layout.tsx`, which remains mounted across routes, restores mini mode, calls the
non-activating window API, and navigates to chat with a monotonic trigger nonce.
`App.tsx` waits until its initial tab snapshot and model are restored before it
consumes the nonce. It then creates/selects the destination and sends a normal
`submit_query` with `capture_mode: "fullscreen"` and `auto_mode: true`.

The backend validates destination idleness, captures the fresh screenshot, and
enqueues a `QueuedQuery` with `tools_enabled: false`. That policy is propagated
through `ConversationService` and `route_chat` to both Ollama and cloud providers.

## 9. Error behavior

Pre-capture policy failures broadcast `auto_mode_error`. Tab-specific failures use
the standard `error` message. Both paths restore renderer visibility and surface a
chat error without calling the focus API. Covered cases include:

- unsafe Wayland session;
- cloud model without cloud-screenshot consent;
- busy keep-context destination;
- tab limit reached;
- screen-capture failure;
- downstream provider or vision errors.

## 10. Test requirements

Regression coverage must verify:

- enabled-state and settings round trips;
- startup/platform gating;
- local versus cloud-consent trigger behavior;
- restored-tab timing and nonce idempotency;
- fresh-tab isolation and tab-limit failure;
- busy keep-context rejection and stale-screenshot replacement;
- capture failure never enqueues;
- flash occurs after `screenshot_added`;
- selected-model synchronization;
- Auto Mode queue items disable tools at both provider paths;
- Windows capture requests every monitor;
- no Auto Mode path calls `focusWindow()`.

## 11. Bundled mini-mode hotkey

The always-on mini-mode hotkey is independent of Auto Mode:

- macOS: `Control+,`
- Windows and Linux: `Alt+,`

It broadcasts `toggle_mini_mode`, and `Layout.tsx` flips the same mini state used by
the title-bar control. Normal bounds are saved before shrinking and restored when
leaving mini mode. This explicit window command is separate from Auto Mode's strict
non-activation guarantee.
