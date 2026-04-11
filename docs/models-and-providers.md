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
- Cloud provider requests run through provider-specific streaming logic.

## Related Docs

- `docs/api-reference.md`
- `docs/configuration.md`
- `docs/features-overview.md`
