# Models and Providers

This document describes how Xpdite handles local and cloud model providers.

## Provider Types

- Local models via Ollama.
- Cloud models via Anthropic, OpenAI, Gemini, and OpenRouter.
- ChatGPT subscription models via the bundled OpenAI Codex app-server.

## Selection and Enablement

- Enabled-model list is persisted in settings.
- Model selection can be adjusted in settings and per request.

## API Endpoints

- `GET /api/models/ollama`
- `GET /api/models/ollama/info/{model_name}`
- `GET /api/settings/ollama`
- `PUT /api/settings/ollama`
- `GET /api/models/enabled`
- `PUT /api/models/enabled`
- `GET /api/models/anthropic`
- `GET /api/models/openai`
- `GET /api/models/gemini`
- `GET /api/models/openrouter`
- `GET /api/models/openai-codex`
- `GET /api/openai/codex/status`
- `POST /api/openai/codex/connect/browser`
- `POST /api/openai/codex/connect/device`
- `POST /api/openai/codex/cancel`
- `POST /api/openai/codex/disconnect`

## Credentials

- Provider keys are managed through:
  - `GET /api/keys`
  - `PUT /api/keys/{provider}`
  - `DELETE /api/keys/{provider}`
- ChatGPT subscription credentials are not API keys. Connect from Settings using browser OAuth or device code. The private Codex home owns credential storage and refresh; Xpdite never copies or decodes its OAuth tokens.

## Runtime Notes

- Ollama backend requests may be globally serialized for local GPU stability.
- Local Ollama models use the persisted Settings > Ollama context size as `num_ctx` and pass `keep_alive` so the daemon can keep model/KV state warm; Ollama cloud models continue using their advertised maximum context window.
- API-key cloud providers run through provider-specific streaming logic backed by LiteLLM. ChatGPT subscription turns use a separate full-duplex Codex app-server provider.
- ChatGPT model discovery is account-scoped: Xpdite displays every non-hidden entry returned by Codex `model/list`, including default, reasoning-effort, modality, and upgrade metadata. A missing context-window value remains unknown.
- Each ChatGPT model row exposes an effort picker containing only the levels reported by that model. Overrides are persisted per model; unavailable or stale choices safely fall back to Xpdite's configured effort and then the account model default.
- Each ChatGPT request uses a fresh isolated ephemeral Codex thread, the exact Xpdite prompt and history, and only the Xpdite tools retrieved for that request. No private-backend or LiteLLM fallback is attempted.
- ChatGPT turns explicitly request Codex's readable reasoning summaries and stream them through Xpdite's `thinking_chunk` / `thinking_complete` path. Raw private chain-of-thought events are never forwarded or persisted.
- The pinned native helper is validated with a real packaged `initialize` handshake in the cross-platform CI matrix. Run `bun run test:codex-runtime` for a host-native packaging smoke test.
- Prompt caching is provider-native. OpenAI API requests include a hashed prompt-cache affinity key, Anthropic/Claude requests use ephemeral cache control, and Gemini/OpenRouter/ChatGPT subscription cache hits are recorded only when the provider reports them.
- Token accounting persists input, output, cached-read, and cache-write totals. Cached tokens are reported separately from the context-window total.

## Related Docs

- `docs/api-reference.md`
- `docs/configuration.md`
- `docs/features-overview.md`
