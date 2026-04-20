import { app, BrowserWindow, ipcMain, session, type IpcMainInvokeEvent } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import { isDev } from './utils.js';
import { startPythonServer, stopPythonServer, getServerPort, getServerToken, onBootMarker } from './pythonApi.js';
import { 
    startChannelBridge, 
    stopChannelBridge, 
    getChannelBridgePort, 
    getChannelBridgeStatus,
    onBridgeMessage 
} from './channelBridgeApi.js';
import { createBootShellDataUrl } from './bootShellHtml.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: BrowserWindow | null = null;
const DEFAULT_WINDOW_BOUNDS = { width: 420, height: 420 };
let normalBounds = { ...DEFAULT_WINDOW_BOUNDS, x: 100, y: 100 };
const DEV_RENDERER_URL = 'http://127.0.0.1:5123';
const bootProfileEnabled = process.env.XPDITE_BOOT_PROFILE === '1';
const bootProfileStartedAt = Date.now();
const DEV_RENDERER_SHELL_PROBE_URLS = [
    `${DEV_RENDERER_URL}/@vite/client`,
    `${DEV_RENDERER_URL}/src/ui/main.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/Layout.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/boot/BootScreen.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/MobilePlatformBadge.tsx`,
    `${DEV_RENDERER_URL}/src/ui/contexts/BootContext.tsx`,
    `${DEV_RENDERER_URL}/src/ui/contexts/TabContext.tsx`,
    `${DEV_RENDERER_URL}/src/ui/contexts/WebSocketContext.tsx`,
    `${DEV_RENDERER_URL}/src/ui/hooks/useChatState.ts`,
    `${DEV_RENDERER_URL}/src/ui/hooks/useScreenshots.ts`,
    `${DEV_RENDERER_URL}/src/ui/hooks/useTokenUsage.ts`,
    `${DEV_RENDERER_URL}/src/ui/services/portDiscovery.ts`,
    `${DEV_RENDERER_URL}/src/ui/utils/modelDisplay.ts`,
    `${DEV_RENDERER_URL}/src/ui/utils/providerLogos.ts`,
    `${DEV_RENDERER_URL}/src/ui/utils/renderableContentBlocks.ts`,
    `${DEV_RENDERER_URL}/src/ui/pages/App.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/TitleBar.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/TabBar.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/chat/ResponseArea.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/chat/LoadingDots.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/icons/AppIcons.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/icons/ProviderLogos.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/icons/iconPaths.ts`,
    `${DEV_RENDERER_URL}/src/ui/components/input/QueryInput.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/input/QueueDropdown.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/input/ModeSelector.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/input/TokenUsagePopup.tsx`,
    `${DEV_RENDERER_URL}/src/ui/components/input/ScreenshotChips.tsx`,
    DEV_RENDERER_URL,
];
const PERF_LOG_MAX_CHARS = 2000;
const PERF_LOG_WINDOW_MS = 1500;
const PERF_LOG_MAX_PER_WINDOW = 140;
const PERF_LOG_MUTE_MS = 2500;

type PerfLogRateState = {
    windowStartedAt: number;
    countInWindow: number;
    mutedUntil: number;
    lastMessage: string;
    lastAt: number;
};

const perfLogRateStateBySender = new Map<number, PerfLogRateState>();

function isTrustedPerfLogSender(event: IpcMainInvokeEvent): boolean {
    const senderUrl = event.senderFrame?.url ?? event.sender.getURL();

    if (isDev()) {
        return senderUrl.startsWith(DEV_RENDERER_URL);
    }

    return senderUrl.startsWith('file://');
}

function isTrustedIpcSender(event: IpcMainInvokeEvent): boolean {
    return isTrustedPerfLogSender(event);
}

function shouldDropPerfLog(senderId: number, safeMessage: string): boolean {
    const now = Date.now();
    const existing = perfLogRateStateBySender.get(senderId);
    const state: PerfLogRateState = existing ?? {
        windowStartedAt: now,
        countInWindow: 0,
        mutedUntil: 0,
        lastMessage: '',
        lastAt: 0,
    };

    if (state.mutedUntil > now) {
        perfLogRateStateBySender.set(senderId, state);
        return true;
    }

    if (now - state.windowStartedAt >= PERF_LOG_WINDOW_MS) {
        state.windowStartedAt = now;
        state.countInWindow = 0;
    }

    state.countInWindow += 1;
    if (state.countInWindow > PERF_LOG_MAX_PER_WINDOW) {
        state.mutedUntil = now + PERF_LOG_MUTE_MS;
        perfLogRateStateBySender.set(senderId, state);
        return true;
    }

    const duplicateBurst = state.lastMessage === safeMessage && now - state.lastAt < 60;
    state.lastMessage = safeMessage;
    state.lastAt = now;
    perfLogRateStateBySender.set(senderId, state);
    return duplicateBurst;
}

