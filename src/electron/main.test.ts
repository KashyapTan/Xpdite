// @vitest-environment node

import { EventEmitter } from 'node:events';

import { beforeEach, describe, expect, test, vi } from 'vitest';

const appHandlers = new Map<string, (...args: unknown[]) => unknown>();
const ipcHandlers = new Map<string, (...args: unknown[]) => unknown>();

const createBootShellDataUrlMock = vi.fn(() => 'data:text/html,boot-shell');
const getChannelBridgePortMock = vi.fn(() => 9010);
const getChannelBridgeStatusMock = vi.fn(async () => ({
  platforms: [{ platform: 'telegram', status: 'connected' }],
}));
const getServerPortMock = vi.fn(() => 8123);
const getServerTokenMock = vi.fn(() => 'token-123');
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
  setResizable = vi.fn();
  setMinimumSize = vi.fn();
  setPosition = vi.fn();
  setSize = vi.fn();
  focus = vi.fn();
}

let latestWindow: MockBrowserWindow | null = null;

const browserWindowCtorSpy = vi.fn();

function BrowserWindowMock() {
  browserWindowCtorSpy();
  latestWindow = new MockBrowserWindow();
  return latestWindow;
}

const appMock = {
  getAppPath: vi.fn(() => 'C:/Program Files/Xpdite'),
  on: vi.fn((event: string, handler: (...args: unknown[]) => unknown) => {
    appHandlers.set(event, handler);
    return appMock;
  }),
  quit: vi.fn(),
};

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

vi.mock('./bootShellHtml.js', () => ({
  createBootShellDataUrl: createBootShellDataUrlMock,
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
    onBootMarkerMock.mockImplementation((callback) => {
      bootMarkerCallback = callback;
    });
    onBridgeMessageMock.mockImplementation((callback) => {
      bridgeMessageCallback = callback;
    });
  });

  test('creates the boot window, boots the backend, and wires trusted IPC handlers', async () => {
    await import('./main.js');
    const readyHandler = appHandlers.get('ready');
    expect(readyHandler).toBeTypeOf('function');

    await readyHandler?.();
    await flushPromises();

    expect(browserWindowCtorSpy).toHaveBeenCalledTimes(1);
    expect(setDisplayMediaRequestHandlerMock).toHaveBeenCalledTimes(1);
    expect(createBootShellDataUrlMock).toHaveBeenCalledTimes(1);
    expect(latestWindow?.loadURL).toHaveBeenCalledWith('data:text/html,boot-shell');
    expect(latestWindow?.setAlwaysOnTop).toHaveBeenCalledWith(true, 'screen-saver');
    expect(startPythonServerMock).toHaveBeenCalledTimes(1);
    expect(startChannelBridgeMock).toHaveBeenCalledWith(8123);
    expect(latestWindow?.loadFile).toHaveBeenCalledWith('C:\\Program Files\\Xpdite\\dist-react\\index.html');

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
    ipcHandlers.get('focus-window')?.(event);
    expect(latestWindow?.focus).toHaveBeenCalledTimes(1);
  });

  test('runs process cleanup on before-quit', async () => {
    await import('./main.js');
    const beforeQuitHandler = appHandlers.get('before-quit');
    expect(beforeQuitHandler).toBeTypeOf('function');

    await beforeQuitHandler?.();

    expect(stopChannelBridgeMock).toHaveBeenCalledTimes(1);
    expect(stopPythonServerMock).toHaveBeenCalledTimes(1);
  });
});
