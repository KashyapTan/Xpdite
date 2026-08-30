import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { WebSocketProvider, useWebSocket } from '../contexts/WebSocketContext';
import { RuntimeCapabilitiesProvider } from '../contexts/RuntimeCapabilitiesContext';
import { useTabKeyboardShortcuts } from '../hooks';
import BootScreen from './boot/BootScreen';
import xpditeLogo from '../assets/new/xpdite-logo-transparent.svg';
import '../CSS/components/Layout.css';

// Strictly-increasing nonce for Auto Mode triggers. A wall-clock timestamp can
// collide within the same millisecond (dropping the second trigger); this stays
// monotonic while still ordering roughly by time.
let autoTriggerNonce = 0;
function nextAutoTriggerNonce(): number {
  autoTriggerNonce = Math.max(autoTriggerNonce + 1, Date.now());
  return autoTriggerNonce;
}

interface HotkeyWindowBridgeProps {
  /** Live mirror of the current mini state (read at event time, never stale). */
  miniRef: React.MutableRefObject<boolean>;
  toggleMini: (val: boolean) => Promise<void>;
  setIsHidden: (hidden: boolean) => void;
}

/**
 * Bridges backend hotkey broadcasts to window/route actions. Lives INSIDE the
 * WebSocketProvider (so it can subscribe) but drives the window state that lives
 * on Layout. It renders nothing.
 *
 *  - `toggle_mini_mode`  → flip mini (kept in sync with the title-bar control).
 *  - `auto_mode_trigger` → restore-from-mini + show WITHOUT focus, then hand the
 *    trigger to the chat route via `location.state`; App does the capture/submit.
 *    Critically, this path never calls `focusWindow()` — the user's active app
 *    keeps OS focus.
 */
const HotkeyWindowBridge: React.FC<HotkeyWindowBridgeProps> = ({
  miniRef,
  toggleMini,
  setIsHidden,
}) => {
  const { subscribe } = useWebSocket();
  const navigate = useNavigate();

  useEffect(() => {
    return subscribe((data) => {
      if (data.type === 'toggle_mini_mode') {
        void toggleMini(!miniRef.current);
        return;
      }

      if (data.type === 'auto_mode_trigger') {
        // Make the answer visible without stealing focus.
        if (miniRef.current) {
          void toggleMini(false);
        }
        setIsHidden(false);
        void window.electronAPI?.showInactive?.();

        const payload = (data.content ?? {}) as Record<string, unknown>;
        // Hand off to the chat route; App reads `location.state.autoTrigger`.
        navigate('/', {
          state: { autoTrigger: { ...payload, nonce: nextAutoTriggerNonce() } },
        });
        return;
      }

      if (data.type === 'auto_mode_error') {
        setIsHidden(false);
        const payload = (data.content ?? {}) as Record<string, unknown>;
        navigate('/', {
          state: { autoError: { ...payload, nonce: nextAutoTriggerNonce() } },
        });
      }
    });
  }, [subscribe, navigate, toggleMini, setIsHidden, miniRef]);

  return null;
};

const Layout: React.FC = () => {
  const [mini, setMini] = useState<boolean>(false);
  const [isHidden, setIsHidden] = useState<boolean>(false);
  const [flash, setFlash] = useState<boolean>(false);
  const miniRef = useRef(mini);
  const flashTimerRef = useRef<number | null>(null);

  // Register tab keyboard shortcuts (Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab)
  useTabKeyboardShortcuts();

  useEffect(() => {
    miniRef.current = mini;
  }, [mini]);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current !== null) {
        window.clearTimeout(flashTimerRef.current);
      }
    };
  }, []);

  const toggleMini = useCallback(async (val: boolean) => {
    setMini(val);
    if (window.electronAPI) {
      await window.electronAPI.setMiniMode(val);
    }
  }, []);

  const triggerFlash = useCallback(() => {
    setFlash(true);
    if (flashTimerRef.current !== null) {
      window.clearTimeout(flashTimerRef.current);
    }
    flashTimerRef.current = window.setTimeout(() => setFlash(false), 450);
  }, []);

  return (
    <WebSocketProvider>
      <RuntimeCapabilitiesProvider>
        <HotkeyWindowBridge
          miniRef={miniRef}
          toggleMini={toggleMini}
          setIsHidden={setIsHidden}
        />
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

          {flash && <div className="auto-mode-flash" aria-hidden="true" />}

          <div className="container" style={{ opacity: isHidden ? 0 : 1 }}>
            <BootScreen />
            <Outlet context={{ setMini: toggleMini, setIsHidden, isHidden, triggerFlash }} />
          </div>
        </div>
      </RuntimeCapabilitiesProvider>
    </WebSocketProvider>
  );
};

export default Layout;
export { Layout };