function sanitizePerfLogMessage(input: string): string {
    let normalized = '';

    for (let index = 0; index < input.length; index += 1) {
        const char = input[index];
        const code = input.charCodeAt(index);

        if (char === '\n' || char === '\r' || char === '\t') {
            normalized += ' ';
        } else if (code >= 0x20 && code !== 0x7f) {
            normalized += char;
        }

        if (normalized.length >= PERF_LOG_MAX_CHARS) {
            break;
        }
    }

    return normalized;
}

function bootProfile(event: string, details: Record<string, unknown> = {}) {
    if (!bootProfileEnabled) {
        return;
    }

    console.log(`XPDITE_ELECTRON_BOOT ${JSON.stringify({
        event,
        elapsed_ms: Date.now() - bootProfileStartedAt,
        ...details,
    })}`);
}

// ── Boot State Management ──────────────────────────────────────────
interface BootState {
    phase: 'starting' | 'launching_backend' | 'connecting_tools' | 'loading_interface' | 'ready' | 'error';
    message: string;
    progress: number;
    error?: string;
}

let currentBootState: BootState = {
    phase: 'starting',
    message: 'Launching local services',
    progress: 5,
};
let channelBridgeStarted = false;
let channelBridgeStartupPromise: Promise<void> | null = null;

function publishBootState(state: BootState) {
    currentBootState = state;
    bootProfile('boot_state', {
        phase: state.phase,
        progress: state.progress,
        message: state.message,
        error: state.error,
    });
    mainWindow?.webContents?.send('boot-state', state);
}

function startChannelBridgeInBackground() {
    if (channelBridgeStarted || channelBridgeStartupPromise) {
        return;
    }

    bootProfile('channel_bridge_start');
    channelBridgeStartupPromise = startChannelBridge(getServerPort())
        .then(() => {
            channelBridgeStarted = true;
            bootProfile('channel_bridge_ready', {
                port: getChannelBridgePort(),
            });
        })
        .catch((error) => {
            const message = error instanceof Error ? error.message : String(error);
            console.warn('Channel Bridge failed to start (non-fatal):', error);
            bootProfile('channel_bridge_error', { message });
        })
        .finally(() => {
            channelBridgeStartupPromise = null;
        });
}

/** Map Python XPDITE_BOOT markers to user-friendly boot state. */
function mapBootMarker(marker: { phase: string; message: string; progress: number }) {
    const phaseMap: Record<string, BootState['phase']> = {
        loading_runtime: 'launching_backend',
        initializing_mcp: 'connecting_tools',
        starting_http: 'connecting_tools',
        ready: 'ready',
    };
    publishBootState({
        phase: phaseMap[marker.phase] || 'launching_backend',
        message: marker.message,
        progress: marker.progress,
    });
}

let bootInProgress = false;

/** Start the Python backend and publish boot state as it progresses. */
async function bootBackend(): Promise<boolean> {
    if (bootInProgress) return false;
    bootInProgress = true;

    publishBootState({ phase: 'launching_backend', message: 'Loading AI runtime...', progress: 10 });

    // Listen for structured boot markers from Python stdout
    onBootMarker(mapBootMarker);

    try {
        await startPythonServer();

        // Start Channel Bridge after Python is ready, but do not block the
        // first workspace render on mobile bridge startup.
        publishBootState({ phase: 'connecting_tools', message: 'Starting mobile channels...', progress: 75 });

        // Listen for Channel Bridge status updates
        onBridgeMessage((message) => {
            if (message.type === 'status') {
                mainWindow?.webContents?.send('channel-bridge-status', message.platforms);
            } else if (message.type === 'whatsapp_pairing_code') {
                // Forward WhatsApp pairing code to renderer
                mainWindow?.webContents?.send('whatsapp-pairing-code', message.code);
            } else if (message.type === 'error') {
                console.error('Channel Bridge error:', message.error);
            }
        });

        startChannelBridgeInBackground();

        return true;
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        console.error('Failed to start Python server:', msg);
        publishBootState({
            phase: 'error',
            message: 'Backend failed to start',
            progress: 0,
            error: msg,
        });
        return false;
    } finally {
        bootInProgress = false;
    }
}

