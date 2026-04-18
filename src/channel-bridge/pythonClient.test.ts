import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createPythonClient } from './pythonClient.js';

describe('createPythonClient', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test('maps submitted messages to the bridge response shape', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, message: 'queued', tab_id: 'tab-1' }),
    } as Response);
    const client = createPythonClient('http://127.0.0.1:8000');

    await expect(
      client.submitMessage({
        platform: 'telegram',
        senderId: 'user-1',
        senderName: 'Alex',
        message: 'Hello',
        messageId: 'msg-1',
        threadId: 'thread-1',
        timestamp: 1,
        isCommand: false,
      }),
    ).resolves.toEqual({
      success: true,
      queued: true,
      error: undefined,
    });

    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/internal/mobile/message',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: 'telegram',
          sender_id: 'user-1',
          message_text: 'Hello',
          thread_id: 'thread-1',
        }),
      }),
    );
  });

  test('routes command execution and joins arguments into a single string', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, response: 'ok' }),
    } as Response);
    const client = createPythonClient('http://127.0.0.1:8000');

    await client.executeCommand({
      platform: 'discord',
      senderId: 'user-2',
      command: 'model',
      args: ['gpt', '4o'],
    });

    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/internal/mobile/command',
      expect.objectContaining({
        body: JSON.stringify({
          platform: 'discord',
          sender_id: 'user-2',
          command: 'model',
          args: 'gpt 4o',
        }),
      }),
    );
  });

  test('updates the base URL for subsequent requests', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    } as Response);
    const client = createPythonClient('http://127.0.0.1:8000');

    client.setBaseUrl('http://127.0.0.1:8008');
    await client.post('/internal/mobile/health', { ping: true });

    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8008/internal/mobile/health',
      expect.objectContaining({
        body: JSON.stringify({ ping: true }),
      }),
    );
  });

  test('returns pairing state from the backend', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ paired: true }),
    } as Response);
    const client = createPythonClient('http://127.0.0.1:8000');

    await expect(client.checkPairing('whatsapp', 'user-3')).resolves.toBe(true);
  });

  test('surfaces backend HTTP errors for generic post requests', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('backend unavailable'),
    } as Response);
    const client = createPythonClient('http://127.0.0.1:8000');

    await expect(client.post('/internal/mobile/command', {})).rejects.toThrow(
      'HTTP 503: backend unavailable',
    );
  });

  test('returns false for failed health checks', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('connection reset'));
    const client = createPythonClient('http://127.0.0.1:8000');

    await expect(client.healthCheck()).resolves.toBe(false);
  });
});
