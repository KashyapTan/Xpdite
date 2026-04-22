// @vitest-environment node

import { EventEmitter } from 'node:events';
import path from 'node:path';
import { PassThrough } from 'node:stream';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const appGetPathMock = vi.fn().mockReturnValue('C:/Users/tester/AppData/Roaming/Xpdite');
const execMock = vi.fn();
const existsSyncMock = vi.fn();
const isDevMock = vi.fn();
const spawnMock = vi.fn();

const expectedVenvPythonPath = () => (
  process.platform === 'win32'
    ? path.join('.venv', 'Scripts', 'python.exe')
    : path.join('.venv', 'bin', 'python')
);

const expectedFallbackPython = () => (process.platform === 'win32' ? 'python' : 'python3');

class FakeChildProcess extends EventEmitter {
  pid = 4321;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  stdout = new PassThrough();
  stderr = new PassThrough();
  killed = false;
  simulateExit = (code = 0) => {
    this.exitCode = code;
    this.emit('exit', code, null);
    this.emit('close', code, null);
  };
  kill = vi.fn(() => {
    this.killed = true;
    this.simulateExit();
    return true;
  });
}

vi.mock('electron', () => ({
  app: {
    getPath: appGetPathMock,
  },
}));

vi.mock('fs', () => ({
  default: {
    existsSync: existsSyncMock,
  },
  existsSync: existsSyncMock,
}));

vi.mock('child_process', () => ({
  exec: execMock,
  spawn: spawnMock,
}));

vi.mock('util', () => ({
  promisify: (fn: (command: string, callback: (error: Error | null, stdout: string, stderr: string) => void) => void) => (
    command: string,
  ) =>
    new Promise<{ stdout: string; stderr: string }>((resolve, reject) => {
      fn(command, (error, stdout, stderr) => {
        if (error) {
          reject(error);
          return;
        }
        resolve({ stdout, stderr });
      });
    }),
}));

vi.mock('./utils.js', () => ({
  isDev: isDevMock,
}));

