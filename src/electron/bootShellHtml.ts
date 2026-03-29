/**
 * Immediate boot shell — a self-contained HTML page rendered as a data: URL.
 *
 * Electron loads this **before** Vite or the production React bundle is
 * available. It uses the same black-hole styling as the renderer-side
 * `BootScreen.css`, then receives live boot updates from the main process
 * through `electronAPI` IPC (exposed by preload.ts).
 *
 * Once the renderer app is reachable, Electron can navigate into React while
 * preserving the same boot-state messaging. This file is never touched at
 * runtime by React — it is pure HTML/CSS/JS.
 */

const BOOT_SHELL_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Xpdite</title>
    <style>
      :root {
        color-scheme: dark;
      }

      * {
        box-sizing: border-box;
      }

      html,
      body {
        margin: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: transparent;
        color: rgba(255, 255, 255, 0.92);
        font-family: "Montserrat", "Segoe UI", sans-serif;
      }

      .boot-screen {
        position: fixed;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: radial-gradient(ellipse at center, rgba(15, 15, 15, 0.95) 0%, rgba(0, 0, 0, 0.98) 100%);
        border: 2px solid rgba(255, 255, 255, 0.5);
        border-radius: 8px;
        cursor: grab;
        user-select: none;
        -webkit-user-select: none;
        -webkit-app-region: drag;
      }

      .boot-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 32px;
        width: min(280px, calc(100vw - 64px));
      }

      .bh-container {
        position: relative;
        width: 120px;
        height: 120px;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .bh-halo {
        position: absolute;
        width: 120px;
        height: 120px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(255, 255, 255, 0.06) 0%, transparent 70%);
        animation: bh-pulse 3s ease-in-out infinite;
      }

      .bh-ring {
        position: absolute;
        width: 72px;
        height: 72px;
        border-radius: 50%;
        border: 1px solid rgba(255, 255, 255, 0.25);
        animation: bh-rotate 8s linear infinite;
      }

      .bh-void {
        position: absolute;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: rgba(5, 5, 5, 1);
        box-shadow: 0 0 20px 4px rgba(0, 0, 0, 0.6);
      }

      .boot-status {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        width: 240px;
      }

      .boot-phase {
        margin: 0;
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.52);
      }

      .boot-progress {
        width: 100%;
        display: grid;
        gap: 8px;
      }

      .boot-progress.hidden {
        display: none;
      }

      .boot-progress-meta {
        display: flex;
        justify-content: flex-end;
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.55);
      }

      .boot-progress-value {
        flex-shrink: 0;
      }

      .boot-progress-track {
        width: 100%;
        height: 3px;
        border-radius: 2px;
        background: rgba(255, 255, 255, 0.1);
        overflow: hidden;
      }

      .boot-progress-fill {
        width: 10%;
        height: 100%;
        border-radius: 2px;
        background: rgba(255, 255, 255, 0.4);
        transition: width 0.25s ease-out;
      }

      .boot-status-detail {
        min-height: 16px;
        margin: 0;
        font-size: 11px;
        text-align: center;
        color: rgba(255, 255, 255, 0.5);
      }

      .boot-error {
        display: none;
        flex-direction: column;
        align-items: center;
        gap: 10px;
      }

      .boot-error.visible {
        display: flex;
      }

      .boot-error-detail {
        margin: 0;
        font-size: 11px;
        color: rgba(255, 100, 100, 0.8);
        text-align: center;
        max-width: 280px;
        word-break: break-word;
      }

      .boot-retry-btn {
        padding: 6px 20px;
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.8);
        font-family: inherit;
        font-size: 12px;
        cursor: pointer;
        transition: background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;
        -webkit-app-region: no-drag;
      }

      .boot-retry-btn:hover {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.5);
      }

      .boot-retry-btn:disabled {
        opacity: 0.64;
        cursor: wait;
      }

      @keyframes bh-rotate {
        from { transform: rotate(0deg); }
        to   { transform: rotate(360deg); }
      }

      @keyframes bh-pulse {
        0%, 100% { opacity: 0.5; transform: scale(1); }
        50%      { opacity: 1; transform: scale(1.08); }
      }

      @media (prefers-reduced-motion: reduce) {
        .bh-ring,
        .bh-halo {
          animation: none;
        }
      }
    </style>
  </head>
  <body>
    <main class="boot-screen">
      <div class="boot-content">
        <div class="bh-container" aria-hidden="true">
          <div class="bh-halo"></div>
          <div class="bh-ring"></div>
          <div class="bh-void"></div>
        </div>

        <div class="boot-status">
          <p class="boot-phase" id="phase">Starting</p>

          <div class="boot-progress" id="progressBlock">
            <div class="boot-progress-meta">
              <span class="boot-progress-value" id="progressValue">5%</span>
            </div>
            <div class="boot-progress-track">
              <div class="boot-progress-fill" id="progressFill"></div>
            </div>
          </div>

          <p class="boot-status-detail" id="status"></p>

          <div class="boot-error" id="errorState">
            <p class="boot-error-detail" id="errorCopy"></p>
            <button class="boot-retry-btn" type="button" id="retryButton">Retry startup</button>
          </div>
        </div>
      </div>
    </main>
    <script>
      const phase         = document.getElementById('phase');
      const status        = document.getElementById('status');
      const progressBlock = document.getElementById('progressBlock');
      const progressValue = document.getElementById('progressValue');
      const progressFill  = document.getElementById('progressFill');
      const errorState    = document.getElementById('errorState');
      const errorCopy     = document.getElementById('errorCopy');
      const retryButton   = document.getElementById('retryButton');
      let unsubscribeBootState = null;

      const phaseLabels = {
        starting:           'Starting',
        launching_backend:  'Launching backend',
        connecting_tools:   'Connecting tools',
        loading_interface:  'Opening workspace',
        ready:              'Ready',
        error:              'Startup failed',
      };

      function applyState(state) {
        const progress = state.phase === 'error'
          ? 0
          : Math.max(5, Math.min(state.progress ?? 0, 100));
        const isError = state.phase === 'error';
        phase.textContent = phaseLabels[state.phase] || 'Starting';
        progressValue.textContent = progress + '%';
        progressFill.style.width = progress + '%';
        progressBlock.classList.toggle('hidden', isError);
        errorState.classList.toggle('visible', isError);
        errorCopy.textContent = state.error || '';
        status.textContent = isError ? (state.message || 'Startup failed.') : '';
      }

      async function init() {
        if (!window.electronAPI || !window.electronAPI.getBootState) return;
        try {
          applyState(await window.electronAPI.getBootState());
          if (window.electronAPI.onBootState) {
            unsubscribeBootState = window.electronAPI.onBootState(applyState);
          }
        } catch (err) {
          console.error('Boot shell init error:', err);
        }
      }

      retryButton.addEventListener('click', async () => {
        if (!window.electronAPI || !window.electronAPI.retryBoot) return;
        retryButton.disabled = true;
        retryButton.textContent = 'Retrying...';
        try {
          await window.electronAPI.retryBoot();
        } catch (err) {
          console.error('Retry failed:', err);
        } finally {
          retryButton.disabled = false;
          retryButton.textContent = 'Retry startup';
        }
      });

      window.addEventListener('beforeunload', () => {
        if (typeof unsubscribeBootState === 'function') unsubscribeBootState();
      });

      init();
    </script>
  </body>
</html>`;

export function createBootShellDataUrl(): string {
    return `data:text/html;charset=UTF-8,${encodeURIComponent(BOOT_SHELL_HTML)}`;
}
