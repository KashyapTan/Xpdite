import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import type React from 'react';

import App from '../../pages/App';
import { api } from '../../services/api';

type WebSocketEvent = {
  type: string;
  tab_id?: string;
  content?: unknown;
};

type ResponseAreaProps = {
  onRetryMessage: (message: {
    role: 'assistant' | 'user';
    content: string;
    messageId?: string;
    turnId?: string;
  }) => void;
  onYouTubeApprovalResponse: (requestId: string, approved: boolean) => void;
};

const navigateMock = vi.fn();
const wsSendMock = vi.fn();
const wsSubscribeMock = vi.fn();
const setIsHiddenMock = vi.fn();

const updateTabTitleMock = vi.fn();
const setQueueItemsMock = vi.fn();
const setTabSnapshotMock = vi.fn();
const deleteTabSnapshotMock = vi.fn();
const registerBeforeSwitchMock = vi.fn(() => () => {});
const registerAfterSwitchMock = vi.fn(() => () => {});
const registerOnTabClosedMock = vi.fn(() => () => {});

let wsSubscriber: ((event: WebSocketEvent) => void) | null = null;
let latestResponseAreaProps: ResponseAreaProps | null = null;

const tabContextState = {
  tabs: [
    { id: 'tab-1', title: 'Tab 1' },
    { id: 'tab-2', title: 'Tab 2' },
  ],
  activeTabId: 'tab-1',
};

const tabSnapshots = new Map<string, unknown>();

const getTabSnapshotMock = vi.fn((tabId: string) => tabSnapshots.get(tabId) ?? null);

setTabSnapshotMock.mockImplementation((tabId: string, snapshot: unknown) => {
  tabSnapshots.set(tabId, snapshot);
});

const chatStateMock = {
  chatHistory: [] as unknown[],
  currentQuery: '',
  thinking: '',
  isThinking: false,
  thinkingCollapsed: true,
  contentBlocks: [] as unknown[],
  canSubmit: true,
  error: '',
  query: 'hello from test',
  responseRef: { current: '' },
  thinkingRef: { current: '' },
  toolCallsRef: { current: [] as unknown[] },
  contentBlocksRef: { current: [] as unknown[] },
  currentQueryRef: { current: '' },
  getSnapshot: vi.fn(() => ({
    chatHistory: [],
    currentQuery: '',
    response: '',
    thinking: '',
    isThinking: false,
    thinkingCollapsed: true,
    toolCalls: [],
    contentBlocks: [],
    conversationId: null,
    query: '',
    canSubmit: true,
    status: '',
    error: '',
  })),
  restoreSnapshot: vi.fn(),
  setStatus: vi.fn(),
  setCanSubmit: vi.fn(),
  setError: vi.fn(),
  setQuery: vi.fn(),
  startQuery: vi.fn(),
  setChatHistory: vi.fn(),
  setThinkingCollapsed: vi.fn(),
  resetForNewChat: vi.fn(),
  appendThinking: vi.fn(),
  setIsThinking: vi.fn(),
  appendResponse: vi.fn(),
  completeResponse: vi.fn(),
  loadConversation: vi.fn(),
  clearStreamingState: vi.fn(),
  setConversationId: vi.fn(),
  addTerminalBlock: vi.fn(),
  updateTerminalBlock: vi.fn(),
  appendTerminalOutput: vi.fn(),
  addYouTubeApprovalBlock: vi.fn(),
  updateYouTubeApprovalBlock: vi.fn(),
  addToolCall: vi.fn(),
  updateToolCall: vi.fn(),
};

const screenshotStateMock = {
  captureMode: 'precision' as const,
  meetingRecordingMode: false,
  screenshots: [] as unknown[],
  getSnapshot: vi.fn(() => ({ screenshots: [], captureMode: 'precision', meetingRecordingMode: false })),
  restoreSnapshot: vi.fn(),
  clearScreenshots: vi.fn(),
  setMeetingRecordingMode: vi.fn(),
  setCaptureMode: vi.fn(),
  addScreenshot: vi.fn(),
  removeScreenshot: vi.fn(),
  getImageData: vi.fn(() => []),
};

const tokenStateMock = {
  tokenUsage: { total: 0, input: 0, output: 0, limit: 128000 },
  showTokenPopup: false,
  getSnapshot: vi.fn(() => ({ tokenUsage: { total: 0, input: 0, output: 0, limit: 128000 } })),
  restoreSnapshot: vi.fn(),
  resetTokens: vi.fn(),
  setTokenUsage: vi.fn(),
  addTokens: vi.fn(),
  setShowTokenPopup: vi.fn(),
};

