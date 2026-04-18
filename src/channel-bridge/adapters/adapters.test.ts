// @vitest-environment node

import { beforeEach, describe, expect, test, vi } from 'vitest';

import { createDiscordAdapter, createTelegramAdapter, createWhatsAppAdapter } from './index.js';

const {
  createTelegramAdapterMock,
  createDiscordAdapterMock,
  createBaileysAdapterMock,
  useMultiFileAuthStateMock,
} = vi.hoisted(() => ({
  createTelegramAdapterMock: vi.fn(),
  createDiscordAdapterMock: vi.fn(),
  createBaileysAdapterMock: vi.fn(),
  useMultiFileAuthStateMock: vi.fn(),
}));

vi.mock('@chat-adapter/telegram', () => ({
  createTelegramAdapter: createTelegramAdapterMock,
}));

vi.mock('@chat-adapter/discord', () => ({
  createDiscordAdapter: createDiscordAdapterMock,
}));

vi.mock('chat-adapter-baileys', () => ({
  createBaileysAdapter: createBaileysAdapterMock,
}));

vi.mock('baileys', () => ({
  useMultiFileAuthState: useMultiFileAuthStateMock,
}));

describe('channel bridge adapter wrappers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('creates, connects, and disconnects the Telegram adapter wrapper', async () => {
    const stopPolling = vi.fn(async () => {});
    const chatSdkAdapter = { stopPolling };
    createTelegramAdapterMock.mockReturnValue(chatSdkAdapter);

    const adapter = createTelegramAdapter();
    await adapter.connect({ botToken: 'telegram-token', botUsername: 'xpdite' });

    expect(createTelegramAdapterMock).toHaveBeenCalledWith({
      botToken: 'telegram-token',
      userName: 'xpdite',
      mode: 'polling',
      longPolling: {
        timeout: 30,
        dropPendingUpdates: false,
      },
    });
    expect(adapter.getChatSDKAdapter()).toBe(chatSdkAdapter);
    expect(adapter.getStatus()).toMatchObject({ platform: 'telegram', status: 'connected' });

    await adapter.disconnect();
    expect(stopPolling).toHaveBeenCalledTimes(1);
    expect(adapter.getChatSDKAdapter()).toBeNull();
    expect(adapter.getStatus()).toMatchObject({ platform: 'telegram', status: 'disconnected' });
  });

  test('maps common Discord auth failures to friendlier status errors', async () => {
    createDiscordAdapterMock.mockImplementation(() => {
      throw new Error('401 Unauthorized');
    });

    const adapter = createDiscordAdapter();
    await expect(
      adapter.connect({
        botToken: 'discord-token',
        publicKey: 'public-key',
        applicationId: 'app-id',
      }),
    ).rejects.toThrow('401 Unauthorized');
    expect(adapter.getStatus()).toMatchObject({
      platform: 'discord',
      status: 'error',
      error: 'Invalid bot token',
    });
  });

  test('creates the WhatsApp adapter, emits pairing codes, and disconnects cleanly', async () => {
    let pairingCodeHandler: ((code: string) => void) | undefined;
    const disconnect = vi.fn(async () => {});
    const connect = vi.fn(async () => {
      pairingCodeHandler?.('123-456');
    });
    createBaileysAdapterMock.mockImplementation((options: { onPairingCode?: (code: string) => void }) => {
      pairingCodeHandler = options.onPairingCode;
      return {
        connect,
        disconnect,
      };
    });
    useMultiFileAuthStateMock.mockResolvedValue({
      state: { creds: {} },
      saveCreds: vi.fn(),
    });

    const emitMessage = vi.fn();
    const adapter = createWhatsAppAdapter();
    await adapter.connect(
      {
        authMethod: 'pairing_code',
        phoneNumber: '+1 (555) 123-4567',
      },
      'C:/Users/test/AppData/Roaming/Xpdite',
      emitMessage,
    );

    expect(useMultiFileAuthStateMock).toHaveBeenCalledWith(expect.stringContaining('whatsapp_auth'));
    expect(createBaileysAdapterMock).toHaveBeenCalledWith(expect.objectContaining({
      userName: 'xpdite-bot',
      phoneNumber: '15551234567',
      onPairingCode: expect.any(Function),
    }));
    expect(emitMessage).toHaveBeenCalledWith({ type: 'whatsapp_pairing_code', code: '123-456' });
    expect(adapter.getStatus()).toMatchObject({ platform: 'whatsapp', status: 'connected' });

    await adapter.disconnect();
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(adapter.getStatus()).toMatchObject({ platform: 'whatsapp', status: 'disconnected' });
  });
});
