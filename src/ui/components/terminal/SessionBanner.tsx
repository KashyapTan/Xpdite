/**
 * Session banner shown while autonomous mode is active.
 */
import { BoltIcon } from '../icons/AppIcons';

interface SessionBannerProps {
  onStop: () => void;
}

export function SessionBanner({ onStop }: SessionBannerProps) {
  return (
    <div className="terminal-session-banner">
      <span className="session-banner-text">
        <BoltIcon size={14} className="session-banner-icon" />
        <span>Autonomous mode active</span>
      </span>
      <button className="btn-stop-session" onClick={onStop}>
        Stop
      </button>
    </div>
  );
}
