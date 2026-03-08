import React, { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import SettingsModels from '../components/settings/SettingsModels';
import SettingsTools from '../components/settings/SettingsTools';
import SettingsApiKey from '../components/settings/SettingsApiKey';
import SettingsConnections from '../components/settings/SettingsConnections';
import SettingsSystemPrompt from '../components/settings/SettingsSystemPrompt';
import SettingsSkills from '../components/settings/SettingsSkills';
import MeetingRecorderSettings from '../components/settings/MeetingRecorderSettings';
import '../CSS/Settings.css';
import modelsIcon from '../assets/models.svg';
import connectionsIcon from '../assets/mcp.svg';
import toolsIcon from '../assets/context-window-icon.svg';
import ollamaIcon from '../assets/ollama.svg';
import anthropicIcon from '../assets/anthropic.svg';
import geminiIcon from '../assets/gemini.svg';
import openaiIcon from '../assets/openai.svg';
import settingsIcon from '../assets/settings-icon.svg';

// ============================================
// Placeholder components for tabs that aren't
// implemented yet. Each one is a simple card
// so users know they're on the right page.
// ============================================
const Placeholder: React.FC<{ title: string }> = ({ title }) => (
  <div style={{ padding: 20, color: 'rgba(255,255,255,0.4)', fontSize: '0.9rem' }}>
    <strong>{title}</strong> — coming soon.
  </div>
);

/**
 * Every tab the Settings page supports.
 * `id` is used as the active-tab key.
 * `icon` / `label` render in the sidebar.
 * `component` is what shows in the content area.
 */
type SettingsTab = {
  id: string;
  label: string;
  icon: string;
  className: string;
  component: React.ReactNode;
};

const Settings: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();

  // Define all tabs
  const tabs: SettingsTab[] = [
    { id: 'models', label: 'Models', icon: modelsIcon, className: 'settings-models', component: <SettingsModels /> },
    { id: 'connections', label: 'Connections', icon: connectionsIcon, className: 'settings-mcp-connections', component: <SettingsConnections /> },
    { id: 'tools', label: 'Tools', icon: toolsIcon, className: 'settings-tools', component: <SettingsTools /> },
    { id: 'skills', label: 'Skills', icon: settingsIcon, className: 'settings-skills-tab', component: <SettingsSkills /> },
    { id: 'meeting', label: 'Meeting', icon: settingsIcon, className: 'settings-meeting-tab', component: <MeetingRecorderSettings /> },
    { id: 'system-prompt', label: 'Prompt', icon: settingsIcon, className: 'settings-system-prompt-tab', component: <SettingsSystemPrompt /> },
    { id: 'ollama', label: 'Ollama', icon: ollamaIcon, className: 'settings-ollama-model', component: <Placeholder title="Ollama Settings" /> },
    { id: 'anthropic', label: 'Anthropic', icon: anthropicIcon, className: 'settings-anthropic-api-key', component: <SettingsApiKey provider="anthropic" /> },
    { id: 'gemini', label: 'Gemini', icon: geminiIcon, className: 'settings-gemini-api-key', component: <SettingsApiKey provider="gemini" /> },
    { id: 'openai', label: 'OpenAI', icon: openaiIcon, className: 'settings-openai-api-key', component: <SettingsApiKey provider="openai" /> },
  ];

  // "models" is selected by default
  const [activeTab, setActiveTab] = useState('models');

  // Find the currently active tab object
  const activeContent = tabs.find((t) => t.id === activeTab)?.component ?? null;

  return (
    <>
      <TitleBar setMini={setMini} />
      <div className="settings-container">
        {/* ====== SIDEBAR ====== */}
        <div className="settings-side-bar">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={`${tab.className} ${activeTab === tab.id ? 'settings-tab-active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <img src={tab.icon} alt={tab.label} className="settings-icons" />
              {tab.label}
            </div>
          ))}
        </div>

        {/* ====== CONTENT AREA ====== */}
        <div className="settings-content">
          {activeContent}
        </div>
      </div>
    </>
  );
};

export default Settings;
