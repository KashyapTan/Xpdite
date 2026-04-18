// @vitest-environment node

import { afterAll, afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const consoleErrorMock = vi.spyOn(console, 'error').mockImplementation(() => {});
const consoleLogMock = vi.spyOn(console, 'log').mockImplementation(() => {});

const createBridgeServerMock = vi.fn();
const createCommandHandlerMock = vi.fn();
const createConfigLoaderMock = vi.fn();
const createPythonClientMock = vi.fn();
const splitDiscordOutboundContentMock = vi.fn((content: string) => [content]);

const canonicalizeWhatsAppThreadIdMock = vi.fn((threadId: string) => threadId);
const createWhatsAppOutboundTrackerMock = vi.fn(() => ({ remember: vi.fn() }));
const getInboundSenderIdMock = vi.fn(() => 'sender-1');
const getMessageTextMock = vi.fn((message: { content?: string }) => message.content ?? '');
const getMessageTimestampMsMock = vi.fn(() => Date.now());
const normalizeInboundTextMock = vi.fn((_platform: string, text: string) => text);
const getWhatsAppInboundGateResultMock = vi.fn(() => 'allow');
const isWhatsAppSelfAuthoredMessageMock = vi.fn(() => false);

const createMemoryStateMock = vi.fn(() => ({}));
const createTelegramSdkAdapterMock = vi.fn();

const serverStartMock = vi.fn();
const serverStopMock = vi.fn();
const loaderLoadMock = vi.fn();
const loaderStartWatchingMock = vi.fn();
const loaderStopWatchingMock = vi.fn();
const pythonClientSetBaseUrlMock = vi.fn();
const pythonClientPostMock = vi.fn();
const pythonClientSubmitMessageMock = vi.fn();
const commandHandleMock = vi.fn();
const commandIsCommandMock = vi.fn();
const processOnSpy = vi.spyOn(process, 'on');
const processExitSpy = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never);

let watchCallback: (() => Promise<void> | void) | null = null;
let signalHandlers: Record<string, (...args: unknown[]) => unknown> = {};
let latestChatInstance: FakeChat | null = null;

function setLatestChatInstance(instance: FakeChat): void {
  latestChatInstance = instance;
}

class FakeChat {
  initialize = vi.fn(async () => {});
  onNewMention = vi.fn((handler: (...args: unknown[]) => unknown) => {
    this.newMentionHandler = handler;
  });
  onSubscribedMessage = vi.fn((handler: (...args: unknown[]) => unknown) => {
    this.subscribedMessageHandler = handler;
  });
  onNewMessage = vi.fn((_pattern: RegExp, handler: (...args: unknown[]) => unknown) => {
    this.newMessageHandler = handler;
  });

  newMentionHandler?: (...args: unknown[]) => unknown;
  subscribedMessageHandler?: (...args: unknown[]) => unknown;
  newMessageHandler?: (...args: unknown[]) => unknown;

  constructor(public readonly options: unknown) {
    setLatestChatInstance(this);
  }
}

vi.mock('./server.js', () => ({
  createBridgeServer: createBridgeServerMock,
}));

vi.mock('./config/index.js', () => ({
  createConfigLoader: createConfigLoaderMock,
}));

vi.mock('./commands/index.js', () => ({
  createCommandHandler: createCommandHandlerMock,
}));

vi.mock('./pythonClient.js', () => ({
  createPythonClient: createPythonClientMock,
}));

vi.mock('./outboundUtils.js', () => ({
  splitDiscordOutboundContent: splitDiscordOutboundContentMock,
}));

vi.mock('./messageUtils.js', () => ({
  canonicalizeWhatsAppThreadId: canonicalizeWhatsAppThreadIdMock,
  createWhatsAppOutboundTracker: createWhatsAppOutboundTrackerMock,
  getInboundSenderId: getInboundSenderIdMock,
  getMessageText: getMessageTextMock,
  getMessageTimestampMs: getMessageTimestampMsMock,
  normalizeInboundText: normalizeInboundTextMock,
  getWhatsAppInboundGateResult: getWhatsAppInboundGateResultMock,
  isWhatsAppSelfAuthoredMessage: isWhatsAppSelfAuthoredMessageMock,
}));

vi.mock('chat', () => ({
  Chat: FakeChat,
}));

vi.mock('@chat-adapter/state-memory', () => ({
  createMemoryState: createMemoryStateMock,
}));

vi.mock('@chat-adapter/telegram', () => ({
  createTelegramAdapter: createTelegramSdkAdapterMock,
}));

async function flushPromises(iterations: number = 6): Promise<void> {
  for (let index = 0; index < iterations; index += 1) {
    await Promise.resolve();
  }
}

async function flushBridgeStartup(): Promise<void> {
  await flushPromises();
  await vi.advanceTimersByTimeAsync(600);
  await flushPromises();
}

