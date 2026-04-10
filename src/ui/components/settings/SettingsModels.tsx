import React, { useState, useEffect, useCallback } from 'react';
import {
  api,
  type ProviderModel,
  type OllamaModel,
  type OllamaRegistryModelInfo,
} from '../../services/api';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { formatModelLabel, getProviderLabel } from '../../utils/modelDisplay';
import { RotateCcwIcon } from '../icons/AppIcons';
import '../../CSS/settings/SettingsModels.css';

type CloudProvider = 'anthropic' | 'openai' | 'gemini' | 'openrouter';
type ProviderKey = CloudProvider | 'ollama';

const CLOUD_PROVIDERS: CloudProvider[] = ['anthropic', 'openai', 'gemini', 'openrouter'];
const KNOWN_CLOUD_PROVIDERS = new Set<CloudProvider>(CLOUD_PROVIDERS);

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

function normalizeOllamaModelName(modelName: string): string {
  const trimmed = modelName.trim();
  if (trimmed.toLowerCase().startsWith('ollama/')) {
    return trimmed.slice('ollama/'.length).trim();
  }
  return trimmed;
}

function isOllamaModelId(modelName: string): boolean {
  const trimmed = modelName.trim();
  if (!trimmed) {
    return false;
  }

  if (trimmed.toLowerCase().startsWith('ollama/')) {
    return true;
  }

  const slashIndex = trimmed.indexOf('/');
  if (slashIndex === -1) {
    return true;
  }

  const provider = trimmed.slice(0, slashIndex).toLowerCase() as CloudProvider;
  return !KNOWN_CLOUD_PROVIDERS.has(provider);
}

function buildCustomOllamaModel(name: string): OllamaModel {
  const normalized = normalizeOllamaModelName(name);
  return {
    name: normalized,
    size: 0,
    parameter_size: '',
    quantization: '',
    source: 'custom',
    is_local: true,
  };
}

