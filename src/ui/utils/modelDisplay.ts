const PROVIDER_LABEL_OVERRIDES: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Gemini',
  ollama: 'Ollama',
  openrouter: 'OpenRouter',
  google: 'Google',
  'meta-llama': 'Meta',
  mistral: 'Mistral',
  deepseek: 'DeepSeek',
  xai: 'xAI',
};

const WORD_OVERRIDES: Record<string, string> = {
  api: 'API',
  gpt: 'GPT',
  ai: 'AI',
  claude: 'Claude',
  gemini: 'Gemini',
  llama: 'Llama',
  qwen: 'Qwen',
  mistral: 'Mistral',
  sonnet: 'Sonnet',
  haiku: 'Haiku',
  opus: 'Opus',
  mini: 'Mini',
  turbo: 'Turbo',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  xai: 'xAI',
  o1: 'o1',
  o3: 'o3',
  o4: 'o4',
  o5: 'o5',
};

function toTitleCase(value: string): string {
  if (!value) {
    return value;
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function isOpenRouterModel(modelId: string): boolean {
  return modelId.startsWith('openrouter/');
}

export function getModelProviderKey(modelId: string): string {
  if (isOpenRouterModel(modelId)) {
    return 'openrouter';
  }

  const slashIndex = modelId.indexOf('/');
  if (slashIndex === -1) {
    return 'ollama';
  }

  return modelId.slice(0, slashIndex).toLowerCase();
}

export function getProviderLabel(providerKey: string): string {
  const normalized = providerKey.toLowerCase();
  return PROVIDER_LABEL_OVERRIDES[normalized] ?? toTitleCase(normalized);
}

export function stripModelProviderPrefix(modelId: string): string {
  if (!modelId) {
    return modelId;
  }

  if (isOpenRouterModel(modelId)) {
    const openRouterId = modelId.slice('openrouter/'.length);
    const slashIndex = openRouterId.indexOf('/');
    return slashIndex >= 0 ? openRouterId.slice(slashIndex + 1) : openRouterId;
  }

  const slashIndex = modelId.indexOf('/');
  return slashIndex >= 0 ? modelId.slice(slashIndex + 1) : modelId;
}

function humanizeModelId(strippedModelId: string): string {
  const base = strippedModelId
    .replace(/[:_]/g, ' ')
    .replace(/-/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!base) {
    return strippedModelId;
  }

  const withDecimalVersion = base.replace(/\b(\d)\s+(\d)\b/g, '$1.$2');

  return withDecimalVersion
    .split(' ')
    .map((word) => {
      const lower = word.toLowerCase();
      if (WORD_OVERRIDES[lower]) {
        return WORD_OVERRIDES[lower];
      }
      if (/^\d+[a-z]+$/i.test(word) || /^[a-z]+\d+$/i.test(word)) {
        return word;
      }
      return toTitleCase(lower);
    })
    .join(' ');
}

export function formatModelLabel(modelId: string): string {
  const stripped = stripModelProviderPrefix(modelId);
  return humanizeModelId(stripped);
}
