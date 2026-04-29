const MODEL_PROVIDERS_WITH_LOGOS = [
  'anthropic',
  'openai',
  'openai-codex',
  'gemini',
  'openrouter',
  'ollama',
] as const;

export type ModelProviderWithLogo = (typeof MODEL_PROVIDERS_WITH_LOGOS)[number];

const PROVIDERS_WITH_LOGOS: ReadonlySet<string> = new Set(MODEL_PROVIDERS_WITH_LOGOS);

export function hasProviderLogo(provider: string): provider is ModelProviderWithLogo {
  return PROVIDERS_WITH_LOGOS.has(provider);
}
