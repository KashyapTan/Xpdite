// @vitest-environment node

import net from 'node:net';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createBridgeServer } from './server.js';

async function getFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        reject(new Error('Failed to resolve a free port'));
        return;
      }

      server.close(() => resolve(address.port));
    });
  });
}

describe('createBridgeServer', () => {
  const deps = {
    sendToPlatform: vi.fn(),
    startTypingIndicator: vi.fn(),
    editPlatformMessage: vi.fn(),
    getPlatformStatuses: vi.fn(),
  };

  let server: ReturnType<typeof createBridgeServer>;
  let port: number;

  beforeEach(async () => {
    vi.clearAllMocks();
    deps.getPlatformStatuses.mockReturnValue([
      { platform: 'telegram', status: 'connected' },
    ]);
    deps.sendToPlatform.mockResolvedValue('message-1');
    port = await getFreePort();
    server = createBridgeServer(deps);
    await server.start(port);
  });

  afterEach(async () => {
    await server.stop();
  });

  test('serves health responses with platform status', async () => {
    const response = await fetch(`http://127.0.0.1:${port}/health`);

    expect(response.ok).toBe(true);
    await expect(response.json()).resolves.toMatchObject({
      status: 'ok',
      platforms: [{ platform: 'telegram', status: 'connected' }],
    });
  });

  test('returns 400 for invalid JSON bodies', async () => {
    const response = await fetch(`http://127.0.0.1:${port}/outbound`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{invalid',
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: 'Invalid JSON body' });
  });

  test('maps outbound relay requests onto the platform sender contract', async () => {
    const response = await fetch(`http://127.0.0.1:${port}/outbound`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform: 'telegram',
        sender_id: 'user-1',
        message_type: 'response',
        content: 'Hello from Python',
        render_mode: 'raw',
        thread_id: 'thread-1',
      }),
    });

    expect(response.ok).toBe(true);
    expect(deps.sendToPlatform).toHaveBeenCalledWith(
      'telegram',
      'user-1',
      'Hello from Python',
      'final_response',
      undefined,
      'thread-1',
      'raw',
    );
    await expect(response.json()).resolves.toEqual({
      success: true,
      message_id: 'message-1',
    });
  });
});
