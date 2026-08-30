import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  RuntimeCapabilitiesProvider,
  useRuntimeCapabilities,
} from '../../contexts/RuntimeCapabilitiesContext';

const { getRuntimeCapabilitiesMock, websocketState } = vi.hoisted(() => ({
  getRuntimeCapabilitiesMock: vi.fn(),
  websocketState: { isConnected: true },
}));

vi.mock('../../services/api', () => ({
  api: { getRuntimeCapabilities: getRuntimeCapabilitiesMock },
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => websocketState,
}));

const intelCapabilities = {
  profile: 'mac-intel-transcription',
  platform: 'darwin',
  architecture: 'x64',
  features: {
    microphone_dictation: { available: true, reason: '' },
    meeting_transcription: { available: true, reason: '' },
    youtube_whisper_fallback: { available: true, reason: '' },
    whisperx_alignment: { available: false, reason: 'Unavailable in the Intel macOS build.' },
    speaker_diarization: { available: false, reason: 'Unavailable in the Intel macOS build.' },
    local_sentence_embeddings: { available: false, reason: 'Unavailable in this build.' },
  },
};

const Consumer = () => {
  const capabilities = useRuntimeCapabilities();
  return <div>{capabilities.profile}:{String(capabilities.features.meeting_transcription.available)}</div>;
};

describe('RuntimeCapabilitiesProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    websocketState.isConnected = true;
    getRuntimeCapabilitiesMock.mockResolvedValue(intelCapabilities);
  });

  test('fetches and shares effective capabilities after backend connection', async () => {
    render(
      <RuntimeCapabilitiesProvider>
        <Consumer />
      </RuntimeCapabilitiesProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('mac-intel-transcription:true')).toBeInTheDocument();
    });
    expect(getRuntimeCapabilitiesMock).toHaveBeenCalledTimes(1);
  });

  test('uses compatibility defaults before the backend is connected', () => {
    websocketState.isConnected = false;
    render(
      <RuntimeCapabilitiesProvider>
        <Consumer />
      </RuntimeCapabilitiesProvider>,
    );

    expect(screen.getByText('compatibility-fallback:true')).toBeInTheDocument();
    expect(getRuntimeCapabilitiesMock).not.toHaveBeenCalled();
  });
});
