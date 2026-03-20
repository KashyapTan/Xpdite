import { describe, expect, test } from 'vitest';

import {
  formatModelLabel,
  getModelProviderKey,
  getProviderLabel,
  isOpenRouterModel,
  stripModelProviderPrefix,
} from '../../utils/modelDisplay';

describe('modelDisplay utilities', () => {
  describe('isOpenRouterModel', () => {
    test('returns true for openrouter-prefixed models', () => {
      expect(isOpenRouterModel('openrouter/anthropic/claude-3.5-sonnet')).toBe(true);
    });

    test('returns false for non-openrouter models', () => {
      expect(isOpenRouterModel('anthropic/claude-3-5-sonnet')).toBe(false);
    });
  });

  describe('getModelProviderKey', () => {
    test('returns openrouter for openrouter models', () => {
      expect(getModelProviderKey('openrouter/openai/gpt-4o')).toBe('openrouter');
    });

    test('returns lowercased provider for slash models', () => {
      expect(getModelProviderKey('OpenAI/gpt-4o-mini')).toBe('openai');
    });

    test('defaults to ollama for bare model names', () => {
      expect(getModelProviderKey('llama3.2:latest')).toBe('ollama');
    });
  });

  describe('getProviderLabel', () => {
    test('uses overrides for known providers', () => {
      expect(getProviderLabel('openai')).toBe('OpenAI');
      expect(getProviderLabel('xai')).toBe('xAI');
    });

    test('falls back to title case for unknown providers', () => {
      expect(getProviderLabel('custom-provider')).toBe('Custom-provider');
    });
  });

  describe('stripModelProviderPrefix', () => {
    test('strips normal provider prefix', () => {
      expect(stripModelProviderPrefix('anthropic/claude-3-5-sonnet')).toBe('claude-3-5-sonnet');
    });

    test('strips openrouter vendor and provider prefix', () => {
      expect(stripModelProviderPrefix('openrouter/anthropic/claude-3.5-sonnet')).toBe(
        'claude-3.5-sonnet',
      );
    });

    test('returns unchanged value for models without slash', () => {
      expect(stripModelProviderPrefix('qwen3:14b')).toBe('qwen3:14b');
    });
  });

  describe('formatModelLabel', () => {
    test('formats hyphenated names with known token overrides', () => {
      expect(formatModelLabel('openai/gpt-4o-mini')).toBe('GPT 4o Mini');
    });

    test('formats colon/underscore names with title casing', () => {
      expect(formatModelLabel('ollama/deepseek_r1:14b')).toBe('DeepSeek r1 14b');
    });

    test('keeps alphanumeric tokens intact', () => {
      expect(formatModelLabel('anthropic/claude-3-5-sonnet')).toBe('Claude 3.5 Sonnet');
    });
  });
});

