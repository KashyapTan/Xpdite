/**
 * Port Discovery Service.
 *
 * The Python backend uses `find_available_port()` to bind to the first free
 * port in the range 8000–8009.  In production Electron asks the main process
 * (which parses the server's stdout) for the port via IPC.  In dev mode
 * (or if IPC isn't available) we fall back to probing the range with a
 * lightweight health request. In packaged Electron we use the per-launch
 * server token so stale leftover backends from prior runs are rejected.
 *
 * Usage:
 *   import { discoverServerPort, getHttpBaseUrl, getWsBaseUrl } from './portDiscovery';
 *
 *   // At startup (call once, e.g. in WebSocketProvider):
 *   await discoverServerPort();
 *
 *   // Then anywhere:
 *   fetch(`${getHttpBaseUrl()}/api/models/ollama`);
 *   new WebSocket(`${getWsBaseUrl()}/ws`);
 */

const DEFAULT_PORT = 8000;
const MAX_PORT = 8009;
const PROBE_TIMEOUT_MS = 800;
/** How long (ms) to cache a "server not found" result before re-probing. */
const FAILURE_CACHE_TTL_MS = 3000;

let resolvedPort: number = DEFAULT_PORT;
let discoveryDone = false;
/** Timestamp of the last failed discovery attempt (0 = never failed). */
let lastFailureTs = 0;

/** Discovery promise so concurrent callers share the same in-flight probe. */
let discoveryPromise: Promise<number> | null = null;

/**
 * Discover which port the Python backend is listening on.
 *
 * 1. Tries the Electron IPC channel (`getServerPort`) — instant in production.
 * 2. Falls back to probing ports 8000–8009 via a lightweight health request.
 * 3. Caches the result so subsequent calls are free.
 */
export async function discoverServerPort(): Promise<number> {
    if (discoveryDone) return resolvedPort;

    // If discovery recently failed, avoid hammering all 10 ports on every call.
    if (lastFailureTs > 0 && Date.now() - lastFailureTs < FAILURE_CACHE_TTL_MS) {
        return DEFAULT_PORT;
    }

    if (discoveryPromise) return discoveryPromise;

    discoveryPromise = _discover();
    const port = await discoveryPromise;
    discoveryPromise = null;
    return port;
}

async function _discover(): Promise<number> {
    const probeConfig = await getHealthProbeConfig();

    // ---- Electron IPC (production) ----
    // In dev mode the main process doesn't start Python, so detectedPort
    // stays at the default 8000 which may be occupied by another app.
    // Always validate the IPC-provided port with a quick health check.
    try {
        const electronAPI = window.electronAPI;
        if (electronAPI?.getServerPort) {
            const port = await electronAPI.getServerPort();
            if (typeof port === 'number' && port > 0) {
                // Verify the port actually has our server
                try {
                    const res = await probePort(port, probeConfig);
                    if (res.ok) {
                        resolvedPort = port;
                        discoveryDone = true;
                        console.log(`[PortDiscovery] Verified port from Electron IPC: ${port}`);
                        return port;
                    }
                } catch {
                    console.warn(`[PortDiscovery] IPC port ${port} failed health check, falling back to probe`);
                }
            }
        }
    } catch {
        // Not in Electron or IPC not available — fall through to probing.
    }

    // ---- Probe ports concurrently ----
    const ports = Array.from({ length: MAX_PORT - DEFAULT_PORT + 1 }, (_, i) => DEFAULT_PORT + i);

    // Race all probes — first successful health check wins.
    const controllers: AbortController[] = [];
    const result = await new Promise<number | null>((resolve) => {
        let settled = false;
        let pending = ports.length;

        for (const port of ports) {
            const controller = new AbortController();
            controllers.push(controller);

            probePort(port, probeConfig, controller)
                .then((res) => {
                    if (res.ok && !settled) {
                        settled = true;
                        resolve(port);
                        // Abort remaining probes
                        controllers.forEach(c => c.abort());
                    } else {
                        if (--pending === 0 && !settled) resolve(null);
                    }
                })
                .catch(() => {
                    if (--pending === 0 && !settled) resolve(null);
                });
        }
    });

    if (result !== null) {
        resolvedPort = result;
        discoveryDone = true;
        console.log(`[PortDiscovery] Found server on port ${result}`);
        return result;
    }

    // Server not yet up — cache the failure so we don't re-probe immediately.
    // WebSocketContext's reconnect loop will retry after its back-off timer.
    lastFailureTs = Date.now();
    console.warn('[PortDiscovery] No server found, using default port');
    return DEFAULT_PORT;
}

const HEALTHCHECK_PATH = '/api/health';
const SESSION_HEALTHCHECK_PATH = '/api/health/session';
const SERVER_TOKEN_HEADER = 'X-Xpdite-Server-Token';

type HealthProbeConfig = {
    headers?: HeadersInit;
    path: string;
};

async function getHealthProbeConfig(): Promise<HealthProbeConfig> {
    const electronAPI = window.electronAPI;
    if (!electronAPI?.getServerToken) {
        return { path: HEALTHCHECK_PATH };
    }

    try {
        const token = await electronAPI.getServerToken();
        if (typeof token === 'string' && token.trim()) {
            return {
                path: SESSION_HEALTHCHECK_PATH,
                headers: { [SERVER_TOKEN_HEADER]: token.trim() },
            };
        }
    } catch {
        console.warn('[PortDiscovery] Failed to fetch server token, using public health probe');
    }

    return { path: HEALTHCHECK_PATH };
}

async function probePort(
    port: number,
    probeConfig: HealthProbeConfig,
    controller = new AbortController(),
): Promise<Response> {
    const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    try {
        return await fetch(`http://localhost:${port}${probeConfig.path}`, {
            headers: probeConfig.headers,
            signal: controller.signal,
        });
    } finally {
        clearTimeout(timeout);
    }
}

/** Reset discovery state (useful when the server restarts on a new port). */
export function resetDiscovery(): void {
    discoveryDone = false;
    discoveryPromise = null;
    resolvedPort = DEFAULT_PORT;
    lastFailureTs = 0;
}

/** Current resolved port (default 8000 until discovery completes). */
export function getServerPort(): number {
    return resolvedPort;
}

/** HTTP base URL derived from the resolved port. */
export function getHttpBaseUrl(): string {
    return `http://localhost:${resolvedPort}`;
}

/** WebSocket base URL derived from the resolved port. */
export function getWsBaseUrl(): string {
    return `ws://localhost:${resolvedPort}`;
}

// Kick off discovery eagerly at module load time so that by the time
// any component calls `discoverServerPort()`, the probe is already in
// flight (or done).  The returned promise is intentionally not awaited.
discoverServerPort();
