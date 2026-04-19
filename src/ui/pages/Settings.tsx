import React, { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import SettingsModels from '../components/settings/SettingsModels';
import SettingsTools from '../components/settings/SettingsTools';
import SettingsApiKey from '../components/settings/SettingsApiKey';
import SettingsConnections from '../components/settings/SettingsConnections';
import SettingsMarketplace from '../components/settings/SettingsMarketplace';
import SettingsSystemPrompt from '../components/settings/SettingsSystemPrompt';
import SettingsSkills from '../components/settings/SettingsSkills';
import SettingsMemory from '../components/settings/SettingsMemory';
import SettingsArtifacts from '../components/settings/SettingsArtifacts';
import MeetingRecorderSettings from '../components/settings/MeetingRecorderSettings';
import SettingsOllama from '../components/settings/SettingsOllama';
import SettingsSubAgents from '../components/settings/SettingsSubAgents';
import SettingsMobileChannels from '../components/settings/SettingsMobileChannels';
import SettingsScheduledJobs from '../components/settings/SettingsScheduledJobs';
import {
  ArtifactsTabIcon,
  ConnectionsTabIcon,
  MeetingTabIcon,
  MemoryTabIcon,
  MobileTabIcon,
  PromptTabIcon,
  SkillsTabIcon,
  SubAgentsTabIcon,
  TasksTabIcon,
  ToolsTabIcon,
} from '../components/icons/AppIcons';
import '../CSS/pages/Settings.css';
import modelsIcon from '../assets/models.svg';
import connectionsIcon from '../assets/mcp.svg';
import ollamaIcon from '../assets/ollama.svg';
import anthropicIcon from '../assets/anthropic.svg';
import geminiIcon from '../assets/gemini.svg';
import openaiIcon from '../assets/openai.svg';
import openrouterIcon from '../assets/openrouter.svg';

/**
 * Every tab the Settings page supports.
 * `id` is used as the active-tab key.
 * `icon` / `label` render in the sidebar.
 * `component` is what shows in the content area.
 */
type SettingsTab = {
  id: string;
  label: string;
  icon: React.ReactNode;
  className: string;
  component: React.ReactNode;
};

const Settings: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();

  // Define all tabs
  const tabs: SettingsTab[] = [
    {
      id: 'models',
      label: 'Models',
      icon: <img src={modelsIcon} alt="Models" className="settings-icons" />,
      className: 'settings-models',
      component: <SettingsModels />,
    },
    {
      id: 'connections',
      label: 'Connections',
      icon: <ConnectionsTabIcon className="settings-icons" size={18} />,
      className: 'settings-mcp-connections',
      component: <SettingsConnections />,
    },
    {
      id: 'marketplace',
      label: 'Marketplace',
      icon: <img src={connectionsIcon} alt="Marketplace" className="settings-icons" />,
      className: 'settings-marketplace-tab',
      component: <SettingsMarketplace />,
    },
    {
      id: 'tools',
      label: 'Tools',
      icon: <ToolsTabIcon className="settings-icons" size={18} />,
      className: 'settings-tools',
      component: <SettingsTools />,
    },
    {
      id: 'skills',
      label: 'Skills',
      icon: <SkillsTabIcon className="settings-icons" size={18} />,
      className: 'settings-skills-tab',
      component: <SettingsSkills />,
    },
    {
      id: 'memory',
      label: 'Memory',
      icon: <MemoryTabIcon className="settings-icons" size={18} />,
      className: 'settings-memory-tab',
      component: <SettingsMemory />,
    },
    {
      id: 'artifacts',
      label: 'Artifacts',
      icon: <ArtifactsTabIcon className="settings-icons" size={18} />,
      className: 'settings-artifacts-tab',
      component: <SettingsArtifacts />,
    },
    {
      id: 'scheduled-jobs',
      label: 'Tasks',
      icon: <TasksTabIcon className="settings-icons" size={18} />,
      className: 'settings-scheduled-jobs-tab',
      component: <SettingsScheduledJobs />,
    },
    {
      id: 'meeting',
      label: 'Meeting',
      icon: <MeetingTabIcon className="settings-icons" size={18} />,
      className: 'settings-meeting-tab',
      component: <MeetingRecorderSettings />,
    },
    {
      id: 'sub-agents',
      label: 'Sub-Agents',
      icon: <SubAgentsTabIcon className="settings-icons" size={18} />,
      className: 'settings-sub-agents-tab',
      component: <SettingsSubAgents />,
    },
    {
      id: 'mobile',
      label: 'Mobile',
      icon: <MobileTabIcon className="settings-icons" size={18} />,
      className: 'settings-mobile-tab',
      component: <SettingsMobileChannels />,
    },
    {
      id: 'system-prompt',
      label: 'Prompt',
      icon: <PromptTabIcon className="settings-icons" size={18} />,
      className: 'settings-system-prompt-tab',
      component: <SettingsSystemPrompt />,
    },
    {
      id: 'ollama',
      label: 'Ollama',
      icon: <img src={ollamaIcon} alt="Ollama" className="settings-icons" />,
      className: 'settings-ollama-model',
      component: <SettingsOllama />,
    },
    {
      id: 'anthropic',
      label: 'Anthropic',
      icon: <img src={anthropicIcon} alt="Anthropic" className="settings-icons" />,
      className: 'settings-anthropic-api-key',
      component: <SettingsApiKey provider="anthropic" />,
    },
    {
      id: 'gemini',
      label: 'Gemini',
      icon: <img src={geminiIcon} alt="Gemini" className="settings-icons" />,
      className: 'settings-gemini-api-key',
      component: <SettingsApiKey provider="gemini" />,
    },
    {
      id: 'openai',
      label: 'OpenAI',
      icon: <img src={openaiIcon} alt="OpenAI" className="settings-icons" />,
      className: 'settings-openai-api-key',
      component: <SettingsApiKey provider="openai" />,
    },
    {
      id: 'openrouter',
      label: 'OpenRouter',
      icon: <img src={openrouterIcon} alt="OpenRouter" className="settings-icons" />,
      className: 'settings-openrouter-api-key',
      component: <SettingsApiKey provider="openrouter" />,
    },
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
              {tab.icon}
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
