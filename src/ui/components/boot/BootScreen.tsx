import React from 'react';
import { useBootContext } from '../../contexts/BootContext';
import '../../CSS/boot/BootScreen.css';

const BootScreen: React.FC = () => {
  const { bootState, retry } = useBootContext();
  const isError = bootState.phase === 'error';

  if (!isError) return null;

  return (
    <div className="startup-error-overlay" role="alert" aria-live="assertive">
      <section className="startup-error-panel" aria-labelledby="startup-error-title">
        <p className="startup-error-label" id="startup-error-title">Startup failed</p>
        {bootState.error && <p className="startup-error-detail">{bootState.error}</p>}
        <button className="startup-error-retry" type="button" onClick={retry}>
          Retry
        </button>
      </section>
    </div>
  );
};

export default BootScreen;
