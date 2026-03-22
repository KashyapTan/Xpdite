import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import ChatHistory from '../../pages/ChatHistory';

type WsMessage = { type: string; content?: unknown };

const navigateMock = vi.fn();
const setMiniMock = vi.fn();
const sendMock = vi.fn();
const subscribeMock = vi.fn();
const unsubscribeMock = vi.fn();
const createTabMock = vi.fn();

let wsHandler: ((message: WsMessage) => void) | null = null;
let isConnectedMock = true;

vi.mock('react-router-dom', () => ({
  useOutletContext: () => ({ setMini: setMiniMock }),
  useNavigate: () => navigateMock,
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: subscribeMock,
    isConnected: isConnectedMock,
  }),
}));

vi.mock('../../contexts/TabContext', () => ({
  useTabs: () => ({
    createTab: createTabMock,
  }),
}));

vi.mock('../../components/TitleBar', () => ({
  default: () => <div data-testid="title-bar">title</div>,
}));

vi.mock('../../components/icons/AppIcons', () => ({
  XIcon: () => <span>x</span>,
}));

describe('ChatHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    wsHandler = null;
    isConnectedMock = true;

    subscribeMock.mockImplementation((handler: (message: WsMessage) => void) => {
      wsHandler = handler;
      return unsubscribeMock;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('requests conversations on mount and on websocket connect event', async () => {
    render(<ChatHistory />);

    expect(screen.getByText('Loading conversations...')).toBeInTheDocument();
    expect(sendMock).toHaveBeenCalledWith({ type: 'get_conversations', limit: 50, offset: 0 });

    await act(async () => {
      wsHandler?.({ type: '__ws_connected' });
    });

    expect(sendMock).toHaveBeenCalledWith({ type: 'get_conversations', limit: 50, offset: 0 });
    expect(sendMock).toHaveBeenCalledTimes(2);
  });

  test('renders conversation list from websocket and handles deletion updates', async () => {
    render(<ChatHistory />);

    await act(async () => {
      wsHandler?.({
        type: 'conversations_list',
        content: [
          { id: 'c1', title: 'Alpha Thread', date: 1700000000 },
          { id: 'c2', title: 'Beta Thread', date: 1700003600 },
        ],
      });
    });

    expect(screen.getByText('Alpha Thread')).toBeInTheDocument();
    expect(screen.getByText('Beta Thread')).toBeInTheDocument();

    await act(async () => {
      wsHandler?.({
        type: 'conversation_deleted',
        content: { conversation_id: 'c1' },
      });
    });

    expect(screen.queryByText('Alpha Thread')).not.toBeInTheDocument();
    expect(screen.getByText('Beta Thread')).toBeInTheDocument();
  });

  test('runs debounced search and resets to list fetch when cleared', async () => {
    render(<ChatHistory />);

    await act(async () => {
      wsHandler?.({ type: 'conversations_list', content: [] });
    });

    const input = screen.getByPlaceholderText('Search chat history...');
    fireEvent.change(input, { target: { value: 'project plan' } });

    expect(sendMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(300);

    expect(sendMock).toHaveBeenCalledWith({ type: 'search_conversations', query: 'project plan' });
    expect(screen.getByText('No conversations match your search.')).toBeInTheDocument();

    fireEvent.change(input, { target: { value: '   ' } });
    await vi.advanceTimersByTimeAsync(300);

    expect(sendMock).toHaveBeenCalledWith({ type: 'get_conversations', limit: 50, offset: 0 });
  });

  test('opens conversation in a new tab when list item is clicked', async () => {
    createTabMock.mockReturnValue('tab-123');
    render(<ChatHistory />);

    await act(async () => {
      wsHandler?.({
        type: 'conversations_list',
        content: [{ id: 'conv-42', title: 'Roadmap', date: 1700000000 }],
      });
    });

    fireEvent.click(screen.getByText('Roadmap'));

    expect(createTabMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/', {
      state: { conversationId: 'conv-42', tabId: 'tab-123' },
    });
  });

  test('delete button sends delete event without triggering navigation', async () => {
    createTabMock.mockReturnValue('tab-777');
    render(<ChatHistory />);

    await act(async () => {
      wsHandler?.({
        type: 'conversations_list',
        content: [{ id: 'conv-del', title: 'Delete Me', date: 1700000000 }],
      });
    });

    fireEvent.click(screen.getByLabelText('Delete Delete Me'));

    expect(sendMock).toHaveBeenCalledWith({
      type: 'delete_conversation',
      conversation_id: 'conv-del',
    });
    expect(createTabMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  test('shows empty state after loading when no conversations exist', async () => {
    render(<ChatHistory />);

    await act(async () => {
      wsHandler?.({ type: 'conversations_list', content: [] });
    });

    expect(screen.getByText('No conversations yet. Start chatting!')).toBeInTheDocument();
  });
});
