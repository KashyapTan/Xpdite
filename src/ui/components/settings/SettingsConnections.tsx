import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import type { ExternalConnector } from '../../services/api';
import '../../CSS/settings/SettingsConnections.css';

interface GoogleStatus {
  connected: boolean;
  email: string | null;
  auth_in_progress: boolean;
}

/**
 * Icon component for external connectors.
 * Add new icons here when adding new connector types.
 */
const ConnectorIcon: React.FC<{ iconType: string }> = ({ iconType }) => {
  switch (iconType) {
    case 'figma':
      return (
        <svg viewBox="0 0 38 57" width="28" height="28">
          <path fill="var(--color-brand-figma-blue)" d="M19 28.5a9.5 9.5 0 1 1 19 0 9.5 9.5 0 0 1-19 0z" />
          <path fill="var(--color-brand-figma-green)" d="M0 47.5A9.5 9.5 0 0 1 9.5 38H19v9.5a9.5 9.5 0 1 1-19 0z" />
          <path fill="var(--color-brand-figma-coral)" d="M19 0v19h9.5a9.5 9.5 0 1 0 0-19H19z" />
          <path fill="var(--color-brand-figma-orange)" d="M0 9.5A9.5 9.5 0 0 0 9.5 19H19V0H9.5A9.5 9.5 0 0 0 0 9.5z" />
          <path fill="var(--color-brand-figma-purple)" d="M0 28.5A9.5 9.5 0 0 0 9.5 38H19V19H9.5A9.5 9.5 0 0 0 0 28.5z" />
        </svg>
      );
    case 'slack':
      return (
        <svg viewBox="0 0 24 24" width="28" height="28">
          <path fill="var(--color-brand-slack-red)" d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z" />
          <path fill="var(--color-brand-slack-blue)" d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z" />
          <path fill="var(--color-brand-slack-green)" d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312z" />
          <path fill="var(--color-brand-slack-yellow)" d="M15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z" />
        </svg>
      );
    case 'github':
      return (
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
        </svg>
      );
    case 'everything':
      // Puzzle piece icon - represents a demo/test server with various tools
      return (
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
          <path d="M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5C13 2.12 11.88 1 10.5 1S8 2.12 8 3.5V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7 1.49 0 2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5c1.38 0 2.5-1.12 2.5-2.5S21.88 11 20.5 11z" />
        </svg>
      );
    default:
      // Generic connector icon (same as fetch for now)
      return (
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
        </svg>
      );
  }
};

/**
 * SettingsConnections — the "Connections" tab inside Settings.
 *
 * Displays connection cards for:
 * 1. Google (special handling for OAuth + Gmail/Calendar)
 * 2. External MCP connectors (Figma, GitHub, etc.) loaded from backend
 *
 * Users just click "Connect" and the browser opens for OAuth (if needed).
 */
