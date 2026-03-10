import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { WebSocketProvider } from '../contexts/WebSocketContext';
import { MeetingRecorderProvider } from '../contexts/MeetingRecorderContext';
import BootScreen from './boot/BootScreen';
import xpditeLogo from '../assets/transparent-xpdite-logo.png';
import '../CSS/App.css';

const Layout: React.FC = () => {
  const [mini, setMini] = useState<boolean>(false);
  const [isHidden, setIsHidden] = useState<boolean>(false);

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
      <MeetingRecorderProvider>
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
      </MeetingRecorderProvider>
    </WebSocketProvider>
  );
};

export default Layout;
export { Layout };

