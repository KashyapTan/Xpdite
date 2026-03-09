import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import { CheckIcon } from '../icons/AppIcons';
import '../../CSS/SettingsSubAgents.css';

interface SubAgentSettings {
  fast_model: string;
  smart_model: string;
}

const SettingsSubAgents: React.FC = () => {
  const [settings, setSettings] = useState<SubAgentSettings>({ fast_model: '', smart_model: '' });
  const [enabledModels, setEnabledModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [subAgentSettings, models] = await Promise.all([
          api.getSubAgentSettings(),
          api.getEnabledModels(),
        ]);
        setSettings(subAgentSettings);
        setEnabledModels(models);
      } catch (error) {
        console.error('Failed to load sub-agent settings', error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleChange = async (tier: 'fast_model' | 'smart_model', value: string) => {
    const updated = { ...settings, [tier]: value };
    setSettings(updated);
    setStatus('saving');
    try {
      await api.setSubAgentSettings(updated);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } catch {
      setStatus('idle');
    }
  };

  if (loading) {
    return <div className="sub-agent-loading">Loading...</div>;
  }

  return (
    <div className="sub-agent-container">
      <div className="sub-agent-header">
        <h2>Sub-Agents</h2>
        <p>
          Configure which models are used when the AI spawns sub-agents.
          Leave blank to use the current active model for that tier.
        </p>
      </div>

      <div className="sub-agent-tiers">
        <div className="sub-agent-tier-card">
          <div className="sub-agent-tier-info">
            <span className="sub-agent-tier-badge fast">FAST</span>
            <div>
              <div className="sub-agent-tier-title">Fast Tier</div>
              <div className="sub-agent-tier-desc">
                For reading, summarizing, searching, or any task that does not require deep reasoning. Cheapest option.
              </div>
            </div>
          </div>
          <select
            className="sub-agent-model-select"
            value={settings.fast_model}
            onChange={(e) => handleChange('fast_model', e.target.value)}
          >
            <option value="">Use current model (default)</option>
            {enabledModels.map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </div>

        <div className="sub-agent-tier-card">
          <div className="sub-agent-tier-info">
            <span className="sub-agent-tier-badge smart">SMART</span>
            <div>
              <div className="sub-agent-tier-title">Smart Tier</div>
              <div className="sub-agent-tier-desc">
                For code review, multi-step reasoning, or tasks with meaningful complexity. Mid-tier cost.
              </div>
            </div>
          </div>
          <select
            className="sub-agent-model-select"
            value={settings.smart_model}
            onChange={(e) => handleChange('smart_model', e.target.value)}
          >
            <option value="">Use current model (default)</option>
            {enabledModels.map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </div>

        <div className="sub-agent-tier-card self-tier">
          <div className="sub-agent-tier-info">
            <span className="sub-agent-tier-badge self">SELF</span>
            <div>
              <div className="sub-agent-tier-title">Self Tier</div>
              <div className="sub-agent-tier-desc">
                Always uses the same model as the calling agent. Most expensive — use sparingly.
              </div>
            </div>
          </div>
          <div className="sub-agent-self-note">Always matches the active model</div>
        </div>
      </div>

      {status === 'saved' && (
        <div className="sub-agent-saved">
          <CheckIcon size={14} className="sub-agent-saved-icon" />
          <span>Settings saved</span>
        </div>
      )}

      <div className="sub-agent-info-section">
        <h3>How Sub-Agents Work</h3>
        <ul>
          <li>Sub-agents are independent LLM calls with no access to conversation history.</li>
          <li>Multiple sub-agents in one turn run in parallel (except local Ollama, which runs sequentially).</li>
          <li>Sub-agents can use file and web tools but cannot run terminal commands or spawn further sub-agents.</li>
          <li>Results are returned as tool results to the main model.</li>
        </ul>
      </div>
    </div>
  );
};

export default SettingsSubAgents;
