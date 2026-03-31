import React from 'react';

const SettingsOllama: React.FC = () => (
  <div style={{ padding: 20 }}>
    <h2 style={{ margin: '0 0 10px 0', fontSize: '1.5rem' }}>Ollama</h2>
    <p style={{ margin: '0 0 18px 0', color: 'rgba(255,255,255,0.65)', lineHeight: 1.6 }}>
      Ollama now runs through the same LiteLLM path as the other providers. Local Ollama keeps working at <code>http://localhost:11434</code> by default.
    </p>
    <div style={{
      border: '1px solid rgba(255,255,255,0.14)',
      borderRadius: 10,
      padding: 16,
      background: 'rgba(255,255,255,0.03)',
      color: 'rgba(255,255,255,0.82)',
      lineHeight: 1.6,
    }}>
      <div style={{ marginBottom: 10 }}>
        For Ollama Cloud or any remote Ollama-compatible endpoint, configure environment variables before launching the app:
      </div>
      <div><code>OLLAMA_API_BASE=https://your-endpoint</code></div>
      <div><code>OLLAMA_API_KEY=your-token</code> (only if the endpoint requires auth)</div>
      <div style={{ marginTop: 10, color: 'rgba(255,255,255,0.62)' }}>
        Model selection stays in the Models tab. Add a custom Ollama model ID there to keep env-driven cloud models selectable.
      </div>
    </div>
  </div>
);

export default SettingsOllama;
