import React, { useCallback, useEffect, useState } from 'react';
import { api, type OpenAICodexStatus } from '../../services/api';
import '../../CSS/settings/SettingsApiKey.css';

interface SettingsApiKeyProps {
  provider: 'anthropic' | 'openai' | 'gemini' | 'openrouter';
}

const emptyCodexStatus: OpenAICodexStatus = {
  available: false,
  connected: false,
  account_type: null,
  email: null,
  plan_type: null,
  requires_openai_auth: true,
  auth_in_progress: false,
  login_method: null,
  login_id: null,
  auth_url: null,
  verification_url: null,
  user_code: null,
  auth_mode: null,
  last_error: null,
  binary_path: null,
};

function getProviderLabel(provider: SettingsApiKeyProps['provider']): string {
  if (provider === 'anthropic') return 'Anthropic';
  if (provider === 'openai') return 'OpenAI';
  if (provider === 'gemini') return 'Gemini';
  return 'OpenRouter';
}

async function openExternalUrl(url: string): Promise<void> {
  const electronOpen = window.electronAPI?.openExternalUrl;
  if (electronOpen) {
    const result = await electronOpen(url);
    if (result?.success) {
      return;
    }
  }

  window.open(url, '_blank', 'noopener,noreferrer');
}

/**
 * SettingsApiKey — API key management for a cloud provider.
 *
 * The OpenAI tab also exposes ChatGPT sign-in so users can route models through
 * their ChatGPT subscription without a Platform key.
 */