describe('channel-bridge entrypoint', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.useFakeTimers();
    signalHandlers = {};
    watchCallback = null;
    latestChatInstance = null;

    processOnSpy.mockImplementation(((event: string, handler: (...args: unknown[]) => unknown) => {
      signalHandlers[event] = handler;
      return process;
    }) as typeof process.on);

    serverStartMock.mockResolvedValue(9123);
    serverStopMock.mockResolvedValue(undefined);
    createBridgeServerMock.mockReturnValue({
      start: serverStartMock,
      stop: serverStopMock,
    });

    loaderLoadMock.mockResolvedValue({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [],
    });
    loaderStartWatchingMock.mockImplementation((callback: () => Promise<void> | void) => {
      watchCallback = callback;
    });
    createConfigLoaderMock.mockReturnValue({
      load: loaderLoadMock,
      startWatching: loaderStartWatchingMock,
      stopWatching: loaderStopWatchingMock,
    });

    commandIsCommandMock.mockReturnValue(false);
    commandHandleMock.mockResolvedValue(null);
    createCommandHandlerMock.mockReturnValue({
      isCommand: commandIsCommandMock,
      handle: commandHandleMock,
    });

    pythonClientSetBaseUrlMock.mockReset();
    pythonClientPostMock.mockResolvedValue(undefined);
    pythonClientSubmitMessageMock.mockResolvedValue({
      success: true,
      queued: true,
      position: 2,
    });
    createPythonClientMock.mockReturnValue({
      setBaseUrl: pythonClientSetBaseUrlMock,
      post: pythonClientPostMock,
      submitMessage: pythonClientSubmitMessageMock,
    });

    createTelegramSdkAdapterMock.mockReturnValue({
      addReaction: vi.fn(async () => {}),
      editMessage: vi.fn(async () => {}),
      openDM: vi.fn(async () => 'telegram:resolved'),
      postMessage: vi.fn(async () => ({ id: 'telegram-sent-1' })),
      startTyping: vi.fn(async () => {}),
    });

    consoleLogMock.mockClear();
    consoleErrorMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('starts the bridge with an empty config, emits ready/status messages, reloads config changes, and shuts down cleanly', async () => {
    await import('./index.js');
    await flushBridgeStartup();

    expect(serverStartMock).toHaveBeenCalledWith(9000);
    expect(pythonClientSetBaseUrlMock).toHaveBeenCalledWith('http://127.0.0.1:8123');
    expect(loaderStartWatchingMock).toHaveBeenCalledTimes(1);
    expect(consoleLogMock).toHaveBeenCalledWith(expect.stringContaining('CHANNEL_BRIDGE_MSG {"type":"ready","port":9123}'));
    expect(consoleLogMock).toHaveBeenCalledWith(expect.stringContaining('"type":"status"'));

    loaderLoadMock.mockResolvedValueOnce({
      pythonServerUrl: 'http://127.0.0.1:9001',
      platforms: [],
    });
    const reloadPromise = watchCallback?.();
    await vi.advanceTimersByTimeAsync(600);
    await reloadPromise;
    await flushPromises();
    expect(loaderLoadMock).toHaveBeenCalledTimes(2);
    expect(pythonClientSetBaseUrlMock).toHaveBeenLastCalledWith('http://127.0.0.1:9001');

    await signalHandlers.SIGTERM?.();
    expect(loaderStopWatchingMock).toHaveBeenCalledTimes(1);
    expect(serverStopMock).toHaveBeenCalledTimes(1);
    expect(processExitSpy).toHaveBeenCalledWith(0);
  });

  test('initializes Telegram adapters and routes inbound messages into the Python queue flow', async () => {
    const telegramSdkAdapter = {
      addReaction: vi.fn(async () => {}),
      editMessage: vi.fn(async () => {}),
      openDM: vi.fn(async () => 'telegram:resolved'),
      postMessage: vi.fn(async () => ({ id: 'telegram-sent-1' })),
      startTyping: vi.fn(async () => {}),
    };
    createTelegramSdkAdapterMock.mockReturnValue(telegramSdkAdapter);
    loaderLoadMock.mockResolvedValue({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [
        {
          platform: 'telegram',
          enabled: true,
          credentials: {
            botToken: 'telegram-token',
            botUsername: 'xpdite_bot',
          },
        },
      ],
    });

    await import('./index.js');
    await flushBridgeStartup();

    expect(createTelegramSdkAdapterMock).toHaveBeenCalledWith({
      botToken: 'telegram-token',
      userName: 'xpdite_bot',
      mode: 'polling',
      longPolling: {
        timeout: 30,
        dropPendingUpdates: false,
      },
    });
    expect(createMemoryStateMock).toHaveBeenCalledTimes(1);
    expect(latestChatInstance?.initialize).toHaveBeenCalledTimes(1);

    await latestChatInstance?.newMessageHandler?.(
      { id: 'telegram:thread-1' },
      {
        id: 'msg-1',
        author: {
          isMe: false,
          userName: 'Alice',
        },
        content: 'Hello bridge',
      },
    );
    await flushPromises();

    expect(pythonClientSubmitMessageMock).toHaveBeenCalledWith(expect.objectContaining({
      platform: 'telegram',
      senderId: 'sender-1',
      senderName: 'Alice',
      message: 'Hello bridge',
      threadId: 'telegram:thread-1',
      isCommand: false,
    }));
    expect(telegramSdkAdapter.addReaction).toHaveBeenCalledWith('telegram:thread-1', 'msg-1', '👍');
    expect(telegramSdkAdapter.startTyping).toHaveBeenCalledWith('telegram:thread-1');
    expect(telegramSdkAdapter.postMessage).toHaveBeenCalledWith('telegram:thread-1', {
      markdown: 'Queued (position 2)',
    });
  });

  test('handles command mentions via the command handler and subscribes after processing', async () => {
    const telegramSdkAdapter = {
      addReaction: vi.fn(async () => {}),
      editMessage: vi.fn(async () => {}),
      openDM: vi.fn(async () => 'telegram:resolved'),
      postMessage: vi.fn(async () => ({ id: 'telegram-command-1' })),
      startTyping: vi.fn(async () => {}),
    };
    const subscribeMock = vi.fn(async () => {});

    createTelegramSdkAdapterMock.mockReturnValue(telegramSdkAdapter);
    loaderLoadMock.mockResolvedValue({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [
        {
          platform: 'telegram',
          enabled: true,
          credentials: {
            botToken: 'telegram-token',
            botUsername: 'xpdite_bot',
          },
        },
      ],
    });
    commandIsCommandMock.mockReturnValue(true);
    commandHandleMock.mockResolvedValue('Pairing complete.');

    await import('./index.js');
    await flushBridgeStartup();

    await latestChatInstance?.newMentionHandler?.(
      { id: 'telegram:thread-2', subscribe: subscribeMock },
      {
        id: 'msg-command-1',
        author: {
          isMe: false,
          userName: 'Alice',
        },
        content: '/pair 123456',
      },
    );
    await flushPromises();

    expect(commandHandleMock).toHaveBeenCalledWith('telegram', 'sender-1', 'Alice', '/pair 123456');
    expect(pythonClientSubmitMessageMock).not.toHaveBeenCalled();
    expect(telegramSdkAdapter.postMessage).toHaveBeenCalledWith('telegram:thread-2', {
      markdown: 'Pairing complete.',
    });
    expect(subscribeMock).toHaveBeenCalledTimes(1);
  });

  test('ignores self-authored telegram messages and suppresses duplicate unpaired responses', async () => {
    const telegramSdkAdapter = {
      addReaction: vi.fn(async () => {}),
      editMessage: vi.fn(async () => {}),
      openDM: vi.fn(async () => 'telegram:resolved'),
      postMessage: vi.fn(async () => ({ id: 'telegram-error-1' })),
      startTyping: vi.fn(async () => {}),
    };

    createTelegramSdkAdapterMock.mockReturnValue(telegramSdkAdapter);
    loaderLoadMock.mockResolvedValue({
      pythonServerUrl: 'http://127.0.0.1:8123',
      platforms: [
        {
          platform: 'telegram',
          enabled: true,
          credentials: {
            botToken: 'telegram-token',
            botUsername: 'xpdite_bot',
          },
        },
      ],
    });
    pythonClientSubmitMessageMock
      .mockResolvedValueOnce({
        success: false,
        error: 'You must pair first before sending messages.',
      })
      .mockResolvedValueOnce({
        success: false,
        error: 'You must pair first before sending messages.',
      });

    await import('./index.js');
    await flushBridgeStartup();

    await latestChatInstance?.newMessageHandler?.(
      { id: 'telegram:thread-3' },
      {
        id: 'msg-self-1',
        author: {
          isMe: true,
          userName: 'Xpdite',
        },
        content: 'self echo',
      },
    );
    await flushPromises();

    expect(commandHandleMock).not.toHaveBeenCalled();
    expect(pythonClientSubmitMessageMock).not.toHaveBeenCalled();

    await latestChatInstance?.newMessageHandler?.(
      { id: 'telegram:thread-3' },
      {
        id: 'msg-unpaired-1',
        author: {
          isMe: false,
          userName: 'Alice',
        },
        content: 'Need help',
      },
    );
    await latestChatInstance?.newMessageHandler?.(
      { id: 'telegram:thread-3' },
      {
        id: 'msg-unpaired-2',
        author: {
          isMe: false,
          userName: 'Alice',
        },
        content: 'Need help again',
      },
    );
    await flushPromises();

    expect(pythonClientSubmitMessageMock).toHaveBeenCalledTimes(2);
    expect(telegramSdkAdapter.postMessage).toHaveBeenCalledTimes(1);
    expect(telegramSdkAdapter.postMessage).toHaveBeenCalledWith('telegram:thread-3', {
      markdown: 'You must pair first before sending messages.',
    });
  });
});

afterAll(() => {
  processOnSpy.mockRestore();
  processExitSpy.mockRestore();
  consoleErrorMock.mockRestore();
  consoleLogMock.mockRestore();
});
