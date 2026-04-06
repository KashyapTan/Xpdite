import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { WebSocketProvider } from '../contexts/WebSocketContext';
import { useTabKeyboardShortcuts } from '../hooks';
import BootScreen from './boot/BootScreen';
import xpditeLogo from '../assets/transparent-xpdite-logo.png';
import '../CSS/Layout.css';

const Layout: React.FC = () => {
  const [mini, setMini] = useState<boolean>(false);
  const [isHidden, setIsHidden] = useState<boolean>(false);

  // Register tab keyboard shortcuts (Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab)
  useTabKeyboardShortcuts();

  const toggleMini = async (val: boolean) => {
    console.log('toggleMini called with:', val);
    setMini(val);
    if (window.electronAPI) {
      await window.electronAPI.setMiniMode(val);
      console.log('electronAPI.setMiniMode call finished');
    }
  };

  return (
    <WebSocketProvider>
      <div className={`app-wrapper ${mini ? 'mini-mode' : 'normal-mode'}`}>
        <div
          className="mini-container"
          title="Restore Xpdite"
          onClick={() => toggleMini(false)}
        >
          <img
            src={xpditeLogo}
            alt="Xpdite Logo"
            className="xpdite-logo"
          />
        </div>

        <div className="container" style={{ opacity: isHidden ? 0 : 1 }}>
          <BootScreen />
          <Outlet context={{ setMini: toggleMini, setIsHidden, isHidden }} />
        </div>
      </div>
    </WebSocketProvider>
  );
};

export default Layout;
export { Layout };

