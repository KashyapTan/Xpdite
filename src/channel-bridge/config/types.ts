/**
 * Configuration Types
 * 
 * Defines the structure of the configuration file that Python writes
 * and the Channel Bridge reads.
 */

import type { PlatformConfig } from '../types.js';

export interface ConfigFile {
  version: number;
  pythonServerPort: number;
  platforms: {
    telegram?: {
      enabled: boolean;
      botToken?: string;
      botUsername?: string;
    };
    discord?: {
      enabled: boolean;
      botToken?: string;
      publicKey?: string;
      applicationId?: string;
    };
    whatsapp?: {
      enabled: boolean;
      authMethod?: 'pairing_code';
      phoneNumber?: string;
      forcePairing?: boolean; // Clear auth state and re-pair
    };
  };
}

export interface LoadedConfig {
  pythonServerUrl: string;
  platforms: PlatformConfig[];
}

export function parseConfigFile(config: ConfigFile): LoadedConfig {
  const platforms: PlatformConfig[] = [];

  if (config.platforms.telegram?.enabled && config.platforms.telegram.botToken) {
    platforms.push({
      platform: 'telegram',
      enabled: true,
      credentials: {
        botToken: config.platforms.telegram.botToken,
        botUsername: config.platforms.telegram.botUsername,
      },
    });
  }

  if (config.platforms.discord?.enabled && config.platforms.discord.botToken) {
    platforms.push({
      platform: 'discord',
      enabled: true,
      credentials: {
        botToken: config.platforms.discord.botToken,
        publicKey: config.platforms.discord.publicKey ?? '',
        applicationId: config.platforms.discord.applicationId ?? '',
      },
    });
  }

  if (config.platforms.whatsapp?.enabled) {
    platforms.push({
      platform: 'whatsapp',
      enabled: true,
      credentials: {
        // WhatsApp uses 8-digit pairing-code auth only.
        authMethod: 'pairing_code',
        phoneNumber: config.platforms.whatsapp.phoneNumber,
        forcePairing: config.platforms.whatsapp.forcePairing,
      },
    });
  }

  return {
    pythonServerUrl: `http://127.0.0.1:${config.pythonServerPort}`,
    platforms,
  };
}

export function getDefaultConfig(pythonPort: number): ConfigFile {
  return {
    version: 1,
    pythonServerPort: pythonPort,
    platforms: {
      telegram: { enabled: false },
      discord: { enabled: false },
      whatsapp: { enabled: false },
    },
  };
}
