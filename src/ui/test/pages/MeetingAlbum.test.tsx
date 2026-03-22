import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import MeetingAlbum from '../../pages/MeetingAlbum';

type WsMessage = { type: string; content?: unknown };

const navigateMock = vi.fn();
const setMiniMock = vi.fn();
const sendMock = vi.fn();
const subscribeMock = vi.fn();
const unsubscribeMock = vi.fn();

let wsHandler: ((message: WsMessage) => void) | null = null;

vi.mock('react-router-dom', () => ({
  useOutletContext: () => ({ setMini: setMiniMock }),
  useNavigate: () => navigateMock,
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: subscribeMock,
  }),
}));

vi.mock('../../components/TitleBar', () => ({
  default: () => <div data-testid="title-bar">title</div>,
}));

vi.mock('../../components/icons/AppIcons', () => ({
  XIcon: () => <span>x</span>,
}));

describe('MeetingAlbum', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsHandler = null;
    subscribeMock.mockImplementation((handler: (message: WsMessage) => void) => {
      wsHandler = handler;
      return unsubscribeMock;
    });
  });

  test('subscribes and requests recordings on mount; renders empty state', () => {
    render(<MeetingAlbum />);

    expect(subscribeMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
    expect(screen.getByText('No meetings recorded yet')).toBeInTheDocument();
  });

  test('renders recordings from websocket and navigates on row click', async () => {
    render(<MeetingAlbum />);

    await act(async () => {
      wsHandler?.({
        type: 'meeting_recordings_list',
        content: [
          {
            id: 'r1',
            title: 'Standup',
            started_at: 1700000000,
            ended_at: 1700000300,
            duration_seconds: 300,
            status: 'ready',
          },
        ],
      });
    });

    fireEvent.click(screen.getByText('Standup'));

    expect(navigateMock).toHaveBeenCalledWith('/recording/r1');
  });

  test('search submits matching websocket events for query and clear', async () => {
    render(<MeetingAlbum />);

    const input = screen.getByPlaceholderText('Search recordings...');
    const form = input.closest('form');
    if (!form) {
      throw new Error('Search form not found');
    }

    fireEvent.change(input, { target: { value: 'retro' } });
    fireEvent.submit(form);
    expect(sendMock).toHaveBeenCalledWith({ type: 'search_meeting_recordings', query: 'retro' });

    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.submit(form);
    expect(sendMock).toHaveBeenCalledWith({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
  });

  test('delete button sends delete event and stops click-through navigation', async () => {
    render(<MeetingAlbum />);

    await act(async () => {
      wsHandler?.({
        type: 'meeting_recordings_list',
        content: [
          {
            id: 'r-del',
            title: 'Delete Target',
            started_at: 1700000000,
            ended_at: 1700000300,
            duration_seconds: 300,
            status: 'ready',
          },
        ],
      });
    });

    fireEvent.click(screen.getByLabelText('Delete Delete Target'));

    expect(sendMock).toHaveBeenCalledWith({ type: 'delete_meeting_recording', recording_id: 'r-del' });
    expect(navigateMock).not.toHaveBeenCalled();
  });

  test('applies processing progress updates and refreshes when processing completes', async () => {
    render(<MeetingAlbum />);

    await act(async () => {
      wsHandler?.({
        type: 'meeting_recordings_list',
        content: [
          {
            id: 'r-proc',
            title: 'Processing Session',
            started_at: 1700000000,
            ended_at: null,
            duration_seconds: null,
            status: 'processing',
          },
        ],
      });
    });

    await act(async () => {
      wsHandler?.({
        type: 'meeting_processing_progress',
        content: {
          recording_id: 'r-proc',
          step: 'transcribing',
          percentage: 55,
          estimated_remaining_seconds: 20,
        },
      });
    });

    expect(screen.getByText('transcribing')).toBeInTheDocument();

    await act(async () => {
      wsHandler?.({
        type: 'meeting_processing_progress',
        content: {
          recording_id: 'r-proc',
          step: 'complete',
          percentage: 100,
          estimated_remaining_seconds: 0,
        },
      });
    });

    await waitFor(() => {
      expect(sendMock).toHaveBeenCalledWith({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
      expect(sendMock).toHaveBeenCalledTimes(2);
    });
  });

  test('removes a recording from list after delete websocket event', async () => {
    render(<MeetingAlbum />);

    await act(async () => {
      wsHandler?.({
        type: 'meeting_recordings_list',
        content: [
          {
            id: 'r1',
            title: 'Kept',
            started_at: 1700000000,
            ended_at: 1700000300,
            duration_seconds: 300,
            status: 'ready',
          },
          {
            id: 'r2',
            title: 'Removed',
            started_at: 1700000400,
            ended_at: 1700000700,
            duration_seconds: 300,
            status: 'ready',
          },
        ],
      });
    });

    await act(async () => {
      wsHandler?.({
        type: 'meeting_recording_deleted',
        content: { recording_id: 'r2' },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Kept')).toBeInTheDocument();
      expect(screen.queryByText('Removed')).not.toBeInTheDocument();
    });
  });
});
