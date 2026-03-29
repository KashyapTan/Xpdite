/**
 * Mobile Channels Settings Component
 *
 * Allows users to configure mobile messaging platform connections
 * (Telegram, Discord, WhatsApp) and manage paired devices.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import '../../CSS/SettingsMobileChannels.css';

// Types
interface PairedDevice {
  id: number;
  platform: string;
  sender_id: string;
  display_name: string | null;
  paired_at: number;
  last_active: number | null;
}

interface PlatformConfig {
  id: string;
  name: string;
  icon: string;
  enabled: boolean;
  configured: boolean;
  status: 'connected' | 'disconnected' | 'error';
  statusMessage?: string;
}

interface PairingCode {
  code: string;
  expiresAt: number;
}

// Platform icons
const PLATFORM_ICONS: Record<string, string> = {
  telegram: '✈️',
  discord: '🎮',
  whatsapp: '📱',
};

const SettingsMobileChannels: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [pairedDevices, setPairedDevices] = useState<PairedDevice[]>([]);
  const [pairingCode, setPairingCode] = useState<PairingCode | null>(null);
  const [platforms, setPlatforms] = useState<PlatformConfig[]>([
    {
      id: 'telegram',
      name: 'Telegram',
      icon: PLATFORM_ICONS.telegram,
      enabled: false,
      configured: false,
      status: 'disconnected',
    },
    {
      id: 'discord',
      name: 'Discord',
      icon: PLATFORM_ICONS.discord,
      enabled: false,
      configured: false,
      status: 'disconnected',
    },
    {
      id: 'whatsapp',
      name: 'WhatsApp',
      icon: PLATFORM_ICONS.whatsapp,
      enabled: false,
      configured: false,
      status: 'disconnected',
    },
  ]);
  const [setupModal, setSetupModal] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState('');
  // WhatsApp specific state
  const [whatsappPhoneNumber, setWhatsappPhoneNumber] = useState('');
  const [whatsappPairingCode, setWhatsappPairingCode] = useState<string | null>(null);
  const [whatsappConnecting, setWhatsappConnecting] = useState(false);

  // Load paired devices
  const loadPairedDevices = useCallback(async () => {
    try {
      const response = await api.getMobilePairedDevices();
      setPairedDevices(response.devices || []);
    } catch (err) {
      console.error('Failed to load paired devices:', err);
    }
  }, []);

  // Load platform config from Python backend and live status from Channel Bridge
  const loadPlatformStatuses = useCallback(async () => {
    try {
      // Get config (enabled/configured) from Python backend database
      const config = await api.getMobileChannelsConfig();
      
      // Get live connection status from Channel Bridge via Electron IPC
      // This is the source of truth for whether platforms are actually connected
      let liveStatuses: Array<{ platform: string; status: string; error?: string }> = [];
      if (typeof window !== 'undefined' && window.electronAPI?.getChannelBridgeStatus) {
        try {
          const bridgeResponse = await window.electronAPI.getChannelBridgeStatus();
          if (bridgeResponse?.platforms) {
            liveStatuses = bridgeResponse.platforms;
          }
        } catch (err) {
          console.warn('Failed to get Channel Bridge status:', err);
        }
      }
      
      setPlatforms((prev) =>
        prev.map((p) => {
          // Find live status from Channel Bridge (source of truth for connection state)
          const liveStatus = liveStatuses.find((s) => s.platform === p.id);
          return {
            ...p,
            enabled: config.platforms?.[p.id]?.enabled ?? false,
            configured: !!config.platforms?.[p.id]?.token,
            // Use live status from Channel Bridge if available, otherwise fallback to DB
            status: (liveStatus?.status as 'connected' | 'disconnected' | 'error') 
              ?? config.platforms?.[p.id]?.status 
              ?? 'disconnected',
            statusMessage: liveStatus?.error,
          };
        })
      );
    } catch (err) {
      console.error('Failed to load platform statuses:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    const load = async () => {
      setLoading(true);
      await Promise.all([loadPairedDevices(), loadPlatformStatuses()]);
      setLoading(false);
    };
    load();
  }, [loadPairedDevices, loadPlatformStatuses]);

  // Listen for WhatsApp pairing code from IPC (Electron)
  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI?.onWhatsAppPairingCode) {
      const unsubscribe = window.electronAPI.onWhatsAppPairingCode((code: string) => {
        console.log('Received WhatsApp pairing code:', code);
        setWhatsappPairingCode(code);
        setWhatsappConnecting(false);
      });
      return () => {
        unsubscribe();
      };
    }
  }, []);

  // Listen for real-time Channel Bridge status updates via IPC (Electron)
  // This is the source of truth for platform connection status
  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI?.onChannelBridgeStatus) {
      const unsubscribe = window.electronAPI.onChannelBridgeStatus((platformStatuses: unknown) => {
        if (Array.isArray(platformStatuses)) {
          setPlatforms((prev) =>
            prev.map((p) => {
              const bridgeStatus = platformStatuses.find(
                (s: { platform: string }) => s.platform === p.id
              ) as { platform: string; status: string; error?: string } | undefined;
              if (bridgeStatus) {
                return {
                  ...p,
                  status: bridgeStatus.status as 'connected' | 'disconnected' | 'error',
                  statusMessage: bridgeStatus.error,
                };
              }
              return p;
            })
          );
        }
      });
      return () => {
        unsubscribe();
      };
    }
  }, []);

  // Generate pairing code
  const generatePairingCode = async () => {
    try {
      const response = await api.generateMobilePairingCode();
      setPairingCode({
        code: response.code,
        expiresAt: Date.now() + response.expires_in_seconds * 1000,
      });
    } catch (err) {
      console.error('Failed to generate pairing code:', err);
    }
  };

  // Countdown timer for pairing code
  useEffect(() => {
    if (!pairingCode) return;

    const interval = setInterval(() => {
      if (Date.now() >= pairingCode.expiresAt) {
        setPairingCode(null);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [pairingCode]);

  // Revoke device
  const revokeDevice = async (deviceId: number) => {
    try {
      await api.revokeMobilePairedDevice(deviceId);
      setPairedDevices((prev) => prev.filter((d) => d.id !== deviceId));
    } catch (err) {
      console.error('Failed to revoke device:', err);
    }
  };

  // Format timestamp
  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  // Get remaining time for pairing code
  const getRemainingTime = () => {
    if (!pairingCode) return '';
    const remaining = Math.max(0, Math.floor((pairingCode.expiresAt - Date.now()) / 1000));
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Save platform config
  const savePlatformConfig = async (platformId: string, token: string) => {
    try {
      await api.setMobilePlatformConfig(platformId, { token, enabled: true });
      setSetupModal(null);
      setTokenInput('');
      await loadPlatformStatuses();
    } catch (err) {
      console.error('Failed to save platform config:', err);
    }
  };

  // Disconnect platform
  const disconnectPlatform = async (platformId: string) => {
    try {
      await api.setMobilePlatformConfig(platformId, { enabled: false });
      await loadPlatformStatuses();
    } catch (err) {
      console.error('Failed to disconnect platform:', err);
    }
  };

  // Render setup modal
  const renderSetupModal = () => {
    if (!setupModal) return null;

    const platform = platforms.find((p) => p.id === setupModal);
    if (!platform) return null;

    return (
      <div className="setup-modal-overlay" onClick={() => setSetupModal(null)}>
        <div className="setup-modal" onClick={(e) => e.stopPropagation()}>
          <div className="setup-modal-header">
            <span className="setup-modal-title">
              {platform.icon} Set up {platform.name}
            </span>
            <button className="setup-modal-close" onClick={() => setSetupModal(null)}>
              ×
            </button>
          </div>

          <div className="setup-modal-body">
            {setupModal === 'telegram' && (
              <>
                <div className="setup-step">
                  <span className="setup-step-number">1</span>
                  <span className="setup-step-title">Create a Telegram Bot</span>
                  <p className="setup-step-desc">
                    Open Telegram and message @BotFather to create a new bot.
                    Use the /newbot command and follow the instructions.
                  </p>
                  <a
                    className="setup-link"
                    href="https://t.me/BotFather"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open BotFather →
                  </a>
                </div>

                <div className="setup-step">
                  <span className="setup-step-number">2</span>
                  <span className="setup-step-title">Copy Your Bot Token</span>
                  <p className="setup-step-desc">
                    After creating the bot, BotFather will give you a token.
                    Copy it and paste it below.
                  </p>
                  <input
                    type="password"
                    className="setup-input"
                    placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    autoComplete="off"
                  />
                </div>
              </>
            )}

            {setupModal === 'discord' && (
              <>
                <div className="setup-step">
                  <span className="setup-step-number">1</span>
                  <span className="setup-step-title">Create a Discord Application</span>
                  <p className="setup-step-desc">
                    Go to the Discord Developer Portal and create a new application.
                  </p>
                  <a
                    className="setup-link"
                    href="https://discord.com/developers/applications"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open Developer Portal →
                  </a>
                </div>

                <div className="setup-step">
                  <span className="setup-step-number">2</span>
                  <span className="setup-step-title">Create a Bot</span>
                  <p className="setup-step-desc">
                    In your application, go to the "Bot" tab and click "Add Bot".
                  </p>
                </div>

                <div className="setup-step">
                  <span className="setup-step-number">3</span>
                  <span className="setup-step-title">Enable Message Content Intent</span>
                  <p className="setup-step-desc">
                    <strong>Important:</strong> In the Bot settings, scroll down to
                    "Privileged Gateway Intents" and enable "Message Content Intent".
                    Without this, the bot cannot read message content.
                  </p>
                </div>

                <div className="setup-step">
                  <span className="setup-step-number">4</span>
                  <span className="setup-step-title">Copy Your Bot Token</span>
                  <p className="setup-step-desc">
                    Click "Reset Token" to get your bot token, then paste it below.
                  </p>
                  <input
                    type="password"
                    className="setup-input"
                    placeholder="MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.Gh7aBC.xyz..."
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    autoComplete="off"
                  />
                </div>
              </>
            )}

            {setupModal === 'whatsapp' && (
              <>
                <div className="setup-step">
                  <span className="setup-step-number">1</span>
                  <span className="setup-step-title">Enter Your Phone Number</span>
                  <p className="setup-step-desc">
                    WhatsApp uses the Linked Devices feature. Enter your phone number
                    (with country code, e.g., +1 for US) to receive an 8-digit pairing code.
                    Messages will appear to come from your phone number, not a separate bot account.
                  </p>
                  <input
                    type="tel"
                    className="setup-input"
                    placeholder="+1234567890"
                    value={whatsappPhoneNumber}
                    onChange={(e) => setWhatsappPhoneNumber(e.target.value)}
                    autoComplete="tel"
                  />
                </div>

                {whatsappPairingCode && (
                  <div className="setup-step">
                    <span className="setup-step-number">2</span>
                    <span className="setup-step-title">Enter Code in WhatsApp</span>
                    <p className="setup-step-desc">
                      Open WhatsApp on your phone → Settings → Linked Devices → Link a Device →
                      &quot;Link with phone number instead&quot; and enter this code:
                    </p>
                    <div className="whatsapp-pairing-code">{whatsappPairingCode}</div>
                  </div>
                )}

                {!whatsappPairingCode && (
                  <div className="setup-step">
                    <span className="setup-step-number">2</span>
                    <span className="setup-step-title">Get Pairing Code</span>
                    <p className="setup-step-desc">
                      After entering your phone number, click the button below to generate
                      an 8-digit pairing code. You&apos;ll enter this code in WhatsApp to link.
                    </p>
                  </div>
                )}

                <div className="warning-notice">
                  ⚠️ <strong>Note:</strong> WhatsApp uses an unofficial API. While ban risk
                  is low for personal use, WhatsApp&apos;s terms prohibit automation. Use at
                  your own discretion.
                </div>

                <div className="setup-step" style={{ marginTop: '20px' }}>
                  <button
                    className="setup-link"
                    disabled={!whatsappPhoneNumber.trim() || whatsappConnecting}
                    onClick={async () => {
                      if (!whatsappPhoneNumber.trim()) return;
                      setWhatsappConnecting(true);
                      setWhatsappPairingCode(null);
                      
                      try {
                        // Save config with phone number and trigger connection
                        // forcePairing: true clears any stale auth state
                        await api.setMobilePlatformConfig('whatsapp', {
                          token: 'linked',
                          enabled: true,
                          phoneNumber: whatsappPhoneNumber.replace(/\D/g, ''), // Strip non-digits
                          authMethod: 'pairing_code',
                          forcePairing: true, // Always force re-pairing when user clicks connect
                        });
                        
                        // The pairing code will be emitted by the Channel Bridge
                        // and displayed via IPC (handled by Electron)
                        // Poll for connection status or wait for IPC message
                        await loadPlatformStatuses();
                        
                      } catch (err) {
                        console.error('Failed to start WhatsApp connection:', err);
                        setWhatsappConnecting(false);
                      }
                    }}
                  >
                    {whatsappConnecting ? 'Connecting...' : 'Connect WhatsApp'}
                  </button>
                </div>
              </>
            )}
          </div>

          {setupModal !== 'whatsapp' && (
            <div className="setup-modal-footer">
              <button className="setup-btn-cancel" onClick={() => setSetupModal(null)}>
                Cancel
              </button>
              <button
                className="setup-btn-save"
                disabled={!tokenInput.trim()}
                onClick={() => savePlatformConfig(setupModal, tokenInput)}
              >
                Save & Connect
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="mobile-channels-container">
        <div className="mobile-channels-loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="mobile-channels-container">
      <div className="mobile-channels-header">
        <h2>Mobile Channels</h2>
        <p>
          Connect messaging platforms to chat with Xpdite from your phone.
          Messages sync to tabs in the desktop app.
        </p>
      </div>

      {/* Pairing Section */}
      <div className="mobile-channels-section">
        <h3 className="mobile-channels-section-title">Device Pairing</h3>
        <div className="pairing-code-card">
          {pairingCode ? (
            <>
              <p className="pairing-code-instructions">
                Send this code to your Xpdite bot on any messaging platform:
              </p>
              <div className="pairing-code-display">{pairingCode.code}</div>
              <p className="pairing-code-expiry">
                Expires in {getRemainingTime()}
              </p>
              <p className="pairing-code-instructions">
                Send: <code>/pair {pairingCode.code}</code>
              </p>
            </>
          ) : (
            <>
              <p className="pairing-code-instructions">
                Generate a pairing code to link a new device to Xpdite.
                Each code can only be used once.
              </p>
              <button className="pairing-code-btn" onClick={generatePairingCode}>
                Generate Pairing Code
              </button>
            </>
          )}
        </div>
      </div>

      {/* Platforms Section */}
      <div className="mobile-channels-section">
        <h3 className="mobile-channels-section-title">Messaging Platforms</h3>
        <div className="platform-cards">
          {platforms.map((platform) => (
            <div
              key={platform.id}
              className={`platform-card ${platform.status}`}
            >
              <div className={`platform-icon ${platform.id}`}>
                {platform.icon}
              </div>
              <div className="platform-info">
                <div className="platform-name">{platform.name}</div>
                <div className={`platform-status ${platform.status}`}>
                  <span className="status-dot" />
                  {platform.status === 'connected' && 'Connected'}
                  {platform.status === 'disconnected' && (
                    platform.configured ? 'Disconnected' : 'Not configured'
                  )}
                  {platform.status === 'error' && (platform.statusMessage || 'Error')}
                </div>
              </div>
              <div className="platform-actions">
                {platform.configured && platform.status === 'connected' ? (
                  <button
                    className="platform-btn disconnect"
                    onClick={() => disconnectPlatform(platform.id)}
                  >
                    Disconnect
                  </button>
                ) : (
                  <button
                    className="platform-btn configure"
                    onClick={() => setSetupModal(platform.id)}
                  >
                    {platform.configured ? 'Reconnect' : 'Set up'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Paired Devices Section */}
      <div className="mobile-channels-section">
        <h3 className="mobile-channels-section-title">Paired Devices</h3>
        {pairedDevices.length > 0 ? (
          <div className="paired-devices">
            {pairedDevices.map((device) => (
              <div key={device.id} className="paired-device">
                <div className={`paired-device-icon ${device.platform}`}>
                  {PLATFORM_ICONS[device.platform] || '📱'}
                </div>
                <div className="paired-device-info">
                  <div className="paired-device-name">
                    {device.display_name || device.sender_id}
                  </div>
                  <div className="paired-device-meta">
                    {device.platform} • Paired {formatDate(device.paired_at)}
                    {device.last_active && (
                      <> • Last active {formatDate(device.last_active)}</>
                    )}
                  </div>
                </div>
                <button
                  className="paired-device-revoke"
                  onClick={() => revokeDevice(device.id)}
                >
                  Revoke
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="no-devices">
            No devices paired yet. Generate a pairing code and send it from your
            messaging app.
          </div>
        )}
      </div>

      {renderSetupModal()}
    </div>
  );
};

export default SettingsMobileChannels;