const SettingsApiKey: React.FC<SettingsApiKeyProps> = ({ provider }) => {
  const [hasKey, setHasKey] = useState(false);
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(true);
  const [codexStatus, setCodexStatus] = useState<OpenAICodexStatus>(emptyCodexStatus);
  const [codexLoading, setCodexLoading] = useState(false);
  const [codexBusy, setCodexBusy] = useState(false);
  const [codexError, setCodexError] = useState('');
  const [codexSuccess, setCodexSuccess] = useState('');

  const providerLabel = getProviderLabel(provider);

  const refreshCodexStatus = useCallback(async (showLoading = false) => {
    if (provider !== 'openai') {
      return;
    }

    if (showLoading) {
      setCodexLoading(true);
    }
    try {
      const status = await api.getOpenAICodexStatus();
      setCodexStatus(status);
      setCodexError(status.last_error ?? '');
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to load ChatGPT subscription status';
      setCodexError(message);
    } finally {
      if (showLoading) {
        setCodexLoading(false);
      }
    }
  }, [provider]);

  useEffect(() => {
    const fetchStatus = async () => {
      setLoading(true);
      try {
        const status = await api.getApiKeyStatus();
        const providerStatus = status[provider];
        if (providerStatus) {
          setHasKey(providerStatus.has_key);
          setMaskedKey(providerStatus.masked);
        }
      } catch {
        // Ignore — will show input state.
      } finally {
        setLoading(false);
      }
    };

    void fetchStatus();
  }, [provider]);

  useEffect(() => {
    if (provider === 'openai') {
      void refreshCodexStatus(true);
    }
  }, [provider, refreshCodexStatus]);

  useEffect(() => {
    if (provider !== 'openai' || !codexStatus.auth_in_progress) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      void refreshCodexStatus(false);
    }, 2000);

    return () => window.clearInterval(intervalId);
  }, [codexStatus.auth_in_progress, provider, refreshCodexStatus]);

  const handleSave = async () => {
    const key = inputValue.trim();
    if (!key) {
      setError('Please enter an API key');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const result = await api.saveApiKey(provider, key);
      setHasKey(true);
      setMaskedKey(result.masked);
      setInputValue('');
      setSuccess('API key saved and validated');
      setTimeout(() => setSuccess(''), 3000);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to save API key';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setError('');
    setSuccess('');
    await api.deleteApiKey(provider);
    setHasKey(false);
    setMaskedKey(null);
    setSuccess('API key removed');
    setTimeout(() => setSuccess(''), 3000);
  };

  const handleCodexBrowserConnect = async () => {
    setCodexBusy(true);
    setCodexError('');
    setCodexSuccess('');
    try {
      const status = await api.connectOpenAICodexBrowser();
      setCodexStatus(status);
      if (status.auth_url) {
        await openExternalUrl(status.auth_url);
        setCodexSuccess('ChatGPT sign-in opened in your browser');
      }
    } catch (e: unknown) {
      setCodexError(e instanceof Error ? e.message : 'Failed to start ChatGPT sign-in');
    } finally {
      setCodexBusy(false);
    }
  };

  const handleCodexDeviceConnect = async () => {
    setCodexBusy(true);
    setCodexError('');
    setCodexSuccess('');
    try {
      const status = await api.connectOpenAICodexDevice();
      setCodexStatus(status);
      setCodexSuccess('Device-code sign-in started');
    } catch (e: unknown) {
      setCodexError(e instanceof Error ? e.message : 'Failed to start device-code sign-in');
    } finally {
      setCodexBusy(false);
    }
  };

  const handleCodexCancel = async () => {
    setCodexBusy(true);
    setCodexError('');
    setCodexSuccess('');
    try {
      const status = await api.cancelOpenAICodexLogin();
      setCodexStatus(status);
    } catch (e: unknown) {
      setCodexError(e instanceof Error ? e.message : 'Failed to cancel ChatGPT sign-in');
    } finally {
      setCodexBusy(false);
    }
  };

  const handleCodexDisconnect = async () => {
    setCodexBusy(true);
    setCodexError('');
    setCodexSuccess('');
    try {
      const status = await api.disconnectOpenAICodex();
      setCodexStatus(status);
      setCodexSuccess('ChatGPT subscription disconnected');
      setTimeout(() => setCodexSuccess(''), 3000);
    } catch (e: unknown) {
      setCodexError(e instanceof Error ? e.message : 'Failed to disconnect ChatGPT subscription');
    } finally {
      setCodexBusy(false);
    }
  };

  const handleOpenDeviceUrl = async () => {
    if (codexStatus.verification_url) {
      await openExternalUrl(codexStatus.verification_url);
    }
  };

  const handleCopyDeviceCode = async () => {
    if (!codexStatus.user_code) {
      return;
    }

    await navigator.clipboard?.writeText(codexStatus.user_code);
    setCodexSuccess('Device code copied');
    setTimeout(() => setCodexSuccess(''), 2000);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !saving) {
      void handleSave();
    }
  };

  const renderCodexPanel = () => {
    if (provider !== 'openai') {
      return null;
    }

    const connectedLabel = [
      codexStatus.email,
      codexStatus.plan_type ? `${codexStatus.plan_type} plan` : null,
    ].filter(Boolean).join(' · ');

    return (
      <div className="settings-apikey-panel settings-codex-panel">
        <div className="settings-apikey-header">
          <h2>ChatGPT Subscription</h2>
          <p>Use your ChatGPT Plus or Pro account through Xpdite's LiteLLM tool loop.</p>
        </div>

        <div className="settings-apikey-content">
          {codexLoading && (
            <div className="settings-apikey-loading">Loading...</div>
          )}

          {!codexLoading && !codexStatus.available && (
            <div className="settings-codex-state settings-apikey-error">
              {codexError || 'OpenAI Codex runtime is not available.'}
            </div>
          )}

          {!codexLoading && codexStatus.available && codexStatus.connected && (
            <div className="settings-apikey-stored">
              <div className="settings-apikey-stored-info">
                <span className="settings-apikey-masked">
                  {connectedLabel || 'ChatGPT account'}
                </span>
                <span className="settings-apikey-status">Connected</span>
              </div>
              <button
                className="settings-apikey-delete-btn"
                onClick={() => void handleCodexDisconnect()}
                disabled={codexBusy}
              >
                Disconnect
              </button>
            </div>
          )}

          {!codexLoading && codexStatus.available && !codexStatus.connected && (
            <div className="settings-codex-connect">
              <div className="settings-codex-state">
                {codexStatus.auth_in_progress ? 'Waiting for ChatGPT sign-in...' : 'Not connected'}
              </div>
              <div className="settings-codex-actions">
                {!codexStatus.auth_in_progress && (
                  <>
                    <button
                      className="settings-apikey-save-btn"
                      onClick={() => void handleCodexBrowserConnect()}
                      disabled={codexBusy}
                    >
                      Connect
                    </button>
                    <button
                      className="settings-apikey-secondary-btn"
                      onClick={() => void handleCodexDeviceConnect()}
                      disabled={codexBusy}
                    >
                      Device Code
                    </button>
                  </>
                )}
                {codexStatus.auth_in_progress && (
                  <button
                    className="settings-apikey-secondary-btn"
                    onClick={() => void handleCodexCancel()}
                    disabled={codexBusy}
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>
          )}

          {codexStatus.auth_in_progress && codexStatus.user_code && (
            <div className="settings-codex-device">
              <div className="settings-codex-code">{codexStatus.user_code}</div>
              <div className="settings-codex-device-actions">
                <button
                  className="settings-apikey-secondary-btn"
                  onClick={() => void handleCopyDeviceCode()}
                >
                  Copy Code
                </button>
                {codexStatus.verification_url && (
                  <button
                    className="settings-apikey-secondary-btn"
                    onClick={() => void handleOpenDeviceUrl()}
                  >
                    Open Page
                  </button>
                )}
              </div>
            </div>
          )}

          {codexError && codexStatus.available && (
            <div className="settings-apikey-error">{codexError}</div>
          )}
          {codexSuccess && (
            <div className="settings-apikey-success">{codexSuccess}</div>
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="settings-apikey-section">
        <div className="settings-apikey-loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="settings-apikey-section">
      <div className="settings-apikey-panel">
        <div className="settings-apikey-header">
          <h2>{providerLabel} API Key</h2>
          <p>Manage your {providerLabel} API key connection.</p>
        </div>

        <div className="settings-apikey-content">
          {hasKey ? (
            <div className="settings-apikey-stored">
              <div className="settings-apikey-stored-info">
                <span className="settings-apikey-masked">{maskedKey}</span>
                <span className="settings-apikey-status">Connected</span>
              </div>
              <button
                className="settings-apikey-delete-btn"
                onClick={() => void handleDelete()}
              >
                Remove
              </button>
            </div>
          ) : (
            <div className="settings-apikey-input-row">
              <input
                type="password"
                className="settings-apikey-input"
                placeholder={`Enter ${providerLabel} API key`}
                value={inputValue}
                onChange={(e) => {
                  setInputValue(e.target.value);
                  setError('');
                }}
                onKeyDown={handleKeyDown}
                disabled={saving}
                autoComplete="off"
                spellCheck={false}
              />
              <button
                className="settings-apikey-save-btn"
                onClick={() => void handleSave()}
                disabled={saving || !inputValue.trim()}
              >
                {saving ? 'Validating...' : 'Save'}
              </button>
            </div>
          )}

          {error && <div className="settings-apikey-error">{error}</div>}
          {success && <div className="settings-apikey-success">{success}</div>}
        </div>
      </div>

      {renderCodexPanel()}
    </div>
  );
};

export default SettingsApiKey;
