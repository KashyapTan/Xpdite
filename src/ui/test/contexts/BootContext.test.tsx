import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import type { BootState } from '../../contexts/BootContext';
import { BootProvider, useBootContext } from '../../contexts/BootContext';

const originalFetch = global.fetch;
const originalElectronAPI = window.electronAPI;

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <BootProvider>{children}</BootProvider>
);

function createElectronApiMock(overrides?: Partial<NonNullable<Window['electronAPI']>>) {
  return {
    focusWindow: vi.fn().mockResolvedValue(undefined),
    setMiniMode: vi.fn().mockResolvedValue(undefined),
    getServerPort: vi.fn().mockResolvedValue(8000),
    getBootState: vi.fn().mockResolvedValue({
      phase: 'starting',
      message: 'Launching local services',
      progress: 5,
    }),
    onBootState: vi.fn().mockReturnValue(() => {}),
    retryBoot: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } satisfies NonNullable<Window['electronAPI']>;
}

describe('BootContext', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    delete window.electronAPI;
    global.fetch = vi.fn().mockRejectedValue(new Error('not available')) as unknown as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    window.electronAPI = originalElectronAPI;
    vi.useRealTimers();
  });

  test('returns default values outside provider', () => {
    const { result } = renderHook(() => useBootContext());

    expect(result.current.isReady).toBe(false);
    expect(result.current.bootState).toEqual({
      phase: 'starting',
      message: 'Launching local services',
      progress: 5,
    });
    expect(typeof result.current.retry).toBe('function');
  });

  test('hydrates from electron boot state and applies IPC updates', async () => {
    let onBootStateHandler: ((state: BootState) => void) | undefined;
    const unsubscribe = vi.fn();

    window.electronAPI = createElectronApiMock({
      getBootState: vi.fn().mockResolvedValue({
        phase: 'launching_backend',
        message: 'Connecting to backend',
        progress: 30,
      }),
      onBootState: vi.fn((callback: (state: BootState) => void) => {
        onBootStateHandler = callback;
        return unsubscribe;
      }),
    });

    const { result, unmount } = renderHook(() => useBootContext(), { wrapper });

    await waitFor(() => {
      expect(result.current.bootState.phase).toBe('launching_backend');
    });

    act(() => {
      onBootStateHandler?.({ phase: 'ready', message: 'Ready', progress: 100 });
    });

    await waitFor(() => {
      expect(result.current.isReady).toBe(true);
      expect(result.current.bootState.phase).toBe('ready');
    });

    unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });

  test('retry transitions to retrying and shows error if electron retry fails', async () => {
    window.electronAPI = createElectronApiMock({
      retryBoot: vi.fn().mockRejectedValue(new Error('IPC disconnected')),
    });

    const { result } = renderHook(() => useBootContext(), { wrapper });

    act(() => {
      result.current.retry();
    });

    expect(result.current.isReady).toBe(false);
    expect(result.current.bootState.message).toBe('Retrying...');

    await waitFor(() => {
      expect(result.current.bootState.phase).toBe('error');
      expect(result.current.bootState.message).toBe('Retry failed');
      expect(result.current.bootState.error).toBe(
        'Could not communicate with the application shell.',
      );
    });
  });

  test('falls back to health polling when electron API is unavailable', async () => {
    const fetchMock = vi.fn().mockImplementation((url: RequestInfo | URL) => {
      const value = String(url);
      if (value.includes(':8003/api/health')) {
        return Promise.resolve({ ok: true } as Response);
      }
      return Promise.reject(new Error('Connection refused'));
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useBootContext(), { wrapper });

    await waitFor(() => {
      expect(result.current.isReady).toBe(true);
      expect(result.current.bootState.phase).toBe('ready');
      expect(result.current.bootState.progress).toBe(100);
    });

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes(':8003/api/health'))).toBe(
      true,
    );
  });

  test('updates boot progress to launching_backend while waiting for health checks', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused')) as unknown as typeof fetch;

    const { result } = renderHook(() => useBootContext(), { wrapper });

    await waitFor(() => {
      expect(result.current.isReady).toBe(false);
      expect(result.current.bootState.phase).toBe('launching_backend');
      expect(result.current.bootState.message).toBe('Connecting to backend...');
      expect(result.current.bootState.progress).toBe(30);
    });
  });
});

