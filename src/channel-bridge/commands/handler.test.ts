import { beforeEach, describe, expect, test, vi } from 'vitest';

import { createCommandHandler } from './handler.js';

describe('createCommandHandler', () => {
  const callPython = vi.fn();

  beforeEach(() => {
    callPython.mockReset();
  });

  test('detects supported commands case-insensitively', () => {
    const handler = createCommandHandler({ callPython });

    expect(handler.isCommand('/help')).toBe(true);
    expect(handler.isCommand(' /MODEL gpt-4o ')).toBe(true);
    expect(handler.isCommand('hello there')).toBe(false);
  });

  test('returns local help text without calling Python', async () => {
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('telegram', 'user-1', 'Alex', '/help')).resolves.toContain('/pair');
    expect(callPython).not.toHaveBeenCalled();
  });

  test('returns usage text when /pair is missing a code', async () => {
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('telegram', 'user-1', 'Alex', '/pair')).resolves.toContain('Usage: /pair CODE');
    expect(callPython).not.toHaveBeenCalled();
  });

  test('verifies pairing codes with a fallback display name', async () => {
    callPython.mockResolvedValue({ success: true, message: 'Paired!' });
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('telegram', 'user-1', undefined, '/pair 123456')).resolves.toBe('Paired!');
    expect(callPython).toHaveBeenCalledWith('/internal/mobile/pair/verify', {
      platform: 'telegram',
      sender_id: 'user-1',
      display_name: 'telegram:user-1',
      code: '123456',
    });
  });

  test('returns a friendly pairing error when verification fails', async () => {
    callPython.mockRejectedValue(new Error('offline'));
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('telegram', 'user-1', 'Alex', '/pair 123456')).resolves.toBe(
      'Pairing failed. Please try again or generate a new code in Xpdite.',
    );
  });

  test('routes non-help commands through the Python command endpoint', async () => {
    callPython.mockResolvedValue({ response: 'Switched model.' });
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('discord', 'user-2', 'Kai', '/model gpt 4o')).resolves.toBe(
      'Switched model.',
    );
    expect(callPython).toHaveBeenCalledWith('/internal/mobile/command', {
      platform: 'discord',
      sender_id: 'user-2',
      command: 'model',
      args: 'gpt 4o',
    });
  });

  test('returns a generic transport error for command failures', async () => {
    callPython.mockRejectedValue(new Error('offline'));
    const handler = createCommandHandler({ callPython });

    await expect(handler.handle('discord', 'user-2', 'Kai', '/status')).resolves.toBe(
      'Failed to execute /status. Is Xpdite running?',
    );
  });
});
