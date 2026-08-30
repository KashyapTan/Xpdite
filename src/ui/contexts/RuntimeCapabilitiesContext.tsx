import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../services/api';
import type { RuntimeCapabilities } from '../services/api';
import { useWebSocket } from './WebSocketContext';

const RuntimeCapabilitiesContext = createContext<RuntimeCapabilities | null>(null);

const CONSERVATIVE_RUNTIME_CAPABILITIES: RuntimeCapabilities = {
  profile: 'compatibility-fallback',
  platform: 'unknown',
  architecture: 'unknown',
  features: {
    microphone_dictation: { available: true, reason: '' },
    meeting_transcription: { available: true, reason: '' },
    youtube_whisper_fallback: { available: true, reason: '' },
    whisperx_alignment: { available: true, reason: '' },
    speaker_diarization: { available: true, reason: '' },
    local_sentence_embeddings: { available: true, reason: '' },
  },
};

export const RuntimeCapabilitiesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isConnected } = useWebSocket();
  const [capabilities, setCapabilities] = useState<RuntimeCapabilities>(
    CONSERVATIVE_RUNTIME_CAPABILITIES,
  );

  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;
    const request = api.getRuntimeCapabilities?.();
    if (!request) return;
    void request.then((resolved) => {
      if (!cancelled) setCapabilities(resolved);
    });
    return () => {
      cancelled = true;
    };
  }, [isConnected]);

  return (
    <RuntimeCapabilitiesContext.Provider value={capabilities}>
      {children}
    </RuntimeCapabilitiesContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export function useRuntimeCapabilities(): RuntimeCapabilities {
  return useContext(RuntimeCapabilitiesContext) ?? CONSERVATIVE_RUNTIME_CAPABILITIES;
}
