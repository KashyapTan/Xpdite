import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import MeetingRecorderSettings from '../../../components/settings/MeetingRecorderSettings';

const sendMock = vi.fn();
const subscribeMock = vi.fn();
const unsubscribeMock = vi.fn();
const {
  getApiKeyStatusMock,
  saveApiKeyMock,
  deleteApiKeyMock,
} = vi.hoisted(() => ({
  getApiKeyStatusMock: vi.fn(),
  saveApiKeyMock: vi.fn(),
  deleteApiKeyMock: vi.fn(),
}));

vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: subscribeMock,
  }),
}));

vi.mock('../../../services/api', () => ({
  api: {
    getApiKeyStatus: getApiKeyStatusMock,
    saveApiKey: saveApiKeyMock,
    deleteApiKey: deleteApiKeyMock,
  },
}));

type Message = Record<string, unknown>;
let subscriber: ((data: Message) => void) | null = null;

describe('MeetingRecorderSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    subscriber = null;
    getApiKeyStatusMock.mockResolvedValue({
      huggingface: {
        has_key: true,
        masked: 'hf-...1234',
      },
    });
    saveApiKeyMock.mockResolvedValue({
      status: 'saved',
      provider: 'huggingface',
      masked: 'hf-...9999',
    });
    deleteApiKeyMock.mockResolvedValue(undefined);
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
    expect(screen.getByDisplayValue('Base | Balanced (recommended)')).toBeInTheDocument();
    await waitFor(() => {
      expect(getApiKeyStatusMock).toHaveBeenCalledTimes(1);
      expect(screen.getByText('Configured')).toBeInTheDocument();
      expect(screen.getByText('hf-...1234')).toBeInTheDocument();
    });
    expect(screen.getByText(/pyannote\/speaker-diarization-3.1/)).toBeInTheDocument();
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
      expect(screen.getByDisplayValue('Small | Most accurate, slower')).toBeInTheDocument();
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

  test('saves and removes the Hugging Face token through the encrypted key API', async () => {
    render(<MeetingRecorderSettings />);

    const tokenInput = screen.getByLabelText('Personal access token');
    fireEvent.change(tokenInput, { target: { value: 'hf_test_token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }));

    await waitFor(() => {
      expect(saveApiKeyMock).toHaveBeenCalledWith('huggingface', 'hf_test_token');
      expect(screen.getByText('Hugging Face token saved.')).toBeInTheDocument();
      expect(screen.getByText('hf-...9999')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Remove token' }));

    await waitFor(() => {
      expect(deleteApiKeyMock).toHaveBeenCalledWith('huggingface');
      expect(screen.getByText('Hugging Face token removed.')).toBeInTheDocument();
    });
  });
});

