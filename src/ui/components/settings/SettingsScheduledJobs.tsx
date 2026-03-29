import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import '../../CSS/SettingsScheduledJobs.css';

interface ScheduledJob {
  id: string;
  name: string;
  cron_expression: string;
  instruction: string;
  model: string | null;
  timezone: string;
  delivery_platform: string | null;
  delivery_sender_id: string | null;
  enabled: boolean;
  is_one_shot: boolean;
  created_at: number;
  last_run_at: number | null;
  next_run_at: number | null;
  run_count: number;
  missed: boolean;
}

interface PlatformConfig {
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'error';
  token?: string;
}

type Platform = 'telegram' | 'discord' | 'whatsapp';

const PLATFORM_LABELS: Record<Platform, string> = {
  telegram: 'Telegram',
  discord: 'Discord',
  whatsapp: 'WhatsApp',
};

const SettingsScheduledJobs: React.FC = () => {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, PlatformConfig>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [editingForwarding, setEditingForwarding] = useState<string | null>(null);
  const [forwardingPlatform, setForwardingPlatform] = useState<string>('');
  const [forwardingSenderId, setForwardingSenderId] = useState<string>('');

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [jobsData, platformsData] = await Promise.all([
        api.getScheduledJobs(),
        api.getMobileChannelsConfig(),
      ]);
      setJobs(jobsData.jobs);
      
      // Start with database config
      const platformConfigs: Record<string, PlatformConfig> = platformsData.platforms || {};
      
      // Try to get live status from Channel Bridge via Electron IPC (source of truth for connection)
      if (typeof window !== 'undefined' && window.electronAPI?.getChannelBridgeStatus) {
        try {
          const bridgeResponse = await window.electronAPI.getChannelBridgeStatus();
          if (bridgeResponse?.platforms && Array.isArray(bridgeResponse.platforms)) {
            // Merge live status into platform configs
            for (const liveStatus of bridgeResponse.platforms) {
              const platformId = liveStatus.platform as Platform;
              if (platformConfigs[platformId]) {
                platformConfigs[platformId] = {
                  ...platformConfigs[platformId],
                  status: liveStatus.status as 'connected' | 'disconnected' | 'error',
                };
              } else {
                // Platform exists in Channel Bridge but not in DB config
                platformConfigs[platformId] = {
                  enabled: false,
                  status: liveStatus.status as 'connected' | 'disconnected' | 'error',
                };
              }
            }
          }
        } catch (err) {
          console.warn('Failed to get Channel Bridge status:', err);
        }
      }
      
      setPlatforms(platformConfigs);
    } catch (err) {
      console.error('Failed to load data:', err);
      setError('Failed to load scheduled tasks');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Listen for real-time Channel Bridge status updates via IPC (Electron)
  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI?.onChannelBridgeStatus) {
      const unsubscribe = window.electronAPI.onChannelBridgeStatus((platformStatuses: unknown) => {
        if (Array.isArray(platformStatuses)) {
          setPlatforms((prev) => {
            const updated = { ...prev };
            for (const bridgeStatus of platformStatuses as Array<{ platform: string; status: string }>) {
              const platformId = bridgeStatus.platform as Platform;
              if (updated[platformId]) {
                updated[platformId] = {
                  ...updated[platformId],
                  status: bridgeStatus.status as 'connected' | 'disconnected' | 'error',
                };
              }
            }
            return updated;
          });
        }
      });
      return () => {
        unsubscribe();
      };
    }
  }, []);

  const handleToggleEnabled = async (job: ScheduledJob) => {
    try {
      setActionLoading(job.id);
      if (job.enabled) {
        await api.pauseScheduledJob(job.id);
      } else {
        await api.resumeScheduledJob(job.id);
      }
      await fetchData();
    } catch (err) {
      console.error('Failed to toggle job:', err);
      setError('Failed to toggle task');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (job: ScheduledJob) => {
    if (!confirm(`Are you sure you want to delete "${job.name}"?`)) {
      return;
    }
    try {
      setActionLoading(job.id);
      await api.deleteScheduledJob(job.id);
      await fetchData();
    } catch (err) {
      console.error('Failed to delete job:', err);
      setError('Failed to delete task');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRunNow = async (job: ScheduledJob) => {
    try {
      setActionLoading(job.id);
      await api.runScheduledJobNow(job.id);
      await fetchData();
    } catch (err) {
      console.error('Failed to run job:', err);
      setError('Failed to run task');
    } finally {
      setActionLoading(null);
    }
  };

  const handleEditForwarding = (job: ScheduledJob) => {
    setEditingForwarding(job.id);
    setForwardingPlatform(job.delivery_platform || '');
    setForwardingSenderId(job.delivery_sender_id || '');
  };

  const handleCancelForwarding = () => {
    setEditingForwarding(null);
    setForwardingPlatform('');
    setForwardingSenderId('');
  };

  const handleSaveForwarding = async (job: ScheduledJob) => {
    try {
      setActionLoading(job.id);
      await api.updateScheduledJob(job.id, {
        delivery_platform: forwardingPlatform || undefined,
        delivery_sender_id: forwardingSenderId || undefined,
      });
      setEditingForwarding(null);
      await fetchData();
    } catch (err) {
      console.error('Failed to save forwarding settings:', err);
      setError('Failed to save forwarding settings');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRemoveForwarding = async (job: ScheduledJob) => {
    try {
      setActionLoading(job.id);
      // Send empty strings to clear forwarding - backend will interpret as removing
      await api.updateScheduledJob(job.id, {
        delivery_platform: '',
        delivery_sender_id: '',
      });
      await fetchData();
    } catch (err) {
      console.error('Failed to remove forwarding:', err);
      setError('Failed to remove forwarding');
    } finally {
      setActionLoading(null);
    }
  };

  const formatTime = (timestamp: number | null, timezone: string) => {
    if (!timestamp) return 'N/A';
    try {
      const date = new Date(timestamp * 1000);
      return date.toLocaleString('en-US', {
        timeZone: timezone,
        dateStyle: 'medium',
        timeStyle: 'short',
      });
    } catch {
      return new Date(timestamp * 1000).toLocaleString();
    }
  };

  const getCronDescription = (cron: string) => {
    const parts = cron.split(' ');
    if (parts.length !== 5) return cron;

    const [minute, hour, dayOfMonth, , dayOfWeek] = parts;

    if (dayOfMonth === '*' && dayOfWeek === '*') {
      if (hour === '*') {
        return `Every hour at :${minute.padStart(2, '0')}`;
      }
      return `Daily at ${hour}:${minute.padStart(2, '0')}`;
    }

    if (dayOfWeek !== '*') {
      const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      const dayNames = dayOfWeek
        .split(',')
        .map((d) => days[parseInt(d)] || d)
        .join(', ');
      return `${dayNames} at ${hour}:${minute.padStart(2, '0')}`;
    }

    return cron;
  };

  const getConnectedPlatforms = (): Platform[] => {
    // Show platforms that are connected (regardless of enabled state in DB)
    // If they're connected via Channel Bridge, they can receive messages
    return (Object.keys(platforms) as Platform[]).filter(
      (key) => platforms[key]?.status === 'connected'
    );
  };

  const connectedPlatforms = getConnectedPlatforms();

  if (loading && jobs.length === 0) {
    return <div className="settings-tasks-loading">Loading scheduled tasks...</div>;
  }

  return (
    <div className="settings-tasks-container">
      <div className="settings-tasks-header">
        <h2>Scheduled Tasks</h2>
        <p>
          Manage your scheduled tasks. Tasks can be created by asking the AI to schedule recurring
          activities using natural language.
        </p>
      </div>

      {error && (
        <div className="settings-tasks-error">
          {error}
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="settings-tasks-empty">
          <div className="settings-tasks-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
          </div>
          <p>No scheduled tasks yet</p>
          <p className="settings-tasks-empty-hint">
            Ask Xpdite to schedule a task, for example: "Summarize my email every morning at 9am"
          </p>
        </div>
      ) : (
        <div className="settings-tasks-list">
          {jobs.map((job) => (
            <div
              key={job.id}
              className={`settings-task-item ${!job.enabled ? 'paused' : ''} ${
                expandedJob === job.id ? 'expanded' : ''
              }`}
            >
              <div
                className="settings-task-header"
                onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
              >
                <div className="settings-task-info">
                  <div className="settings-task-name">
                    {job.name}
                    {job.is_one_shot && <span className="settings-task-badge one-shot">One-shot</span>}
                    {!job.enabled && <span className="settings-task-badge paused">Paused</span>}
                    {job.missed && <span className="settings-task-badge missed">Missed</span>}
                    {job.delivery_platform && (
                      <span className="settings-task-badge forwarding">
                        {PLATFORM_LABELS[job.delivery_platform as Platform] || job.delivery_platform}
                      </span>
                    )}
                  </div>
                  <div className="settings-task-schedule">{getCronDescription(job.cron_expression)}</div>
                </div>
                <div className="settings-task-toggle">
                  <button
                    className={`toggle-button ${job.enabled ? 'enabled' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggleEnabled(job);
                    }}
                    disabled={actionLoading === job.id}
                    title={job.enabled ? 'Pause task' : 'Resume task'}
                  >
                    <span className="toggle-slider" />
                  </button>
                </div>
              </div>

              {expandedJob === job.id && (
                <div className="settings-task-details">
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Instruction</span>
                    <span className="settings-task-detail-value">{job.instruction}</span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Schedule (cron)</span>
                    <span className="settings-task-detail-value">
                      <code>{job.cron_expression}</code>
                    </span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Timezone</span>
                    <span className="settings-task-detail-value">{job.timezone}</span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Model</span>
                    <span className="settings-task-detail-value">{job.model || 'Default'}</span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Next run</span>
                    <span className="settings-task-detail-value">
                      {formatTime(job.next_run_at, job.timezone)}
                    </span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Last run</span>
                    <span className="settings-task-detail-value">
                      {formatTime(job.last_run_at, job.timezone)}
                    </span>
                  </div>
                  <div className="settings-task-detail-row">
                    <span className="settings-task-detail-label">Run count</span>
                    <span className="settings-task-detail-value">{job.run_count}</span>
                  </div>

                  {/* Forwarding Section */}
                  <div className="settings-task-forwarding-section">
                    <div className="settings-task-forwarding-header">
                      <span className="settings-task-detail-label">Forward Results To</span>
                    </div>
                    
                    {editingForwarding === job.id ? (
                      <div className="settings-task-forwarding-edit">
                        <div className="settings-task-forwarding-field">
                          <label>Platform</label>
                          <select
                            value={forwardingPlatform}
                            onChange={(e) => setForwardingPlatform(e.target.value)}
                            disabled={actionLoading === job.id}
                          >
                            <option value="">None (In-app only)</option>
                            {connectedPlatforms.map((platform) => (
                              <option key={platform} value={platform}>
                                {PLATFORM_LABELS[platform]}
                              </option>
                            ))}
                          </select>
                          {connectedPlatforms.length === 0 && (
                            <span className="settings-task-forwarding-hint">
                              No messaging platforms connected. Configure them in Settings.
                            </span>
                          )}
                        </div>
                        {forwardingPlatform && (
                          <div className="settings-task-forwarding-field">
                            <label>Recipient ID (phone/user/channel)</label>
                            <input
                              type="text"
                              value={forwardingSenderId}
                              onChange={(e) => setForwardingSenderId(e.target.value)}
                              placeholder={
                                forwardingPlatform === 'whatsapp'
                                  ? '+1234567890'
                                  : forwardingPlatform === 'telegram'
                                    ? 'Chat ID or @username'
                                    : 'Channel or User ID'
                              }
                              disabled={actionLoading === job.id}
                            />
                          </div>
                        )}
                        <div className="settings-task-forwarding-actions">
                          <button
                            className="settings-task-action save"
                            onClick={() => handleSaveForwarding(job)}
                            disabled={actionLoading === job.id || (!!forwardingPlatform && !forwardingSenderId)}
                          >
                            {actionLoading === job.id ? 'Saving...' : 'Save'}
                          </button>
                          <button
                            className="settings-task-action cancel"
                            onClick={handleCancelForwarding}
                            disabled={actionLoading === job.id}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="settings-task-forwarding-display">
                        {job.delivery_platform ? (
                          <div className="settings-task-forwarding-current">
                            <span className="forwarding-platform-badge">
                              {PLATFORM_LABELS[job.delivery_platform as Platform] || job.delivery_platform}
                            </span>
                            <span className="forwarding-recipient">{job.delivery_sender_id}</span>
                            <div className="forwarding-actions">
                              <button
                                className="settings-task-action edit"
                                onClick={() => handleEditForwarding(job)}
                                disabled={actionLoading === job.id}
                              >
                                Edit
                              </button>
                              <button
                                className="settings-task-action remove"
                                onClick={() => handleRemoveForwarding(job)}
                                disabled={actionLoading === job.id}
                              >
                                Remove
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="settings-task-forwarding-none">
                            <span className="forwarding-none-text">In-app notifications only</span>
                            <button
                              className="settings-task-action add-forwarding"
                              onClick={() => handleEditForwarding(job)}
                              disabled={actionLoading === job.id}
                            >
                              Add Forwarding
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="settings-task-actions">
                    <button
                      className="settings-task-action run-now"
                      onClick={() => handleRunNow(job)}
                      disabled={actionLoading === job.id}
                    >
                      {actionLoading === job.id ? 'Running...' : 'Run Now'}
                    </button>
                    <button
                      className="settings-task-action delete"
                      onClick={() => handleDelete(job)}
                      disabled={actionLoading === job.id}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SettingsScheduledJobs;
