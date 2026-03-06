import React from 'react';
import { useNavigate } from 'react-router-dom';
import '../CSS/TitleBar.css';
import xpditeLogo from '../assets/transparent-xpdite-logo.png';


interface TitleBarProps {
  onClearContext: () => void;
  setMini: (mini: boolean) => void;
}

const TitleBar: React.FC<TitleBarProps> = ({ onClearContext, setMini }) => {
  const navigate = useNavigate();

  return (
    <div className="title-bar">
      <div className="nav-bar">
        <div className="settingsButton" onClick={() => navigate('/settings')}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="settings-icon">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            <circle cx="12" cy="12" r="4"/>
          </svg>
        </div>
        <div className="chatHistoryButton" onClick={() => navigate('/history')}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="chat-history-icon">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
            <path d="M12 7v5l4 2"/>
          </svg>
        </div>
        <div className="recordedMeetingsAlbumButton" onClick={() => navigate('/album')}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="recorded-meetings-album-icon">
            <circle cx="12" cy="12" r="10"/>
            <path d="M6 12c0-1.7.7-3.2 1.8-4.2"/>
            <circle cx="12" cy="12" r="2"/>
            <path d="M18 12c0 1.7-.7 3.2-1.8 4.2"/>
          </svg>
        </div>
      </div>
      <div className="blank-space-to-drag" onClick={() => navigate('/')}></div>
      <div className="nav-bar-right-side">
        <div className="newChatButton" onClick={() => { onClearContext(); navigate('/', { state: { newChat: true } }); }} title="Start new chat">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="new-chat-icon">
            <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>
          </svg>
        </div>
        <div className="xpdite-logo-holder">
          <img
            src={xpditeLogo}
            alt="Xpdite Logo"
            className='xpdite-logo'
            onClick={() => {
              console.log('Logo clicked, entering mini mode');
              setMini(true);
              window.electronAPI?.setMiniMode(true);
            }}
            style={{ cursor: 'pointer' }}
            title="Mini mode"
          />
        </div>
      </div>
    </div>
  );
};

export default TitleBar;
