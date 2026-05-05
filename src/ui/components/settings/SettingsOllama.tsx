import React, { useEffect, useMemo, useState } from 'react';
import { api, type OllamaSettings } from '../../services/api';
import { CheckIcon } from '../icons/AppIcons';
import '../../CSS/settings/SettingsOllama.css';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const fallbackSettings: OllamaSettings = {
  local_context_size: 32768,
  default_local_context_size: 32768,
  min_local_context_size: 512,
  max_local_context_size: 1048576,
  is_custom: false,
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

const SettingsOllama: React.FC = () => {
  const [settings, setSettings] = useState<OllamaSettings>(fallbackSettings);
  const [draftContextSize, setDraftContextSize] = useState(String(fallbackSettings.local_context_size));
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const loadSettings = async () => {
      setLoading(true);
      try {
        const loaded = await api.getOllamaSettings();
        if (cancelled) {
          return;
        }
        setSettings(loaded);
        setDraftContextSize(String(loaded.local_context_size));
      } catch {
        if (!cancelled) {
          setError('Failed to load Ollama settings.');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  const parsedDraft = useMemo(() => {
    const parsed = Number(draftContextSize);
    return Number.isInteger(parsed) ? parsed : Number.NaN;
  }, [draftContextSize]);

  const validationError = useMemo(() => {
    if (!Number.isInteger(parsedDraft)) {
      return 'Enter a whole number.';
    }
    if (
      parsedDraft < settings.min_local_context_size
      || parsedDraft > settings.max_local_context_size
    ) {
      return `Use ${formatNumber(settings.min_local_context_size)} to ${formatNumber(settings.max_local_context_size)}.`;
    }
    return '';
  }, [parsedDraft, settings.max_local_context_size, settings.min_local_context_size]);

  const saveContextSize = async () => {
    if (validationError) {
      setError(validationError);
      setStatus('error');
      return;
    }

    setStatus('saving');
    setError('');
    try {
      const updated = await api.setOllamaSettings({ local_context_size: parsedDraft });
      setSettings(updated);
      setDraftContextSize(String(updated.local_context_size));
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 2000);
    } catch (saveError) {
      setStatus('error');
      setError(saveError instanceof Error ? saveError.message : 'Failed to save Ollama settings.');
    }
  };

  const resetContextSize = async () => {
    setStatus('saving');
    setError('');
    try {
      const updated = await api.setOllamaSettings({ local_context_size: null });
      setSettings(updated);
      setDraftContextSize(String(updated.local_context_size));
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 2000);
    } catch (saveError) {
      setStatus('error');
      setError(saveError instanceof Error ? saveError.message : 'Failed to reset Ollama settings.');
    }
  };

  if (loading) {
    return <div className="settings-ollama-loading">Loading Ollama settings...</div>;
  }

  return (
    <div className="settings-ollama-container">
      <div className="settings-ollama-header">
        <h2>Ollama</h2>
        <p>Local model runtime settings.</p>
      </div>

      <div className="settings-ollama-card">
        <div className="settings-ollama-card-header">
          <div>
            <div className="settings-ollama-title">Local Context Size</div>
            <div className="settings-ollama-desc">
              Applied as <code>num_ctx</code> for local Ollama models only.
            </div>
          </div>
          <span className={`settings-ollama-badge ${settings.is_custom ? 'custom' : ''}`}>
            {settings.is_custom ? 'Custom' : 'Default'}
          </span>
        </div>

        <div className="settings-ollama-input-row">
          <input
            aria-label="Local Ollama context size"
            className="settings-ollama-input"
            type="number"
            min={settings.min_local_context_size}
            max={settings.max_local_context_size}
            step="1024"
            value={draftContextSize}
            onChange={(event) => {
              setDraftContextSize(event.target.value);
              setStatus('idle');
              setError('');
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                void saveContextSize();
              }
            }}
          />
          <button
            type="button"
            className="settings-ollama-button primary"
            onClick={() => void saveContextSize()}
            disabled={status === 'saving' || !!validationError}
          >
            Save
          </button>
          <button
            type="button"
            className="settings-ollama-button"
            onClick={() => void resetContextSize()}
            disabled={status === 'saving' || !settings.is_custom}
          >
            Reset
          </button>
        </div>

        <div className="settings-ollama-meta">
          <span>Current: {formatNumber(settings.local_context_size)}</span>
          <span>Default: {formatNumber(settings.default_local_context_size)}</span>
        </div>

        <div className="settings-ollama-note">
          Ollama cloud models continue using their advertised maximum context window.
        </div>
      </div>

      {status === 'saved' && (
        <div className="settings-ollama-status saved">
          <CheckIcon size={14} className="settings-ollama-status-icon" />
          <span>Settings saved</span>
        </div>
      )}
      {(status === 'error' || validationError) && (
        <div className="settings-ollama-status error">
          {error || validationError}
        </div>
      )}
    </div>
  );
};

export default SettingsOllama;
