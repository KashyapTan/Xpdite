import React, { useState, useEffect, useCallback } from 'react';
import { api, type ProviderModel } from '../../services/api';
import { formatModelLabel, getProviderLabel } from '../../utils/modelDisplay';
import '../../CSS/SettingsModels.css';

interface OllamaModel {
  name: string;
  size: number;
  parameter_size: string;
  quantization: string;
}

type CloudProvider = 'anthropic' | 'openai' | 'gemini' | 'openrouter';
type ProviderKey = CloudProvider | 'ollama';

const CLOUD_PROVIDERS: CloudProvider[] = ['anthropic', 'openai', 'gemini', 'openrouter'];

const EMPTY_CLOUD_MODELS: Record<CloudProvider, ProviderModel[]> = {
  anthropic: [],
  openai: [],
  gemini: [],
  openrouter: [],
};

const EMPTY_PROVIDER_ERRORS: Record<ProviderKey, string> = {
  ollama: '',
  anthropic: '',
  openai: '',
  gemini: '',
  openrouter: '',
};

const EMPTY_REFRESHING_STATE: Record<ProviderKey, boolean> = {
  ollama: false,
  anthropic: false,
  openai: false,
  gemini: false,
  openrouter: false,
};

function toEnabledModelId(provider: CloudProvider, modelId: string): string {
  if (provider === 'openrouter' && !modelId.startsWith('openrouter/')) {
    return `openrouter/${modelId}`;
  }
  return modelId;
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
 * 6. Allow cache-busting refresh for each provider section.
 */
const SettingsModels: React.FC = () => {
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [cloudModels, setCloudModels] = useState<Record<CloudProvider, ProviderModel[]>>(EMPTY_CLOUD_MODELS);
  const [keyStatus, setKeyStatus] = useState<Record<string, { has_key: boolean; masked: string | null }>>({});
  const [enabledModels, setEnabledModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [providerErrors, setProviderErrors] = useState<Record<ProviderKey, string>>(EMPTY_PROVIDER_ERRORS);
  const [refreshingProviders, setRefreshingProviders] = useState<Record<ProviderKey, boolean>>(EMPTY_REFRESHING_STATE);

  const setProviderError = useCallback((provider: ProviderKey, message: string) => {
    setProviderErrors((prev) => ({ ...prev, [provider]: message }));
  }, []);

  const loadOllamaModels = useCallback(async (refresh = false) => {
    const result = await api.getOllamaModels(refresh);
    setOllamaModels(result.models);
    setProviderError('ollama', result.error ?? '');
  }, [setProviderError]);

  const loadCloudProviderModels = useCallback(async (provider: CloudProvider, refresh = false) => {
    try {
      const models = await api.getProviderModels(provider, refresh);
      setCloudModels((prev) => ({ ...prev, [provider]: models }));
      setProviderError(provider, '');
    } catch (e: unknown) {
      const message =
        e instanceof Error
          ? e.message
          : `Failed to fetch ${getProviderLabel(provider)} models`;
      setCloudModels((prev) => ({ ...prev, [provider]: [] }));
      setProviderError(provider, message);
    }
  }, [setProviderError]);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const [enabled, keys] = await Promise.all([
          api.getEnabledModels(),
          api.getApiKeyStatus(),
        ]);

        setEnabledModels(enabled);
        setKeyStatus(keys);

        await loadOllamaModels(false);

        await Promise.all(
          CLOUD_PROVIDERS.map(async (provider) => {
            if (keys[provider]?.has_key) {
              await loadCloudProviderModels(provider, false);
              return;
            }

            setCloudModels((prev) => ({ ...prev, [provider]: [] }));
            setProviderError(provider, '');
          }),
        );
      } catch {
        setError('Could not reach the backend. Is the server running?');
      } finally {
        setLoading(false);
      }
    };

    void fetchData();
  }, [loadCloudProviderModels, loadOllamaModels, setProviderError]);

  const refreshProviderModels = useCallback(async (provider: ProviderKey) => {
    setRefreshingProviders((prev) => ({ ...prev, [provider]: true }));
    try {
      if (provider === 'ollama') {
        await loadOllamaModels(true);
        return;
      }

      await loadCloudProviderModels(provider, true);
    } finally {
      setRefreshingProviders((prev) => ({ ...prev, [provider]: false }));
    }
  }, [loadCloudProviderModels, loadOllamaModels]);

  const toggleModel = useCallback(
    async (modelName: string) => {
      setEnabledModels((prev) => {
        const isEnabled = prev.includes(modelName);
        const updated = isEnabled
          ? prev.filter((m) => m !== modelName)
          : [...prev, modelName];

        // Persist to backend (SQLite) — fire-and-forget
        void api.setEnabledModels(updated);

        return updated;
      });
    },
    [],
  );

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(0)} MB`;
  };

  const formatContextLength = (contextLength?: number) => {
    if (typeof contextLength !== 'number') {
      return '';
    }

    return `${new Intl.NumberFormat().format(contextLength)} ctx`;
  };

  const renderSectionHeader = (
    provider: ProviderKey,
    label: string,
    classPrefix: string,
  ) => (
    <div className={`settings-models-${classPrefix}-header settings-models-provider-header`}>
      <span>{label}</span>
      <button
        className="settings-models-refresh-btn"
        onClick={() => {
          void refreshProviderModels(provider);
        }}
        disabled={refreshingProviders[provider] || loading}
      >
        {refreshingProviders[provider] ? 'Refreshing...' : 'Refresh'}
      </button>
    </div>
  );

  const renderCloudModelRow = (
    provider: CloudProvider,
    model: ProviderModel,
    classPrefix: string,
  ) => {
    const enabledModelId = toEnabledModelId(provider, model.id);
    const isEnabled = enabledModels.includes(enabledModelId);
    const modelLabel = provider === 'openrouter'
      ? model.display_name || formatModelLabel(model.id)
      : formatModelLabel(model.id);
    const metaParts: string[] = [];

    if (provider === 'openrouter') {
      const contextLabel = formatContextLength(model.context_length);
      if (contextLabel) {
        metaParts.push(contextLabel);
      }
      metaParts.push(model.id);
    } else if (model.display_name && model.display_name !== modelLabel) {
      metaParts.push(model.display_name);
    }

    return (
      <div
        key={`${provider}-${model.id}`}
        className={`settings-models-${classPrefix}-model ${isEnabled ? 'settings-models-enabled' : ''}`}
        onClick={() => {
          void toggleModel(enabledModelId);
        }}
      >
        <div className="settings-model-toggle">
          <div className={`settings-model-toggle-track ${isEnabled ? 'active' : ''}`}>
            <div className="settings-model-toggle-thumb" />
          </div>
        </div>
        <div className="settings-model-info">
          <span className="settings-model-name">{modelLabel}</span>
          <span className="settings-model-meta">{metaParts.join(' · ')}</span>
        </div>
      </div>
    );
  };

  const renderCloudModels = (
    provider: Exclude<CloudProvider, 'openrouter'>,
    classPrefix: string,
  ) => {
    const models = cloudModels[provider];
    const hasKey = keyStatus[provider]?.has_key;
    const providerError = providerErrors[provider];

    return (
      <>
        {renderSectionHeader(provider, getProviderLabel(provider), classPrefix)}
        <div className={`settings-models-${classPrefix}-content`}>
          {!hasKey && (
            <div className={`settings-models-${classPrefix}-model settings-models-placeholder`}>
              No API key configured. Add one in the {getProviderLabel(provider)} tab.
            </div>
          )}

          {hasKey && providerError && (
            <div className={`settings-models-${classPrefix}-model settings-models-error`}>
              {providerError}
            </div>
          )}

          {hasKey && !providerError && models.length === 0 && !loading && (
            <div className={`settings-models-${classPrefix}-model settings-models-placeholder`}>
              No models available.
            </div>
          )}

          {hasKey && !providerError && models.map((model) => renderCloudModelRow(provider, model, classPrefix))}
        </div>
      </>
    );
  };

  const renderOpenRouterModels = () => {
    const provider: CloudProvider = 'openrouter';
    const classPrefix = 'openrouter';
    const models = cloudModels.openrouter;
    const hasKey = keyStatus.openrouter?.has_key;
    const providerError = providerErrors.openrouter;

    const groups = new Map<string, ProviderModel[]>();
    models.forEach((model) => {
      const group = (model.provider_group || 'openrouter').toLowerCase();
      const existing = groups.get(group) ?? [];
      existing.push(model);
      groups.set(group, existing);
    });

    const groupedSections: Array<{ group: string; models: ProviderModel[] }> = [];
    const ungrouped: ProviderModel[] = [];

    Array.from(groups.entries())
      .sort(([groupA], [groupB]) => groupA.localeCompare(groupB))
      .forEach(([group, groupedModels]) => {
        if (groupedModels.length > 1) {
          groupedSections.push({
            group,
            models: [...groupedModels].sort((a, b) => (
              (a.display_name || a.id).localeCompare(b.display_name || b.id)
            )),
          });
          return;
        }

        ungrouped.push(groupedModels[0]);
      });

    ungrouped.sort((a, b) => (a.display_name || a.id).localeCompare(b.display_name || b.id));

    return (
      <>
        {renderSectionHeader(provider, 'OpenRouter', classPrefix)}
        <div className={`settings-models-${classPrefix}-content`}>
          {!hasKey && (
            <div className="settings-models-openrouter-model settings-models-placeholder">
              Add your OpenRouter API key in the API Keys tab to browse models.
            </div>
          )}

          {hasKey && providerError && (
            <div className="settings-models-openrouter-model settings-models-error">
              {providerError}
            </div>
          )}

          {hasKey && !providerError && models.length === 0 && !loading && (
            <div className="settings-models-openrouter-model settings-models-placeholder">
              No tool-compatible OpenRouter models were returned.
            </div>
          )}

          {hasKey && !providerError && ungrouped.map((model) => renderCloudModelRow(provider, model, classPrefix))}

          {hasKey && !providerError && groupedSections.map(({ group, models: groupedModels }) => (
            <div key={`group-${group}`} className="settings-models-provider-group">
              <div className="settings-models-provider-group-header">{getProviderLabel(group)}</div>
              {groupedModels.map((model) => renderCloudModelRow(provider, model, classPrefix))}
            </div>
          ))}
        </div>
      </>
    );
  };

  return (
    <div className="settings-models-section">
      <div className="settings-models-header">
        <h2>Models</h2>
        <p>Enable or disable models for your workspace.</p>
      </div>
      <div className="settings-models-ollama-section">
        {renderSectionHeader('ollama', 'Ollama', 'ollama')}

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
          {!loading && !error && providerErrors.ollama && (
            <div className="settings-models-ollama-model settings-models-error">
              {providerErrors.ollama}
            </div>
          )}
          {!loading && !error && !providerErrors.ollama && ollamaModels.length === 0 && (
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
                  onClick={() => {
                    void toggleModel(model.name);
                  }}
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

        {renderCloudModels('anthropic', 'anthropic')}
        {renderCloudModels('openai', 'openai')}
        {renderCloudModels('gemini', 'gemini')}
        {renderOpenRouterModels()}
      </div>
    </div>
  );
};

export default SettingsModels;
export { SettingsModels };
