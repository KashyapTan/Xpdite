# Models and Providers

This document describes how Xpdite handles local and cloud model providers.

## Provider Types

- Local models via Ollama.
- Cloud models via Anthropic, OpenAI, Gemini, and OpenRouter.

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

## Credentials

- Provider keys are managed through:
  - `GET /api/keys`
  - `PUT /api/keys/{provider}`
  - `DELETE /api/keys/{provider}`

## Runtime Notes

- Ollama backend requests may be globally serialized for local GPU stability.
- Local Ollama models use the persisted Settings > Ollama context size as `num_ctx` and pass `keep_alive` so the daemon can keep model/KV state warm; Ollama cloud models continue using their advertised maximum context window.
- Cloud provider requests run through provider-specific streaming logic.
- Prompt caching is provider-native. OpenAI/ChatGPT subscription requests include a hashed prompt-cache affinity key, Anthropic/Claude requests use ephemeral cache control, and Gemini/OpenRouter cache hits are recorded when the provider reports them.
- Token accounting persists input, output, cached-read, and cache-write totals. Cached tokens are reported separately from the context-window total.

## Related Docs

- `docs/api-reference.md`
- `docs/configuration.md`
- `docs/features-overview.md`
