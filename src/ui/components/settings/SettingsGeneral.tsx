import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { ElectronContentProtectionStatus } from '../../types';
import { PinIcon } from '../icons/AppIcons';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { api } from '../../services/api';
import '../../CSS/settings/SettingsGeneral.css';

const unavailableStatus: ElectronContentProtectionStatus = {
  enabled: false,
  active: false,
  supported: false,
};

/** Auto Mode (Instant Answer) settings, mirrored from the Python DB. */
interface AutoModeSettings {
  enabled: boolean;
  prompt: string;
  pinned_model: string;
  keep_context: boolean;
  flash: boolean;
}

function errorMessageFor(error: unknown): string {
  return error instanceof Error ? error.message : 'Unable to update content protection.';
}

const SettingsGeneral: React.FC = () => {
  const [status, setStatus] = useState<ElectronContentProtectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // ── Auto Mode ────────────────────────────────────────────────
  const { send, subscribe, isConnected } = useWebSocket();
  const [autoMode, setAutoMode] = useState<AutoModeSettings | null>(null);
  const [autoModels, setAutoModels] = useState<string[]>([]);
  // True while the user is editing the prompt textarea, so an incoming settings
  // echo (e.g. a reconnect re-fetch) doesn't overwrite unsaved edits.
  const promptFocusedRef = useRef(false);
  // Last prompt value known to be persisted, so blur only saves real changes.
  const lastSavedPromptRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadContentProtection = async () => {
      const getContentProtection = window.electronAPI?.getContentProtection;
      if (!getContentProtection) {
        if (!cancelled) {
          setStatus(unavailableStatus);
          setMessage('Content protection is only available in the desktop app.');
          setLoading(false);
        }
        return;
      }

      try {
        const currentStatus = await getContentProtection();
        if (!cancelled) {
          setStatus(currentStatus);
          setMessage(currentStatus.error ?? '');
        }
      } catch (error) {
        if (!cancelled) {
          setStatus(unavailableStatus);
          setMessage(errorMessageFor(error));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadContentProtection();

    return () => {
      cancelled = true;
    };
  }, []);

  // Load Auto Mode settings over the WebSocket and the model list for the
  // pinned-model dropdown. Re-request on (re)connect so a settings visit before
  // the socket is ready still populates.
  useEffect(() => {
    const unsubscribe = subscribe((data) => {
      if (data.type === 'auto_mode_settings') {
        const incoming = data.content as AutoModeSettings;
        if (promptFocusedRef.current) {
          // Keep the in-progress prompt edit; merge everything else.
          setAutoMode((prev) => (prev ? { ...incoming, prompt: prev.prompt } : incoming));
        } else {
          lastSavedPromptRef.current = incoming.prompt;
          setAutoMode(incoming);
        }
      } else if (data.type === '__ws_connected') {
        send({ type: 'auto_mode_get_settings' });
      }
    });
    send({ type: 'auto_mode_get_settings' });
    void api.getEnabledModels().then(setAutoModels).catch(() => setAutoModels([]));
    return unsubscribe;
  }, [send, subscribe]);

  const patchAutoMode = useCallback(
    (patch: Partial<AutoModeSettings>) => {
      setAutoMode((prev) => (prev ? { ...prev, ...patch } : prev));
      send({ type: 'auto_mode_update_settings', settings: patch });
    },
    [send],
  );

  const handleInvisibleModeChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextEnabled = event.target.checked;
    const previousStatus = status;
    const setContentProtection = window.electronAPI?.setContentProtection;

    if (!setContentProtection) {
      setStatus(unavailableStatus);
      setMessage('Content protection is only available in the desktop app.');
      return;
    }

    setSaving(true);
    setMessage('');
    setStatus({
      enabled: nextEnabled,
      active: nextEnabled,
      supported: previousStatus?.supported ?? true,
    });

    try {
      const nextStatus = await setContentProtection(nextEnabled);
      setStatus(nextStatus);
      setMessage(nextStatus.error ?? '');
    } catch (error) {
      setStatus(previousStatus ?? unavailableStatus);
      setMessage(errorMessageFor(error));
    } finally {
      setSaving(false);
    }
  };

  const invisibleModeEnabled = status?.enabled ?? false;
  const toggleDisabled = loading || saving || status?.supported === false;

  const autoLoaded = autoMode !== null;
  const autoEnabled = autoMode?.enabled ?? false;

  return (
    <div className="general-settings">
      <h2 className="general-settings-title">General</h2>

      <div className="general-settings-card">
        <div className="general-settings-card-header">
          <div className="general-settings-option">
            <span className={`general-settings-pin ${invisibleModeEnabled ? 'active' : ''}`}>
              <PinIcon size={18} />
            </span>
            <div className="general-settings-card-info">
              <h3 className="general-settings-card-title">Invisible Mode</h3>
              <p className="general-settings-card-description">
                Protects the app window from supported native screen capture on Windows and macOS.
              </p>
              <p className="general-settings-card-note">
                Some macOS capture apps that use ScreenCaptureKit may still include protected windows.
              </p>
            </div>
          </div>

          <label className="general-settings-toggle">
            <input
              type="checkbox"
              aria-label="Invisible Mode"
              checked={invisibleModeEnabled}
              disabled={toggleDisabled}
              onChange={handleInvisibleModeChange}
            />
            <span className="general-settings-toggle-slider" />
          </label>
        </div>

        <div className="general-settings-status-row">
          {loading && <span className="general-settings-status">Loading...</span>}
          {saving && <span className="general-settings-status">Saving...</span>}
          {!loading && !saving && message && (
            <span className="general-settings-warning">{message}</span>
          )}
          {!loading && !saving && !message && status?.supported === false && (
            <span className="general-settings-warning">Available on Windows and macOS.</span>
          )}
        </div>
      </div>

      {/* ── Auto Mode (Instant Answer) ────────────────────────── */}
      <div className="general-settings-card">
        <div className="general-settings-card-header">
          <div className="general-settings-option">
            <span className={`general-settings-pin ${autoEnabled ? 'active' : ''}`}>
              <PinIcon size={18} />
            </span>
            <div className="general-settings-card-info">
              <h3 className="general-settings-card-title">Auto Mode</h3>
              <p className="general-settings-card-description">
                Press the screenshot hotkey to instantly capture the whole screen, send your saved
                prompt, and stream the answer into a new tab — hands-off, without stealing focus.
              </p>
              <p className="general-settings-card-note">
                While on, the screenshot hotkey runs Auto Mode instead of region capture.
              </p>
            </div>
          </div>

          <label className="general-settings-toggle">
            <input
              type="checkbox"
              aria-label="Auto Mode"
              checked={autoEnabled}
              disabled={!autoLoaded || !isConnected}
              onChange={(event) => patchAutoMode({ enabled: event.target.checked })}
            />
            <span className="general-settings-toggle-slider" />
          </label>
        </div>

        {autoEnabled && (
          <div className="general-settings-body">
            <div className="general-settings-field">
              <label className="general-settings-field-label" htmlFor="auto-mode-prompt">
                Prompt sent with every capture
              </label>
              <textarea
                id="auto-mode-prompt"
                className="general-settings-textarea"
                rows={3}
                value={autoMode?.prompt ?? ''}
                placeholder="Answer the question on my screen concisely."
                onFocus={() => {
                  promptFocusedRef.current = true;
                }}
                onChange={(event) =>
                  setAutoMode((prev) => (prev ? { ...prev, prompt: event.target.value } : prev))
                }
                onBlur={(event) => {
                  promptFocusedRef.current = false;
                  const value = event.target.value;
                  if (value !== lastSavedPromptRef.current) {
                    lastSavedPromptRef.current = value;
                    send({ type: 'auto_mode_update_settings', settings: { prompt: value } });
                  }
                }}
              />
            </div>

            <div className="general-settings-field">
              <label className="general-settings-field-label" htmlFor="auto-mode-model">
                Model
              </label>
              <select
                id="auto-mode-model"
                className="general-settings-select"
                value={autoMode?.pinned_model ?? ''}
                onChange={(event) => patchAutoMode({ pinned_model: event.target.value })}
              >
                <option value="">Use currently selected model</option>
                {autoMode?.pinned_model && !autoModels.includes(autoMode.pinned_model) && (
                  <option value={autoMode.pinned_model}>
                    {autoMode.pinned_model} (unavailable)
                  </option>
                )}
                {autoModels.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>

            <div className="general-settings-subrow">
              <div className="general-settings-card-info">
                <span className="general-settings-subrow-title">Keep context</span>
                <span className="general-settings-card-note">
                  Chain captures into the same conversation instead of a fresh tab each time.
                </span>
              </div>
              <label className="general-settings-toggle">
                <input
                  type="checkbox"
                  aria-label="Keep context"
                  checked={autoMode?.keep_context ?? false}
                  onChange={(event) => patchAutoMode({ keep_context: event.target.checked })}
                />
                <span className="general-settings-toggle-slider" />
              </label>
            </div>

            <div className="general-settings-subrow">
              <div className="general-settings-card-info">
                <span className="general-settings-subrow-title">Flash on trigger</span>
                <span className="general-settings-card-note">
                  Briefly flash the window when a capture fires.
                </span>
              </div>
              <label className="general-settings-toggle">
                <input
                  type="checkbox"
                  aria-label="Flash on trigger"
                  checked={autoMode?.flash ?? false}
                  onChange={(event) => patchAutoMode({ flash: event.target.checked })}
                />
                <span className="general-settings-toggle-slider" />
              </label>
            </div>

            <p className="general-settings-disclaimer">
              Auto Mode sends a screenshot with every trigger. Make sure your selected (or pinned)
              model is vision-capable, otherwise it won&apos;t be able to read your screen.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default SettingsGeneral;
