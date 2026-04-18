import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createConfigLoader } from './loader.js';

async function waitFor(predicate: () => boolean, timeoutMs: number = 3000): Promise<void> {
  const startedAt = Date.now();

  while (!predicate()) {
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error('Timed out waiting for condition');
    }

    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

describe('createConfigLoader', () => {
  let userDataDir: string;

  beforeEach(() => {
    vi.useRealTimers();
    userDataDir = mkdtempSync(path.join(tmpdir(), 'xpdite-loader-'));
  });

  afterEach(() => {
    rmSync(userDataDir, { recursive: true, force: true });
    vi.useRealTimers();
  });

  test('loads defaults when the config file is missing', async () => {
    const loader = createConfigLoader(userDataDir, 8123);

    await expect(loader.load()).resolves.toEqual({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [],
    });
  });

  test('loads and parses the saved config file', async () => {
    writeFileSync(
      loaderConfigPath(),
      JSON.stringify({
        version: 1,
        pythonServerPort: 9000,
        platforms: {
          telegram: { enabled: true, botToken: 'telegram-token' },
        },
      }),
      'utf8',
    );
    const loader = createConfigLoader(userDataDir, 8123);

    await expect(loader.load()).resolves.toEqual({
      pythonServerUrl: 'http://127.0.0.1:9000',
      platforms: [
        {
          platform: 'telegram',
          enabled: true,
          credentials: {
            botToken: 'telegram-token',
            botUsername: undefined,
          },
        },
      ],
    });
  });

  test('falls back to defaults when the config file is invalid', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    writeFileSync(loaderConfigPath(), '{invalid json', 'utf8');
    const loader = createConfigLoader(userDataDir, 8123);

    await expect(loader.load()).resolves.toEqual({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [],
    });
    expect(errorSpy).toHaveBeenCalledWith('[ConfigLoader] Error loading config:', expect.any(Error));
    errorSpy.mockRestore();
  });

  test('awaits async change handlers when watched config files update', async () => {
    const loader = createConfigLoader(userDataDir, 8123);
    const onChange = vi.fn().mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });

    loader.startWatching(onChange);
    await new Promise((resolve) => setTimeout(resolve, 50));

    writeFileSync(
      loaderConfigPath(),
      JSON.stringify({
        version: 1,
        pythonServerPort: 9001,
        platforms: {
          whatsapp: { enabled: true, phoneNumber: '+15551234567' },
        },
      }),
      'utf8',
    );

    await waitFor(() => onChange.mock.calls.length > 0);
    expect(onChange).toHaveBeenCalledWith({
      pythonServerUrl: 'http://127.0.0.1:9001',
      platforms: [
        {
          platform: 'whatsapp',
          enabled: true,
          credentials: {
            authMethod: 'pairing_code',
            phoneNumber: '+15551234567',
            forcePairing: undefined,
          },
        },
      ],
    });

    loader.stopWatching();
  });

  test('logs async reload failures instead of leaking rejected promises', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const loader = createConfigLoader(userDataDir, 8123);

    loader.startWatching(async () => {
      throw new Error('apply failed');
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    writeFileSync(
      loaderConfigPath(),
      JSON.stringify({
        version: 1,
        pythonServerPort: 9001,
        platforms: {
          telegram: { enabled: true, botToken: 'telegram-token' },
        },
      }),
      'utf8',
    );

    await waitFor(() => errorSpy.mock.calls.length > 0);
    expect(errorSpy).toHaveBeenCalledWith('[ConfigLoader] Error reloading config:', expect.any(Error));

    loader.stopWatching();
    errorSpy.mockRestore();
  });

  function loaderConfigPath(): string {
    return path.join(userDataDir, 'mobile_channels_config.json');
  }
});
