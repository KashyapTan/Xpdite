import React from 'react';
import { useBootContext } from '../../contexts/BootContext';
import '../../CSS/boot/BootScreen.css';

/**
 * React-side boot screen overlay.
 *
 * The Electron boot shell (pure HTML) handles the very first part of startup.
 * Once Electron navigates to the React app, this component keeps the same
 * loading UI in place until the renderer receives the final `ready` state.
 *
 * It remains as a safety net for:
 * - Dev-mode browser (no Electron) where the fallback health poll is used
 * - Any edge case where isReady hasn't been set yet when React mounts
 */
const phaseLabels: Record<string, string> = {
  starting: 'Starting',
  launching_backend: 'Launching backend',
  connecting_tools: 'Connecting tools',
  loading_interface: 'Opening workspace',
  ready: 'Ready',
  error: 'Startup failed',
};

const BootScreen: React.FC = () => {
  const { bootState, isReady, retry } = useBootContext();
  const isError = bootState.phase === 'error';
  const progress = Math.max(5, Math.min(bootState.progress, 100));
  const [shouldRender, setShouldRender] = React.useState(!isReady);
  const [isFading, setIsFading] = React.useState(false);

  React.useEffect(() => {
    if (!isReady) {
      setShouldRender(true);
      setIsFading(false);
      return;
    }

    if (!shouldRender) return;

    setIsFading(true);
    const timeoutId = window.setTimeout(() => {
      setShouldRender(false);
      setIsFading(false);
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [isReady, shouldRender]);

  if (!shouldRender) return null;

  return (
    <div className={`boot-screen${isFading ? ' boot-screen--fading' : ''}`}>
      <div className="boot-content">
        <div className="bh-container">
          <div className="bh-halo" />
          <div className="bh-ring" />
          <div className="bh-void" />
        </div>

        <div className="boot-status">
          <p className="boot-phase">{phaseLabels[bootState.phase] ?? 'Starting'}</p>

          {!isError && (
            <div className="boot-progress">
              <div className="boot-progress-meta">
                <span className="boot-progress-value">{progress}%</span>
              </div>
              <div className="boot-progress-track">
                <div
                  className="boot-progress-fill"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {isError && (
            <div className="boot-error">
              {bootState.error && <p className="boot-error-detail">{bootState.error}</p>}
              <button className="boot-retry-btn" type="button" onClick={retry}>
                Retry
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BootScreen;
