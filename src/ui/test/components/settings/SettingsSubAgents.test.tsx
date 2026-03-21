import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsSubAgents from '../../../components/settings/SettingsSubAgents';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getSubAgentSettings: vi.fn(),
    getEnabledModels: vi.fn(),
    setSubAgentSettings: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsSubAgents', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getSubAgentSettings.mockResolvedValue({
      fast_model: 'gpt-5-mini',
      smart_model: 'claude-sonnet-4.5',
    });
    mockedApi.getEnabledModels.mockResolvedValue([
      'gpt-5-mini',
      'claude-sonnet-4.5',
      'gpt-5.2',
    ]);
    mockedApi.setSubAgentSettings.mockResolvedValue(undefined);
  });

  test('renders loaded settings and model options', async () => {
    render(<SettingsSubAgents />);

    expect(await screen.findByText('Sub-Agents')).toBeInTheDocument();
    expect(screen.getByDisplayValue('gpt-5-mini')).toBeInTheDocument();
    expect(screen.getByDisplayValue('claude-sonnet-4.5')).toBeInTheDocument();
  });

  test('updates fast tier model and persists', async () => {
    render(<SettingsSubAgents />);
    const selects = await screen.findAllByRole('combobox');

    fireEvent.change(selects[0], { target: { value: 'gpt-5.2' } });

    await waitFor(() => {
      expect(mockedApi.setSubAgentSettings).toHaveBeenCalledWith({
        fast_model: 'gpt-5.2',
        smart_model: 'claude-sonnet-4.5',
      });
      expect(screen.getByText('Settings saved')).toBeInTheDocument();
    });
  });

  test('falls back to idle status when save fails', async () => {
    mockedApi.setSubAgentSettings.mockRejectedValue(new Error('write failed'));

    render(<SettingsSubAgents />);
    const selects = await screen.findAllByRole('combobox');
    fireEvent.change(selects[1], { target: { value: 'gpt-5.2' } });

    await waitFor(() => {
      expect(mockedApi.setSubAgentSettings).toHaveBeenCalled();
    });
    expect(screen.queryByText('Settings saved')).not.toBeInTheDocument();
  });
});

