import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsApiKey from '../../../components/settings/SettingsApiKey';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getApiKeyStatus: vi.fn(),
    saveApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
    getOpenAICodexStatus: vi.fn(),
    connectOpenAICodexBrowser: vi.fn(),
    connectOpenAICodexDevice: vi.fn(),
    cancelOpenAICodexLogin: vi.fn(),
    disconnectOpenAICodex: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);
const disconnectedCodexStatus = {
  available: true,
  connected: false,
  account_type: null,
  email: null,
  plan_type: null,
  requires_openai_auth: true,
  auth_in_progress: false,
  login_method: null,
  login_id: null,
  auth_url: null,
  verification_url: null,
  user_code: null,
  auth_mode: null,
  last_error: null,
  binary_path: 'codex.exe',
};

describe('SettingsApiKey', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getOpenAICodexStatus.mockResolvedValue(disconnectedCodexStatus);
    Object.defineProperty(window, 'electronAPI', {
      value: undefined,
      configurable: true,
    });
  });

  test('renders input state when provider has no key', async () => {
    mockedApi.getApiKeyStatus.mockResolvedValue({
      openai: { has_key: false, masked: null },
    });

    render(<SettingsApiKey provider="openai" />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Enter OpenAI API key')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  test('saves key and switches to connected state', async () => {
    mockedApi.getApiKeyStatus.mockResolvedValue({
      anthropic: { has_key: false, masked: null },
    });
    mockedApi.saveApiKey.mockResolvedValue({
      status: 'saved',
      provider: 'anthropic',
      masked: 'sk-ant-...1234',
    });

    render(<SettingsApiKey provider="anthropic" />);
    const input = await screen.findByPlaceholderText('Enter Anthropic API key');
    fireEvent.change(input, { target: { value: 'sk-ant-real' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mockedApi.saveApiKey).toHaveBeenCalledWith('anthropic', 'sk-ant-real');
      expect(screen.getByText('Connected')).toBeInTheDocument();
      expect(screen.getByText('sk-ant-...1234')).toBeInTheDocument();
    });
  });

  test('shows validation error when save fails', async () => {
    mockedApi.getApiKeyStatus.mockResolvedValue({
      openrouter: { has_key: false, masked: null },
    });
    mockedApi.saveApiKey.mockRejectedValue(new Error('Invalid API key'));

    render(<SettingsApiKey provider="openrouter" />);
    const input = await screen.findByPlaceholderText('Enter OpenRouter API key');
    fireEvent.change(input, { target: { value: 'bad-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByText('Invalid API key')).toBeInTheDocument();
    });
  });

  test('removes stored key and returns to input state', async () => {
    mockedApi.getApiKeyStatus.mockResolvedValue({
      gemini: { has_key: true, masked: 'AIza...xyz' },
    });
    mockedApi.deleteApiKey.mockResolvedValue(undefined);

    render(<SettingsApiKey provider="gemini" />);

    await waitFor(() => {
      expect(screen.getByText('AIza...xyz')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(mockedApi.deleteApiKey).toHaveBeenCalledWith('gemini');
      expect(screen.getByPlaceholderText('Enter Gemini API key')).toBeInTheDocument();
      expect(screen.getByText('API key removed')).toBeInTheDocument();
    });
  });

  test('starts ChatGPT subscription browser sign-in from the OpenAI tab', async () => {
    const openExternalUrl = vi.fn().mockResolvedValue({ success: true });
    Object.defineProperty(window, 'electronAPI', {
      value: { openExternalUrl },
      configurable: true,
    });
    mockedApi.getApiKeyStatus.mockResolvedValue({
      openai: { has_key: false, masked: null },
    });
    mockedApi.connectOpenAICodexBrowser.mockResolvedValue({
      ...disconnectedCodexStatus,
      auth_in_progress: true,
      auth_url: 'https://chatgpt.com/auth/openai/codex',
    });

    render(<SettingsApiKey provider="openai" />);

    await screen.findByText('ChatGPT Subscription');
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    await waitFor(() => {
      expect(mockedApi.connectOpenAICodexBrowser).toHaveBeenCalled();
      expect(openExternalUrl).toHaveBeenCalledWith('https://chatgpt.com/auth/openai/codex');
    });
  });
});