/** Navigate from boot shell to the real React app. */
async function loadReactApp(): Promise<void> {
    if (!mainWindow) return;

    bootProfile('renderer_load_start', { dev: isDev() });

    if (isDev()) {
        await mainWindow.loadURL(DEV_RENDERER_URL);
    } else {
        await mainWindow.loadFile(path.join(app.getAppPath(), '/dist-react/index.html'));
    }

    bootProfile('renderer_load_resolved', {
        url: mainWindow.webContents.getURL(),
    });
}

async function waitForRendererApp(): Promise<void> {
    if (!isDev()) return;

    bootProfile('renderer_wait_start', { urls: DEV_RENDERER_SHELL_PROBE_URLS });

    for (let attempt = 0; attempt < 300; attempt++) {
        try {
            const responses = await Promise.all(
                DEV_RENDERER_SHELL_PROBE_URLS.map((url) =>
                    fetch(url).catch(() => null),
                ),
            );
            const allReady = responses.every((response) => response?.ok);
            if (allReady) {
                await Promise.all(
                    responses.map(async (response) => {
                        if (!response) {
                            return;
                        }
                        await response.text().catch(() => '');
                    }),
                );
                bootProfile('renderer_wait_ready', {
                    urls: DEV_RENDERER_SHELL_PROBE_URLS,
                    attempts: attempt + 1,
                });
                return;
            }
        } catch {
            // Ignore fetch failures while Vite is still starting up.
        }

        await new Promise(resolve => setTimeout(resolve, 200));
    }

    throw new Error(`Vite dev server probes were not reachable: ${DEV_RENDERER_SHELL_PROBE_URLS.join(', ')}`);
}

let bootSequenceInProgress = false;
let reactAppLoaded = false;

async function startBootSequence(): Promise<void> {
    if (bootSequenceInProgress) return;
    bootSequenceInProgress = true;
    bootProfile('boot_sequence_start');

    const rendererAppLoadPromise = (reactAppLoaded
        ? Promise.resolve()
        : waitForRendererApp().then(async () => {
            await loadReactApp();
            reactAppLoaded = true;
        }))
        .then(() => ({ ok: true as const }))
        .catch((error: unknown) => ({
            ok: false as const,
            error: error instanceof Error ? error : new Error(String(error)),
        }));

    try {
        const bootSuccessful = await bootBackend();
        if (!bootSuccessful) return;

        publishBootState({
            phase: 'loading_interface',
            message: 'Rendering chat workspace...',
            progress: 92,
        });

        const rendererAppLoaded = await rendererAppLoadPromise;
        if (!rendererAppLoaded.ok) {
            throw rendererAppLoaded.error;
        }

        publishBootState({ phase: 'ready', message: 'Ready', progress: 100 });
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error('Failed to load renderer during boot:', message);
        publishBootState({
            phase: 'error',
            message: 'Application shell failed to load',
            progress: 0,
            error: message,
        });
    } finally {
        bootSequenceInProgress = false;
    }
}

