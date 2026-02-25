/**
 * TabBar — horizontal tab strip between the title bar and the chat area.
 *
 * Shows one tab per open conversation, with a close (×) button on each tab
 * and a "new chat" button that reuses the existing new-chat icon.
 */
import React from 'react';
import { useTabs } from '../contexts/TabContext';
import newChatIcon from '../assets/new-chat-icon.svg';
import '../CSS/TabBar.css';

interface TabBarProps {
  /** WebSocket send function — for notifying the backend about tab lifecycle. */
  wsSend: (msg: Record<string, unknown>) => void;
}

const TabBar: React.FC<TabBarProps> = ({ wsSend }) => {
  const { tabs, activeTabId, createTab, closeTab, switchTab } = useTabs();

  const handleCreate = () => {
    const id = createTab();
    if (id) {
      wsSend({ type: 'tab_created', tab_id: id });
    }
  };

  const handleClose = (e: React.MouseEvent, tabId: string) => {
    e.stopPropagation();
    wsSend({ type: 'tab_closed', tab_id: tabId });
    closeTab(tabId);
  };

  // Don't render the bar when only one tab is open — keep the UI clean.
  if (tabs.length <= 1) return null;

  return (
    <div className="tab-bar">
      <div className="tab-bar-tabs">
        {tabs.map(tab => (
          <div
            key={tab.id}
            className={`tab-bar-tab ${tab.id === activeTabId ? 'active' : ''}`}
            onClick={() => switchTab(tab.id)}
            title={tab.title}
          >
            <span className="tab-bar-tab-title">{tab.title}</span>
            {tabs.length > 1 && (
              <button
                className="tab-bar-tab-close"
                onClick={e => handleClose(e, tab.id)}
                title="Close tab"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      <button className="tab-bar-new" onClick={handleCreate} title="New tab">
        <img src={newChatIcon} alt="New Tab" className="tab-bar-new-icon" />
      </button>
    </div>
  );
};

export default TabBar;
