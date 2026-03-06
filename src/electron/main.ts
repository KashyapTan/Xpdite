import { app, BrowserWindow, ipcMain, session } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import { isDev } from './utils.js';
import { startPythonServer, stopPythonServer, getServerPort } from './pythonApi.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: BrowserWindow | null = null;
let normalBounds = { width: 450, height: 450, x: 100, y: 100 };

app.on('ready', async () => {
    // Auto-approve getDisplayMedia requests for meeting recording.
    // Uses tab capture (request.frame) for the mandatory video track and
    // Electron's built-in WASAPI loopback for system audio capture.
    //
    // Tab capture goes through Chromium's compositor (CopyOutputRequest),
    // completely bypassing WGC (Windows Graphics Capture) which fails with
    // E_FAIL on some GPU/driver combos. The renderer strips the video track
    // immediately — only the WASAPI audio loopback is used.
    session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
        if (request.frame) {
            callback({ video: request.frame, audio: 'loopback' });
        } else {
            // request.frame should always exist for renderer-initiated calls.
            // Deny the request — causes getDisplayMedia to reject with NotAllowedError.
            console.error('setDisplayMediaRequestHandler: request.frame is null — denying request');
            callback({});
        }
    });

    // Only start Python server in production mode
    // In development, the dev:pyserver script handles this
    if (!isDev()) {
        try {
            await startPythonServer();
            console.log('Python server started successfully');
        } catch (error) {
            console.error('Failed to start Python server:', error);
        }
    } else {
        console.log('Development mode: Python server should be started by dev:pyserver script');
    }

    const preloadPath = path.join(__dirname, 'preload.js');
    console.log('Preload path:', preloadPath);
    console.log('App path:', app.getAppPath());
    console.log('__dirname:', __dirname);

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

    // Strengthen always-on-top level (optional):
    mainWindow.setAlwaysOnTop(true, 'screen-saver'); // or 'floating'
    mainWindow.setContentProtection(true); // Prevent screen capture on some OSes

    // IPC: Toggle mini mode - resize the actual electron window
    ipcMain.handle('set-mini-mode', (_event, mini: boolean) => {
        // console.log('IPC set-mini-mode called with:', mini);
        // console.log('Current Bounds before action:', mainWindow?.getBounds());

        if (!mainWindow) {
            console.log('mainWindow is null');
            return;
        }

        if (mini) {
            const currentBounds = mainWindow.getBounds();
            // Only update normalBounds if we are currently "large"
            if (currentBounds.width > 100 || currentBounds.height > 100) {
                normalBounds = currentBounds;
                // console.log('Saved normalBounds:', normalBounds);
            }

            // Calculate position: top-right of the current window
            const newX = normalBounds.x + normalBounds.width - 52;
            const newY = normalBounds.y;

            mainWindow.setResizable(true); // Ensure we can resize
            mainWindow.setMinimumSize(52, 52);
            mainWindow.setSize(52, 52, false); // false to disable animation which can sometimes bug out size setting
            mainWindow.setPosition(newX, newY, false);
            // console.log('Window resized to mini mode. New Bounds:', mainWindow.getBounds());
        } else {
            // console.log('Restoring to normalBounds:', normalBounds);
            mainWindow.setMinimumSize(30, 20);

            // Explicitly set size and position separately if setBounds fails
            mainWindow.setSize(normalBounds.width, normalBounds.height, false);
            mainWindow.setPosition(normalBounds.x, normalBounds.y, false);

            // console.log('Window restored. New Bounds:', mainWindow.getBounds());
        }
    });

    // IPC: Focus the window
    ipcMain.handle('focus-window', () => {
        if (!mainWindow) return;
        mainWindow.focus();
    });

    // IPC: Get the Python server port
    ipcMain.handle('get-server-port', () => {
        return getServerPort();
    });

    // Show across virtual desktops / fullscreen spaces:
    // mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

    // Handle window closed event — cleanup handled by app-level quit handlers.
    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    if (isDev()) {
        mainWindow.loadURL('http://localhost:5123');
    }
    else {
        mainWindow.loadFile(path.join(app.getAppPath(), '/dist-react/index.html'));
    }
})

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