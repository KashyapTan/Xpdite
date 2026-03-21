import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsConnections from '../../../components/settings/SettingsConnections';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getGoogleStatus: vi.fn(),
    connectGoogle: vi.fn(),
    disconnectGoogle: vi.fn(),
    getExternalConnectors: vi.fn(),
    connectExternalConnector: vi.fn(),
    disconnectExternalConnector: vi.fn(),
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
    mockedApi.getExternalConnectors.mockResolvedValue([]);
    mockedApi.connectExternalConnector.mockResolvedValue({ success: true });
    mockedApi.disconnectExternalConnector.mockResolvedValue({ success: true });
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

describe('SettingsConnections - External Connectors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getGoogleStatus.mockResolvedValue({
      connected: false,
      email: null,
      auth_in_progress: false,
    });
    mockedApi.connectGoogle.mockResolvedValue({ success: true });
    mockedApi.disconnectGoogle.mockResolvedValue({ success: true });
    mockedApi.connectExternalConnector.mockResolvedValue({ success: true });
    mockedApi.disconnectExternalConnector.mockResolvedValue({ success: true });
  });

  test('renders external connectors from API', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: false,
        connected: false,
        last_error: null,
      },
    ]);

    render(<SettingsConnections />);

    expect(await screen.findByText('Everything (Demo)')).toBeInTheDocument();
    expect(screen.getByText('Demo server with sample tools for testing')).toBeInTheDocument();
    expect(screen.getByText('Demo')).toBeInTheDocument();
  });

  test('shows connected state for external connector', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: true,
        connected: true,
        last_error: null,
      },
    ]);

    render(<SettingsConnections />);

    expect(await screen.findByText('Everything (Demo)')).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
    // Should show Disconnect button for the external connector
    const disconnectButtons = await screen.findAllByRole('button', { name: 'Disconnect' });
    expect(disconnectButtons.length).toBeGreaterThan(0);
  });

  test('shows error state for external connector', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: true,
        connected: false,
        last_error: 'Connection timeout',
      },
    ]);

    render(<SettingsConnections />);

    expect(await screen.findByText('Everything (Demo)')).toBeInTheDocument();
    expect(screen.getByText('Error: Connection timeout')).toBeInTheDocument();
  });

  test('connects external connector successfully', async () => {
    mockedApi.getExternalConnectors
      .mockResolvedValueOnce([
        {
          name: 'everything',
          display_name: 'Everything (Demo)',
          description: 'Demo server with sample tools for testing',
          services: ['Demo'],
          icon_type: 'everything',
          auth_type: null,
          enabled: false,
          connected: false,
          last_error: null,
        },
      ])
      .mockResolvedValueOnce([
        {
          name: 'everything',
          display_name: 'Everything (Demo)',
          description: 'Demo server with sample tools for testing',
          services: ['Demo'],
          icon_type: 'everything',
          auth_type: null,
          enabled: true,
          connected: true,
          last_error: null,
        },
      ]);

    render(<SettingsConnections />);

    // Wait for Everything card to appear, then find its Connect button
    await screen.findByText('Everything (Demo)');
    const connectButtons = screen.getAllByRole('button', { name: 'Connect' });
    // Click the last Connect button (Everything, since Google is rendered first if not connected)
    fireEvent.click(connectButtons[connectButtons.length - 1]);

    await waitFor(() => {
      expect(mockedApi.connectExternalConnector).toHaveBeenCalledWith('everything');
    });
  });

  test('shows error when external connector connect fails', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: false,
        connected: false,
        last_error: null,
      },
    ]);
    mockedApi.connectExternalConnector.mockResolvedValue({
      success: false,
      error: 'Connection failed',
    });

    render(<SettingsConnections />);

    // Wait for Everything card to appear, then find its Connect button
    await screen.findByText('Everything (Demo)');
    const connectButtons = screen.getAllByRole('button', { name: 'Connect' });
    fireEvent.click(connectButtons[connectButtons.length - 1]); // Click Everything connect

    expect(await screen.findByText('Connection failed')).toBeInTheDocument();
  });

  test('disconnects external connector successfully', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: true,
        connected: true,
        last_error: null,
      },
    ]);

    render(<SettingsConnections />);

    // Find Disconnect buttons (one for Google if connected, one for Everything)
    const disconnectButtons = await screen.findAllByRole('button', { name: 'Disconnect' });
    // Click the Everything disconnect button
    fireEvent.click(disconnectButtons[disconnectButtons.length - 1]);

    await waitFor(() => {
      expect(mockedApi.disconnectExternalConnector).toHaveBeenCalledWith('everything');
    });
  });

  test('renders multiple external connectors', async () => {
    mockedApi.getExternalConnectors.mockResolvedValue([
      {
        name: 'everything',
        display_name: 'Everything (Demo)',
        description: 'Demo server with sample tools for testing',
        services: ['Demo'],
        icon_type: 'everything',
        auth_type: null,
        enabled: false,
        connected: false,
        last_error: null,
      },
      {
        name: 'github',
        display_name: 'GitHub',
        description: 'Repositories and issues',
        services: ['Code'],
        icon_type: 'github',
        auth_type: 'browser',
        enabled: false,
        connected: false,
        last_error: null,
      },
    ]);

    render(<SettingsConnections />);

    expect(await screen.findByText('Everything (Demo)')).toBeInTheDocument();
    // Use getAllByText for GitHub since it appears in both title and service badge
    const githubElements = await screen.findAllByText('GitHub');
    expect(githubElements.length).toBeGreaterThan(0);
    expect(screen.getByText('Demo server with sample tools for testing')).toBeInTheDocument();
    expect(screen.getByText('Repositories and issues')).toBeInTheDocument();
  });
});