app.on('ready', async () => {
    bootProfile('app_ready');
    // Auto-approve getDisplayMedia requests for meeting recording.
    session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
        if (request.frame) {
            callback({ video: request.frame, audio: 'loopback' });
        } else {
            console.error('setDisplayMediaRequestHandler: request.frame is null — denying request');
            callback({});
        }
    });

    // ── Create window IMMEDIATELY (before backend starts) ──────────
    const preloadPath = path.join(__dirname, 'preload.js');

    mainWindow = new BrowserWindow({
        width: DEFAULT_WINDOW_BOUNDS.width,
        height: DEFAULT_WINDOW_BOUNDS.height,
        minWidth: 30,
        minHeight: 20,
        title: 'Xpdite',
        frame: false,
        transparent: true,
        resizable: true,
        movable: true,
        alwaysOnTop: true,
        minimizable: false,
        maximizable: false,
        fullscreenable: false,
        skipTaskbar: true,
        type: 'panel',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: false,
            preload: preloadPath,
        }
    });

    if (process.platform === 'darwin') {
        // Required for macOS to show over full-screen apps and other spaces
        mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

        // Hide dock icon to enable NSWindowCollectionBehaviorFullScreenAuxiliary flavor.
        // Check for existence of 'dock' to satisfy TypeScript (undefined on Windows/Linux).
        if (app.dock) {
            app.dock.hide();
        }
    }

    normalBounds = mainWindow.getBounds();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');

    mainWindow.webContents.on('did-start-loading', () => {
        bootProfile('did_start_loading', {
            url: mainWindow?.webContents.getURL(),
        });
    });

    mainWindow.webContents.on('dom-ready', () => {
        bootProfile('dom_ready', {
            url: mainWindow?.webContents.getURL(),
        });
    });

    mainWindow.webContents.on('did-finish-load', () => {
        bootProfile('did_finish_load', {
            url: mainWindow?.webContents.getURL(),
        });
    });

    mainWindow.webContents.on('did-stop-loading', () => {
        bootProfile('did_stop_loading', {
            url: mainWindow?.webContents.getURL(),
        });
    });

    // Load the boot shell HTML *instantly* as a data: URL.
    // This renders the black-hole animation + progress bar before Vite or
    // the production React bundle is even available.
    mainWindow.loadURL(createBootShellDataUrl());

    // ── IPC handlers ───────────────────────────────────────────────
    ipcMain.handle('get-boot-state', (event) => {
        if (!isTrustedIpcSender(event)) {
            return null;
        }
        return currentBootState;
    });

    ipcMain.handle('retry-boot', async (event) => {
        if (!isTrustedIpcSender(event)) {
            return;
        }

        if (currentBootState.phase === 'error' && !bootSequenceInProgress) {
            publishBootState({ phase: 'starting', message: 'Retrying...', progress: 5 });
            await stopPythonServer();
            void startBootSequence();
        }
    });

    ipcMain.handle('perf-log', (event, message: string) => {
        if (!isTrustedPerfLogSender(event)) {
            return;
        }

        const safeMessage = sanitizePerfLogMessage(String(message));
        if (!safeMessage) {
            return;
        }

        if (shouldDropPerfLog(event.sender.id, safeMessage)) {
            return;
        }

        console.log(`[renderer-perf] ${safeMessage}`);
    });

    ipcMain.handle('set-mini-mode', (event, mini: boolean) => {
        if (!isTrustedIpcSender(event)) {
            return;
        }

        if (!mainWindow) {
            console.log('mainWindow is null');
            return;
        }

        if (mini) {
            const currentBounds = mainWindow.getBounds();
            if (currentBounds.width > 100 || currentBounds.height > 100) {
                normalBounds = currentBounds;
            }
            const newX = normalBounds.x + normalBounds.width - 52;
            const newY = normalBounds.y;
            mainWindow.setResizable(true);
            mainWindow.setMinimumSize(52, 52);
            mainWindow.setSize(52, 52, false);
            mainWindow.setPosition(newX, newY, false);
        } else {
            mainWindow.setMinimumSize(30, 20);
            mainWindow.setSize(normalBounds.width, normalBounds.height, false);
            mainWindow.setPosition(normalBounds.x, normalBounds.y, false);
        }
    });

    ipcMain.handle('focus-window', (event) => {
        if (!isTrustedIpcSender(event)) {
            return;
        }

        if (!mainWindow) return;
        mainWindow.focus();
    });

    ipcMain.handle('get-server-port', (event) => {
        if (!isTrustedIpcSender(event)) {
            return null;
        }

        return getServerPort();
    });

    ipcMain.handle('get-server-token', (event) => {
        if (!isTrustedIpcSender(event)) {
            return '';
        }

        return getServerToken();
    });

    // Channel Bridge IPC handlers
    ipcMain.handle('get-channel-bridge-port', (event) => {
        if (!isTrustedIpcSender(event)) {
            return null;
        }

        return getChannelBridgePort();
    });

    ipcMain.handle('get-channel-bridge-status', async (event) => {
        if (!isTrustedIpcSender(event)) {
            return { platforms: [] };
        }

        return getChannelBridgeStatus();
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    // ── Start backend and navigate to React app when ready ───────
    void startBootSequence();
});

// Handle all windows closed
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// Single cleanup hook — stopPythonServer() is itself idempotent, but there
// is no reason to invoke it from every lifecycle event.  `before-quit` fires
// before the window closes and before `will-quit`, so one handler is enough.
app.on('before-quit', async () => {
    console.log('App is quitting, cleaning up processes...');
    perfLogRateStateBySender.clear();
    await stopChannelBridge();
    await stopPythonServer();
    channelBridgeStarted = false;
    channelBridgeStartupPromise = null;
});
