import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { MeetingRecorderProvider } from '../contexts/MeetingRecorderContext';
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
          <Outlet context={{ setMini: toggleMini, setIsHidden, isHidden }} />
        </div>
      </div>
    </MeetingRecorderProvider>
  );
};

export default Layout;
export { Layout };

