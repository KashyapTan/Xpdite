// @vitest-environment node

import { EventEmitter } from 'node:events';
import path from 'node:path';

import { beforeEach, describe, expect, test, vi } from 'vitest';

const appHandlers = new Map<string, (...args: unknown[]) => unknown>();
const ipcHandlers = new Map<string, (...args: unknown[]) => unknown>();

const getChannelBridgePortMock = vi.fn(() => 9010);
const getChannelBridgeStatusMock = vi.fn(async () => ({
  platforms: [{ platform: 'telegram', status: 'connected' }],
}));
const getServerPortMock = vi.fn(() => 8123);
const getServerTokenMock = vi.fn(() => 'token-123');
const mkdirSyncMock = vi.fn();
const readFileSyncMock = vi.fn();
const writeFileSyncMock = vi.fn();
const isDevMock = vi.fn(() => false);
const onBootMarkerMock = vi.fn();
const onBridgeMessageMock = vi.fn();
const startChannelBridgeMock = vi.fn(async () => {});
const startPythonServerMock = vi.fn(async () => {});
const stopChannelBridgeMock = vi.fn(async () => {});
const stopPythonServerMock = vi.fn(async () => {});

let bootMarkerCallback: ((marker: { phase: string; message: string; progress: number }) => void) | undefined;
let bridgeMessageCallback: ((message: {
  type: string;
  platforms?: Array<{ platform: string; status: string; error?: string }>;
  code?: string;
  error?: string;
}) => void) | undefined;

class MockWebContents extends EventEmitter {
  currentUrl = 'file://boot';
  send = vi.fn();
  getURL = vi.fn(() => this.currentUrl);
}

class MockBrowserWindow extends EventEmitter {
  webContents = new MockWebContents();
  loadFile = vi.fn(async (filePath: string) => {
    this.webContents.currentUrl = `file://${filePath}`;
  });
  loadURL = vi.fn(async (url: string) => {
    this.webContents.currentUrl = url;
  });
  getBounds = vi.fn(() => ({ width: 420, height: 420, x: 100, y: 100 }));
  setAlwaysOnTop = vi.fn();
  setVisibleOnAllWorkspaces = vi.fn();
  setResizable = vi.fn();
  setMinimumSize = vi.fn();
  setPosition = vi.fn();
  setSize = vi.fn();
  setBackgroundColor = vi.fn();
  contentProtected = false;
  setContentProtection = vi.fn((enabled: boolean) => {
    this.contentProtected = enabled;
  });
  isContentProtected = vi.fn(() => this.contentProtected);
  show = vi.fn();
  focus = vi.fn();
}

let latestWindow: MockBrowserWindow | null = null;

const browserWindowCtorSpy = vi.fn();

function BrowserWindowMock(options?: unknown) {
  browserWindowCtorSpy(options);
  latestWindow = new MockBrowserWindow();
  return latestWindow;
}

const appMock = {
  getAppPath: vi.fn(() => 'C:/Program Files/Xpdite'),
  getPath: vi.fn(() => 'C:/Users/Test/AppData/Roaming/Xpdite'),
  on: vi.fn((event: string, handler: (...args: unknown[]) => unknown) => {
    appHandlers.set(event, handler);
    return appMock;
  }),
  exit: vi.fn(),
  quit: vi.fn(),
};

vi.mock('node:fs', () => ({
  mkdirSync: mkdirSyncMock,
  readFileSync: readFileSyncMock,
  writeFileSync: writeFileSyncMock,
}));

const ipcMainMock = {
  handle: vi.fn((channel: string, handler: (...args: unknown[]) => unknown) => {
    ipcHandlers.set(channel, handler);
  }),
};

const setDisplayMediaRequestHandlerMock = vi.fn();

