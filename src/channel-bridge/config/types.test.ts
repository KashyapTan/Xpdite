import { describe, expect, test } from 'vitest';

import { getDefaultConfig, parseConfigFile } from './types.js';

describe('channel bridge config types', () => {
  test('parses enabled platform credentials into runtime config', () => {
    const result = parseConfigFile({
      version: 1,
      pythonServerPort: 8123,
      platforms: {
        telegram: {
          enabled: true,
          botToken: 'telegram-token',
          botUsername: 'xpdite_bot',
        },
        discord: {
          enabled: true,
          botToken: 'discord-token',
          publicKey: 'discord-public-key',
          applicationId: 'discord-app-id',
        },
        whatsapp: {
          enabled: true,
          phoneNumber: '+15551234567',
        },
      },
    });

    expect(result).toEqual({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [
        {
          platform: 'telegram',
          enabled: true,
          credentials: {
            botToken: 'telegram-token',
            botUsername: 'xpdite_bot',
          },
        },
        {
          platform: 'discord',
          enabled: true,
          credentials: {
            botToken: 'discord-token',
            publicKey: 'discord-public-key',
            applicationId: 'discord-app-id',
          },
        },
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
  });

  test('omits disabled or incomplete platforms', () => {
    const result = parseConfigFile({
      version: 1,
      pythonServerPort: 8005,
      platforms: {
        telegram: {
          enabled: true,
        },
        discord: {
          enabled: true,
        },
        whatsapp: {
          enabled: false,
        },
      },
    });

    expect(result).toEqual({
      pythonServerUrl: 'http://127.0.0.1:8005',
      platforms: [],
    });
  });

  test('builds a fully disabled default config', () => {
    expect(getDefaultConfig(9001)).toEqual({
      version: 1,
      pythonServerPort: 9001,
      platforms: {
        telegram: { enabled: false },
        discord: { enabled: false },
        whatsapp: { enabled: false },
      },
    });
  });
});
