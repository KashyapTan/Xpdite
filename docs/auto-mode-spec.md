# Auto Mode (Instant Answer) — Implementation Spec

> Status: Draft / proposal
> Working name: **Auto Mode** (a.k.a. "Instant Answer" / "Glance Mode" — final name TBD)
> Scope: the main **Auto Mode** feature (Sections 1–11) plus a bundled **mini-mode toggle keybind** mini-feature — `Control+,` (macOS) / `Alt+,` (Windows/Linux) — in Section 12.

---

## 1. Goal

Add a mode where the user presses a single global keybind and Xpdite, with **zero further interaction**:

1. Captures a screenshot of the **entire screen**.
2. Submits it to the LLM together with a **pre-written custom prompt** the user has configured.
3. Streams the answer back and shows it **without stealing focus** — so the user keeps looking at whatever app they were in, and never has to click into the Xpdite window.

The defining constraint is **hands-off after the hotkey**: no region selection, no typing, no clicking the window.

---

## 2. Problem Statement

Today the fast path is: trigger precision capture → drag a region → click into the Xpdite window → type/submit. That final click brings the always-on-top window to the foreground and **switches the OS focus away** from the app the user was screenshotting. For a tool meant to answer questions *about the thing on screen*, forcing the user to leave that thing on screen is the core friction.

Auto Mode removes every manual step between "I have a question about my screen" and "I have an answer", and — critically — never takes foreground focus, so the user's active window/tab is never disturbed.

---

## 3. Feature Summary

Auto Mode is an **explicitly enabled mode**, toggled on/off with a switch in **Settings → General**. While it is **on**, a dedicated global hotkey runs a fixed one-shot pipeline:

