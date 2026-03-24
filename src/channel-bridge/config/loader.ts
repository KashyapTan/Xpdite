/**
 * Configuration Loader
 * 
 * Loads configuration from a JSON file and watches for changes.
 * Python backend writes this file when the user saves settings.
 */

import { readFile, watch } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import type { ConfigFile, LoadedConfig } from './types.js';
import { parseConfigFile, getDefaultConfig } from './types.js';

export interface ConfigLoader {
  load: () => Promise<LoadedConfig>;
  startWatching: (onChange: (config: LoadedConfig) => void) => void;
  stopWatching: () => void;
  getConfigPath: () => string;
}

export function createConfigLoader(userDataDir: string, defaultPythonPort: number = 8000): ConfigLoader {
  const configPath = path.join(userDataDir, 'mobile_channels_config.json');
  let watcher: AsyncIterable<{ eventType: string; filename: string | null }> | null = null;
  let watchAbortController: AbortController | null = null;

  async function loadConfigFile(): Promise<ConfigFile> {
    if (!existsSync(configPath)) {
      console.log(`[ConfigLoader] Config file not found at ${configPath}, using defaults`);
      return getDefaultConfig(defaultPythonPort);
    }

    try {
      const content = await readFile(configPath, 'utf8');
      const parsed = JSON.parse(content) as ConfigFile;
      console.log(`[ConfigLoader] Loaded config from ${configPath}`);
      return parsed;
    } catch (err) {
      console.error(`[ConfigLoader] Error loading config:`, err);
      return getDefaultConfig(defaultPythonPort);
    }
  }

  return {
    async load(): Promise<LoadedConfig> {
      const configFile = await loadConfigFile();
      return parseConfigFile(configFile);
    },

    startWatching(onChange: (config: LoadedConfig) => void): void {
      if (watchAbortController) {
        return; // Already watching
      }

      watchAbortController = new AbortController();
      
      // Debounce rapid file changes
      let debounceTimer: ReturnType<typeof setTimeout> | null = null;
      
      const handleChange = async () => {
        if (debounceTimer) {
          clearTimeout(debounceTimer);
        }
        debounceTimer = setTimeout(async () => {
          try {
            const configFile = await loadConfigFile();
            const config = parseConfigFile(configFile);
            console.log(`[ConfigLoader] Config changed, notifying listeners`);
            onChange(config);
          } catch (err) {
            console.error(`[ConfigLoader] Error reloading config:`, err);
          }
        }, 100); // 100ms debounce
      };

      // Watch the directory for the config file
      const dirPath = path.dirname(configPath);
      const fileName = path.basename(configPath);

      (async () => {
        try {
          watcher = watch(dirPath, { signal: watchAbortController?.signal });
          for await (const event of watcher) {
            if (event.filename === fileName) {
              await handleChange();
            }
          }
        } catch (err) {
          if ((err as NodeJS.ErrnoException).name !== 'AbortError') {
            console.error(`[ConfigLoader] Watch error:`, err);
          }
        }
      })();

      console.log(`[ConfigLoader] Started watching ${configPath}`);
    },

    stopWatching(): void {
      if (watchAbortController) {
        watchAbortController.abort();
        watchAbortController = null;
        watcher = null;
        console.log(`[ConfigLoader] Stopped watching config file`);
      }
    },

    getConfigPath(): string {
      return configPath;
    },
  };
}
