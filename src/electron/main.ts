import { app, BrowserWindow, ipcMain, session } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import { isDev } from './utils.js';
import { startPythonServer, stopPythonServer, getServerPort, onBootMarker } from './pythonApi.js';
import { createBootShellDataUrl } from './bootShellHtml.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: BrowserWindow | null = null;
let normalBounds = { width: 450, height: 450, x: 100, y: 100 };

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

function publishBootState(state: BootState) {
    currentBootState = state;
    mainWindow?.webContents?.send('boot-state', state);
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

    if (isDev()) {
        await mainWindow.loadURL('http://localhost:5123');
    } else {
        await mainWindow.loadFile(path.join(app.getAppPath(), '/dist-react/index.html'));
    }
}

async function waitForRendererApp(): Promise<void> {
    if (!isDev()) return;

    const viteUrl = 'http://localhost:5123';

    for (let attempt = 0; attempt < 300; attempt++) {
        try {
            const response = await fetch(viteUrl, { method: 'HEAD' }).catch(() => null);
            if (response?.ok) return;
        } catch {
            // Ignore fetch failures while Vite is still starting up.
        }

        await new Promise(resolve => setTimeout(resolve, 200));
    }

    throw new Error(`Vite dev server was not reachable at ${viteUrl}`);
}

let bootSequenceInProgress = false;
let reactAppLoaded = false;

async function startBootSequence(): Promise<void> {
    if (bootSequenceInProgress) return;
    bootSequenceInProgress = true;

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
        width: 550,
        height: 550,
        minWidth: 30,
        minHeight: 20,
        title: 'Xpdite',
        frame: false,
        transparent: true,
        resizable: true,
        alwaysOnTop: true,
        minimizable: false,
        maximizable: false,
        fullscreenable: false,
        skipTaskbar: true,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: false,
            preload: preloadPath,
        }
    });

    normalBounds = mainWindow.getBounds();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');

    // Load the boot shell HTML *instantly* as a data: URL.
    // This renders the black-hole animation + progress bar before Vite or
    // the production React bundle is even available.
    mainWindow.loadURL(createBootShellDataUrl());

    // ── IPC handlers ───────────────────────────────────────────────
    ipcMain.handle('get-boot-state', () => currentBootState);

    ipcMain.handle('retry-boot', async () => {
        if (currentBootState.phase === 'error' && !bootSequenceInProgress) {
            publishBootState({ phase: 'starting', message: 'Retrying...', progress: 5 });
            await stopPythonServer();
            void startBootSequence();
        }
    });

    ipcMain.handle('set-mini-mode', (_event, mini: boolean) => {
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

    ipcMain.handle('focus-window', () => {
        if (!mainWindow) return;
        mainWindow.focus();
    });

    ipcMain.handle('get-server-port', () => {
        return getServerPort();
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
    await stopPythonServer();
});