const emitWebSocketEvent = (event: WebSocketEvent) => {
  expect(wsSubscriber).not.toBeNull();
  act(() => {
    wsSubscriber?.(event);
  });
};

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useLocation: () => ({ pathname: '/', state: null }),
    useNavigate: () => navigateMock,
    useOutletContext: () => ({ setMini: vi.fn(), setIsHidden: setIsHiddenMock, isHidden: false }),
  };
});

vi.mock('../../hooks/useChatState', () => ({ useChatState: () => chatStateMock }));
vi.mock('../../hooks/useScreenshots', () => ({ useScreenshots: () => screenshotStateMock }));
vi.mock('../../hooks/useTokenUsage', () => ({ useTokenUsage: () => tokenStateMock }));

vi.mock('../../contexts/TabContext', () => ({
  useTabs: () => ({
    tabs: tabContextState.tabs,
    activeTabId: tabContextState.activeTabId,
    updateTabTitle: updateTabTitleMock,
    queueMap: {},
    setQueueItems: setQueueItemsMock,
    getTabSnapshot: getTabSnapshotMock,
    setTabSnapshot: setTabSnapshotMock,
    deleteTabSnapshot: deleteTabSnapshotMock,
    registerBeforeSwitch: registerBeforeSwitchMock,
    registerAfterSwitch: registerAfterSwitchMock,
    registerOnTabClosed: registerOnTabClosedMock,
  }),
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: wsSendMock,
    subscribe: wsSubscribeMock,
    isConnected: true,
  }),
}));

vi.mock('../../services/api', () => ({
  api: {
    getEnabledModels: vi.fn().mockResolvedValue(['openai/gpt-4o']),
  },
}));

vi.mock('../../components/TitleBar', () => ({ default: () => <div>title-bar</div> }));
vi.mock('../../components/TabBar', () => ({ default: () => <div>tab-bar</div> }));
vi.mock('../../components/input/QueueDropdown', () => ({ QueueDropdown: () => <div>queue-dropdown</div> }));
vi.mock('../../components/input/TokenUsagePopup', () => ({ TokenUsagePopup: () => <div>token-popup</div> }));
vi.mock('../../components/input/ScreenshotChips', () => ({ ScreenshotChips: () => <div>screenshot-chips</div> }));

vi.mock('../../components/chat/ResponseArea.tsx', () => ({
  ResponseArea: (props: ResponseAreaProps) => {
    latestResponseAreaProps = props;
    return (
      <div>
        response-area
        <button
          type="button"
          onClick={() => props.onRetryMessage({ role: 'assistant', content: 'old response', messageId: 'assistant-msg-1', turnId: 'turn-1' })}
        >
          retry-message
        </button>
        <button type="button" onClick={() => props.onYouTubeApprovalResponse('yt-req-1', true)}>
          youtube-approve
        </button>
      </div>
    );
  },
}));

vi.mock('../../components/input/QueryInput', () => ({
  QueryInput: ({ onSubmit, onStopStreaming }: { onSubmit: (e: React.FormEvent) => void; onStopStreaming: () => void }) => (
    <div>
      <button type="button" onClick={() => onSubmit({ preventDefault: () => {} } as React.FormEvent)}>
        submit-query
      </button>
      <button type="button" onClick={onStopStreaming}>stop-streaming</button>
    </div>
  ),
}));

vi.mock('../../components/input/ModeSelector', () => ({
  ModeSelector: ({ onFullscreenMode, onPrecisionMode, onMeetingMode }: {
    onFullscreenMode: () => void;
    onPrecisionMode: () => void;
    onMeetingMode: () => void;
  }) => (
    <div>
      <button type="button" onClick={onFullscreenMode}>mode-fullscreen</button>
      <button type="button" onClick={onPrecisionMode}>mode-precision</button>
      <button type="button" onClick={onMeetingMode}>mode-meeting</button>
    </div>
  ),
}));

