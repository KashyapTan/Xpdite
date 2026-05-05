import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsOllama from '../../../components/settings/SettingsOllama';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getOllamaSettings: vi.fn(),
    setOllamaSettings: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsOllama', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getOllamaSettings.mockResolvedValue({
      local_context_size: 32768,
      default_local_context_size: 32768,
      min_local_context_size: 512,
      max_local_context_size: 1048576,
      is_custom: false,
    });
    mockedApi.setOllamaSettings.mockResolvedValue({
      local_context_size: 65536,
      default_local_context_size: 32768,
      min_local_context_size: 512,
      max_local_context_size: 1048576,
      is_custom: true,
    });
  });

  test('loads current local context size', async () => {
    render(<SettingsOllama />);

    expect(await screen.findByRole('heading', { name: 'Ollama' })).toBeInTheDocument();
    expect(screen.getByLabelText('Local Ollama context size')).toHaveValue(32768);
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  test('saves a custom local context size', async () => {
    render(<SettingsOllama />);

    const input = await screen.findByLabelText('Local Ollama context size');
    fireEvent.change(input, { target: { value: '65536' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mockedApi.setOllamaSettings).toHaveBeenCalledWith({
        local_context_size: 65536,
      });
      expect(screen.getByText('Settings saved')).toBeInTheDocument();
      expect(screen.getByText('Custom')).toBeInTheDocument();
    });
  });

  test('resets custom context size to default', async () => {
    mockedApi.getOllamaSettings.mockResolvedValue({
      local_context_size: 65536,
      default_local_context_size: 32768,
      min_local_context_size: 512,
      max_local_context_size: 1048576,
      is_custom: true,
    });
    mockedApi.setOllamaSettings.mockResolvedValue({
      local_context_size: 32768,
      default_local_context_size: 32768,
      min_local_context_size: 512,
      max_local_context_size: 1048576,
      is_custom: false,
    });

    render(<SettingsOllama />);

    await screen.findByText('Custom');
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));

    await waitFor(() => {
      expect(mockedApi.setOllamaSettings).toHaveBeenCalledWith({
        local_context_size: null,
      });
      expect(screen.getByText('Default')).toBeInTheDocument();
    });
  });
});