vi.mock('electron', () => ({
  app: appMock,
  BrowserWindow: BrowserWindowMock,
  ipcMain: ipcMainMock,
  session: {
    defaultSession: {
      setDisplayMediaRequestHandler: setDisplayMediaRequestHandlerMock,
    },
  },
}));

vi.mock('./channelBridgeApi.js', () => ({
  getChannelBridgePort: getChannelBridgePortMock,
  getChannelBridgeStatus: getChannelBridgeStatusMock,
  onBridgeMessage: onBridgeMessageMock,
  startChannelBridge: startChannelBridgeMock,
  stopChannelBridge: stopChannelBridgeMock,
}));

vi.mock('./pythonApi.js', () => ({
  getServerPort: getServerPortMock,
  getServerToken: getServerTokenMock,
  onBootMarker: onBootMarkerMock,
  startPythonServer: startPythonServerMock,
  stopPythonServer: stopPythonServerMock,
}));

vi.mock('./utils.js', () => ({
  isDev: isDevMock,
}));

async function flushPromises(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function trustedEvent() {
  return {
    sender: {
      id: 7,
      getURL: () => 'file://renderer',
    },
    senderFrame: {
      url: 'file://renderer',
    },
  };
}

describe('electron main entrypoint', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    appHandlers.clear();
    ipcHandlers.clear();
    bootMarkerCallback = undefined;
    bridgeMessageCallback = undefined;
    latestWindow = null;

    browserWindowCtorSpy.mockClear();
    readFileSyncMock.mockImplementation(() => {
      throw new Error('settings missing');
    });
    mkdirSyncMock.mockImplementation(() => undefined);
    writeFileSyncMock.mockImplementation(() => undefined);
    onBootMarkerMock.mockImplementation((callback) => {
      bootMarkerCallback = callback;
    });
    onBridgeMessageMock.mockImplementation((callback) => {
      bridgeMessageCallback = callback;
    });
  });

  test('creates the app window, loads React, boots the backend, and wires trusted IPC handlers', async () => {
    await import('./main.js');
    const readyHandler = appHandlers.get('ready');
    expect(readyHandler).toBeTypeOf('function');

    await readyHandler?.();
    await flushPromises();

    expect(browserWindowCtorSpy).toHaveBeenCalledTimes(1);
    expect(browserWindowCtorSpy).toHaveBeenCalledWith(expect.objectContaining({
      backgroundColor: '#101014',
      show: true,
    }));
    expect(setDisplayMediaRequestHandlerMock).toHaveBeenCalledTimes(1);
    expect(latestWindow?.setContentProtection).toHaveBeenCalledWith(false);
    expect(latestWindow?.setAlwaysOnTop).toHaveBeenCalledWith(true, 'screen-saver');
    expect(latestWindow?.show).toHaveBeenCalledTimes(1);
    expect(startPythonServerMock).toHaveBeenCalledTimes(1);
    expect(startChannelBridgeMock).toHaveBeenCalledWith(8123);
    expect(latestWindow?.loadFile).toHaveBeenCalledWith(path.join('C:/Program Files/Xpdite', 'dist-react', 'index.html'));
    expect(latestWindow?.setBackgroundColor).toHaveBeenCalledWith('#00000000');

    const event = trustedEvent();
    expect(ipcHandlers.get('get-server-port')?.(event)).toBe(8123);
    expect(ipcHandlers.get('get-server-token')?.(event)).toBe('token-123');
    await expect(ipcHandlers.get('get-channel-bridge-status')?.(event)).resolves.toEqual({
      platforms: [{ platform: 'telegram', status: 'connected' }],
    });

    bootMarkerCallback?.({
      phase: 'starting_http',
      message: 'Starting HTTP server',
      progress: 60,
    });
    expect(ipcHandlers.get('get-boot-state')?.(event)).toEqual({
      phase: 'connecting_tools',
      message: 'Starting HTTP server',
      progress: 60,
    });

    bridgeMessageCallback?.({
      type: 'status',
      platforms: [{ platform: 'whatsapp', status: 'connecting' }],
    });
    bridgeMessageCallback?.({
      type: 'whatsapp_pairing_code',
      code: '123-456',
    });
    expect(latestWindow?.webContents.send).toHaveBeenCalledWith('channel-bridge-status', [
      { platform: 'whatsapp', status: 'connecting' },
    ]);
    expect(latestWindow?.webContents.send).toHaveBeenCalledWith('whatsapp-pairing-code', '123-456');

    ipcHandlers.get('set-mini-mode')?.(event, true);
    expect(latestWindow?.setSize).toHaveBeenCalledWith(52, 52, false);
    expect(ipcHandlers.get('get-content-protection')?.(event)).toEqual({
      enabled: false,
      active: false,
      supported: process.platform === 'darwin' || process.platform === 'win32',
    });
    expect(ipcHandlers.get('set-content-protection')?.(event, true)).toEqual({
      enabled: true,
      active: true,
      supported: process.platform === 'darwin' || process.platform === 'win32',
    });
    expect(latestWindow?.setContentProtection).toHaveBeenCalledWith(true);
    expect(writeFileSyncMock).toHaveBeenCalledWith(
      path.join('C:/Users/Test/AppData/Roaming/Xpdite', 'general-settings.json'),
      JSON.stringify({ invisibleMode: true }, null, 2),
      'utf8',
    );
    ipcHandlers.get('focus-window')?.(event);
    expect(latestWindow?.focus).toHaveBeenCalledTimes(1);
  });

  test('restores persisted content protection before showing the window', async () => {
    readFileSyncMock.mockReturnValueOnce(JSON.stringify({ invisibleMode: true }));

    await import('./main.js');
    const readyHandler = appHandlers.get('ready');
    expect(readyHandler).toBeTypeOf('function');

    await readyHandler?.();
    await flushPromises();

    expect(readFileSyncMock).toHaveBeenCalledWith(
      path.join('C:/Users/Test/AppData/Roaming/Xpdite', 'general-settings.json'),
      'utf8',
    );
    expect(latestWindow?.setContentProtection).toHaveBeenCalledWith(true);
    expect(latestWindow?.show).toHaveBeenCalledTimes(1);
    expect(ipcHandlers.get('get-content-protection')?.(trustedEvent())).toEqual({
      enabled: true,
      active: true,
      supported: process.platform === 'darwin' || process.platform === 'win32',
    });
  });

  test('loads the React shell before backend boot resolves', async () => {
    let resolveBackend!: () => void;
    startPythonServerMock.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveBackend = resolve;
    }));

    await import('./main.js');
    const readyHandler = appHandlers.get('ready');
    expect(readyHandler).toBeTypeOf('function');

    await readyHandler?.();
    await flushPromises();

    expect(startPythonServerMock).toHaveBeenCalledTimes(1);
    expect(latestWindow?.loadFile).toHaveBeenCalledWith(path.join('C:/Program Files/Xpdite', 'dist-react', 'index.html'));
    expect(latestWindow?.loadURL).not.toHaveBeenCalledWith(expect.stringContaining('data:text/html'));
    expect(startChannelBridgeMock).not.toHaveBeenCalled();

    resolveBackend();
    await flushPromises();

    expect(startChannelBridgeMock).toHaveBeenCalledWith(8123);
  });

  test('blocks quit until process cleanup finishes, then exits', async () => {
    await import('./main.js');
    const beforeQuitHandler = appHandlers.get('before-quit');
    expect(beforeQuitHandler).toBeTypeOf('function');

    const preventDefault = vi.fn();
    beforeQuitHandler?.({ preventDefault });
    await flushPromises();

    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(stopChannelBridgeMock).toHaveBeenCalledTimes(1);
    expect(stopPythonServerMock).toHaveBeenCalledTimes(1);
    expect(appMock.exit).toHaveBeenCalledWith(0);
  });
});
