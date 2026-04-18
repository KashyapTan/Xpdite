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

class FakeChildProcess extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  killed = false;
  kill = vi.fn(() => {
    this.killed = true;
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

  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    global.fetch = vi.fn();
    isDevMock.mockReturnValue(true);
    existsSyncMock.mockImplementation((value: string) => (
      value.includes(path.join('.venv', 'Scripts', 'python.exe'))
    ));
    execMock.mockImplementation((command: string, callback: (error: Error | null, stdout: string, stderr: string) => void) => {
      if (command.startsWith('netstat')) {
        callback(null, '', '');
        return;
      }
      if (command.includes('Get-CimInstance')) {
        callback(null, '', '');
        return;
      }
      if (command.startsWith('tasklist')) {
        callback(null, 'INFO: No tasks are running which match the specified criteria.\n', '');
        return;
      }
      if (command.startsWith('taskkill')) {
        callback(null, '', '');
        return;
      }

      callback(null, '', '');
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test('starts the Python backend, tracks boot markers, and polls until health checks pass', async () => {
    const child = new FakeChildProcess();
    const onBootMarker = vi.fn();
    spawnMock.mockReturnValue(child);
    vi.mocked(fetch).mockImplementation(async (input) => ({
      ok: String(input).includes('127.0.0.1:8000'),
      text: () => Promise.resolve('ok'),
    } as Response));
    const {
      getServerPort,
      getServerToken,
      onBootMarker: registerBootMarker,
      startPythonServer,
    } = await import('./pythonApi.js');

    registerBootMarker(onBootMarker);
    const startPromise = startPythonServer();
    await expect(startPromise).resolves.toBeUndefined();
    child.stdout.write('XPDITE_BOOT {"phase":"loading_runtime","message":"Loading runtime","progress":25}\n');
    await Promise.resolve();

    expect(spawnMock).toHaveBeenCalledWith(
      expect.stringContaining(path.join('.venv', 'Scripts', 'python.exe')),
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
    expect(onBootMarker).toHaveBeenCalledWith({
      phase: 'loading_runtime',
      message: 'Loading runtime',
      progress: 25,
    });
  });

  test('rejects immediately when startup emits a fatal import error', async () => {
    const child = new FakeChildProcess();
    spawnMock.mockReturnValue(child);
    vi.mocked(fetch).mockRejectedValue(new Error('offline'));
    const { startPythonServer } = await import('./pythonApi.js');

    const startPromise = startPythonServer();
    child.stderr.write('ImportError: missing dependency\n');

    await expect(startPromise).rejects.toThrow(/Python server failed to start/);
  });

  test('stops the running Python process only once', async () => {
    const child = new FakeChildProcess();
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
    expect(child.kill).toHaveBeenCalledWith('SIGTERM');

    await stopPythonServer();
    expect(child.kill).toHaveBeenCalledTimes(1);
  });
});
