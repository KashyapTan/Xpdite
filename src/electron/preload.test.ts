// @vitest-environment node

import { beforeEach, describe, expect, test, vi } from 'vitest';

const exposeInMainWorldMock = vi.fn();
const invokeMock = vi.fn();
const onMock = vi.fn();
const removeListenerMock = vi.fn();

vi.mock('electron', () => ({
  contextBridge: {
    exposeInMainWorld: exposeInMainWorldMock,
  },
  ipcRenderer: {
    invoke: invokeMock,
    on: onMock,
    removeListener: removeListenerMock,
  },
}));

describe('preload bridge', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  test('exposes the renderer IPC bridge and wires each IPC helper', async () => {
    await import('./preload.js');

    expect(exposeInMainWorldMock).toHaveBeenCalledTimes(1);
    const [key, api] = exposeInMainWorldMock.mock.calls[0] as [
      string,
      Record<string, (...args: unknown[]) => unknown>,
    ];

    expect(key).toBe('electronAPI');

    await api.setMiniMode(true);
    await api.focusWindow();
    await api.getServerPort();
    await api.getServerToken();
    await api.getBootState();
    await api.retryBoot();
    await api.perfLog('boot complete');
    await api.getChannelBridgePort();
    await api.getChannelBridgeStatus();
    expect(invokeMock).toHaveBeenCalledWith('set-mini-mode', true);
    expect(invokeMock).toHaveBeenCalledWith('focus-window');
    expect(invokeMock).toHaveBeenCalledWith('get-server-port');
    expect(invokeMock).toHaveBeenCalledWith('get-server-token');
    expect(invokeMock).toHaveBeenCalledWith('get-boot-state');
    expect(invokeMock).toHaveBeenCalledWith('retry-boot');
    expect(invokeMock).toHaveBeenCalledWith('perf-log', 'boot complete');
    expect(invokeMock).toHaveBeenCalledWith('get-channel-bridge-port');
    expect(invokeMock).toHaveBeenCalledWith('get-channel-bridge-status');

    const callback = vi.fn();
    const unsubscribe = api.onBootState(callback) as () => void;
    expect(onMock).toHaveBeenCalledWith('boot-state', expect.any(Function));
    const bootStateHandler = onMock.mock.calls.find(([channel]) => channel === 'boot-state')?.[1] as ((event: unknown, state: unknown) => void);
    bootStateHandler({}, { phase: 'ready' });
    expect(callback).toHaveBeenCalledWith({ phase: 'ready' });

    unsubscribe();
    expect(removeListenerMock).toHaveBeenCalledWith('boot-state', expect.any(Function));

    const onChannelBridgeStatus = vi.fn();
    const unsubscribeBridge = api.onChannelBridgeStatus(onChannelBridgeStatus) as () => void;
    expect(onMock).toHaveBeenCalledWith('channel-bridge-status', expect.any(Function));
    const bridgeHandler = onMock.mock.calls.find(([channel]) => channel === 'channel-bridge-status')?.[1] as ((event: unknown, platforms: unknown) => void);
    bridgeHandler({}, [{ platform: 'telegram', status: 'connected' }]);
    expect(onChannelBridgeStatus).toHaveBeenCalledWith([{ platform: 'telegram', status: 'connected' }]);
    unsubscribeBridge();
    expect(removeListenerMock).toHaveBeenCalledWith('channel-bridge-status', expect.any(Function));

    const onPairingCode = vi.fn();
    const unsubscribePairingCode = api.onWhatsAppPairingCode(onPairingCode) as () => void;
    expect(onMock).toHaveBeenCalledWith('whatsapp-pairing-code', expect.any(Function));
    const pairingHandler = onMock.mock.calls.find(([channel]) => channel === 'whatsapp-pairing-code')?.[1] as ((event: unknown, code: string) => void);
    pairingHandler({}, '123-456');
    expect(onPairingCode).toHaveBeenCalledWith('123-456');
    unsubscribePairingCode();
    expect(removeListenerMock).toHaveBeenCalledWith('whatsapp-pairing-code', expect.any(Function));
  });
});
