// @vitest-environment node

import { EventEmitter } from 'node:events';
import path from 'node:path';
import { PassThrough } from 'node:stream';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const appGetPathMock = vi.fn().mockReturnValue('C:/Users/tester/AppData/Roaming/Xpdite');
const existsSyncMock = vi.fn();
const forkMock = vi.fn();
const spawnMock = vi.fn();
const isDevMock = vi.fn();

class FakeChildProcess extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  killed = false;
  kill = vi.fn(() => {
    this.killed = true;
    return true;
  });
}

vi.mock('electron', () => ({
  app: {
    getPath: appGetPathMock,
  },
}));

vi.mock('fs', () => ({
  default: {
    existsSync: existsSyncMock,
  },
  existsSync: existsSyncMock,
}));

vi.mock('child_process', () => ({
  fork: forkMock,
  spawn: spawnMock,
}));

vi.mock('./utils.js', () => ({
  isDev: isDevMock,
}));

describe('channelBridgeApi helpers', () => {
  const originalFetch = global.fetch;
  const originalResourcesPath = process.resourcesPath;

  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    global.fetch = vi.fn();
    isDevMock.mockReturnValue(true);
    existsSyncMock.mockImplementation((value: string) => (
      value.includes(path.join('src', 'channel-bridge', 'index.ts'))
    ));
    Object.defineProperty(process, 'resourcesPath', {
      configurable: true,
      value: 'C:/Program Files/Xpdite/resources',
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    Object.defineProperty(process, 'resourcesPath', {
      configurable: true,
      value: originalResourcesPath,
    });
  });

  test('posts outbound messages to the detected bridge port', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(''),
    } as Response);
    const { getChannelBridgePort, sendToChannelBridge } = await import('./channelBridgeApi.js');

    expect(getChannelBridgePort()).toBe(9000);
    await sendToChannelBridge('telegram', 'user-1', 'hello', 'ack');

    expect(fetch).toHaveBeenCalledWith('http://127.0.0.1:9000/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform: 'telegram',
        senderId: 'user-1',
        message: 'hello',
        messageType: 'ack',
        replyToMessageId: undefined,
      }),
    });
  });

  test('starts the bridge in development and forwards structured status messages', async () => {
    const child = new FakeChildProcess();
    const onMessage = vi.fn();
    spawnMock.mockReturnValue(child);
    const { getChannelBridgePort, isChannelBridgeRunning, onBridgeMessage, startChannelBridge } = await import('./channelBridgeApi.js');

    onBridgeMessage(onMessage);
    const startPromise = startChannelBridge(8123);
    child.stdout.write('CHANNEL_BRIDGE_MSG {"type":"status","platforms":[{"platform":"telegram","status":"connected"}]}\n');
    child.stdout.write('CHANNEL_BRIDGE_MSG {"type":"ready","port":9012}\n');
    await expect(startPromise).resolves.toBeUndefined();

    expect(spawnMock).toHaveBeenCalledWith(
      'bun',
      ['run', expect.stringContaining(path.join('src', 'channel-bridge', 'index.ts'))],
      expect.objectContaining({
        cwd: process.cwd(),
        env: expect.objectContaining({
          XPDITE_USER_DATA_DIR: path.join(process.cwd(), 'user_data'),
          PYTHON_SERVER_PORT: '8123',
          BRIDGE_PORT: '9000',
        }),
      }),
    );
    expect(onMessage).toHaveBeenCalledWith({
      type: 'status',
      platforms: [{ platform: 'telegram', status: 'connected' }],
    });
    expect(getChannelBridgePort()).toBe(9012);
    expect(isChannelBridgeRunning()).toBe(true);

    child.emit('close', 0);
    expect(isChannelBridgeRunning()).toBe(false);
  });

  test('falls back to the compiled development bundle when the TypeScript entrypoint is missing', async () => {
    const child = new FakeChildProcess();
    spawnMock.mockReturnValue(child);
    existsSyncMock.mockImplementation((value: string) => (
      value.includes(path.join('dist-channel-bridge', 'index.js'))
    ));
    const { startChannelBridge } = await import('./channelBridgeApi.js');

    const startPromise = startChannelBridge(8005);
    child.stdout.write('CHANNEL_BRIDGE_MSG {"type":"ready"}\n');
    await expect(startPromise).resolves.toBeUndefined();

    expect(spawnMock).toHaveBeenCalledWith(
      'node',
      [expect.stringContaining(path.join('dist-channel-bridge', 'index.js'))],
      expect.any(Object),
    );
  });

  test('uses fork with the bundled script in production builds', async () => {
    const child = new FakeChildProcess();
    forkMock.mockReturnValue(child);
    isDevMock.mockReturnValue(false);
    existsSyncMock.mockImplementation((value: string) => (
      value.includes(path.join('channel-bridge', 'index.js'))
    ));
    const { startChannelBridge } = await import('./channelBridgeApi.js');

    const startPromise = startChannelBridge(8009);
    child.stdout.write('CHANNEL_BRIDGE_MSG {"type":"ready","port":9055}\n');
    await expect(startPromise).resolves.toBeUndefined();

    expect(forkMock).toHaveBeenCalledWith(
      expect.stringContaining(path.join('channel-bridge', 'index.js')),
      [],
      expect.objectContaining({
        stdio: ['pipe', 'pipe', 'pipe', 'ipc'],
        env: expect.objectContaining({
          XPDITE_USER_DATA_DIR: 'C:/Users/tester/AppData/Roaming/Xpdite',
          PYTHON_SERVER_PORT: '8009',
          BRIDGE_PORT: '9000',
        }),
      }),
    );
  });

  test('returns an empty status list when the bridge status endpoint is unavailable', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('offline'));
    const { getChannelBridgeStatus } = await import('./channelBridgeApi.js');

    await expect(getChannelBridgeStatus()).resolves.toEqual({ platforms: [] });
  });

  test('throws when outbound delivery fails', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      text: () => Promise.resolve('bridge offline'),
    } as Response);
    const { sendToChannelBridge } = await import('./channelBridgeApi.js');

    await expect(
      sendToChannelBridge('telegram', 'user-1', 'hello', 'final_response'),
    ).rejects.toThrow('Channel Bridge send failed: bridge offline');
  });

  test('stops the bridge process gracefully', async () => {
    const child = new FakeChildProcess();
    spawnMock.mockReturnValue(child);
    const { startChannelBridge, stopChannelBridge } = await import('./channelBridgeApi.js');

    const startPromise = startChannelBridge(8006);
    child.stdout.write('CHANNEL_BRIDGE_MSG {"type":"ready"}\n');
    await startPromise;

    const stopPromise = stopChannelBridge();
    await new Promise((resolve) => setTimeout(resolve, 1100));
    await expect(stopPromise).resolves.toBeUndefined();
    expect(child.kill).toHaveBeenCalledWith('SIGTERM');
  });
});