**hotkey → hide own window (so it isn't in the shot) → full-screen capture → auto-submit with the saved prompt → stream answer into a non-focus-stealing surface**

While it is **off**, the hotkey is inert and the pipeline never fires. Everything after the hotkey is automatic. The user reads the answer and carries on; the answer surface can be dismissed with a key or fades on the next trigger.

---

## 4. End-to-End UX Flow

1. **Enable (one time):** In **Settings → General**, the user flips the **Auto Mode toggle on**, writes their default Auto Mode prompt (e.g. "Explain what's on screen" / "Answer the question visible here concisely"), and optionally customizes the hotkey. While the toggle is off, the hotkey does nothing.
2. **Trigger:** With Auto Mode on, the user presses the Auto Mode hotkey from anywhere.
3. **Self-hide:** Xpdite momentarily hides/excludes its own window from the capture (reusing the existing hide-before-capture behavior) so the overlay doesn't appear in the screenshot.
4. **Capture:** The full screen is captured as an image.
5. **Auto-submit:** The saved prompt + the captured image are submitted to the currently selected model, with no compose step.
6. **New tab + answer appears:** A brand-new tab is created and becomes Xpdite's *in-app* shown tab; the answer streams into it. The window is shown **inactive** (visible, always-on-top, but never grabs keyboard/foreground focus), so the user's underlying app stays active the whole time.
7. **Persistence / dismiss:** The tab behaves like any normal tab — it stays open and is saved to history. The user closes it manually via its × when done. Pressing the keybind again creates the next new tab and shows it.

---

## 5. Design Decisions (resolved)

These forks are now **decided**. Each is marked ✅ **DECIDED** with the confirmed behavior.

### 5.1 Where does the answer render?
- ✅ **DECIDED — Reuse the existing main overlay window.** No separate HUD window. The answer streams into the normal Xpdite overlay, reusing the whole existing streaming/render stack. The only special behavior is that it appears *inactive* (see 5.2).

### 5.2 How is focus-stealing avoided?
- ✅ **DECIDED — The window NEVER activates. Focus/window/tab switching must never happen, period.** This is a hard requirement, not a best-effort. When the hotkey fires and the answer surfaces, the user's currently focused app stays focused — their keyboard input keeps going to whatever they were using. Xpdite becomes *visible* (always-on-top) but never *active*, on every trigger without exception.
- Implication: the window must be surfaced through the windowing layer's non-activating "show" path only. No code path in the Auto Mode flow may call focus/activate/raise-to-front on the window. The full-screen capture is global and needs no focus, so nothing in the pipeline requires activation.

### 5.3 Which conversation/tab does the answer go into?
- ✅ **DECIDED — Each trigger opens a brand-new tab, which becomes the shown tab inside Xpdite.** Every hotkey press spins up a fresh tab holding only that one Auto Mode capture + answer, and Xpdite switches its **in-app** visible tab to that new tab so the user sees the streaming response. It never appends to another conversation.
- **Two levels of "active" — do not confuse them (ties to 5.2):**
  - *In-app active tab:* YES — the new Auto tab becomes the selected/visible tab in Xpdite's own tab strip. That is the point: the user must see the response.
  - *OS window focus:* NO — the OS window is only ever *shown inactive*; the user's other application keeps keyboard/foreground focus. Switching the in-app tab must not activate/raise the OS window.
- The tab is a **normal, persistent tab**: it stays open until the user closes it with its own × (see 5.4a) and is saved to history like any chat (see 5.4b).

### 5.4 One-shot vs. continuous?
- ✅ **DECIDED — One-shot.** Every keybind press = new tab → capture → answer → done. No shared/continuing context between presses; each answer is self-contained.

### 5.4a Dismiss / lifecycle
- ✅ **DECIDED — Auto tabs behave exactly like normal tabs.** They are permanent — nothing auto-closes or auto-hides them. The user closes one by clicking its × in the tab strip, same as any tab. There is no special Esc/auto-fade behavior. Pressing the keybind again simply creates the next new tab and shows it (per 5.3/5.6).

### 5.4b History persistence
- ✅ **DECIDED — Saved to history like a normal chat.** Auto Mode turns persist to conversation history through the standard save flow — no ephemeral/no-trace behavior. They appear in Chat History and are searchable like any conversation.

### 5.5 How is the mode enabled, and what does the keybind do?
- ✅ **DECIDED — A single Settings → General on/off toggle governs everything.** When the toggle is **on**, the (single, same) Auto Mode keybind runs the automode pipeline: capture the screen and answer using the user's saved Auto Mode prompt/instructions. When the toggle is **off**, the keybind is inert. One toggle, one keybind — no per-trigger mode picking.
- **Gating mechanism:** a **persisted on/off flag** is the single source of truth. The hotkey listener checks this flag at trigger time (mirroring how the existing screenshot hotkey is already gated by capture mode) and no-ops when off. Enabling/disabling takes effect immediately, with no restart.
- **Hotkey:** a **fixed default combo** ships for v1 (no customization needed to use the feature); user-configurable rebinding is a later-phase nicety. The default must be distinct from the existing screenshot hotkeys and verified conflict-free on each target OS.

### 5.6 Trigger origin: backend or frontend?
- ✅ **DECIDED — Backend-driven, frontend-state-independent.** The native hotkey listener on the backend handles the press regardless of what state the frontend is in (hidden, mini, unfocused, on another route). On trigger it captures full-screen, opens the new tab, enqueues the query (saved prompt + image), and broadcasts streaming as usual. The response then **automatically shows, streaming back live**, without the user touching the UI. The frontend's only jobs are to render the stream and to surface the window inactive per 5.2.

### 5.7 Model selection
- ✅ **DECIDED — Use the currently selected model.** No separate Auto Mode model. If the currently selected model is **not vision-capable** (can't accept images), do not fail silently — route the failure through **the app's existing custom error handler / error-message component** (the same error UI used for normal chat failures, rendered as an assistant-style error message) telling the user to switch to a vision-capable model.

---

## 6. Component-Level Changes (high level)

Described by role, not by file.

**Global hotkey / listener layer**
- Register a new, distinct global accelerator for Auto Mode, independent of the existing screenshot hotkey and of the current capture-mode gate.
- On press, kick off the Auto Mode pipeline (hide → capture → submit) on the event loop from the listener thread, carrying the correct destination context.

**Screenshot / capture layer**
- Reuse existing full-screen capture and the existing "hide own window before capture, reshow after" behavior. No interactive region path is involved.
- Ensure the momentary self-hide covers the answer surface too, so a previous answer isn't captured into the next shot.

**Chat submission pipeline**
- Provide a path to submit a turn programmatically (saved prompt text + captured image) into a **freshly created tab** (new per trigger, per 5.3) without a user compose action. Reuse the normal enqueue → stream → persist flow so streaming, cancellation, and token accounting all behave identically.
- If the currently selected model is not vision-capable, short-circuit into the app's existing error-message component instead of submitting (per 5.7).

**Settings / configuration store**
- Persist the **Auto Mode enabled flag** (the General-tab toggle) — the gate the hotkey checks.
- Persist the user's Auto Mode prompt.
- Persist the (optionally customizable) hotkey.
- Persist any toggles added later (pinned model, keep-context, sound/flash on trigger).

**Windowing / Electron layer**
- Add the ability to **show the window inactive** (visible + always-on-top, no focus/activation) specifically for the Auto Mode answer. **Hard rule (5.2):** no Auto Mode code path may focus/activate/raise-to-front the window — ever.
- Respect Invisible Mode / content protection so the window is excluded from its own capture where that setting is on.
- Open the new per-trigger tab and surface it inactive, without disturbing the user's active app/tab or taking focus.

**Settings UI**
- In the **General** tab, add an **Auto Mode thumb/toggle switch** (same control style as the existing Invisible Mode toggle) as the primary on/off control.
- Alongside it: a text area for the default prompt, a hotkey field, and (future) the optional toggles. The prompt/hotkey inputs can be shown only while the toggle is on, or shown greyed-out when off.

**Answer presentation (frontend)**
- Render the streamed answer in the chosen surface (reused main window per 5.1), styled for a quick glance, with an obvious dismiss affordance (Esc / trigger-again).

---

## 7. Settings & Configuration

| Setting | Purpose | Default |
|---|---|---|
| **Auto Mode enabled** | General-tab thumb toggle; gates the hotkey | Off |
| Auto Mode prompt | The text sent with every Auto Mode capture | A sensible starter ("Answer the question on my screen concisely.") |
| Auto Mode hotkey | Global trigger key | **Fixed default combo** shipped for v1 (distinct from the existing screenshot hotkeys; must be verified conflict-free per-OS). User customization is deferred to a later phase. |
| (future) Pinned model | Force a specific vision model for Auto Mode | Off → use current model |
| (future) Keep context | Chain successive captures into one thread | Off (one-shot) |

---

## 8. Edge Cases & Risks

- **Focus theft is a hard-fail (5.2)** — if the answer surface activates the window even once, the feature fails its core promise. Must be verified on every target OS, since show-without-focus and new-window semantics differ per platform (creating a new tab/window is a common place activation sneaks back in).
- **Self-capture / feedback loop** — the overlay (and any prior answer) must be excluded from the shot; rely on the existing hide-before-capture plus Invisible Mode.
- **Non-vision models** — selected model may not accept images; detect this and route through the app's existing error-message component (assistant-style error) prompting the user to switch models, rather than a cryptic error or silent failure.
- **Rapid re-triggers** — debounce so mashing the hotkey doesn't stack captures/queries (a debounce already exists for the screenshot trigger and should be mirrored).
- **In-flight answer + new trigger** — define behavior: cancel the previous Auto answer and start fresh (recommended) vs. queue.
- **Multi-monitor / scaling** — full-screen capture must handle the user's monitor layout and DPI correctly (the capture layer already accounts for DPI; confirm it holds for the "entire screen" case).
- **Window hidden/mini at trigger time** — Auto Mode must work and present an answer even if the window was minimized/hidden when the hotkey fired.
- **Hotkey collisions** — validate the chosen accelerator doesn't clash with OS or app shortcuts; make it configurable to resolve conflicts.
- **Toggle state on boot** — the enabled flag must be read at startup so the hotkey is correctly armed/disarmed before the first trigger (mirrors how Invisible Mode restores its persisted state before the renderer loads).
- **Toggling mid-session** — flipping the switch off must immediately disarm the hotkey (no stale-flag captures); flipping on must arm it without a restart.

---

## 9. Testing Considerations

- Gating test: hotkey fires the pipeline only when the enabled flag is on; is inert when off; arm/disarm updates immediately on toggle.
- Pipeline test: simulated trigger → capture invoked → query enqueued with the saved prompt + image → streaming/persist behaves like a normal turn.
- Settings round-trip: enabled flag, prompt, and hotkey persist and reload (flag restored before first trigger on boot).
- Focus behavior: assert the answer surface is shown without activation (to the extent the platform allows automated verification).
- Debounce / re-trigger behavior.
- Non-vision-model fallback: routes through the app's error-message component instead of submitting.
- New-tab isolation: each trigger creates a new tab and never mutates or steals focus from the user's active tab/conversation.

---

## 10. Suggested Phasing

1. **Phase 1 — Core loop:** General-tab **on/off toggle** + fixed default hotkey (gated by the toggle) → full-screen capture → new tab created & shown in-app (window shown *inactive*) → auto-submit saved prompt → answer streams in → turn saved to history like a normal chat; non-vision model routes to the app error component. Ships with a reasonable default prompt + fixed hotkey. This alone delivers the user's ask end to end.
2. **Phase 2 — Configuration:** Settings panel for editing the prompt text and (newly) customizing the hotkey; debounce polish.
3. **Phase 3 — Refinements:** pinned Auto Mode model, keep-context toggle, trigger feedback (subtle flash/sound), optional dedicated glance HUD surface.

---

## 11. Decisions — All Resolved

Every design fork is now decided:

- **5.1** Reuse the main overlay window (no separate HUD).
- **5.2** Window never activates; OS focus / app / window switching never happens, period.
- **5.3** Each trigger opens a new tab that becomes the *in-app* shown tab (without taking OS focus).
- **5.4** One-shot per press.
- **5.4a** Auto tabs are permanent, closed only by the user's × — no auto-dismiss.
- **5.4b** Saved to history like a normal chat.
- **5.5** Single Settings→General toggle + single keybind, gated by a persisted flag; a fixed default hotkey ships in v1 (customization deferred).
- **5.6** Backend-driven; works regardless of frontend state; response auto-shows streaming live.
- **5.7** Current selected model; if not vision-capable, route through the app's existing error-message component.

The remaining implementation-time detail is only the **exact default hotkey combo** (must be conflict-free per-OS) — a build decision, not a design one.

---

## 12. Bundled Mini-Feature — Keybind to Toggle Mini Mode

A small, self-contained addition shipped alongside Auto Mode.

### 12.1 Goal
Let the user toggle **mini mode** on/off with a keybind instead of only by clicking the title-bar control. The keybind flips the state based on where the app currently is: if the window is normal, it shrinks to mini; if it's already mini, it restores to normal.

**Keybind (platform-specific, mirroring the existing screenshot hotkey pattern `Control+.` / `Alt+.`):**
- **macOS:** `Control+,`
- **Windows / Linux:** `Alt+,`

### 12.2 Behavior
- **`Control+,` (macOS) / `Alt+,` (Windows/Linux)** → read the current mini state and toggle it:
  - normal → mini (shrink to the small overlay dot).
  - mini → normal (restore to the previous/normal bounds).
- Reuses the **existing mini-mode mechanism** end to end — the same shrink/restore logic the click control already uses (including saving and restoring normal window bounds). The keybind is just a second trigger for the same action; no new windowing behavior is introduced.
- The existing click control and the keybind stay in sync — toggling by one is reflected by the other, because both drive the same single source of mini state.

### 12.3 Global vs. in-app
- ✅ **Global hotkey (recommended).** Because "restore from mini" happens when the window is a tiny dot that likely doesn't hold keyboard focus, an in-app-only shortcut couldn't reliably bring it back. A global accelerator works in both directions regardless of focus.
- Unlike the Auto Mode keybind, this one is **not gated** by the Auto Mode toggle — it's always available.
- Consistent with 5.2's spirit: restoring/mini-izing the window is an explicit user request about the window itself, so activation here is acceptable (it is not the silent, focus-preserving Auto Mode path).

### 12.4 Edge cases
- **Hotkey collision (low risk)** — the platform choices are deliberately safe: on macOS the system Preferences shortcut is `Command+,` (⌘,), **not** `Control+,`, so `Control+,` is largely free at the OS level; on Windows/Linux `Alt+,` is uncommon and not a reserved system shortcut. Since these are *global* accelerators, only OS-level conflicts matter (per-app bindings like VS Code's `Ctrl+,` on Windows are moot because we use `Alt+,` there). Still verify per-OS at build time, and consider making it rebindable in the same later phase as the Auto Mode hotkey.
- **Rapid toggles** — debounce so a quick double-press doesn't leave the window in an inconsistent size; the toggle must always resolve to a definite normal/mini state.
- **State source of truth** — the keybind must read the *current* mini state (not a stale cached value) so it always flips correctly regardless of how the last change was made.

### 12.5 Component-level changes (high level)
- **Global hotkey / listener layer:** register the platform-specific accelerator (`Control+,` on macOS, `Alt+,` on Windows/Linux) as an always-on global trigger that requests a mini-mode toggle.
- **Windowing / Electron layer:** on toggle, invoke the existing mini/restore path (no new logic).
- **Title-bar UI:** ensure the existing mini control reflects state changes triggered by the keybind (shared state, not a duplicated local flag).

### 12.6 Testing
- Pressing the keybind from normal shrinks to mini; pressing again restores to normal.
- Keybind and click control stay in sync (toggle by one, observe the other reflects it).
- Restore returns to the prior normal bounds.
- Debounce prevents inconsistent intermediate sizes.

---

## 13. Implementation Notes (as built)

Three decisions taken at build time changed the design from the draft above. They
are recorded here so the doc matches the shipped code.

### 13.1 No separate Auto Mode hotkey — the screenshot hotkey is repurposed
Instead of a distinct v1 accelerator (Section 5.5 / 8), Auto Mode **takes over the
existing screenshot hotkey** (`Control+.` / `Alt+.`). The Settings toggle switches
its personality:
- **Off** → today's behavior (region/precision capture, wait for the user's query).
- **On** → the hands-off Auto Mode pipeline (full-screen capture + auto-submit).

`ScreenshotService.on_activate` checks `app_state.auto_mode_enabled` first and, when
set, fires the auto pipeline regardless of capture mode; otherwise it falls back to
the precision-mode gate. Trade-off: while Auto Mode is on, the hotkey no longer does
a manual region capture — turn Auto Mode off to get it back. This removes the
per-OS conflict-verification burden of a third global accelerator.

### 13.2 No vision-capability detection — user picks a vision model
Section 5.7's non-vision fallback was dropped. There is **no `supports_vision`
gate**; the user is responsible for selecting a vision-capable model. Settings shows
a disclaimer next to the Auto Mode controls. A non-vision model simply fails through
the app's normal error path.

### 13.3 Scope — Phases 1–3 shipped
The editable prompt (Phase 2), plus the Phase 3 refinements (**pinned model**,
**keep-context** toggle, and a subtle **flash on trigger**) are all included.

### 13.4 Architecture: backend-trigger → frontend-orchestrate
Tab creation and `submit_query` are frontend-owned, so the backend hotkey broadcasts
a single `auto_mode_trigger` (global, no `tab_id`) carrying `{prompt, model,
keep_context, flash}`. `Layout.tsx` (always mounted) restores-from-mini + shows the
window inactive (`electronAPI.showInactive`, never `focusWindow`) and hands off to the
chat route via `navigate('/', { state: { autoTrigger } })`. `App.tsx` reads
`location.state.autoTrigger` and reuses the normal submit flow: it opens a new tab
(or the current one, keep-context) and sends `submit_query` with
`capture_mode: 'fullscreen'` and `auto_mode: true` (the flag forces the backend to
capture even when the tab already has history). Settings persist in the SQLite
`settings` table (`auto_mode_*` keys) and `app_state.auto_mode_enabled` is restored at
boot before the hotkey listener starts.

### 13.5 Mini-mode keybind
`Control+,` / `Alt+,` is a second, always-on global hotkey registered on the same
pynput listener; it broadcasts `toggle_mini_mode`, which `Layout.tsx` applies by
flipping the shared mini state (kept in sync with the title-bar control).
