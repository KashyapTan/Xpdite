import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsGeneral from '../../../components/settings/SettingsGeneral';
import type { ElectronContentProtectionStatus } from '../../../types';

const getContentProtectionMock = vi.fn<() => Promise<ElectronContentProtectionStatus>>();
const setContentProtectionMock = vi.fn<(enabled: boolean) => Promise<ElectronContentProtectionStatus>>();

function installElectronApi() {
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    writable: true,
    value: {
      focusWindow: vi.fn(),
      setMiniMode: vi.fn(),
      getContentProtection: getContentProtectionMock,
      setContentProtection: setContentProtectionMock,
      getServerPort: vi.fn(),
      getBootState: vi.fn(),
      onBootState: vi.fn(() => () => {}),
      retryBoot: vi.fn(),
      getChannelBridgePort: vi.fn(),
      getChannelBridgeStatus: vi.fn(),
      onChannelBridgeStatus: vi.fn(() => () => {}),
      onWhatsAppPairingCode: vi.fn(() => () => {}),
    } satisfies Window['electronAPI'],
  });
}

describe('SettingsGeneral', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getContentProtectionMock.mockResolvedValue({
      enabled: false,
      active: false,
      supported: true,
    });
    setContentProtectionMock.mockResolvedValue({
      enabled: true,
      active: true,
      supported: true,
    });
    installElectronApi();
  });

  test('loads the current content protection state', async () => {
    render(<SettingsGeneral />);

    const toggle = await screen.findByLabelText('Invisible Mode') as HTMLInputElement;

    expect(getContentProtectionMock).toHaveBeenCalledTimes(1);
    expect(toggle.checked).toBe(false);
  });

  test('enables invisible mode through the Electron bridge', async () => {
    render(<SettingsGeneral />);

    const toggle = await screen.findByLabelText('Invisible Mode') as HTMLInputElement;
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(setContentProtectionMock).toHaveBeenCalledWith(true);
    });
    expect(toggle.checked).toBe(true);
  });

  test('shows an unavailable state without the Electron bridge', async () => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      writable: true,
      value: undefined,
    });

    render(<SettingsGeneral />);

    expect(await screen.findByText('Content protection is only available in the desktop app.')).toBeInTheDocument();
    expect(screen.getByLabelText('Invisible Mode')).toBeDisabled();
  });
});
