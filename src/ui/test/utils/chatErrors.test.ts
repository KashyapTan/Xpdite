import { describe, expect, test } from 'vitest';
import { createChatErrorDescriptor, createChatErrorMessage } from '../../utils/chatErrors';

describe('chatErrors', () => {
  test('formats queue saturation as a descriptive assistant error', () => {
    const descriptor = createChatErrorDescriptor({
      rawError: 'Tab queue is full (5 items).',
      source: 'queue',
      action: 'submit',
      model: 'openai/gpt-4o',
    });

    expect(descriptor.status).toBe('Queue full.');
    expect(descriptor.message.variant).toBe('error');
    expect(descriptor.message.model).toBe('openai/gpt-4o');
    expect(descriptor.message.content).toContain('Queue full');
    expect(descriptor.message.content).toContain('cancel a queued item');
  });

  test('formats connection failures with reconnect guidance', () => {
    const message = createChatErrorMessage({
      rawError: 'Lost connection to the local backend.',
      source: 'connection',
      action: 'connection',
    });

    expect(message.variant).toBe('error');
    expect(message.content).toContain('Backend disconnected');
    expect(message.content).toContain('retrying automatically');
  });

  test('maps Ollama connection failures to a clear Ollama-not-running error', () => {
    const message = createChatErrorMessage({
      rawError: 'All connection attempts failed',
      source: 'backend',
      action: 'submit',
      model: 'qwen3.5:397b-cloud',
    });

    expect(message.content).toContain('Ollama is not running');
    expect(message.content).toContain('http://localhost:11434');
    expect(message.content).toContain('Launch Ollama');
  });

  test('maps missing provider credentials to setup guidance', () => {
    const message = createChatErrorMessage({
      rawError: 'No API key configured for openai. Add one in Settings.',
      source: 'backend',
      action: 'submit',
      model: 'openai/gpt-4o',
    });

    expect(message.content).toContain('OpenAI API key missing');
    expect(message.content).toContain('Open Settings');
    expect(message.content).toContain('OpenAI key');
  });

  test('keeps provider errors descriptive instead of echoing generic backend copy only', () => {
    const message = createChatErrorMessage({
      rawError: 'LLM service temporarily unavailable. See server logs for details.',
      source: 'backend',
      action: 'submit',
      model: 'openai/gpt-4o',
    });

    expect(message.content).toContain('OpenAI request failed');
    expect(message.content).toContain('OpenAI provider');
    expect(message.content).toContain('switch to another model');
  });
});
