import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SettingsGeneral from '../../../components/settings/SettingsGeneral';
import type { ElectronContentProtectionStatus } from '../../../types';

// ── WebSocket mock (Auto Mode settings travel over the socket) ──────
type WsHandler = (data: Record<string, unknown>) => void;
const wsHandlers = new Set<WsHandler>();
const emitWs = (data: Record<string, unknown>) => {
  act(() => {
    for (const handler of [...wsHandlers]) {
      handler(data);
    }
  });
};
const sendMock = vi.fn();

vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: (handler: WsHandler) => {
      wsHandlers.add(handler);
      return () => wsHandlers.delete(handler);
    },
    isConnected: true,
  }),
}));

vi.mock('../../../services/api', () => ({
  api: {
    getEnabledModels: vi.fn().mockResolvedValue(['model-a', 'model-b']),
  },
}));

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

const AUTO_DEFAULTS = {
  enabled: false,
  prompt: '',
  pinned_model: '',
  keep_context: false,
  flash: false,
  allow_cloud: false,
  supported: true,
  unsupported_reason: '',
};

describe('SettingsGeneral', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsHandlers.clear();
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

  // ── Invisible Mode (existing behavior) ─────────────────────────
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

  // ── Auto Mode (new) ────────────────────────────────────────────
  test('requests Auto Mode settings on mount and shows the toggle', async () => {
    render(<SettingsGeneral />);

    await waitFor(() => {
      expect(sendMock).toHaveBeenCalledWith({ type: 'auto_mode_get_settings' });
    });
    expect(screen.getByLabelText('Auto Mode')).toBeInTheDocument();
  });

  test('config fields are hidden until Auto Mode is enabled', () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: AUTO_DEFAULTS });

    expect(screen.queryByLabelText('Keep context')).not.toBeInTheDocument();
  });

  test('enabling Auto Mode persists the flag and reveals config fields', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: AUTO_DEFAULTS });

    await userEvent.click(screen.getByLabelText('Auto Mode'));

    expect(sendMock).toHaveBeenCalledWith({
      type: 'auto_mode_update_settings',
      settings: { enabled: true },
    });
    expect(screen.getByLabelText('Keep context')).toBeInTheDocument();
    expect(screen.getByText(/vision-capable/i)).toBeInTheDocument();
  });

  test('editing the prompt saves on blur', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true } });

    const textarea = screen.getByLabelText(/Prompt sent with every capture/i);
    await userEvent.clear(textarea);
    await userEvent.type(textarea, 'Read my screen');
    act(() => {
      textarea.blur();
    });

    expect(sendMock).toHaveBeenCalledWith({
      type: 'auto_mode_update_settings',
      settings: { prompt: 'Read my screen' },
    });
  });

  test('pinned-model dropdown lists enabled models and saves selection', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true } });

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'model-a' })).toBeInTheDocument();
    });

    await userEvent.selectOptions(screen.getByLabelText('Model'), 'model-b');
    expect(sendMock).toHaveBeenCalledWith({
      type: 'auto_mode_update_settings',
      settings: { pinned_model: 'model-b' },
    });
  });

  test('a settings echo does not clobber an in-progress prompt edit', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true, prompt: 'saved' } });

    const textarea = screen.getByLabelText(/Prompt sent with every capture/i) as HTMLTextAreaElement;
    await userEvent.clear(textarea);
    await userEvent.type(textarea, 'in progress'); // focuses the textarea

    // A reconnect re-fetch echo lands while the user is still typing.
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true, prompt: 'server value' } });

    expect(textarea.value).toBe('in progress');
  });

  test('a pinned model no longer in the enabled list is still shown as an option', async () => {
    render(<SettingsGeneral />);
    emitWs({
      type: 'auto_mode_settings',
      content: { ...AUTO_DEFAULTS, enabled: true, pinned_model: 'removed-model' },
    });

    await waitFor(() => {
      expect(
        screen.getByRole('option', { name: /removed-model \(unavailable\)/i }),
      ).toBeInTheDocument();
    });
  });

  test('keep-context toggle persists', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true } });

    await userEvent.click(screen.getByLabelText('Keep context'));
    expect(sendMock).toHaveBeenCalledWith({
      type: 'auto_mode_update_settings',
      settings: { keep_context: true },
    });
  });

  test('cloud screenshots require an explicit opt-in', async () => {
    render(<SettingsGeneral />);
    emitWs({ type: 'auto_mode_settings', content: { ...AUTO_DEFAULTS, enabled: true } });

    await userEvent.click(screen.getByLabelText('Allow cloud screenshots'));
    expect(sendMock).toHaveBeenCalledWith({
      type: 'auto_mode_update_settings',
      settings: { allow_cloud: true },
    });
  });

  test('disables Auto Mode when the platform cannot show it safely', () => {
    render(<SettingsGeneral />);
    emitWs({
      type: 'auto_mode_settings',
      content: {
        ...AUTO_DEFAULTS,
        supported: false,
        unsupported_reason: 'Unavailable on Wayland.',
      },
    });

    expect(screen.getByLabelText('Auto Mode')).toBeDisabled();
    expect(screen.getByText('Unavailable on Wayland.')).toBeInTheDocument();
  });
});
