import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import MeetingRecorderSettings from '../../../components/settings/MeetingRecorderSettings';

const sendMock = vi.fn();
const subscribeMock = vi.fn();
const unsubscribeMock = vi.fn();

vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: subscribeMock,
  }),
}));

type Message = Record<string, unknown>;
let subscriber: ((data: Message) => void) | null = null;

describe('MeetingRecorderSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    subscriber = null;
    subscribeMock.mockImplementation((handler: (data: Message) => void) => {
      subscriber = handler;
      return unsubscribeMock;
    });
  });

  test('requests compute info/settings on mount and renders defaults', async () => {
    render(<MeetingRecorderSettings />);

    expect(sendMock).toHaveBeenCalledWith({ type: 'meeting_get_compute_info' });
    expect(sendMock).toHaveBeenCalledWith({ type: 'meeting_get_settings' });
    expect(screen.getByText('Detecting...')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Base — Balanced (recommended)')).toBeInTheDocument();
  });

  test('applies websocket updates for compute info and settings', async () => {
    render(<MeetingRecorderSettings />);

    await act(async () => {
      subscriber?.({
        type: 'meeting_compute_info',
        content: {
          backend: 'cuda',
          device_name: 'RTX 4090',
          vram_gb: 24,
          compute_type: 'float16',
        },
      });
      subscriber?.({
        type: 'meeting_settings',
        content: {
          whisper_model: 'small',
          keep_audio: 'true',
          diarization_enabled: 'false',
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('NVIDIA CUDA — RTX 4090 (24 GB)')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Small — Most accurate, slower')).toBeInTheDocument();
      expect(screen.getByText('Disabled')).toBeInTheDocument();
      expect(screen.getByText('Keep files')).toBeInTheDocument();
    });
  });

  test('sends update messages when user changes settings', async () => {
    render(<MeetingRecorderSettings />);

    const modelSelect = screen.getByRole('combobox');
    fireEvent.change(modelSelect, { target: { value: 'tiny' } });

    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]); // diarization
    fireEvent.click(checkboxes[1]); // keep_audio

    await waitFor(() => {
      expect(sendMock).toHaveBeenCalledWith({
        type: 'meeting_update_settings',
        settings: { whisper_model: 'tiny' },
      });
      expect(sendMock).toHaveBeenCalledWith({
        type: 'meeting_update_settings',
        settings: { diarization_enabled: 'false' },
      });
      expect(sendMock).toHaveBeenCalledWith({
        type: 'meeting_update_settings',
        settings: { keep_audio: 'true' },
      });
      expect(screen.getByText('Saving...')).toBeInTheDocument();
    });
  });
});

