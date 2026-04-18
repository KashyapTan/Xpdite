import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { logPerf } from '../../utils/perfLogger';

describe('logPerf', () => {
  const originalElectronApi = window.electronAPI;

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  afterEach(() => {
    window.electronAPI = originalElectronApi;
  });

  test('logs locally and forwards the message to the Electron perf transport when available', async () => {
    const perfLog = vi.fn().mockResolvedValue(undefined);
    window.electronAPI = {
      ...window.electronAPI,
      perfLog,
    } as typeof window.electronAPI;

    logPerf('boot complete');
    await Promise.resolve();

    expect(console.log).toHaveBeenCalledWith('boot complete');
    expect(perfLog).toHaveBeenCalledWith('boot complete');
  });

  test('swallows transport failures after logging to the console', async () => {
    const perfLog = vi.fn().mockRejectedValue(new Error('transport offline'));
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    window.electronAPI = {
      ...window.electronAPI,
      perfLog,
    } as typeof window.electronAPI;

    logPerf('still log this');
    await Promise.resolve();
    await Promise.resolve();

    expect(console.log).toHaveBeenCalledWith('still log this');
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
