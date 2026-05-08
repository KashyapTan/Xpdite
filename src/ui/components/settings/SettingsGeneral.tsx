import React, { useEffect, useState } from 'react';
import type { ElectronContentProtectionStatus } from '../../types';
import { PinIcon } from '../icons/AppIcons';
import '../../CSS/settings/SettingsGeneral.css';

const unavailableStatus: ElectronContentProtectionStatus = {
  enabled: false,
  active: false,
  supported: false,
};

function errorMessageFor(error: unknown): string {
  return error instanceof Error ? error.message : 'Unable to update content protection.';
}

const SettingsGeneral: React.FC = () => {
  const [status, setStatus] = useState<ElectronContentProtectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

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
    </div>
  );
};

export default SettingsGeneral;
