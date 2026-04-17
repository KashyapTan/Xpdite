import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import SettingsMobileChannels from '../../../components/settings/SettingsMobileChannels';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getMobilePairedDevices: vi.fn(),
    generateMobilePairingCode: vi.fn(),
    revokeMobilePairedDevice: vi.fn(),
    getMobileChannelsConfig: vi.fn(),
    setMobilePlatformConfig: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);
const DISCORD_PUBLIC_KEY =
  '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';

function makeConfig(overrides?: Record<string, Record<string, unknown>>) {
  return {
    platforms: {
      telegram: {
        enabled: false,
        status: 'disconnected' as const,
      },
      discord: {
        enabled: false,
        status: 'disconnected' as const,
      },
      whatsapp: {
        enabled: false,
        status: 'disconnected' as const,
      },
      ...overrides,
    },
  };
}

describe('SettingsMobileChannels', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getMobilePairedDevices.mockResolvedValue({ devices: [] });
    mockedApi.getMobileChannelsConfig.mockResolvedValue(makeConfig());
    mockedApi.setMobilePlatformConfig.mockResolvedValue(undefined);
    mockedApi.generateMobilePairingCode.mockResolvedValue({
      code: 'PAIRME',
      expires_in_seconds: 60,
    });
    mockedApi.revokeMobilePairedDevice.mockResolvedValue(undefined);

    window.electronAPI = {
      getChannelBridgeStatus: vi.fn().mockResolvedValue({ platforms: [] }),
      onWhatsAppPairingCode: vi.fn(() => vi.fn()),
      onChannelBridgeStatus: vi.fn(() => vi.fn()),
    } as unknown as Window['electronAPI'];
  });

  test('collects Discord application ID and public key before saving', async () => {
    render(<SettingsMobileChannels />);

    const discordCard = (await screen.findByText('Discord')).closest('.platform-card');
    expect(discordCard).not.toBeNull();

    fireEvent.click(within(discordCard as HTMLElement).getByRole('button', { name: 'Set up' }));

    const saveButton = screen.getByRole('button', { name: 'Save & Connect' });
    expect(saveButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Discord application ID'), {
      target: { value: '123456789012345678' },
    });
    fireEvent.change(screen.getByLabelText('Discord public key'), {
      target: { value: DISCORD_PUBLIC_KEY },
    });

    expect(saveButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Discord bot token'), {
      target: { value: 'discord-bot-token' },
    });
    expect(saveButton).toBeEnabled();

    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockedApi.setMobilePlatformConfig).toHaveBeenCalledWith('discord', {
        enabled: true,
        token: 'discord-bot-token',
        publicKey: DISCORD_PUBLIC_KEY,
        applicationId: '123456789012345678',
      });
    });
  });

  test('reuses the saved Discord token when reconnecting', async () => {
    mockedApi.getMobileChannelsConfig.mockResolvedValue(
      makeConfig({
        discord: {
          enabled: false,
          token: '***',
          publicKey: DISCORD_PUBLIC_KEY,
          applicationId: '123456789012345678',
          status: 'disconnected',
        },
      }),
    );

    render(<SettingsMobileChannels />);

    const discordCard = (await screen.findByText('Discord')).closest('.platform-card');
    expect(discordCard).not.toBeNull();

    fireEvent.click(
      within(discordCard as HTMLElement).getByRole('button', { name: 'Reconnect' }),
    );

    expect(screen.getByText('Leave this blank to keep the saved token.')).toBeInTheDocument();
    expect(screen.getByLabelText('Discord application ID')).toHaveValue(
      '123456789012345678',
    );
    expect(screen.getByLabelText('Discord public key')).toHaveValue(DISCORD_PUBLIC_KEY);
    expect(screen.getByLabelText('Discord bot token')).toHaveValue('');

    fireEvent.click(screen.getByRole('button', { name: 'Save & Connect' }));

    await waitFor(() => {
      expect(mockedApi.setMobilePlatformConfig).toHaveBeenCalledWith('discord', {
        enabled: true,
        publicKey: DISCORD_PUBLIC_KEY,
        applicationId: '123456789012345678',
      });
    });
  });
});
