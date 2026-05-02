import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

export interface BootState {
  phase: 'starting' | 'launching_backend' | 'connecting_tools' | 'loading_interface' | 'ready' | 'error';
  message: string;
  progress: number;
  error?: string;
}

const DEFAULT_BOOT_STATE: BootState = {
  phase: 'starting',
  message: 'Launching local services',
  progress: 5,
};

const DEV_HEALTH_PORTS = [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009];
const DEV_HEALTH_TIMEOUT_MS = 800;

interface BootContextValue {
  bootState: BootState;
  isReady: boolean;
  retry: () => void;
}

const BootContext = createContext<BootContextValue>({
  bootState: DEFAULT_BOOT_STATE,
  isReady: false,
  retry: () => {},
});

// eslint-disable-next-line react-refresh/only-export-components
export const useBootContext = () => useContext(BootContext);

export const BootProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [bootState, setBootState] = useState<BootState>(DEFAULT_BOOT_STATE);
  const [isReady, setIsReady] = useState(false);
  const hasReceivedReady = useRef(false);

  const handleBootState = useCallback((state: BootState) => {
    setBootState(state);
    if (state.phase === 'ready' && !hasReceivedReady.current) {
      hasReceivedReady.current = true;
      setIsReady(true);
    }
  }, []);

  const retry = useCallback(() => {
    hasReceivedReady.current = false;
    setIsReady(false);
    setBootState({
      phase: 'starting',
      message: 'Retrying...',
      progress: 5,
    });
    if (window.electronAPI?.retryBoot) {
      window.electronAPI.retryBoot().catch(() => {
        setBootState({
          phase: 'error',
          message: 'Retry failed',
          progress: 0,
          error: 'Could not communicate with the application shell.',
        });
      });
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    // If running inside Electron, listen for IPC boot state updates
    if (window.electronAPI?.onBootState) {
      const unsubscribe = window.electronAPI.onBootState(handleBootState);
      // Get initial state
      if (window.electronAPI.getBootState) {
        window.electronAPI.getBootState().then((state) => {
          if (!isMounted) return;
          handleBootState(state);
        }).catch(() => {
          if (!isMounted) return;
          setBootState({
            phase: 'error',
            message: 'Boot state unavailable',
            progress: 0,
            error: 'Could not read startup state from the application shell.',
          });
        });
      }
      return () => {
        isMounted = false;
        unsubscribe();
      };
    }

    // Fallback for dev mode (no Electron) or browser: poll health endpoint
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const activeControllers = new Set<AbortController>();

    const probeHealth = async (port: number): Promise<boolean> => {
      const controller = new AbortController();
      activeControllers.add(controller);
      const tid = setTimeout(() => controller.abort(), DEV_HEALTH_TIMEOUT_MS);
      try {
        const res = await fetch(`http://localhost:${port}/api/health`, {
          signal: controller.signal,
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        clearTimeout(tid);
        activeControllers.delete(controller);
      }
    };

    const findHealthyDevBackend = async (): Promise<boolean> => {
      let resolved = false;
      let pending = DEV_HEALTH_PORTS.length;

      return new Promise((resolve) => {
        DEV_HEALTH_PORTS.forEach((port) => {
          void probeHealth(port).then((healthy) => {
            if (cancelled) {
              if (!resolved) {
                resolved = true;
                resolve(false);
              }
              return;
            }
            if (resolved) return;
            if (healthy) {
              resolved = true;
              activeControllers.forEach((controller) => controller.abort());
              resolve(true);
              return;
            }

            pending -= 1;
            if (pending === 0) {
              resolved = true;
              resolve(false);
            }
          });
        });
      });
    };

    const pollHealth = async () => {
      if (cancelled || hasReceivedReady.current) return;

      if (await findHealthyDevBackend()) {
        if (!cancelled) {
          handleBootState({ phase: 'ready', message: 'Ready', progress: 100 });
        }
        return;
      }

      // Update progress display while waiting
      setBootState(prev => {
        if (prev.phase === 'starting') {
          return { phase: 'launching_backend', message: 'Connecting to backend...', progress: 30 };
        }
        return prev;
      });

      if (!cancelled) {
        timeoutId = setTimeout(pollHealth, 1500);
      }
    };

    pollHealth();
    return () => {
      cancelled = true;
      isMounted = false;
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
    };
  }, [handleBootState]);

  return (
    <BootContext.Provider value={{ bootState, isReady, retry }}>
      {children}
    </BootContext.Provider>
  );
};