describe('pythonApi', () => {
  const originalFetch = global.fetch;
  const originalResourcesPath = (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath;
  let latestChild: FakeChildProcess | null = null;

  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    global.fetch = vi.fn();
    latestChild = null;
    isDevMock.mockReturnValue(true);
    existsSyncMock.mockImplementation((value: string) => (
      value.includes(expectedVenvPythonPath())
    ));
    execMock.mockImplementation((command: string, callback: (error: Error | null, stdout: string, stderr: string) => void) => {
      if (command.startsWith('netstat')) {
        callback(null, '', '');
        return;
      }
      if (command.startsWith('lsof')) {
        callback(null, '', '');
        return;
      }
      if (command.includes('Get-CimInstance')) {
        callback(null, '', '');
        return;
      }
      if (command.startsWith('ps -eo')) {
        callback(null, '', '');
        return;
      }
      if (command.startsWith('ps -p')) {
        callback(null, '', '');
        return;
      }
      if (command.startsWith('tasklist')) {
        callback(null, 'INFO: No tasks are running which match the specified criteria.\n', '');
        return;
      }
      if (command.startsWith('taskkill')) {
        queueMicrotask(() => latestChild?.simulateExit());
        callback(null, '', '');
        return;
      }
      if (command.startsWith('kill ')) {
        queueMicrotask(() => latestChild?.simulateExit());
        callback(null, '', '');
        return;
      }

      callback(null, '', '');
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    Object.defineProperty(process, 'resourcesPath', {
      value: originalResourcesPath,
      configurable: true,
    });
  });

  test('starts the Python backend, tracks boot markers, and polls until health checks pass', async () => {
    const child = new FakeChildProcess();
    latestChild = child;
    const onBootMarker = vi.fn();
    spawnMock.mockReturnValue(child);
    const {
      getServerPort,
      getServerToken,
      onBootMarker: registerBootMarker,
      startPythonServer,
    } = await import('./pythonApi.js');

    vi.mocked(fetch).mockImplementation(async (input, init) => ({
      ok: String(input).includes('127.0.0.1:8000/api/health/session')
        && (init?.headers as Record<string, string> | undefined)?.['X-Xpdite-Server-Token'] === getServerToken(),
      text: () => Promise.resolve('ok'),
    } as Response));

    registerBootMarker(onBootMarker);
    const startPromise = startPythonServer();
    await expect(startPromise).resolves.toBeUndefined();
    child.stdout.write('XPDITE_BOOT {"phase":"loading_runtime","message":"Loading runtime","progress":25}\n');
    await Promise.resolve();

    expect(spawnMock).toHaveBeenCalledWith(
      expect.stringMatching(new RegExp(`(${expectedVenvPythonPath().replace(/\\/g, '\\\\')})|(${expectedFallbackPython()})`)),
      ['-m', 'source.main'],
      expect.objectContaining({
        cwd: process.cwd(),
        env: expect.objectContaining({
          XPDITE_SERVER_TOKEN: expect.stringMatching(/^[a-f0-9]{64}$/),
        }),
      }),
    );
    expect(getServerPort()).toBe(8000);
    expect(getServerToken()).toMatch(/^[a-f0-9]{64}$/);
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/health/session',
      expect.objectContaining({
        method: 'GET',
        headers: { 'X-Xpdite-Server-Token': getServerToken() },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(onBootMarker).toHaveBeenCalledWith({
      phase: 'loading_runtime',
      message: 'Loading runtime',
      progress: 25,
    });
  });

  test('ignores stale healthy servers from previous sessions and waits for the current backend token', async () => {
    const child = new FakeChildProcess();
    latestChild = child;
    spawnMock.mockReturnValue(child);

    const {
      getServerPort,
      getServerToken,
      startPythonServer,
    } = await import('./pythonApi.js');

    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      const token = (init?.headers as Record<string, string> | undefined)?.['X-Xpdite-Server-Token'];

      if (url.includes('127.0.0.1:8000/api/health/session')) {
        return { ok: false, status: 403, text: () => Promise.resolve('forbidden') } as Response;
      }

      if (url.includes('127.0.0.1:8001/api/health/session') && token === getServerToken()) {
        return { ok: true, status: 200, text: () => Promise.resolve('ok') } as Response;
      }

      return { ok: false, status: 404, text: () => Promise.resolve('missing') } as Response;
    });

    const startPromise = startPythonServer();
    child.stdout.write('Starting server on port 8001\n');
    await expect(startPromise).resolves.toBeUndefined();

    expect(getServerPort()).toBe(8001);
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8001/api/health/session',
      expect.objectContaining({
        headers: { 'X-Xpdite-Server-Token': getServerToken() },
      }),
    );
  });

  test('rejects immediately when startup emits a fatal import error', async () => {
    const child = new FakeChildProcess();
    latestChild = child;
    spawnMock.mockReturnValue(child);
    vi.mocked(fetch).mockRejectedValue(new Error('offline'));
    const { startPythonServer } = await import('./pythonApi.js');

    const startPromise = startPythonServer();
    child.stderr.write('ImportError: missing dependency\n');

    await expect(startPromise).rejects.toThrow(/Python server failed to start/);
  });

  test('stops the running Python process only once', async () => {
    const child = new FakeChildProcess();
    latestChild = child;
    spawnMock.mockReturnValue(child);
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('ok'),
    } as Response);
    const { startPythonServer, stopPythonServer } = await import('./pythonApi.js');

    await startPythonServer();

    const stopPromise = stopPythonServer();
    await new Promise((resolve) => setTimeout(resolve, 1100));
    await expect(stopPromise).resolves.toBeUndefined();
    if (process.platform === 'win32') {
      expect(execMock).toHaveBeenCalledWith(
        expect.stringContaining(`taskkill /T /PID ${child.pid}`),
        expect.any(Function),
      );
      expect(child.kill).not.toHaveBeenCalled();
    } else {
      expect(child.kill).toHaveBeenCalledWith('SIGTERM');
    }

    await stopPythonServer();
    if (process.platform !== 'win32') {
      expect(child.kill).toHaveBeenCalledTimes(1);
    }
  });

  test('passes packaged runtime env paths to the bundled backend in production', async () => {
    const child = new FakeChildProcess();
    latestChild = child;
    spawnMock.mockReturnValue(child);
    isDevMock.mockReturnValue(false);

    const packagedResourcesPath = process.platform === 'win32' ? 'C:/resources' : '/tmp/resources';
    Object.defineProperty(process, 'resourcesPath', {
      value: packagedResourcesPath,
      configurable: true,
    });

    const bundledServerPath = path.join(
      packagedResourcesPath,
      'python-server',
      process.platform === 'win32' ? 'xpdite-server.exe' : 'xpdite-server',
    );
    const runtimeRoot = path.join(packagedResourcesPath, 'python-runtime');
    const runtimeEnvFile = path.join(packagedResourcesPath, 'runtime-config', 'google-oauth.env');
    const childPythonPath = process.platform === 'win32'
      ? path.join(runtimeRoot, '.venv', 'Scripts', 'python.exe')
      : path.join(runtimeRoot, '.venv', 'bin', 'python');

    existsSyncMock.mockImplementation((value: string) => (
      value === bundledServerPath
      || value === runtimeRoot
      || value === runtimeEnvFile
      || value === childPythonPath
    ));

    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('ok'),
    } as Response);

    const { startPythonServer } = await import('./pythonApi.js');

    await expect(startPythonServer()).resolves.toBeUndefined();

    expect(spawnMock).toHaveBeenCalledWith(
      bundledServerPath,
      [],
      expect.objectContaining({
        env: expect.objectContaining({
          XPDITE_USER_DATA_DIR: 'C:/Users/tester/AppData/Roaming/Xpdite',
          XPDITE_RUNTIME_ROOT: runtimeRoot,
          XPDITE_RUNTIME_ENV_FILE: runtimeEnvFile,
          XPDITE_CHILD_PYTHON_EXECUTABLE: childPythonPath,
        }),
      }),
    );
  });
});
