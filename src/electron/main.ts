import { app, BrowserWindow, ipcMain, screen } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import { isDev } from './utils.js';
import { startPythonServer, stopPythonServer } from './pythonApi.js';
import { initMain } from 'electron-audio-loopback';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: BrowserWindow | null = null;
let normalBounds = { width: 450, height: 450, x: 100, y: 100 };

// Initialize electron-audio-loopback BEFORE app is ready.
// This registers IPC handlers: 'enable-loopback-audio' / 'disable-loopback-audio'.
initMain();

app.on('ready', async () => {
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
        width: 450,
        height: 450,
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
    // mainWindow.setContentProtection(true); // Prevent screen capture on some OSes

    // IPC: Toggle mini mode - resize the actual electron window
    ipcMain.handle('set-mini-mode', (_event, mini: boolean) => {
        console.log('IPC set-mini-mode called with:', mini);
        console.log('Current Bounds before action:', mainWindow?.getBounds());

        if (!mainWindow) {
            console.log('mainWindow is null');
            return;
        }

        if (mini) {
            const currentBounds = mainWindow.getBounds();
            // Only update normalBounds if we are currently "large"
            if (currentBounds.width > 100 || currentBounds.height > 100) {
                normalBounds = currentBounds;
                console.log('Saved normalBounds:', normalBounds);
            }

            // Calculate position: top-right of the current window
            const newX = normalBounds.x + normalBounds.width - 52;
            const newY = normalBounds.y;

            mainWindow.setResizable(true); // Ensure we can resize
            mainWindow.setMinimumSize(52, 52);
            mainWindow.setSize(52, 52, false); // false to disable animation which can sometimes bug out size setting
            mainWindow.setPosition(newX, newY, false);
            console.log('Window resized to mini mode. New Bounds:', mainWindow.getBounds());
        } else {
            console.log('Restoring to normalBounds:', normalBounds);
            mainWindow.setMinimumSize(30, 20);

            // Explicitly set size and position separately if setBounds fails
            mainWindow.setSize(normalBounds.width, normalBounds.height, false);
            mainWindow.setPosition(normalBounds.x, normalBounds.y, false);

            console.log('Window restored. New Bounds:', mainWindow.getBounds());
        }
    });

    // IPC: Focus the window
    ipcMain.handle('focus-window', () => {
        if (!mainWindow) return;
        mainWindow.focus();
    });

    // Show across virtual desktops / fullscreen spaces:
    // mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

    // Handle window closed event
    mainWindow.on('closed', async () => {
        console.log('Main window closed, cleaning up...');
        await stopPythonServer();
        mainWindow = null;
    });

    // Handle window close event (before window is actually closed)
    mainWindow.on('close', async () => {
        console.log('Main window closing, initiating cleanup...');
        await stopPythonServer();
    });

    if (isDev()) {
        mainWindow.loadURL('http://localhost:5123');
    }
    else {
        mainWindow.loadFile(path.join(app.getAppPath(), '/dist-react/index.html'));
    }
})

// Handle all windows closed
app.on('window-all-closed', async () => {
    console.log('All windows closed, stopping Python server...');
    await stopPythonServer();
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// Handle app before quit
app.on('before-quit', async () => {
    console.log('App is quitting, cleaning up processes...');
    await stopPythonServer();
});

// Handle app will quit
app.on('will-quit', async () => {
    console.log('App will quit, final cleanup...');
    await stopPythonServer();
});