const SettingsConnections: React.FC = () => {
  // Google-specific state
  const [googleStatus, setGoogleStatus] = useState<GoogleStatus>({
    connected: false,
    email: null,
    auth_in_progress: false,
  });

  // External connectors state
  const [externalConnectors, setExternalConnectors] = useState<ExternalConnector[]>([]);
  const [connectingConnector, setConnectingConnector] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');

  // Fetch all connection statuses
  const fetchStatus = useCallback(async () => {
    try {
      const [googleStatusResult, connectorsResult] = await Promise.all([
        api.getGoogleStatus(),
        api.getExternalConnectors(),
      ]);
      setGoogleStatus(googleStatusResult);
      setExternalConnectors(connectorsResult);
      setError('');
    } catch {
      setError('Could not reach the backend');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Handle Google Connect button click
  const handleGoogleConnect = async () => {
    setConnecting(true);
    setError('');

    try {
      const result = await api.connectGoogle();
      if (result.success) {
        await fetchStatus();
      } else {
        setError(result.error || 'Connection failed');
      }
    } catch {
      setError('Could not reach the server. Is it running?');
    } finally {
      setConnecting(false);
    }
  };

  // Handle Google Disconnect button click
  const handleGoogleDisconnect = async () => {
    setError('');
    try {
      const result = await api.disconnectGoogle();
      if (result.success) {
        setGoogleStatus((prev) => ({
          ...prev,
          connected: false,
          email: null,
        }));
      } else {
        setError(result.error || 'Disconnect failed');
      }
    } catch {
      setError('Failed to disconnect');
    }
  };

  // Handle external connector connect
  const handleConnectorConnect = async (name: string) => {
    setConnectingConnector(name);
    setError('');

    try {
      const result = await api.connectExternalConnector(name);
      if (result.success) {
        await fetchStatus();
      } else {
        setError(result.error || `Failed to connect ${name}`);
      }
    } catch {
      setError(`Could not connect to ${name}. Is the server running?`);
    } finally {
      setConnectingConnector(null);
    }
  };

  // Handle external connector disconnect
  const handleConnectorDisconnect = async (name: string) => {
    setError('');
    try {
      const result = await api.disconnectExternalConnector(name);
      if (result.success) {
        // Update local state immediately
        setExternalConnectors((prev) =>
          prev.map((c) =>
            c.name === name ? { ...c, connected: false, enabled: false, last_error: null } : c
          )
        );
      } else {
        setError(result.error || `Failed to disconnect ${name}`);
      }
    } catch {
      setError(`Failed to disconnect ${name}`);
    }
  };

  return (
    <div className="settings-connections-section">
      <div className="settings-connections-header">
        <h2>Connections</h2>
        <p>Connect external services to give Xpdite more tools!</p>
      </div>

      {error && <div className="settings-connections-error">{error}</div>}

      <div className="settings-connections-grid">
        {/* Google Connection Card */}
        <div className={`settings-connection-card ${googleStatus.connected ? 'connected' : ''}`}>
          <div className="settings-connection-card-icon">
            <svg viewBox="0 0 24 24" width="28" height="28">
              <path fill="var(--color-brand-google-blue)" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
              <path fill="var(--color-brand-google-green)" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="var(--color-brand-google-yellow)" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="var(--color-brand-google-red)" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
          </div>

          <div className="settings-connection-card-info">
            <div className="settings-connection-card-title">Google</div>
            <div className="settings-connection-card-desc">
              {loading
                ? 'Checking...'
                : googleStatus.connected
                  ? `Connected as ${googleStatus.email || 'your account'}`
                  : 'Gmail & Calendar access'}
            </div>
          </div>

          <div className="settings-connection-card-services">
            <span className="settings-connection-service-badge">Gmail</span>
            <span className="settings-connection-service-badge">Calendar</span>
          </div>

          <div className="settings-connection-card-actions">
            {googleStatus.connected ? (
              <button
                className="settings-connection-btn disconnect"
                onClick={handleGoogleDisconnect}
              >
                Disconnect
              </button>
            ) : connecting ? (
              <button className="settings-connection-btn connecting" disabled>
                Connecting...
              </button>
            ) : (
              <button
                className="settings-connection-btn connect"
                onClick={handleGoogleConnect}
                disabled={loading}
              >
                Connect
              </button>
            )}
          </div>
        </div>

        {/* External Connector Cards */}
        {externalConnectors.map((connector) => (
          <div
            key={connector.name}
            className={`settings-connection-card ${connector.connected ? 'connected' : ''}`}
          >
            <div className="settings-connection-card-icon">
              <ConnectorIcon iconType={connector.icon_type} />
            </div>

            <div className="settings-connection-card-info">
              <div className="settings-connection-card-title">{connector.display_name}</div>
              <div className="settings-connection-card-desc">
                {loading
                  ? 'Checking...'
                  : connector.connected
                    ? 'Connected'
                    : connector.last_error
                      ? `Error: ${connector.last_error}`
                      : connector.description}
              </div>
            </div>

            <div className="settings-connection-card-services">
              {connector.services.map((service) => (
                <span key={service} className="settings-connection-service-badge">
                  {service}
                </span>
              ))}
            </div>

            <div className="settings-connection-card-actions">
              {connector.connected ? (
                <button
                  className="settings-connection-btn disconnect"
                  onClick={() => handleConnectorDisconnect(connector.name)}
                >
                  Disconnect
                </button>
              ) : connectingConnector === connector.name ? (
                <button className="settings-connection-btn connecting" disabled>
                  Connecting...
                </button>
              ) : (
                <button
                  className="settings-connection-btn connect"
                  onClick={() => handleConnectorConnect(connector.name)}
                  disabled={loading}
                >
                  Connect
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default SettingsConnections;
