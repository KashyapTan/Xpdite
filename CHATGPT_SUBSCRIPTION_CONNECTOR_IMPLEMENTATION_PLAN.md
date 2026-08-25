# ChatGPT Subscription Connector Implementation Plan

- **Status:** Proposed implementation specification
- **Research date:** 2026-08-25
- **Scope:** ChatGPT subscription authentication, model discovery, inference, streaming, system instructions, Xpdite tools, cancellation, errors, packaging, and tests
- **Out of scope for this document:** Implementing the changes

## Executive decision

Replace the current split connector with one end-to-end integration through Xpdite's bundled OpenAI Codex app-server.

- The Codex app-server owns ChatGPT OAuth, refresh tokens, account state, subscription entitlements, model discovery, upstream model turns, and rate-limit metadata.
- Xpdite remains the source of truth for the exact system prompt, conversation history, retrieved tool allowlist, tool execution, artifact parsing, UI streaming events, cancellation, and persistence.
- Each Xpdite request uses a fresh ephemeral Codex thread, injects the existing Xpdite history, and starts one turn. This preserves Xpdite's current stateless provider contract and avoids a second conversation database.
- Xpdite passes only the tools retrieved for that request as Codex dynamic tools. It starts the thread with `environments: []` so Codex cannot add or execute shell, file-edit, or local-environment tools outside Xpdite's tool boundary.
- Codex runs against a dedicated empty working directory with automatic project, environment, permissions, apps, and skills instruction blocks disabled. Repository `AGENTS.md` files or a user's Codex configuration must not silently alter Xpdite's prompt.
- Remove the ChatGPT subscription inference path through LiteLLM and remove the duplicated LiteLLM token store. LiteLLM remains unchanged for API-key-based cloud providers.
- Do not silently fall back to the current private-backend path. A fallback could replay a request after tool side effects and would make protocol failures difficult to detect.

This is the best-supported design available for subscription access. OpenAI documents “Sign in with ChatGPT” as a Codex authentication mode and documents the Codex app-server as the protocol for rich clients. OpenCode and Pi demonstrate that direct use of ChatGPT's internal Codex Responses endpoint can work, but that endpoint is not a documented public OpenAI API and should be treated only as implementation research, not Xpdite's production contract.

## User-visible contract

After this work:

1. A user can sign in with a ChatGPT account accepted by the bundled Codex runtime using browser OAuth or device code.
2. Xpdite shows every non-hidden model returned to that signed-in account by Codex `model/list`.
3. Selecting one of those models sends the exact Xpdite system prompt and the current Xpdite conversation to the model.
4. The model can call only the Xpdite tools retrieved and registered for that request. Calls execute through Xpdite's existing MCP and inline-tool machinery and stream through the existing UI.
5. Text, reasoning summaries, artifacts, tool activity, usage, cancellations, usage limits, authentication failures, and upstream failures terminate in a deterministic UI state.
6. The connection survives normal access-token expiration and application restarts without Xpdite copying, decoding, or refreshing OAuth tokens itself.

“All ChatGPT models” means all non-hidden models that Codex `model/list` returns for the active account. This is a resolved product rule: Xpdite will not advertise or hardcode support for named subscription or workspace types. It will expose the capabilities authorized by `account/read`, account-scoped `model/list`, and the active workspace policy. Xpdite must not promise every model or mode visible in the ChatGPT consumer UI: some ChatGPT experiences are product features rather than Codex-callable models, and availability varies by account, workspace policy, plan, rollout, and runtime version.

## Research findings

### Official OpenAI contract

