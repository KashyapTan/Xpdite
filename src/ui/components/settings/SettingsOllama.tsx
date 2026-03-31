import React from 'react';

const SettingsOllama: React.FC = () => (
  <div style={{ padding: 20 }}>
    <h2 style={{ margin: '0 0 10px 0', fontSize: '1.5rem' }}>Ollama</h2>
    <p style={{ margin: '0 0 18px 0', color: 'rgba(255,255,255,0.65)', lineHeight: 1.6 }}>
      Ollama now runs through the same LiteLLM path as the other providers, with a local-first setup at <code>http://localhost:11434</code>.
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
        1) Start your local Ollama daemon. 2) Pull models (for example <code>ollama pull llama3.2</code>). 3) Refresh the Models tab.
      </div>
      <div style={{ marginTop: 10, color: 'rgba(255,255,255,0.62)' }}>
        Model selection stays in the Models tab. Add a custom Ollama model ID there if you want to keep a model selectable before it is pulled.
      </div>
    </div>
  </div>
);

export default SettingsOllama;