function mergeOllamaModels(models: OllamaModel[], enabledModels: string[]): OllamaModel[] {
  const merged = new Map<string, OllamaModel>();

  models.forEach((model) => {
    const normalized = normalizeOllamaModelName(model.name);
    if (!normalized) {
      return;
    }
    merged.set(normalized.toLowerCase(), { ...model, name: normalized });
  });

  enabledModels
    .filter((modelName) => isOllamaModelId(modelName))
    .map((modelName) => normalizeOllamaModelName(modelName))
    .filter(Boolean)
    .forEach((modelName) => {
      const key = modelName.toLowerCase();
      if (!merged.has(key)) {
        merged.set(key, buildCustomOllamaModel(modelName));
      }
    });

  return Array.from(merged.values());
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
  const { send, subscribe } = useWebSocket();
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [cloudModels, setCloudModels] = useState<Record<CloudProvider, ProviderModel[]>>(EMPTY_CLOUD_MODELS);
  const [keyStatus, setKeyStatus] = useState<Record<string, { has_key: boolean; masked: string | null }>>({});
  const [enabledModels, setEnabledModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [providerErrors, setProviderErrors] = useState<Record<ProviderKey, string>>(EMPTY_PROVIDER_ERRORS);
  const [refreshingProviders, setRefreshingProviders] = useState<Record<ProviderKey, boolean>>(EMPTY_REFRESHING_STATE);
  const [customOllamaModel, setCustomOllamaModel] = useState('');
  const [customOllamaError, setCustomOllamaError] = useState('');

  // Model pull modal state
  const [pullModalOpen, setPullModalOpen] = useState(false);
  const [pullModelName, setPullModelName] = useState('');
  const [pullModelInfo, setPullModelInfo] = useState<OllamaRegistryModelInfo | null>(null);
  const [pullInfoLoading, setPullInfoLoading] = useState(false);
  const [pullInProgress, setPullInProgress] = useState(false);
  const [pullProgress, setPullProgress] = useState<{
    status: string;
    percent: number;
    completed: number;
    total: number;
  } | null>(null);
  const [pullComplete, setPullComplete] = useState(false);
  const [pullError, setPullError] = useState('');
  const [pullConfirmChecked, setPullConfirmChecked] = useState(false);

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
      const normalizedName = isOllamaModelId(modelName)
        ? normalizeOllamaModelName(modelName)
        : modelName;

      setEnabledModels((prev) => {
        const isEnabled = prev.includes(normalizedName);
        const updated = isEnabled
          ? prev.filter((m) => m !== normalizedName)
          : [...prev, normalizedName];

        // Persist to backend (SQLite) — fire-and-forget
        void api.setEnabledModels(updated);

        return updated;
      });
    },
    [],
  );

  const buildPullErrorMessage = useCallback((rawError: string, modelName: string) => {
    const message = rawError.trim();
    const lowered = message.toLowerCase();

    if (
      lowered.includes('not found')
      || lowered.includes('pull model manifest')
      || lowered.includes('manifest')
    ) {
      return `Could not find model "${modelName}". Check the model name/tag, verify it exists in Ollama, or update Ollama and try again.`;
    }

    if (lowered.includes('connect') || lowered.includes('connection')) {
      return 'Cannot connect to Ollama at http://localhost:11434. Make sure Ollama is running and try again.';
    }

    return message || 'Failed to pull model.';
  }, []);

  // Subscribe to WebSocket messages for pull progress
  useEffect(() => {
    let isMounted = true;

    const unsubscribe = subscribe((data) => {
      const type = data.type as string;
      if (!['ollama_pull_progress', 'ollama_pull_complete', 'ollama_pull_error', 'ollama_pull_cancelled'].includes(type)) {
        return;
      }

      const content = data.content as Record<string, unknown>;
      const messageModelName = normalizeOllamaModelName(String(content.model_name ?? ''));

      // Ignore pull events from other model names
      if (pullModelName && messageModelName && messageModelName !== pullModelName) {
        return;
      }

      if (!isMounted) {
        return;
      }

      switch (type) {
        case 'ollama_pull_progress': {
          setPullProgress({
            status: String(content.status ?? 'Downloading...'),
            percent: Number(content.percent ?? 0),
            completed: Number(content.completed ?? 0),
            total: Number(content.total ?? 0),
          });
          break;
        }
        case 'ollama_pull_complete': {
          setPullInProgress(false);
          setPullComplete(true);
          setPullProgress(null);
          setPullError('');

          const modelName = messageModelName || pullModelName;
          if (modelName) {
            setEnabledModels((prev) => {
              if (prev.includes(modelName)) {
                return prev;
              }
              const updated = [...prev, modelName];
              void api.setEnabledModels(updated);
              return updated;
            });
          }

          void loadOllamaModels(true);
          break;
        }
        case 'ollama_pull_error': {
          setPullInProgress(false);
          setPullProgress(null);
          const rawError = String(content.error ?? 'Failed to pull model');
          setPullError(buildPullErrorMessage(rawError, pullModelName || messageModelName || 'this model'));
          break;
        }
        case 'ollama_pull_cancelled': {
          setPullInProgress(false);
          setPullProgress(null);
          setPullError('Model pull cancelled.');
          break;
        }
      }
    });

    return () => {
      isMounted = false;
      unsubscribe();
    };
  }, [subscribe, loadOllamaModels, pullModelName, buildPullErrorMessage]);

  const loadPullModelInfo = useCallback(async (normalized: string) => {
    setPullInfoLoading(true);
    setPullError('');

    const result = await api.getOllamaModelInfo(normalized);
    if (result.success && result.data) {
      setPullModelInfo(result.data);

      if (result.data.is_installed) {
        setEnabledModels((prev) => {
          if (prev.includes(normalized)) return prev;
          const updated = [...prev, normalized];
          void api.setEnabledModels(updated);
          return updated;
        });

        setCustomOllamaModel('');
        setPullModalOpen(false);
        setPullModelName('');
        setPullModelInfo(null);
        setPullInfoLoading(false);
        void loadOllamaModels(true);
        return;
      }
    } else {
      setPullModelInfo(null);
      setPullError(result.error || 'Failed to fetch model info');
    }

    setPullInfoLoading(false);
  }, [loadOllamaModels]);

  // Handler for the "Add" button - opens pull confirmation modal
  const handleAddCustomModel = useCallback(async () => {
    const normalized = normalizeOllamaModelName(customOllamaModel);

    if (!normalized) {
      setCustomOllamaError('Enter an Ollama model name.');
      return;
    }

    if (!isOllamaModelId(customOllamaModel)) {
      setCustomOllamaError('Use an Ollama model ID like llama3.2 or ollama/llama3.2.');
      return;
    }

    setCustomOllamaError('');

    // Check if model is already installed locally
    const existingModel = ollamaModels.find(
      m => m.name.toLowerCase() === normalized.toLowerCase()
    );

    if (existingModel) {
      // Already installed, just add to enabled list
      setEnabledModels((prev) => {
        if (prev.includes(normalized)) return prev;
        const updated = [...prev, normalized];
        void api.setEnabledModels(updated);
        return updated;
      });
      setCustomOllamaModel('');
      return;
    }

    // Open pull confirmation modal
    setPullModalOpen(true);
    setPullModelName(normalized);
    setPullModelInfo(null);
    setPullInfoLoading(true);
    setPullComplete(false);
    setPullError('');
    setPullProgress(null);
    setPullConfirmChecked(false);

    await loadPullModelInfo(normalized);
  }, [customOllamaModel, ollamaModels, loadPullModelInfo]);

  // Start pulling the model
  const startPullModel = useCallback(() => {
    if (!pullModelName || !pullConfirmChecked) {
      return;
    }

    setPullInProgress(true);
    setPullComplete(false);
    setPullError('');
    setPullProgress({ status: 'Starting download...', percent: 0, completed: 0, total: 0 });

    send({ type: 'ollama_pull_model', model_name: pullModelName });
  }, [pullModelName, pullConfirmChecked, send]);

  const cancelPullModel = useCallback(() => {
    if (!pullInProgress || !pullModelName) {
      return;
    }
    send({ type: 'ollama_cancel_pull', model_name: pullModelName });
  }, [pullInProgress, pullModelName, send]);

  // Close the modal
  const closePullModal = useCallback(() => {
    if (pullInProgress) {
      return;
    }

    setPullModalOpen(false);
    setPullModelName('');
    setPullModelInfo(null);
    setPullInfoLoading(false);
    setPullComplete(false);
    setPullError('');
    setPullProgress(null);
    setPullConfirmChecked(false);

    if (pullComplete) {
      setCustomOllamaModel('');
    }
  }, [pullInProgress, pullComplete]);

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
        title={refreshingProviders[provider] ? 'Refreshing...' : 'Refresh'}
      >
        {refreshingProviders[provider] ? <RotateCcwIcon className="spin" size={14} /> : <RotateCcwIcon size={14} />}
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

  const visibleOllamaModels = mergeOllamaModels(ollamaModels, enabledModels);

  return (
    <div className="settings-models-section">
      <div className="settings-models-header">
        <h2>Models</h2>
        <p>Enable or disable models for your workspace.</p>
      </div>
      <div className="settings-models-ollama-section">
        {renderSectionHeader('ollama', 'Ollama', 'ollama')}

        <div className="settings-models-ollama-content">
          <div className="settings-models-ollama-custom">
            <div className="settings-models-ollama-custom-copy">
              What to use more Ollama models? Add them below!
            </div>
            <div className="settings-models-ollama-custom-row">
              <input
                className="settings-models-ollama-input"
                type="text"
                value={customOllamaModel}
                onChange={(e) => {
                  setCustomOllamaModel(e.target.value);
                  if (customOllamaError) {
                    setCustomOllamaError('');
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    void handleAddCustomModel();
                  }
                }}
                placeholder="Ex: qwen3.5:9b, qwen3.5:cloud"
              />
              <button
                className="settings-models-refresh-btn settings-models-add-btn"
                onClick={() => void handleAddCustomModel()}
                disabled={loading}
              >
                Add
              </button>
            </div>
            {customOllamaError && (
              <div className="settings-models-ollama-custom-error">{customOllamaError}</div>
            )}
          </div>

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
          {!loading && !error && visibleOllamaModels.length === 0 && (
            <div className="settings-models-ollama-model settings-models-empty">
              No Ollama models found. Pull one with <code>ollama pull model-name</code> or add a custom model ID above.
            </div>
          )}
          {!loading &&
            visibleOllamaModels.map((model) => {
              const isEnabled = enabledModels.includes(model.name);
                const metaParts = [
                  model.source === 'custom'
                  ? 'Custom'
                  : '',
                model.parameter_size,
                model.quantization,
                formatSize(model.size),
              ].filter(Boolean);
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
                      {metaParts.join(' · ')}
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

      {/* Model Pull Confirmation Modal */}
      {pullModalOpen && pullModelName && (
        <div className="settings-models-modal-overlay" onClick={closePullModal}>
          <div className="settings-models-modal" onClick={(e) => e.stopPropagation()}>
            <div className="settings-models-modal-header">
              <h3>{pullComplete ? 'Model Ready' : pullInProgress ? 'Pulling Model' : 'Confirm Pull'}</h3>
              {!pullInProgress && (
                <button className="settings-models-modal-close" onClick={closePullModal}>
                  {pullComplete ? 'Done' : 'Cancel'}
                </button>
              )}
            </div>
            <div className="settings-models-modal-body">
              {/* Confirmation state */}
              {!pullInProgress && !pullComplete && (
                <>
                  {pullInfoLoading && (
                    <div className="settings-models-modal-loading">Fetching model info from Ollama registry...</div>
                  )}

                  {!pullInfoLoading && !pullError && (
                    <>
                      <div className="settings-models-modal-info">
                        <div className="settings-models-modal-row">
                          <span className="settings-models-modal-label">Model</span>
                          <span className="settings-models-modal-value">{pullModelInfo?.full_name || pullModelName}</span>
                        </div>

                        {!!pullModelInfo?.family && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Family</span>
                            <span className="settings-models-modal-value">{pullModelInfo.family}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.parameter_size && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Parameters</span>
                            <span className="settings-models-modal-value">{pullModelInfo.parameter_size}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.quantization && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Quantization</span>
                            <span className="settings-models-modal-value">{pullModelInfo.quantization}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.format && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Format</span>
                            <span className="settings-models-modal-value">{pullModelInfo.format}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.architecture && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Architecture</span>
                            <span className="settings-models-modal-value">{pullModelInfo.architecture}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.os && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">OS</span>
                            <span className="settings-models-modal-value">{pullModelInfo.os}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.total_size_human && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Download Size</span>
                            <span className="settings-models-modal-value">{pullModelInfo.total_size_human}</span>
                          </div>
                        )}

                        {!!pullModelInfo?.layers?.length && (
                          <div className="settings-models-modal-row">
                            <span className="settings-models-modal-label">Layers</span>
                            <span className="settings-models-modal-value">{pullModelInfo.layers.length}</span>
                          </div>
                        )}
                      </div>

                      <div className="settings-models-modal-warning">
                        Pulling this model will start a local Ollama download. For cloud-tagged models,
                        Ollama may only pull the manifest first and stream layer progress as needed.
                      </div>
                      <label className="settings-models-modal-confirm">
                        <input
                          type="checkbox"
                          checked={pullConfirmChecked}
                          onChange={(e) => setPullConfirmChecked(e.target.checked)}
                        />
                        <span>I understand this will download model data via Ollama.</span>
                      </label>
                      <div className="settings-models-modal-note">
                        If pull fails, it may mean the model name/tag is incorrect, the model doesn't exist,
                        or your Ollama version needs updating.
                      </div>
                    </>
                  )}
                </>
              )}

              {/* Pull Progress */}
              {pullInProgress && pullProgress && (
                <div className="settings-models-pull-progress">
                  <div className="settings-models-pull-status">
                    {pullProgress.status}
                  </div>
                  <div className="settings-models-pull-bar-container">
                    <div
                      className="settings-models-pull-bar"
                      style={{ width: `${pullProgress.percent}%` }}
                    />
                  </div>
                  <div className="settings-models-pull-percent">
                    {pullProgress.percent > 0 ? `${pullProgress.percent}%` : 'Starting...'}
                  </div>
                </div>
              )}

              {/* Pull Complete */}
              {pullComplete && (
                <div className="settings-models-pull-complete">
                  <div className="settings-models-pull-complete-icon">✓</div>
                  <div className="settings-models-pull-complete-text">
                    Model is ready to use
                  </div>
                </div>
              )}

              {/* Pull Error */}
              {pullError && (
                <div className="settings-models-modal-error">
                  {pullError}
                </div>
              )}
            </div>

            {/* Footer buttons */}
            {!pullComplete && !pullInProgress && !pullError && !pullInfoLoading && (
              <div className="settings-models-modal-footer">
                <button
                  className="settings-models-modal-btn"
                  onClick={closePullModal}
                >
                  Cancel
                </button>
                <button
                  className="settings-models-modal-btn settings-models-modal-btn-primary"
                  onClick={startPullModel}
                  disabled={!pullConfirmChecked}
                >
                  Confirm & Pull
                </button>
              </div>
            )}

            {pullComplete && (
              <div className="settings-models-modal-footer">
                <button
                  className="settings-models-modal-btn settings-models-modal-btn-primary"
                  onClick={closePullModal}
                >
                  Done
                </button>
              </div>
            )}

            {pullInProgress && (
              <div className="settings-models-modal-footer">
                <button
                  className="settings-models-modal-btn"
                  onClick={cancelPullModel}
                >
                  Cancel Pull
                </button>
              </div>
            )}

            {pullError && !pullInProgress && (
              <div className="settings-models-modal-footer">
                <button
                  className="settings-models-modal-btn"
                  onClick={closePullModal}
                >
                  Close
                </button>
                <button
                  className="settings-models-modal-btn settings-models-modal-btn-primary"
                  onClick={() => {
                    setPullError('');
                    setPullConfirmChecked(false);
                    void loadPullModelInfo(pullModelName);
                  }}
                >
                  Try Again
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsModels;
export { SettingsModels };