- OpenAI's [Codex authentication documentation](https://learn.chatgpt.com/docs/auth) supports signing in with ChatGPT for subscription access. Codex stores the login and automatically refreshes managed credentials. Browser, device-code, desktop, and CLI flows share this account model.
- The official [Codex app-server README for Xpdite's pinned `0.125.0` runtime](https://github.com/openai/codex/blob/rust-v0.125.0/codex-rs/app-server/README.md) defines initialization, `account/read`, managed login, logout, rate limits, paginated `model/list`, threads, turns, streamed item events, interruption, raw history injection, and host-managed dynamic tools.
- The pinned [V2 protocol types](https://github.com/openai/codex/blob/rust-v0.125.0/codex-rs/app-server-protocol/src/protocol/v2.rs) include `baseInstructions`, `developerInstructions`, `ephemeral`, `environments`, `dynamicTools`, `thread/inject_items`, reasoning-effort metadata, input modalities, and terminal turn states.
- App-server managed ChatGPT authentication is explicitly the recommended mode in the official protocol. Codex owns OAuth persistence and refresh; clients consume account state through RPC.
- `model/list` is account- and runtime-aware. It returns model IDs, display metadata, hidden/default state, supported reasoning efforts, default reasoning effort, input modalities, and pagination. The pinned response does not provide a context-window number, so Xpdite must not fabricate one.
- Dynamic tools are an official but experimental app-server capability in `0.125.0`. They require `initialize.params.capabilities.experimentalApi = true`; calls arrive as server-initiated `item/tool/call` JSON-RPC requests and must receive a structured response.
- `thread/start.environments: []` disables environment access. In the pinned runtime, this causes environment-dependent built-ins such as shell, apply-patch, and local-image inspection tools to be omitted. This is required to preserve Xpdite's tool boundary.
- `thread/inject_items` appends raw Responses API history without running the model. It lets Xpdite reconstruct its existing conversation in an ephemeral thread and remains the source of truth for persistence.
- `turn/interrupt` is the protocol cancellation mechanism. The terminal event is still `turn/completed` with an `interrupted` state.
- The public [Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) is useful for the shape and semantics of instructions, response items, tools, parallel tool calls, and terminal events. It does not establish the private ChatGPT backend URL as a public subscription API.

### OpenCode findings

OpenCode's [ChatGPT/Codex plugin](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/openai/codex.ts) implements its own OAuth and request adapter. It refreshes tokens with concurrency protection, extracts the ChatGPT account ID from token claims, rewrites Responses requests to `https://chatgpt.com/backend-api/codex/responses`, adds account/originator/session headers, removes unsupported output-token limits, and filters models.

Useful lessons for Xpdite:

- Serialize refresh activity so concurrent requests do not race.
- Keep a stable per-request/session identifier for tracing and cache affinity.
- Treat account ID and refresh behavior as part of a coherent credential owner.
- Remove or reject parameters that the subscription transport does not support.

What not to copy:

- Xpdite should not implement OAuth or JWT claim parsing when the bundled Codex app-server already owns that lifecycle.
- Xpdite should not make a private ChatGPT URL its stable provider interface.
- A static allowlist/denylist is not a substitute for account-scoped `model/list`.

### Pi findings

Pi's [OpenAI Codex OAuth implementation](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/auth/oauth/openai-codex.ts), [Codex Responses adapter](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/api/openai-codex-responses.ts), and [shared Responses conversion](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/api/openai-responses-shared.ts) form a mature direct adapter to the same private backend.

Useful lessons for Xpdite's protocol and test design:

- Preserve the exact system instructions instead of relying on a provider default.
- Preserve function call IDs, empty tool results, image tool results, partial JSON argument streams, and reasoning replay.
- Include encrypted reasoning content when directly replaying Responses history; when app-server owns the turn, let it own that opaque upstream detail.
- Handle `response.done`, `response.completed`, `response.incomplete`, and `response.failed`, rather than assuming one happy-path terminal event.
- Honor `Retry-After`, bound retry delay, distinguish usage-limit failures from transient failures, and do not retry after observable side effects.
- Support SSE/transport disconnects, aborted requests, and terminal-event normalization with explicit tests.

Pi is strong evidence for the edge cases Xpdite must test. It is not evidence that the private backend is a supported public API.

## Current Xpdite state and failure analysis

The current connector is internally split:

```text
Codex app-server                     LiteLLM chatgpt provider
  browser/device login  ──copies──>   second auth.json
  writes/refreshes auth                reads/refreshes its own copy
                                        calls private ChatGPT backend
                                        runs Xpdite's manual tool loop
```

The split creates multiple sources of truth and explains why a successful-looking login does not guarantee a working model turn.

| Area | Current behavior | Failure or robustness gap |
|---|---|---|
| Credential ownership | `openai_codex.py` copies Codex auth into a second LiteLLM auth file | Codex and LiteLLM can refresh different files; freshness is inferred from modification time |
| Status | `get_status()` reads the copied file and ignores its `refresh_token` argument | Expired, revoked, malformed, or wrong-workspace credentials can appear connected |
| Models | `list_models()` uses LiteLLM's registry or a hardcoded fallback and assigns a fixed context window | Models are not the account's authoritative entitlements; metadata can be false or stale |
| Inference | `cloud_provider.py` calls `litellm.aresponses()` as `chatgpt/<model>` | The production request depends on an undocumented backend adapter separate from the official auth client |
| System prompt | Xpdite passes its prompt, while LiteLLM prepends a process-global `CHATGPT_DEFAULT_INSTRUCTIONS` value | Prompt ownership is split and there is no end-to-end contract test proving the upstream instruction payload or behavior |
| Stream handling | The subscription path handles text deltas, function arguments, and `response.completed` | Reasoning, incomplete/failed/error terminals, refusal-like output, disconnects, and duplicate terminal events are not comprehensively handled |
| Tool protocol | Xpdite manually reissues Responses calls after tool results | It must reproduce opaque Responses continuation behavior and is easy to break across model/backend changes |
| JSON-RPC transport | Any message with an integer `id` is treated as a response | App-server server requests such as `item/tool/call` would be dropped; JSON-RPC is bidirectional and ID namespaces may overlap |
| Cancellation | The LiteLLM iterator is abandoned when Xpdite cancellation is observed | The upstream turn is not explicitly interrupted through the owner protocol |
| Tests | 10 service tests and 3 provider tests pass, but all use local files or mocks | They validate the current split design, not a real app-server handshake, system prompt, refresh, model entitlement, terminal state, or packaged runtime |
| Documentation | Backend guidance says model discovery uses app-server even though implementation uses LiteLLM/hardcoded data | Maintainers cannot rely on the documented architecture |

Baseline research run on 2026-08-25:

- `uv run pytest tests/test_openai_codex_service.py -q`: 10 passed.
- `uv run pytest tests/test_cloud_provider.py -q -k openai_codex`: 3 passed, 60 deselected.

Passing these tests does not demonstrate a working subscription connection because no test performs an app-server inference turn.

## Target architecture

```text
Settings/API ───────────────┐
                            v
                  CodexAppServerClient
                 one managed subprocess
                  full-duplex JSON-RPC
                    /       |        \
                   v        v         v
            account RPC  model/list  ephemeral thread + turn
                                         |
                              item/tool/call requests
                                         v
                              XpditeToolExecutor
                            retrieved allowlist only
                                         |
                            existing MCP/inline tools

Turn notifications ──> OpenAICodexProvider ──> existing Xpdite websocket,
                                             artifact, thinking, usage,
                                             persistence, and UI contracts
```

### Component boundaries

#### 1. `CodexAppServerClient`

Create a transport-focused service, preferably at `source/services/integrations/codex_app_server.py`. It must not know about FastAPI, LiteLLM, artifact rendering, or the chat UI.

Responsibilities:

- Resolve and launch the bundled pinned runtime using the existing native-binary and Node-wrapper logic.
- Use one long-lived subprocess per backend process and one private `CODEX_HOME`.
- Perform exactly one `initialize` / `initialized` handshake per subprocess.
- Advertise `experimentalApi: true` because dynamic tools and environment selection are required.
- Implement full-duplex JSON-RPC request, response, notification, and server-request dispatch.
- Maintain pending client requests separately from active thread/turn event subscriptions.
- Respond to server requests, including concurrent `item/tool/call` requests.
- Expose typed operations for account, models, thread creation/history injection, turns, interruption, and shutdown.
- Surface protocol errors as structured internal exceptions without leaking tokens or raw sensitive payloads.
- Detect process exit, fail all pending work once, and allow a clean lazy restart.

Message classification must be based on shape, in this order:

1. `method` plus `id`: server request; dispatch and send a result/error response.
2. `method` without `id`: notification; route by method and thread/turn identifiers.
3. `id` plus `result` or `error`: response to a client request.
4. Anything else: malformed protocol message; record a redacted diagnostic and ignore or fail the affected operation.

Do not classify by numeric ID alone. Client and server request IDs are independent directions and may collide.

Concurrency and lifecycle requirements:

- Serialize writes to stdin.
- Never block the stdout reader while a tool runs. Enqueue the server request to the matching active turn, continue reading protocol messages, and write the eventual tool response through the serialized writer.
- Use unique monotonic client request IDs per subprocess generation.
- Associate each pending request and event subscription with a subprocess generation so late messages from a dead process cannot complete new work.
- Expose an async turn/event API to providers and a small synchronous wrapper for settings calls. Do not create nested event loops or bind a long-lived subprocess to a short-lived request loop.
- Bound request queues and timeouts. Timeouts remove pending entries and include the RPC method, never payload data.
- Maintain a bounded redacted stderr tail for diagnostics.
- On crash, fail each pending request/turn exactly once. Restart only for a later operation; do not automatically replay an in-progress turn.
- Shutdown closes stdin, waits briefly, terminates, then kills only the exact child process if necessary.
- Never log OAuth tokens, authorization URLs containing sensitive query parameters, full prompts, tool arguments/results, or raw `auth.json` content.

#### 2. `OpenAICodexService`

Retain `source/services/integrations/openai_codex.py` as the account/catalog facade, backed by `CodexAppServerClient`.

Changes:

- Remove `configure_litellm_environment`, `get_chatgpt_token_dir`, the LiteLLM auth conversion/copy, `CHATGPT_TOKEN_DIR`, `CHATGPT_AUTH_FILE`, and `CHATGPT_DEFAULT_INSTRUCTIONS` mutation.
- Keep the existing private Codex home, legacy Codex auth migration if needed, binary resolution, browser/device login UI state, cancel, and logout behavior.
- Make `account/read` authoritative for status. Use `refreshToken: false` for routine polling; use `true` for an explicit refresh, immediately after login completion, and as a preflight when the first turn after startup reports stale/unauthorized credentials.
- Report `connected: true` only when `account/read` returns `account.type == "chatgpt"`. An API-key account in the same Codex home is not a ChatGPT subscription connection.
- Treat runtime unavailable, disconnected, authenticating, connected, refreshing, rate-limited, and degraded/error as distinct internal states. Preserve backward-compatible fields during the transition.
- Subscribe to `account/login/completed` and `account/updated`; invalidate cached account/model state on either event.
- Implement `account/rateLimits/read` and cache the latest `account/rateLimits/updated` notification for UI diagnostics.
- Implement paginated `model/list`, `includeHidden: false` by default, following `nextCursor` to completion with a maximum page count.
- Cache models briefly per account identity/runtime generation. Invalidate on login/logout/account update/runtime restart or explicit refresh.
- Preserve model metadata supplied by the protocol: `id`, `model`, `displayName`, `description`, `hidden`, `isDefault`, reasoning efforts/default, input modalities, and upgrade metadata.
- Leave context window unknown when the protocol does not provide it. Update API/frontend types to make that value optional instead of returning `400000`.

The current endpoints can remain stable:

- `GET /api/openai/codex/status`
- `POST /api/openai/codex/connect/browser`
- `POST /api/openai/codex/connect/device`
- `POST /api/openai/codex/cancel`
- `POST /api/openai/codex/disconnect`
- `GET /api/models/openai-codex`

Additive response fields may include runtime version, connection state, model refresh timestamp, rate-limit windows, and a stable error code. Human messages remain user-safe; detailed redacted diagnostics stay in logs.

#### 3. `OpenAICodexProvider`

Create `source/llm/providers/openai_codex_provider.py` and route `openai-codex/*` models to it before the generic LiteLLM path. Keep the public provider return tuple and websocket events compatible with current callers.

One Xpdite request maps to one ephemeral Codex thread:

1. Verify a ChatGPT account through `account/read` and verify that the selected model exists in the current `model/list` cache.
   - Use the returned picker `id` as the Xpdite selection/protocol value and retain the separate underlying `model` field as metadata unless pinned-runtime conformance proves a different requirement.
   - If the request contains images, require the catalog's `inputModalities` to advertise image input and return a clear preflight error otherwise.
2. Build the exact Xpdite system prompt through the existing `source/llm/core/prompt.py` path.
3. Retrieve the allowed Xpdite tools exactly as today.
4. Start an ephemeral thread with the selected model, exact `baseInstructions`, `environments: []`, Xpdite `dynamicTools`, and `serviceName: "xpdite"`.
5. Inject prior user/assistant history with `thread/inject_items` as raw Responses message items. Do not inject the current user message twice.
6. Start the current turn with text and image inputs.
7. Stream notifications, service tool requests, and wait for the matching `turn/completed` terminal event.
8. Discard the ephemeral thread reference after completion. Xpdite's persisted conversation remains authoritative.

Why ephemeral-per-request is the first implementation:

- It matches the existing provider interface, which receives full Xpdite history on every call.
- It supports retry, edit, restored tabs, and backend restarts without maintaining a second thread ID or branch graph.
- The semantically retrieved tool set may change every turn; dynamic tools are registered at `thread/start`, so a fresh thread gives an exact per-request allowlist.
- It avoids persistence and migration complexity while preserving prompt caching opportunities in the upstream runtime.

Persistent Codex threads may be evaluated later as a measured optimization, but only after defining reconciliation for edits, retries, tool-schema changes, runtime upgrades, and Xpdite database restores.

### Exact prompt contract

- Pass the fully assembled Xpdite system prompt as `thread/start.baseInstructions` without prepending the Codex CLI persona or a generic provider prompt.
- Do not set `CHATGPT_DEFAULT_INSTRUCTIONS` or depend on process-global prompt environment variables.
- Set the thread `cwd` to a dedicated empty directory below Xpdite's private connector state, not `PROJECT_ROOT`, the user's home, or a conversation workspace.
- Disable project-document discovery/injection (`project_doc_max_bytes: 0`), automatic environment and permissions blocks, app instructions, and automatic skill instructions through pinned, schema-validated thread config overrides.
- Launch the subprocess from the same isolated directory. Do not allow repository `AGENTS.md`, `.codex` project configuration, hooks, plugins, or user fallback instruction files to become implicit prompt input.
- Use `developerInstructions` only if a short transport-specific instruction proves necessary in conformance tests. It must never duplicate or override the Xpdite prompt.
- Do not pass a Codex personality unless Xpdite intentionally exposes that product setting; use `personality: "none"` where supported.
- Preserve user and assistant roles in injected history. Do not flatten history into the system prompt.
- Preserve image inputs as supported `image` URLs/data URLs. Avoid local-path inputs when a data URL is already available.
- Add an outbound payload contract test that asserts the exact `baseInstructions` string, history ordering, one current user input, selected model, and absence of a second provider prompt.
- Add a behavioral smoke test with a unique, harmless system-prompt canary to prove the live model receives and follows the Xpdite instruction. Never use hidden secrets as the canary.

### Tool bridge contract

Convert each retrieved OpenAI-style Xpdite function schema into a Codex dynamic tool:

```json
{
  "name": "tool_name",
  "description": "Tool description",
  "deferLoading": false,
  "inputSchema": { "type": "object", "properties": {} }
}
```

Requirements:

- Register only tools in `allowed_tool_names` for that request. An empty allowlist means no dynamic tools.
- Validate the Codex name constraint (`^[A-Za-z0-9_-]{1,128}$`). For an incompatible or colliding Xpdite name, create a deterministic per-turn safe alias and retain a private alias-to-registry mapping.
- Never dispatch a model-supplied name directly to the global MCP registry. Resolve through the per-turn map and recheck the original allowlist.
- Validate arguments as a JSON object with the existing `normalize_tool_args` behavior and keep existing sanitization for logs/UI.
- Refactor the current execution logic into a shared `XpditeToolExecutor` so the generic LiteLLM provider and Codex provider use identical MCP, inline tool, skills, terminal, memory, scheduler, video, and sub-agent behavior.
- Keep existing tool-start/tool-result broadcasts and `interleaved_blocks` persistence.
- Return text results as `inputText`. Convert embedded image content to inline `data:` URLs for `inputImage`; app-server rejects remote HTTP(S) image URLs in dynamic tool responses.
- Represent an empty successful result explicitly, for example an empty `inputText`, rather than omitting the response.
- Return `success: false` with a safe textual error for invalid arguments, unavailable/disallowed tools, timeout, connector loss, or execution failure.
- Support parallel server tool requests while preserving per-call IDs and deterministic result association.
- Enforce `MAX_MCP_TOOL_ROUNDS`, a maximum total tool-call count, and an overall turn deadline. Once the budget is exhausted, fail the request safely and interrupt a model that continues calling tools.
- Never retry an executed tool automatically after an app-server disconnect. The call may have produced an external side effect.

Tool isolation is defense in depth:

- Required: `thread/start.environments: []`.
- Required: an isolated empty `cwd`, `project_doc_max_bytes: 0`, and disabled automatic environment/permissions/apps/skills instruction injection.
- Required: pass no Codex MCP servers, apps, plugins, skills, or writable environment.
- Required: schema-validated per-thread overrides disable web search, shell/unified execution, apply patch, collaboration, code mode, apps/connectors, and other built-ins not owned by Xpdite where the pinned config supports them.
- Required: if any unexpected built-in execution/approval item appears, interrupt the turn and surface an internal protocol-invariant error. Do not approve or execute it.
- Required: pin `@openai/codex`; an upgrade must pass the protocol and isolation conformance suite before release.

### Streaming and output state machine

Use the app-server item lifecycle as the authoritative stream. Route events only when both thread ID and turn ID match the active request.

| App-server event | Xpdite behavior |
|---|---|
| `turn/started` | Record the turn ID and mark the request active |
| `item/agentMessage/delta` | Feed the delta once through `ArtifactStreamParser`, broadcast resulting `response_chunk`/artifact events, and accumulate final text |
| `item/agentMessage/completed` or final `item/completed` | Reconcile the authoritative final text with deltas without duplicating content |
| `item/reasoning/summaryTextDelta` | Broadcast `thinking_chunk`; group sections by item/summary index |
| `item/reasoning/textDelta` | Broadcast only if Xpdite's existing reasoning-display policy permits it |
| `item/tool/call` server request | Execute through `XpditeToolExecutor` and create the existing Xpdite tool UI/persistence record exactly once, keyed by `callId` |
| `item/started` / `item/completed` for `dynamicToolCall` | Reconcile protocol status/diagnostics with the `callId`; never create or execute a second Xpdite tool call |
| `thread/tokenUsage/updated` | Normalize to Xpdite input/output/cached/cache-write counters and retain the latest cumulative snapshot |
| `error` | Record the structured error but wait for terminal state unless transport is gone |
| `turn/completed: completed` | Finalize artifacts, emit exactly one `response_complete`, then emit the normalized usage snapshot in the ordering expected by the existing frontend contract |
| `turn/completed: interrupted` | Finish cancellation without a false success or late chunks |
| `turn/completed: failed` | Map and emit one user-safe error, then close the request deterministically |

Additional rules:

- Treat `item/completed` as authoritative for final item content.
- Deduplicate deltas and terminal notifications by `(process_generation, thread_id, turn_id, item_id, event kind/index)`.
- Finalize the artifact parser exactly once, including on error/cancellation.
- Do not emit `response_complete` before the terminal turn event.
- Do not append partial hidden reasoning to the assistant's persisted response text.
- Preserve partial visible assistant text on failure using the same semantics as other providers.
- Normalize refusal or non-text agent output into a clear supported UI block or a safe error rather than silently returning an empty message.
- Ignore late events after a request reaches a terminal state.

### Cancellation and timeout behavior

- When `is_current_request_cancelled()` first becomes true, send one `turn/interrupt` for the active thread/turn.
- Continue draining events until `turn/completed: interrupted` or a short interrupt timeout.
- If interruption times out, close the request locally, detach its event subscription, and leave the shared app-server running unless the transport itself is unhealthy.
- Cancellation during a dynamic tool call cannot undo a completed external side effect. Cancel the local task where supported, return a failed tool response if the server still awaits it, then interrupt the turn.
- Separate timeouts for startup/initialize, account/model RPCs, turn start, idle stream, overall turn, individual tool execution, and interruption.
- A timeout message should identify the stage and offer reconnect/retry guidance without exposing payload data.

### Error model and retries

Introduce stable internal error codes such as:

- `codex_runtime_unavailable`
- `codex_protocol_mismatch`
- `chatgpt_not_connected`
- `chatgpt_auth_expired`
- `chatgpt_workspace_denied`
- `chatgpt_model_unavailable`
- `chatgpt_usage_limit`
- `chatgpt_context_limit`
- `chatgpt_upstream_unavailable`
- `chatgpt_stream_disconnected`
- `chatgpt_turn_failed`
- `chatgpt_tool_protocol_error`
- `chatgpt_cancelled`

Map official `codexErrorInfo` values first, then HTTP status, then message text only as a last resort. Preserve structured details internally.

Retry policy:

- Safe to retry once: initialization before any turn, read-only `account/read`, read-only `model/list`, and thread creation/history injection before `turn/start` begins.
- Conditionally safe: a turn rejected before `turn/started` and before any tool request or visible output.
- Never automatic: after `turn/started`, after any visible text/reasoning, after any tool request, or after an ambiguous transport disconnect.
- Honor server-directed backoff for a later user-initiated retry, capped to a reasonable UI wait. Do not sleep through a long usage-limit reset inside an active request.
- On `Unauthorized`, perform one app-server-owned account refresh/preflight. If still unauthorized, mark disconnected and require sign-in.

### Security and privacy

- Codex app-server is the only reader/writer of its current OAuth record after any one-time legacy migration.
- Store `CODEX_HOME` outside the repo with directory mode `0700` and sensitive files `0600` where the platform supports POSIX modes.
- Never copy refresh/access tokens into a LiteLLM directory, Xpdite settings database, logs, API responses, crash reports, analytics, or frontend state.
- Keep app secrets stripped from the Codex subprocess environment, preserving the current minimal-environment approach.
- Keep the subprocess and every thread rooted in a connector-owned empty working directory so project discovery cannot import instructions, hooks, or configuration from the Xpdite repository or user workspace.
- Do not expose the raw Codex auth file through diagnostic endpoints.
- Redact sensitive query values from browser OAuth URLs in logs.
- Validate model IDs against the latest account model catalog before starting a turn.
- Validate every server request method. Respond with JSON-RPC “method not found” or an internal error for unknown requests; never guess approval behavior.
- Fail closed on command/file/network approval requests because Xpdite did not authorize Codex built-ins.
- Limit injected history size through the same Xpdite context policy used by other providers; handle `ContextWindowExceeded` explicitly.

## File-level implementation plan

### Backend

1. Add `source/services/integrations/codex_app_server.py`.
   - Move runtime resolution, process lifecycle, JSON-RPC framing, initialization, pending requests, notifications, server requests, event subscriptions, redaction, and typed RPC helpers here.
   - Define protocol dataclasses/TypedDicts for only the pinned fields Xpdite consumes; retain unknown fields for forward-compatible diagnostics.

2. Refactor `source/services/integrations/openai_codex.py`.
   - Keep account UX state and public service facade.
   - Replace filesystem-derived status and LiteLLM model discovery with app-server RPC.
   - Remove the second token store and all ChatGPT LiteLLM environment setup.
   - Add model/rate-limit caching and invalidation.

3. Add `source/llm/providers/openai_codex_provider.py`.
   - Build ephemeral thread requests, inject history, start/interrupt turns, bridge dynamic tools, parse events, and return Xpdite's standard response tuple.
   - Keep artifact, websocket, tool-call, and token usage semantics compatible.

4. Extract shared tool execution from `source/llm/providers/cloud_provider.py`.
   - Prefer a focused module such as `source/llm/core/tool_executor.py` rather than importing private provider functions into the Codex adapter.
   - Preserve all special inline tool routes and call-display behavior.

5. Update `source/llm/providers/cloud_provider.py` and `source/llm/core/router.py`.
   - Route `openai-codex` directly to the new provider.
   - Delete `_stream_chatgpt_subscription_responses` and ChatGPT-specific LiteLLM helpers once parity tests pass.
   - Leave generic LiteLLM behavior unchanged for Anthropic, OpenAI API, Gemini, and OpenRouter.

6. Update `source/api/http.py`.
   - Keep endpoint paths stable.
   - Return authoritative account/model states and optional metadata.
   - Normalize structured connector errors to appropriate HTTP statuses without collapsing login-required, runtime-unavailable, and upstream-error states.

7. Update token/model types where a context window is currently required.
   - Do not substitute a fake number. Render unknown context capacity explicitly or omit the progress denominator.

### Frontend

1. Update `src/ui/services/api.ts` types for the richer status and model metadata while retaining existing fields during rollout.
2. Update `src/ui/components/settings/SettingsApiKey.tsx` copy from “LiteLLM tool loop” to “ChatGPT subscription through OpenAI Codex”.
3. Show distinct states for runtime unavailable, waiting for sign-in, connected, refreshing, expired/reconnect required, rate limited, and protocol/runtime error.
4. Show plan/email only when returned by `account/read`; never infer them from token claims.
5. Use model metadata from `model/list`, including default and supported reasoning efforts. Hide hidden models unless a developer setting explicitly requests them.
6. Preserve the current browser and device-code flows, with a clear timeout/cancel state and an external-browser fallback.
7. Optionally show rate-limit percentage/reset time in settings; it should not block the core connector release.

### Packaging and documentation

1. Keep `@openai/codex` exactly pinned in `package.json`; do not use a range.
2. Keep `scripts/build-codex-runtime.mjs` and packaged native targets, but add a packaged-runtime protocol smoke test for macOS arm64/x64, Windows x64, and Linux x64/arm64 targets that Xpdite ships.
3. Validate the runtime version/capabilities at startup. If required fields are absent, return `codex_protocol_mismatch` with upgrade/reinstall guidance rather than falling back.
4. Update `CLAUDE.md`, `source/CLAUDE_backend.md`, `src/CLAUDE_frontend.md`, and `docs/models-and-providers.md` after implementation so they describe the app-server inference path, single credential owner, dynamic tool boundary, and model catalog accurately.
5. Remove documentation that claims prompt caching or context metadata unless it is observable in the app-server contract or measured behavior.

## Protocol sequence

### Process startup

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"Xpdite","version":"<app-version>"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized","params":{}}
```

Startup succeeds only after a valid initialize response. Record the returned runtime/platform metadata for diagnostics.

### Account and model preflight

```json
{"id":2,"method":"account/read","params":{"refreshToken":false}}
{"id":3,"method":"model/list","params":{"includeHidden":false,"limit":100}}
```

Follow `nextCursor` until null. Reject inference if the account is not ChatGPT-managed or if the selected model is absent.

### One Xpdite turn

The illustrative shape below must be checked against the generated schema for the pinned runtime during implementation:

```json
{
  "id":10,
  "method":"thread/start",
  "params":{
    "model":"<account-model-id>",
    "baseInstructions":"<exact Xpdite system prompt>",
    "personality":"none",
    "ephemeral":true,
    "serviceName":"xpdite",
    "cwd":"<private empty connector runtime directory>",
    "environments":[],
    "config":{
      "project_doc_max_bytes":0,
      "include_environment_context":false,
      "include_permissions_instructions":false,
      "include_apps_instructions":false,
      "include_apply_patch_tool":false,
      "skills.include_instructions":false,
      "web_search":"disabled",
      "features.shell_tool":false,
      "features.unified_exec":false,
      "features.apply_patch_freeform":false,
      "features.code_mode":false,
      "features.js_repl":false,
      "features.collab":false,
      "features.multi_agent":false,
      "features.computer_use":false,
      "features.image_generation":false,
      "features.request_permissions_tool":false,
      "features.default_mode_request_user_input":false,
      "features.tool_search":false,
      "features.apps":false,
      "features.plugins":false
    },
    "dynamicTools":["<retrieved Xpdite tool schemas>"]
  }
}
```

Then:

```json
{"id":11,"method":"thread/inject_items","params":{"threadId":"<thread>","items":["<prior Responses message items>"]}}
{"id":12,"method":"turn/start","params":{"threadId":"<thread>","input":[{"type":"text","text":"<current user text>","textElements":[]}]}}
```

During the turn, app-server may issue:

```json
{"id":60,"method":"item/tool/call","params":{"threadId":"<thread>","turnId":"<turn>","callId":"<call>","tool":"<safe alias>","arguments":{}}}
```

Xpdite executes the mapped allowed tool and replies:

```json
{"id":60,"result":{"contentItems":[{"type":"inputText","text":"<result>"}],"success":true}}
```

The request completes only after the matching `turn/completed` notification.

## Test plan

### Transport unit tests

- Initialize/initialized ordering and exactly-once initialization.
- Client responses, notifications, and server requests with overlapping numeric IDs.
- Concurrent client RPCs and concurrent dynamic tool calls.
- Partial lines, multiple lines, invalid JSON, unknown messages, JSON-RPC errors, and non-JSON stderr.
- Request timeout cleanup and late response rejection.
- Subprocess exit before initialize, during an RPC, during a turn, and during a tool call.
- Generation isolation after restart.
- Bounded stderr retention and redaction.
- Graceful shutdown followed by terminate/kill fallback of only the child process.

### Account and catalog tests

- No account, ChatGPT account, API-key account, malformed response, and forced refresh.
- Browser login success/failure/cancel/timeout and device-code success/failure/cancel/timeout.
- Account update invalidates model/status caches.
- Logout clears the Codex-owned login and Xpdite enabled subscription models without touching unrelated settings.
- Multi-page model list, hidden filtering, default model, upgrade metadata, reasoning options, and input modalities.
- Empty model list and selected model removed between selection and turn start.
- No fabricated context window.
- Rate-limit snapshots and updates.

### Provider contract tests

- Exact `baseInstructions` equality with the Xpdite-built prompt.
- No `CHATGPT_DEFAULT_INSTRUCTIONS`, Codex CLI persona, or duplicated system message.
- Isolated connector `cwd`; project `AGENTS.md`, `.codex` configuration, hooks, apps, plugins, and Codex skills do not appear in the model-visible prompt or tool catalog.
- History role/order preservation, empty history, long history, edited/retried history, Unicode, and images.
- Current user input appears exactly once.
- Ephemeral thread and `environments: []` always set.
- Only retrieved tools registered; empty set registers none.
- Valid name, aliased invalid name, collisions, large schema, missing description, and invalid JSON Schema.
- Text, empty, image, structured, error, timed-out, and cancelled tool results.
- Parallel tools, repeated tool calls, invalid arguments, disallowed name, unknown server request, and tool budget exhaustion.
- Existing inline tool categories and sub-agent tool behavior.
- Unexpected Codex command/file/network item interrupts and fails closed.

### Stream state-machine tests

- Multiple agent messages and fragmented UTF-8/text deltas.
- Reasoning summary sections and permitted raw-reasoning deltas.
- Artifact markers split across deltas and artifact finalization on all terminal paths.
- Authoritative item completion without duplicate text.
- Cumulative token usage, missing usage, and late usage.
- Completed, interrupted, failed, error-before-failed, transport disconnect, and duplicate/late terminal events.
- Partial visible output followed by failure.
- Cancellation before thread start, before turn start, during text, during a tool, and immediately before completion.
- Exactly one terminal UI sequence and no chunks after terminal state.

### Fake app-server integration tests

Add a deterministic executable fixture that speaks newline-delimited JSON-RPC over stdio. Test the real client/service/provider stack without network access:

- Login notification flow through FastAPI status endpoints.
- Paginated models through `/api/models/openai-codex`.
- System prompt + history + text stream through the websocket handler.
- One and parallel dynamic tool calls through the real Xpdite tool executor.
- Reasoning, artifacts, usage, interruption, auth expiration, quota, crash, and restart.
- Exact transcript assertions for every outbound RPC.

This fixture is the main CI guard. Unit mocks alone are insufficient.

### Opt-in live smoke matrix

Run manually or in a protected non-fork CI environment using approved test subscriptions. Never store subscription credentials in repository CI secrets intended for pull requests.

- Fresh browser login and device-code login.
- App restart with managed credential refresh.
- Representative account and workspace-policy combinations available to the test team, without turning those test fixtures into hardcoded product promises.
- Every model returned by `model/list`: simple text and a harmless system-prompt canary.
- Representative reasoning model: reasoning summary and usage.
- Representative tool-capable model: one tool, parallel tools, tool error, and empty result.
- Image input where advertised by `inputModalities`.
- Cancellation and usage-limit UX.
- Packaged builds on each shipping operating system/architecture.

Live smoke tests should verify capability, not snapshot exact prose.

### Regression tests

- Full backend test suite.
- Full frontend unit suite and typecheck/build.
- Generic LiteLLM provider tests for Anthropic, OpenAI API, Gemini, and OpenRouter.
- Ollama/local provider tests.
- Settings model enable/disable and conversation persistence tests.
- Packaged binary resolution and no-global-install behavior.

## Rollout plan

### Phase 0: Lock the contract

- Check generated schema/types from the exact `@openai/codex` pin into test fixtures or generate a minimal compatibility manifest during tests.
- Capture sanitized app-server transcripts for initialize, account, models, a text turn, a tool turn, cancellation, and failure.
- Add the fake app-server harness before changing production routing.

### Phase 1: Full-duplex client

- Extract process/runtime logic and implement the transport.
- Add account/model typed calls while the existing UI still uses the old service facade.
- Pass transport, crash, concurrency, and packaged-runtime tests.

### Phase 2: Authoritative account and models

- Switch status and model endpoints to app-server RPC.
- Remove status/model assumptions based on copied token files and LiteLLM registries.
- Update frontend states and metadata.

### Phase 3: App-server inference provider

- Add ephemeral thread/history/turn flow.
- Add exact prompt and event streaming.
- Extract and connect the shared Xpdite tool executor.
- Add cancellation, error mapping, and all provider/integration tests.

### Phase 4: Controlled release

- Gate the new provider behind a temporary local feature flag such as `XPDITE_CHATGPT_CONNECTOR_V2` for development and beta validation.
- Never shadow-send a user's prompt to both paths.
- Make V2 the default only after live smoke and packaged-platform acceptance passes.
- On V2 failure, show the structured error and reconnect/retry action; do not silently run the legacy path.

### Phase 5: Remove legacy path

- Delete the ChatGPT LiteLLM environment setup, duplicate token directory, auth conversion code, hardcoded model fallback, and `_stream_chatgpt_subscription_responses`.
- After verifying that the canonical Codex account remains readable, remove the now-redundant LiteLLM token copy from Xpdite's private state. Never delete the canonical Codex credential as part of this migration.
- Remove obsolete tests and replace them with app-server contract tests.
- Remove the temporary flag after one stable release.
- Update all relevant `CLAUDE.md` guidance and provider documentation in the same change.

## Release gates and acceptance criteria

The connector is ready only when all of the following are true:

- A clean development checkout and each packaged target can resolve and initialize the pinned Codex runtime without a global installation.
- Browser and device-code login complete, cancel, fail, and restart cleanly.
- `account/read` is the only connection authority and Codex is the only refresh-token owner.
- Every visible `model/list` result is selectable, hidden/removed models are handled, and no model/context metadata is invented.
- An outbound contract test proves byte-for-byte Xpdite `baseInstructions` and correct history/current-input placement.
- A live harmless canary confirms the Xpdite system instruction reaches the model without Codex CLI persona leakage.
- Repository/user Codex project instructions, skills, apps, plugins, hooks, and environment/permission blocks do not leak into the Xpdite turn.
- Text streams incrementally and final text is neither dropped nor duplicated.
- Reasoning summaries, artifacts, usage, errors, incomplete turns, and cancellation render and persist consistently with other providers.
- Retrieved MCP tools, inline tools, and sub-agent tools work for text, empty, image, error, timeout, sequential, and parallel cases.
- A model cannot call a non-retrieved Xpdite tool or a Codex built-in shell/file/network tool.
- No automatic retry occurs after visible output or a possible tool side effect.
- Access-token expiry is recovered by app-server; revoked/invalid auth transitions to reconnect-required instead of remaining falsely connected.
- No access/refresh token or sensitive OAuth URL appears in environment dumps, logs, HTTP responses, frontend state, Xpdite DB, or the removed LiteLLM auth directory.
- Fake app-server integration tests, full backend tests, frontend tests/typecheck/build, and packaged smoke tests pass.
- Documentation matches the shipped architecture.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Dynamic tools and environment selection are experimental in `0.125.0` | Exact runtime pin, capability handshake, generated-schema conformance tests, fail-fast protocol mismatch, deliberate upgrade process |
| App-server is a coding-agent runtime with built-in tools | `environments: []`, disable built-ins in validated per-thread config, pass no Codex MCP/apps/plugins, detect and interrupt unexpected built-in events |
| Per-request ephemeral history costs tokens/latency | Preserve correctness first; measure prompt caching and only then design persistent thread reconciliation |
| Account model catalog changes | Always use `model/list`, short cache, invalidation, selected-model preflight, no hardcoded allowlist |
| Process crash during a side-effecting tool | Never auto-replay ambiguous turns/tools; preserve partial output and require explicit user retry |
| Runtime upgrade changes protocol fields/events | Pin version, transcript fixtures, compatibility manifest, staged upgrade with live smoke |
| Subscription/workspace policy denies a capability | Surface account-scoped result and structured error; do not infer entitlement from plan name |
| History conversion loses provider-private reasoning state | App-server owns opaque reasoning within the current turn; Xpdite injects only its authoritative persisted user/assistant history, matching current cross-provider behavior |
| Large or invalid MCP schemas are rejected | Validate and normalize before thread start, identify the offending tool, and fail or omit it according to an explicit policy tested in CI |

## Resolved product decisions

The following defaults are approved for implementation:

1. Do not advertise named ChatGPT subscription or workspace types. Support is capability-driven: use `account/read`, every non-hidden result from account-scoped Codex `model/list`, and the active workspace policy as the authority. “All ChatGPT models” does not mean every mode in the ChatGPT UI.
2. Preserve the existing provider ID `openai-codex` for database/API compatibility, but label it “ChatGPT subscription (via OpenAI Codex)” in the UI.
3. Use each model's default reasoning effort unless Xpdite's configured `REASONING_EFFORT` is present in that model's supported effort list; otherwise fall back to the model default and log a redacted debug note.
4. Ship ephemeral threads first. Treat persistent Codex threads as a later optimization, not part of correctness work.
5. Do not retain the private LiteLLM path as an automatic fallback.

There are no remaining product questions blocking implementation in this specification.

## Source index

Official OpenAI sources:

- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Codex app-server protocol, pinned `0.125.0`](https://github.com/openai/codex/blob/rust-v0.125.0/codex-rs/app-server/README.md)
- [Codex app-server V2 types, pinned `0.125.0`](https://github.com/openai/codex/blob/rust-v0.125.0/codex-rs/app-server-protocol/src/protocol/v2.rs)
- [Codex app-server source, pinned `0.125.0`](https://github.com/openai/codex/tree/rust-v0.125.0/codex-rs/app-server)
- [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

Reference implementations:

- [OpenCode OpenAI Codex plugin](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/openai/codex.ts)
- [Pi OpenAI Codex OAuth](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/auth/oauth/openai-codex.ts)
- [Pi OpenAI Codex Responses adapter](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/api/openai-codex-responses.ts)
- [Pi shared OpenAI Responses conversion](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/api/openai-responses-shared.ts)

Repository guidance and implementation examined:

- `CLAUDE.md`
- `source/CLAUDE_backend.md`
- `src/CLAUDE_frontend.md`
- `mcp_servers/CLAUDE_mcp.md`
- `docs/models-and-providers.md`
- `source/services/integrations/openai_codex.py`
- `source/llm/providers/cloud_provider.py`
- `source/llm/core/router.py`
- `source/llm/core/prompt.py`
- `source/api/http.py`
- `src/ui/components/settings/SettingsApiKey.tsx`
- `src/ui/services/api.ts`
- `scripts/build-codex-runtime.mjs`
- `tests/test_openai_codex_service.py`
- `tests/test_cloud_provider.py`