describe('App websocket-driven behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    latestResponseAreaProps = null;
    wsSubscriber = null;
    wsSubscribeMock.mockImplementation((handler: (event: WebSocketEvent) => void) => {
      wsSubscriber = handler;
      return () => {
        if (wsSubscriber === handler) {
          wsSubscriber = null;
        }
      };
    });

    tabContextState.tabs = [
      { id: 'tab-1', title: 'Tab 1' },
      { id: 'tab-2', title: 'Tab 2' },
    ];
    tabContextState.activeTabId = 'tab-1';
    tabSnapshots.clear();
    chatStateMock.chatHistory = [];
    chatStateMock.query = 'hello from test';
    chatStateMock.canSubmit = true;
    chatStateMock.currentQueryRef.current = '';
    chatStateMock.contentBlocksRef.current = [];
    chatStateMock.responseRef.current = '';
    chatStateMock.thinkingRef.current = '';
    screenshotStateMock.captureMode = 'precision';
    screenshotStateMock.meetingRecordingMode = false;
  });

  test('renders core sections', async () => {
    render(<App />);

    expect(screen.getByText('title-bar')).toBeInTheDocument();
    expect(screen.getByText('tab-bar')).toBeInTheDocument();
    expect(await screen.findByText('response-area')).toBeInTheDocument();
  });

  test('submits query through websocket with active tab routing', async () => {
    render(<App />);

    await waitFor(() => {
      expect(api.getEnabledModels).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByText('submit-query'));

    await waitFor(() => {
      expect(wsSendMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'submit_query',
          content: 'hello from test',
          capture_mode: 'precision',
          model: 'openai/gpt-4o',
          tab_id: 'tab-1',
        }),
      );
    });
  });

  test('bootstraps tab state on ws_connected event', () => {
    render(<App />);
    wsSendMock.mockClear();

    emitWebSocketEvent({ type: '__ws_connected' });

    expect(chatStateMock.setStatus).toHaveBeenCalledWith('Connected to server');
    expect(chatStateMock.setError).toHaveBeenCalledWith('');
    expect(wsSendMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'tab_created', tab_id: 'tab-1' }));
    expect(wsSendMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'tab_created', tab_id: 'tab-2' }));
    expect(wsSendMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'tab_activated', tab_id: 'tab-1' }));
    expect(wsSendMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'set_capture_mode', mode: 'precision', tab_id: 'tab-1' }));
  });

  test('routes background-tab messages into snapshots, not active state handlers', () => {
    render(<App />);
    setTabSnapshotMock.mockClear();
    chatStateMock.startQuery.mockClear();
    screenshotStateMock.addScreenshot.mockClear();

    emitWebSocketEvent({ type: 'query', tab_id: 'tab-2', content: 'background question' });

    expect(chatStateMock.startQuery).not.toHaveBeenCalled();
    expect(setTabSnapshotMock).toHaveBeenCalledWith(
      'tab-2',
      expect.objectContaining({
        chat: expect.objectContaining({
          currentQuery: 'background question',
          status: 'Thinking...',
          isThinking: true,
        }),
      }),
    );

    setTabSnapshotMock.mockClear();

    emitWebSocketEvent({
      type: 'screenshot_added',
      tab_id: 'tab-2',
      content: { id: 'ss-1', image_data: 'abc123', timestamp: 1234 },
    });

    expect(screenshotStateMock.addScreenshot).not.toHaveBeenCalled();
    expect(setTabSnapshotMock).toHaveBeenCalledWith(
      'tab-2',
      expect.objectContaining({
        screenshots: expect.objectContaining({
          screenshots: expect.arrayContaining([expect.objectContaining({ id: 'ss-1' })]),
        }),
      }),
    );
  });

  test('keeps pending retry flow until conversation_saved then resumes conversation', async () => {
    render(<App />);

    await waitFor(() => {
      expect(api.getEnabledModels).toHaveBeenCalled();
    });
    expect(await screen.findByText('response-area')).toBeInTheDocument();

    fireEvent.click(screen.getByText('retry-message'));

    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'retry_message',
        message_id: 'assistant-msg-1',
        model: 'openai/gpt-4o',
        tab_id: 'tab-1',
      }),
    );

    chatStateMock.completeResponse.mockClear();
    chatStateMock.setStatus.mockClear();
    chatStateMock.setIsThinking.mockClear();
    wsSendMock.mockClear();

    emitWebSocketEvent({ type: 'response_complete', tab_id: 'tab-1' });

    expect(chatStateMock.completeResponse).not.toHaveBeenCalled();
    expect(chatStateMock.setIsThinking).toHaveBeenCalledWith(false);
    expect(chatStateMock.setStatus).toHaveBeenCalledWith('Saving updated turn...');

    emitWebSocketEvent({
      type: 'conversation_saved',
      tab_id: 'tab-1',
      content: { conversation_id: 'conv-123' },
    });

    await waitFor(() => {
      expect(chatStateMock.setConversationId).toHaveBeenCalledWith('conv-123');
      expect(chatStateMock.clearStreamingState).toHaveBeenCalledWith('Updated turn saved. Reloading conversation...');
      expect(wsSendMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'resume_conversation',
          conversation_id: 'conv-123',
          tab_id: 'tab-1',
        }),
      );
    });
  });

  test('links first terminal output to pending run_command metadata', () => {
    render(<App />);
    chatStateMock.contentBlocksRef.current = [];
    chatStateMock.addTerminalBlock.mockClear();
    chatStateMock.appendTerminalOutput.mockClear();
    chatStateMock.setStatus.mockClear();

    emitWebSocketEvent({
      type: 'tool_call',
      tab_id: 'tab-1',
      content: {
        server: 'terminal',
        name: 'run_command',
        status: 'calling',
        args: { command: 'ls -la', cwd: '/tmp' },
      },
    });

    expect(chatStateMock.setStatus).toHaveBeenCalledWith('Running command: ls -la...');

    emitWebSocketEvent({
      type: 'terminal_output',
      tab_id: 'tab-1',
      content: { request_id: 'req-1', text: 'line 1', raw: false },
    });

    expect(chatStateMock.addTerminalBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        requestId: 'req-1',
        command: 'ls -la',
        cwd: '/tmp',
        status: 'running',
      }),
    );
    expect(chatStateMock.appendTerminalOutput).toHaveBeenCalledWith('req-1', 'line 1', false);
  });

  test('handles youtube approval message and approval action callback', async () => {
    render(<App />);
    chatStateMock.addYouTubeApprovalBlock.mockClear();
    chatStateMock.updateYouTubeApprovalBlock.mockClear();
    wsSendMock.mockClear();

    expect(await screen.findByText('response-area')).toBeInTheDocument();

    emitWebSocketEvent({
      type: 'youtube_transcription_approval',
      tab_id: 'tab-1',
      content: {
        request_id: 'yt-req-1',
        title: 'Demo Video',
        channel: 'Xpdite',
        duration: '3:12',
        duration_seconds: 192,
        url: 'https://youtube.com/watch?v=demo',
        no_captions_reason: 'disabled',
        audio_size_estimate: '4MB',
        audio_size_bytes: 4000000,
        download_time_estimate: '10s',
        transcription_time_estimate: '20s',
        total_time_estimate: '30s',
        whisper_model: 'base',
        compute_backend: 'cpu',
        playlist_note: null,
      },
    });

    expect(chatStateMock.addYouTubeApprovalBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        requestId: 'yt-req-1',
        title: 'Demo Video',
        status: 'pending',
      }),
    );

    expect(latestResponseAreaProps).not.toBeNull();
    fireEvent.click(screen.getByText('youtube-approve'));

    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'youtube_transcription_approval_response',
        request_id: 'yt-req-1',
        approved: true,
        tab_id: 'tab-1',
      }),
    );
    expect(chatStateMock.updateYouTubeApprovalBlock).toHaveBeenCalledWith('yt-req-1', { status: 'approved' });
  });

  test('sends stop streaming event', () => {
    render(<App />);

    fireEvent.click(screen.getByText('stop-streaming'));

    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'stop_streaming', tab_id: 'tab-1' }),
    );
  });

  test('toggles capture modes and sends mode updates', () => {
    render(<App />);

    fireEvent.click(screen.getByText('mode-fullscreen'));
    fireEvent.click(screen.getByText('mode-precision'));

    expect(screenshotStateMock.setCaptureMode).toHaveBeenCalledWith('fullscreen');
    expect(screenshotStateMock.setCaptureMode).toHaveBeenCalledWith('precision');
    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'set_capture_mode', mode: 'fullscreen', tab_id: 'tab-1' }),
    );
    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'set_capture_mode', mode: 'precision', tab_id: 'tab-1' }),
    );
  });

  test('enables meeting mode and navigates to recorder', () => {
    render(<App />);

    fireEvent.click(screen.getByText('mode-meeting'));

    expect(screenshotStateMock.setMeetingRecordingMode).toHaveBeenCalledWith(true);
    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'set_capture_mode', mode: 'none', tab_id: 'tab-1' }),
    );
    expect(navigateMock).toHaveBeenCalledWith('/recorder');
  });
});
