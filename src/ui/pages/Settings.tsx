import React, { Suspense, lazy, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
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

const modelsIcon = new URL('../assets/models.svg', import.meta.url).href;
const connectionsIcon = new URL('../assets/mcp.svg', import.meta.url).href;
const ollamaIcon = new URL('../assets/ollama.svg', import.meta.url).href;
const anthropicIcon = new URL('../assets/anthropic.svg', import.meta.url).href;
const geminiIcon = new URL('../assets/gemini.svg', import.meta.url).href;
const openaiIcon = new URL('../assets/openai.svg', import.meta.url).href;
const openrouterIcon = new URL('../assets/openrouter.svg', import.meta.url).href;

const SettingsModels = lazy(() => import('../components/settings/SettingsModels'));
const SettingsTools = lazy(() => import('../components/settings/SettingsTools'));
const SettingsApiKey = lazy(() => import('../components/settings/SettingsApiKey'));
const SettingsConnections = lazy(() => import('../components/settings/SettingsConnections'));
const SettingsMarketplace = lazy(() => import('../components/settings/SettingsMarketplace'));
const SettingsSystemPrompt = lazy(() => import('../components/settings/SettingsSystemPrompt'));
const SettingsSkills = lazy(() => import('../components/settings/SettingsSkills'));
const SettingsMemory = lazy(() => import('../components/settings/SettingsMemory'));
const SettingsArtifacts = lazy(() => import('../components/settings/SettingsArtifacts'));
const MeetingRecorderSettings = lazy(() => import('../components/settings/MeetingRecorderSettings'));
const SettingsOllama = lazy(() => import('../components/settings/SettingsOllama'));
const SettingsSubAgents = lazy(() => import('../components/settings/SettingsSubAgents'));
const SettingsMobileChannels = lazy(() => import('../components/settings/SettingsMobileChannels'));
const SettingsScheduledJobs = lazy(() => import('../components/settings/SettingsScheduledJobs'));

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
  const [canRenderPanel, setCanRenderPanel] = useState(false);

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
  const activeContent = canRenderPanel
    ? tabs.find((t) => t.id === activeTab)?.component ?? null
    : null;

  useEffect(() => {
    const animationFrameId = window.requestAnimationFrame(() => {
      setCanRenderPanel(true);
    });

    return () => {
      window.cancelAnimationFrame(animationFrameId);
    };
  }, []);

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
          <Suspense fallback={<div className="settings-section-loading">Loading...</div>}>
            {activeContent ?? <div className="settings-section-loading">Loading...</div>}
          </Suspense>
        </div>
      </div>
    </>
  );
};

export default Settings;
