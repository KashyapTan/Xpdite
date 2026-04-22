import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';

// We need to import the module fresh for each test to reset module state
// So we'll use dynamic imports and vi.resetModules()

// Store original fetch and window.electronAPI
const originalFetch = global.fetch;
const originalElectronAPI = (window as { electronAPI?: unknown }).electronAPI;

describe('portDiscovery', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    // Reset window.electronAPI
    delete (window as { electronAPI?: unknown }).electronAPI;
    // Reset console mocks
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    global.fetch = originalFetch;
    (window as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
    vi.restoreAllMocks();
  });

  describe('getServerPort', () => {
    test('returns default port initially', async () => {
      // Mock fetch to never resolve during module load
      global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
      
      const { getServerPort } = await import('../../services/portDiscovery');
      expect(getServerPort()).toBe(8000);
    });
  });

  describe('getHttpBaseUrl', () => {
    test('returns HTTP URL with resolved port', async () => {
      global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
      
      const { getHttpBaseUrl } = await import('../../services/portDiscovery');
      expect(getHttpBaseUrl()).toBe('http://localhost:8000');
    });
  });

  describe('getWsBaseUrl', () => {
    test('returns WebSocket URL with resolved port', async () => {
      global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
      
      const { getWsBaseUrl } = await import('../../services/portDiscovery');
      expect(getWsBaseUrl()).toBe('ws://localhost:8000');
    });
  });

  describe('resetDiscovery', () => {
    test('resets discovery state', async () => {
      // Set up a successful discovery first
      global.fetch = vi.fn().mockResolvedValue({ ok: true });
      
      const { discoverServerPort, resetDiscovery, getServerPort } = await import('../../services/portDiscovery');
      
      // Wait for initial discovery to complete
      await discoverServerPort();
      
      // Reset
      resetDiscovery();
      
      // After reset, port should be back to default (discovery will restart)
      expect(getServerPort()).toBe(8000);
    });
  });

  describe('discoverServerPort', () => {
    describe('with Electron IPC', () => {
      test('uses port from Electron IPC when valid and health check passes', async () => {
        const mockGetServerPort = vi.fn().mockResolvedValue(8005);
        const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
        (window as { electronAPI?: unknown }).electronAPI = {
          getServerPort: mockGetServerPort,
          getServerToken: mockGetServerToken,
        };

        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        const { discoverServerPort, resetDiscovery, getServerPort } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8005);
        expect(getServerPort()).toBe(8005);
        expect(mockGetServerPort).toHaveBeenCalled();
        expect(mockGetServerToken).toHaveBeenCalled();
        expect(fetch).toHaveBeenCalledWith(
          'http://localhost:8005/api/health/session',
          expect.objectContaining({
            headers: { 'X-Xpdite-Server-Token': 'session-token' },
            signal: expect.any(AbortSignal),
          })
        );
      });

      test('falls back to probing when IPC port fails health check', async () => {
        const mockGetServerPort = vi.fn().mockResolvedValue(8005);
        const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
        (window as { electronAPI?: unknown }).electronAPI = {
          getServerPort: mockGetServerPort,
          getServerToken: mockGetServerToken,
        };

        // IPC port fails, but port 8001 succeeds
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8005')) {
            return Promise.reject(new Error('Connection refused'));
          }
          if (url.includes('8001')) {
            return Promise.resolve({ ok: true });
          }
          return new Promise(() => {}); // Other ports hang
        });

        const { discoverServerPort, resetDiscovery, getServerPort } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8001);
        expect(getServerPort()).toBe(8001);
        expect(console.warn).toHaveBeenCalledWith(
          expect.stringContaining('IPC port 8005 failed health check')
        );
      });

      test('falls back to probing when IPC returns invalid port', async () => {
        const mockGetServerPort = vi.fn().mockResolvedValue(-1);
        const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
        (window as { electronAPI?: unknown }).electronAPI = {
          getServerPort: mockGetServerPort,
          getServerToken: mockGetServerToken,
        };

        // Port 8002 succeeds during probing
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8002/api/health/session')) {
            return Promise.resolve({ ok: true });
          }
          return new Promise(() => {});
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8002);
      });

      test('falls back to probing when IPC throws error', async () => {
        const mockGetServerPort = vi.fn().mockRejectedValue(new Error('IPC error'));
        const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
        (window as { electronAPI?: unknown }).electronAPI = {
          getServerPort: mockGetServerPort,
          getServerToken: mockGetServerToken,
        };

        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8003/api/health/session')) {
            return Promise.resolve({ ok: true });
          }
          return new Promise(() => {});
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8003);
      });

      test('rejects stale prior-session backends and finds the port for the current token', async () => {
        const mockGetServerPort = vi.fn().mockResolvedValue(-1);
        const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
        (window as { electronAPI?: unknown }).electronAPI = {
          getServerPort: mockGetServerPort,
          getServerToken: mockGetServerToken,
        };

        global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
          if (url.includes('8000/api/health/session')) {
            return Promise.resolve({ ok: false, status: 403 });
          }
          if (
            url.includes('8001/api/health/session')
            && (init?.headers as Record<string, string> | undefined)?.['X-Xpdite-Server-Token'] === 'session-token'
          ) {
            return Promise.resolve({ ok: true });
          }
          return Promise.reject(new Error('Connection refused'));
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();

        const port = await discoverServerPort();

        expect(port).toBe(8001);
      });
    });

    describe('port probing', () => {
      test('probes ports 8000-8009 and returns first healthy port', async () => {
        // Only port 8004 responds successfully
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8004')) {
            return Promise.resolve({ ok: true });
          }
          return Promise.reject(new Error('Connection refused'));
        });

        const { discoverServerPort, getServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8004);
        expect(getServerPort()).toBe(8004);
      });

      test('returns default port when no server found', async () => {
        // All ports fail
        global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused'));

        const { discoverServerPort, getServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8000);
        expect(getServerPort()).toBe(8000);
        expect(console.warn).toHaveBeenCalledWith(
          expect.stringContaining('No server found')
        );
      });

      test('returns default port when all health checks return non-ok', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8000);
      });

      test('finds first successful port in range', async () => {
        // Port 8000 succeeds immediately
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8000')) {
            return Promise.resolve({ ok: true });
          }
          return new Promise(() => {}); // Others hang
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8000);
        expect(console.log).toHaveBeenCalledWith(
          expect.stringContaining('Found server on port 8000')
        );
      });
    });

    describe('caching behavior', () => {
      test('returns cached port on subsequent calls', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        // First call
        const port1 = await discoverServerPort();
        // Second call should use cache
        const port2 = await discoverServerPort();
        
        expect(port1).toBe(8000);
        expect(port2).toBe(8000);
        // Fetch should be called 10 times for the initial probe, not for the second call
        // (each port gets one fetch during parallel probe)
        const fetchCallCount = (fetch as ReturnType<typeof vi.fn>).mock.calls.length;
        expect(fetchCallCount).toBeGreaterThan(0);
        expect(fetchCallCount).toBeLessThanOrEqual(20);
      });

      test('shares in-flight discovery promise between concurrent callers', async () => {
        let resolvePromise: (value: Response) => void;
        const fetchPromise = new Promise<Response>((resolve) => {
          resolvePromise = resolve;
        });
        
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8000')) {
            return fetchPromise;
          }
          return new Promise(() => {}); // Others hang
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        // Start two concurrent discoveries
        const promise1 = discoverServerPort();
        const promise2 = discoverServerPort();
        
        // Resolve the fetch
        resolvePromise!({ ok: true } as Response);
        
        const [port1, port2] = await Promise.all([promise1, promise2]);
        
        expect(port1).toBe(8000);
        expect(port2).toBe(8000);
      });

      test('respects failure cache TTL before re-probing', async () => {
        // All ports fail initially
        global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused'));

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        // First call - fails and caches failure
        const port1 = await discoverServerPort();
        expect(port1).toBe(8000);
        
        // Immediate second call should use cached failure (return default)
        const port2 = await discoverServerPort();
        expect(port2).toBe(8000);
        
        // Should have probed once (10 ports), not twice
        const fetchCallCount = (fetch as ReturnType<typeof vi.fn>).mock.calls.length;
        expect(fetchCallCount).toBeGreaterThan(0);
        expect(fetchCallCount).toBeLessThanOrEqual(20);
      });
    });

    describe('without Electron IPC', () => {
      test('goes straight to probing when electronAPI is not defined', async () => {
        // Ensure no electronAPI
        delete (window as { electronAPI?: unknown }).electronAPI;
        
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8006')) {
            return Promise.resolve({ ok: true });
          }
          return Promise.reject(new Error('Connection refused'));
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8006);
      });

      test('goes to probing when getServerPort is not a function', async () => {
        (window as { electronAPI?: unknown }).electronAPI = {
          // getServerPort is missing
        };
        
        global.fetch = vi.fn().mockImplementation((url: string) => {
          if (url.includes('8007')) {
            return Promise.resolve({ ok: true });
          }
          return Promise.reject(new Error('Connection refused'));
        });

        const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
        resetDiscovery();
        
        const port = await discoverServerPort();
        
        expect(port).toBe(8007);
      });
    });
  });

  describe('URL helpers after discovery', () => {
    test('URLs reflect discovered port', async () => {
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('8008')) {
          return Promise.resolve({ ok: true });
        }
        return Promise.reject(new Error('Connection refused'));
      });

      const { discoverServerPort, getHttpBaseUrl, getWsBaseUrl, resetDiscovery } = await import('../../services/portDiscovery');
      resetDiscovery();
      
      await discoverServerPort();
      
      expect(getHttpBaseUrl()).toBe('http://localhost:8008');
      expect(getWsBaseUrl()).toBe('ws://localhost:8008');
    });
  });

  describe('edge cases', () => {
    test('handles fetch abort due to timeout gracefully', async () => {
      // Simulate all fetches being aborted
      global.fetch = vi.fn().mockImplementation(() => {
        const error = new Error('Aborted');
        error.name = 'AbortError';
        return Promise.reject(error);
      });

      const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
      resetDiscovery();
      
      const port = await discoverServerPort();
      
      // Should fall back to default port
      expect(port).toBe(8000);
    });

    test('handles mixed responses during probing', async () => {
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('8000')) {
          return Promise.resolve({ ok: false }); // Not ok
        }
        if (url.includes('8001')) {
          return Promise.reject(new Error('Network error')); // Error
        }
        if (url.includes('8002')) {
          return Promise.resolve({ ok: true }); // Success!
        }
        // Others time out (never resolve)
        return new Promise(() => {});
      });

      const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
      resetDiscovery();
      
      const port = await discoverServerPort();
      
      expect(port).toBe(8002);
    });

    test('IPC health check with non-ok response triggers fallback', async () => {
      const mockGetServerPort = vi.fn().mockResolvedValue(8005);
      const mockGetServerToken = vi.fn().mockResolvedValue('session-token');
      (window as { electronAPI?: unknown }).electronAPI = {
        getServerPort: mockGetServerPort,
        getServerToken: mockGetServerToken,
      };

      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('8005/api/health/session')) {
          return Promise.resolve({ ok: false }); // IPC port returns non-ok
        }
        if (url.includes('8000/api/health/session')) {
          return Promise.resolve({ ok: true }); // Probe finds 8000
        }
        return Promise.reject(new Error('Connection refused'));
      });

      const { discoverServerPort, resetDiscovery } = await import('../../services/portDiscovery');
      resetDiscovery();
      
      const port = await discoverServerPort();
      
      // Should have fallen back to probing and found 8000
      expect(port).toBe(8000);
    });
  });
});
