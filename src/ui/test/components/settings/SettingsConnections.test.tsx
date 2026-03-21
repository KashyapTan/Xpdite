import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsConnections from '../../../components/settings/SettingsConnections';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getGoogleStatus: vi.fn(),
    connectGoogle: vi.fn(),
    disconnectGoogle: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsConnections', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getGoogleStatus.mockResolvedValue({
      connected: false,
      email: null,
      auth_in_progress: false,
    });
    mockedApi.connectGoogle.mockResolvedValue({ success: true });
    mockedApi.disconnectGoogle.mockResolvedValue({ success: true });
  });

  test('loads Google status and renders connect view', async () => {
    render(<SettingsConnections />);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeInTheDocument();
    expect(screen.getByText('Gmail & Calendar access')).toBeInTheDocument();
  });

  test('connects successfully and refreshes status', async () => {
    mockedApi.getGoogleStatus
      .mockResolvedValueOnce({
        connected: false,
        email: null,
        auth_in_progress: false,
      })
      .mockResolvedValueOnce({
        connected: true,
        email: 'me@example.com',
        auth_in_progress: false,
      });
    mockedApi.connectGoogle.mockResolvedValue({ success: true, email: 'me@example.com' });

    render(<SettingsConnections />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));

    await waitFor(() => {
      expect(mockedApi.connectGoogle).toHaveBeenCalledTimes(1);
      expect(screen.getByText('Connected as me@example.com')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
    });
  });

  test('shows backend error when connect returns unsuccessful result', async () => {
    mockedApi.connectGoogle.mockResolvedValue({ success: false, error: 'OAuth denied' });

    render(<SettingsConnections />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));

    expect(await screen.findByText('OAuth denied')).toBeInTheDocument();
  });

  test('shows server error when connect throws', async () => {
    mockedApi.connectGoogle.mockRejectedValue(new Error('network'));

    render(<SettingsConnections />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));

    expect(await screen.findByText('Could not reach the server. Is it running?')).toBeInTheDocument();
  });

  test('disconnects successfully and returns to connect view', async () => {
    mockedApi.getGoogleStatus.mockResolvedValue({
      connected: true,
      email: 'person@example.com',
      auth_in_progress: false,
    });

    render(<SettingsConnections />);
    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }));

    await waitFor(() => {
      expect(mockedApi.disconnectGoogle).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'Connect' })).toBeInTheDocument();
      expect(screen.getByText('Gmail & Calendar access')).toBeInTheDocument();
    });
  });
});

