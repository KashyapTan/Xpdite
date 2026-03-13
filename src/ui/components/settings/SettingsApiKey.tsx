import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import '../../CSS/SettingsApiKey.css';

interface SettingsApiKeyProps {
  provider: 'anthropic' | 'openai' | 'gemini' | 'openrouter';
}

/**
 * SettingsApiKey — API key management for a cloud provider.
 *
 * States:
 * - No key stored: shows input field + save button
 * - Key stored: shows masked key + delete button
 * - Saving: shows validation spinner
 */
const SettingsApiKey: React.FC<SettingsApiKeyProps> = ({ provider }) => {
  const [hasKey, setHasKey] = useState(false);
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(true);

  const providerLabel =
    provider === 'anthropic'
      ? 'Anthropic'
      : provider === 'openai'
        ? 'OpenAI'
        : provider === 'gemini'
          ? 'Gemini'
          : 'OpenRouter';

  // Fetch key status on mount
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
        // Ignore — will show input state
      } finally {
        setLoading(false);
      }
    };
    fetchStatus();
  }, [provider]);

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !saving) {
      handleSave();
    }
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
      <div className="settings-apikey-header">
        <h2>{providerLabel} API Key</h2>
        <p>Manage your {providerLabel} API key connection.</p>
      </div>

      <div className="settings-apikey-content">
        {hasKey ? (
          /* Key is stored — show masked key + delete */
          <div className="settings-apikey-stored">
            <div className="settings-apikey-stored-info">
              <span className="settings-apikey-masked">{maskedKey}</span>
              <span className="settings-apikey-status">Connected</span>
            </div>
            <button
              className="settings-apikey-delete-btn"
              onClick={handleDelete}
            >
              Remove
            </button>
          </div>
        ) : (
          /* No key — show input */
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
              onClick={handleSave}
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
  );
};

export default SettingsApiKey;
