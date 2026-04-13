import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsTools from '../../../components/settings/SettingsTools';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getMcpServers: vi.fn(),
    getToolsSettings: vi.fn(),
    setToolsSettings: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsTools', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getMcpServers.mockResolvedValue([
      {
        server: 'filesystem',
        display_name: 'filesystem',
        tools: [{ id: 'read_file', name: 'read_file' }, { id: 'write_file', name: 'write_file' }],
      },
      {
        server: 'terminal',
        display_name: 'terminal',
        tools: [{ id: 'run_command', name: 'run_command' }],
      },
    ]);
    mockedApi.getToolsSettings.mockResolvedValue({
      always_on: ['read_file'],
      top_k: 3,
    });
    mockedApi.setToolsSettings.mockResolvedValue(undefined);
  });

  test('loads and renders server cards with tool counts', async () => {
    render(<SettingsTools />);

    expect(await screen.findByText('filesystem')).toBeInTheDocument();
    expect(screen.getByText('2 tools')).toBeInTheDocument();
    expect(screen.getByText('terminal')).toBeInTheDocument();
  });

  test('updates top-k slider and persists settings', async () => {
    render(<SettingsTools />);

    const slider = await screen.findByRole('slider');
    fireEvent.change(slider, { target: { value: '7' } });

    await waitFor(() => {
      expect(mockedApi.setToolsSettings).toHaveBeenCalledWith(['read_file'], 7);
      expect(screen.getByText('7')).toBeInTheDocument();
    });
  });

  test('expands server and toggles individual tool', async () => {
    render(<SettingsTools />);

    const filesystemHeader = await screen.findByText('filesystem');
    fireEvent.click(filesystemHeader);
    fireEvent.click(await screen.findByText('write_file'));

    await waitFor(() => {
      expect(mockedApi.setToolsSettings).toHaveBeenCalledWith(
        ['read_file', 'write_file'],
        3,
      );
    });
  });

  test('toggles all tools for a server using group toggle', async () => {
    render(<SettingsTools />);

    const toggles = await screen.findAllByTitle('Toggle all tools for this server');
    fireEvent.click(toggles[0]);

    await waitFor(() => {
      expect(mockedApi.setToolsSettings).toHaveBeenCalledWith(
        ['read_file', 'write_file'],
        3,
      );
    });
  });

  test('renders loading fallback while initial fetch resolves', async () => {
    let resolveServers: (value: {
      server: string;
      display_name: string;
      tools: { id: string; name: string }[];
    }[]) => void = () => {};
    mockedApi.getMcpServers.mockReturnValue(
      new Promise((resolve) => {
        resolveServers = resolve;
      }),
    );

    render(<SettingsTools />);
    expect(screen.getByText('Loading tools...')).toBeInTheDocument();

    resolveServers([{ server: 'filesystem', display_name: 'filesystem', tools: [{ id: 'read_file', name: 'read_file' }] }]);

    expect(await screen.findByText('filesystem')).toBeInTheDocument();
  });
});

