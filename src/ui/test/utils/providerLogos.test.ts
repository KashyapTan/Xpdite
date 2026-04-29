import { describe, expect, test } from 'vitest';

import { hasProviderLogo } from '../../utils/providerLogos';

describe('providerLogos', () => {
  test('returns true for supported logo providers', () => {
    expect(hasProviderLogo('anthropic')).toBe(true);
    expect(hasProviderLogo('openai')).toBe(true);
    expect(hasProviderLogo('openai-codex')).toBe(true);
    expect(hasProviderLogo('gemini')).toBe(true);
    expect(hasProviderLogo('openrouter')).toBe(true);
    expect(hasProviderLogo('ollama')).toBe(true);
  });

  test('returns false for unsupported providers', () => {
    expect(hasProviderLogo('calendar')).toBe(false);
    expect(hasProviderLogo('gmail')).toBe(false);
    expect(hasProviderLogo('')).toBe(false);
  });
});

