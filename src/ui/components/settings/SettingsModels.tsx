import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import '../../CSS/SettingsModels.css';

interface OllamaModel {
  name: string;
  size: number;
  parameter_size: string;
  quantization: string;
}

interface CloudModel {
  name: string;       // e.g., "anthropic/claude-sonnet-4-20250514"
  provider: string;   // e.g., "anthropic"
  description: string;
}

/**
 * SettingsModels — the "Models" tab inside Settings.
 *
 * Responsibilities:
 * 1. Fetch all Ollama models installed on the machine (GET /api/models/ollama).
 * 2. Fetch cloud models for providers with stored API keys.
 * 3. Fetch which models the user has enabled (GET /api/models/enabled).
 * 4. Let the user toggle models on/off.
 * 5. Persist changes (PUT /api/models/enabled).
 *
 * The enabled models list is consumed by App.tsx's model-selector dropdown
 * so only toggled models appear there.
 */
const SettingsModels: React.FC = () => {
  // All Ollama models on the machine
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  // Cloud models per provider
  const [anthropicModels, setAnthropicModels] = useState<CloudModel[]>([]);
  const [openaiModels, setOpenaiModels] = useState<CloudModel[]>([]);
  const [geminiModels, setGeminiModels] = useState<CloudModel[]>([]);
  // API key status
  const [keyStatus, setKeyStatus] = useState<Record<string, { has_key: boolean; masked: string | null }>>({});
  // Names of models the user has toggled on
  const [enabledModels, setEnabledModels] = useState<string[]>([]);
  // Loading / error states
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Ollama-specific warning (e.g. "Ollama is not running")
  const [ollamaWarning, setOllamaWarning] = useState('');

  // --------------------------------------------------
  // Fetch data on mount
  // --------------------------------------------------
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        // Fire all requests in parallel
        const [ollamaResult, enabled, keys] = await Promise.all([
          api.getOllamaModels(),
          api.getEnabledModels(),
          api.getApiKeyStatus(),
        ]);
        setOllamaModels(ollamaResult.models);
        setOllamaWarning(ollamaResult.error ?? '');
        setEnabledModels(enabled);
        setKeyStatus(keys);

        // Fetch cloud models for providers with keys
        const cloudFetches: Promise<void>[] = [];

        if (keys.anthropic?.has_key) {
          cloudFetches.push(
            api.getProviderModels('anthropic').then(setAnthropicModels)
          );
        }
        if (keys.openai?.has_key) {
          cloudFetches.push(
            api.getProviderModels('openai').then(setOpenaiModels)
          );
        }
        if (keys.gemini?.has_key) {
          cloudFetches.push(
            api.getProviderModels('gemini').then(setGeminiModels)
          );
        }

        await Promise.all(cloudFetches);
      } catch {
        setError('Could not reach the backend. Is the server running?');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // --------------------------------------------------
  // Toggle a model on/off and persist
  // --------------------------------------------------
  const toggleModel = useCallback(
    async (modelName: string) => {
      setEnabledModels((prev) => {
        const isEnabled = prev.includes(modelName);
        const updated = isEnabled
          ? prev.filter((m) => m !== modelName)
          : [...prev, modelName];

        // Persist to backend (SQLite) — fire-and-forget
        api.setEnabledModels(updated);

        return updated;
      });
    },
    [],
  );

  // --------------------------------------------------
  // Helper: human-readable file size
  // --------------------------------------------------
  const formatSize = (bytes: number) => {
    if (bytes === 0) return '';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(0)} MB`;
  };

  // --------------------------------------------------
  // Helper: strip provider prefix for display
  // --------------------------------------------------
  const displayName = (fullName: string) => {
    const slashIdx = fullName.indexOf('/');
    return slashIdx >= 0 ? fullName.substring(slashIdx + 1) : fullName;
  };

  // --------------------------------------------------
  // Render a cloud model list
  // --------------------------------------------------
  const renderCloudModels = (
    provider: string,
    models: CloudModel[],
    cssPrefix: string,
  ) => {
    const hasKey = keyStatus[provider]?.has_key;

    return (
      <>
        <div className={`settings-models-${cssPrefix}-header`}>
          {provider.charAt(0).toUpperCase() + provider.slice(1)}
        </div>
        <div className={`settings-models-${cssPrefix}-content`}>
          {!hasKey && (
            <div className={`settings-models-${cssPrefix}-model settings-models-placeholder`}>
              No API key configured. Add one in the {provider.charAt(0).toUpperCase() + provider.slice(1)} tab.
            </div>
          )}
          {hasKey && models.length === 0 && !loading && (
            <div className={`settings-models-${cssPrefix}-model settings-models-placeholder`}>
              Loading models...
            </div>
          )}
          {hasKey &&
            models.map((model) => {
              const isEnabled = enabledModels.includes(model.name);
              return (
                <div
                  key={model.name}
                  className={`settings-models-${cssPrefix}-model ${isEnabled ? 'settings-models-enabled' : ''}`}
                  onClick={() => toggleModel(model.name)}
                >
                  <div className="settings-model-toggle">
                    <div className={`settings-model-toggle-track ${isEnabled ? 'active' : ''}`}>
                      <div className="settings-model-toggle-thumb" />
                    </div>
                  </div>
                  <div className="settings-model-info">
                    <span className="settings-model-name">{displayName(model.name)}</span>
                    <span className="settings-model-meta">{model.description}</span>
                  </div>
                </div>
              );
            })}
        </div>
      </>
    );
  };

  // --------------------------------------------------
  // Render
  // --------------------------------------------------
  return (
    <div className="settings-models-section">
      <div className="settings-models-header">
        <h2>Models</h2>
        <p>Enable or disable models for your workspace.</p>
      </div>
      <div className="settings-models-ollama-section">
        {/* ====== OLLAMA SECTION ====== */}
        <div className="settings-models-ollama-header">Ollama</div>

        <div className="settings-models-ollama-content">
          {loading && (
            <div className="settings-models-ollama-model settings-models-loading">
              Loading models...
            </div>
          )}
          {error && (
            <div className="settings-models-ollama-model settings-models-error">
              {error}
            </div>
          )}
          {!loading && !error && ollamaWarning && (
            <div className="settings-models-ollama-model settings-models-error">
              {ollamaWarning}
            </div>
          )}
          {!loading && !error && !ollamaWarning && ollamaModels.length === 0 && (
            <div className="settings-models-ollama-model settings-models-empty">
              No Ollama models found. Pull one with <code>ollama pull model-name</code>
            </div>
          )}
          {!loading &&
            ollamaModels.map((model) => {
              const isEnabled = enabledModels.includes(model.name);
              return (
                <div
                  key={model.name}
                  className={`settings-models-ollama-model ${isEnabled ? 'settings-models-enabled' : ''}`}
                  onClick={() => toggleModel(model.name)}
                >
                  <div className="settings-model-toggle">
                    <div className={`settings-model-toggle-track ${isEnabled ? 'active' : ''}`}>
                      <div className="settings-model-toggle-thumb" />
                    </div>
                  </div>
                  <div className="settings-model-info">
                    <span className="settings-model-name">{model.name}</span>
                    <span className="settings-model-meta">
                      {[model.parameter_size, model.quantization, formatSize(model.size)]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </div>
                </div>
              );
            })}
        </div>

        {/* ====== ANTHROPIC SECTION ====== */}
        {renderCloudModels('anthropic', anthropicModels, 'anthropic')}

        {/* ====== OPENAI SECTION ====== */}
        {renderCloudModels('openai', openaiModels, 'openai')}

        {/* ====== GEMINI SECTION ====== */}
        {renderCloudModels('gemini', geminiModels, 'gemini')}
      </div>
    </div>
  );
};

export default SettingsModels;
export { SettingsModels };
