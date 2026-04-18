import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import ScheduledJobsResults from '../../pages/ScheduledJobsResults';
import { api } from '../../services/api';

type WsMessage = { type: string; content?: unknown };

const createTabMock = vi.fn();
const navigateMock = vi.fn();
const sendMock = vi.fn();
const subscribeMock = vi.fn();
const setMiniMock = vi.fn();

let wsHandler: ((message: WsMessage) => void) | null = null;

vi.mock('../../services/api', () => ({
  api: {
    getScheduledJobConversations: vi.fn(),
    getScheduledJobs: vi.fn(),
  },
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
  useOutletContext: () => ({ setMini: setMiniMock }),
}));

vi.mock('../../contexts/TabContext', () => ({
  useTabs: () => ({
    createTab: createTabMock,
  }),
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

const mockedApi = vi.mocked(api);

describe('ScheduledJobsResults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsHandler = null;
    createTabMock.mockReturnValue('tab-100');
    subscribeMock.mockImplementation((handler: (message: WsMessage) => void) => {
      wsHandler = handler;
      return vi.fn();
    });
    mockedApi.getScheduledJobs.mockResolvedValue({
      jobs: [
        {
          id: 'job-1',
          name: 'Morning Brief',
          cron_expression: '0 9 * * *',
          enabled: true,
        },
      ],
    });
    mockedApi.getScheduledJobConversations.mockResolvedValue({
      conversations: [
        {
          id: 'conversation-1',
          job_id: 'job-1',
          job_name: 'Morning Brief',
          title: 'Inbox summary',
          created_at: Math.floor(Date.now() / 1000),
          updated_at: Math.floor(Date.now() / 1000),
        },
      ],
    });
  });

  test('loads job conversations, filters/searches them, opens a conversation, and deletes results', async () => {
    render(<ScheduledJobsResults />);

    expect(screen.getByTestId('title-bar')).toBeInTheDocument();
    expect(await screen.findByText('Inbox summary')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Morning Brief' })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Search task results...'), {
      target: { value: 'summary' },
    });
    expect(screen.getByText('Inbox summary')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Morning Brief' }));
    expect(screen.getByText('Inbox summary')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Inbox summary'));
    expect(createTabMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/', {
      state: { conversationId: 'conversation-1', tabId: 'tab-100' },
    });

    fireEvent.click(screen.getByLabelText('Delete Inbox summary'));
    expect(sendMock).toHaveBeenCalledWith({
      type: 'delete_conversation',
      conversation_id: 'conversation-1',
    });
  });

  test('reacts to websocket deletions and refetches on job-complete notifications', async () => {
    mockedApi.getScheduledJobConversations
      .mockResolvedValueOnce({
        conversations: [
          {
            id: 'conversation-1',
            job_id: 'job-1',
            job_name: 'Morning Brief',
            title: 'Inbox summary',
            created_at: Math.floor(Date.now() / 1000),
            updated_at: Math.floor(Date.now() / 1000),
          },
        ],
      })
      .mockResolvedValueOnce({
        conversations: [
          {
            id: 'conversation-2',
            job_id: 'job-1',
            job_name: 'Morning Brief',
            title: 'Inbox summary (retry)',
            created_at: Math.floor(Date.now() / 1000),
            updated_at: Math.floor(Date.now() / 1000),
          },
        ],
      });

    render(<ScheduledJobsResults />);
    expect(await screen.findByText('Inbox summary')).toBeInTheDocument();

    await act(async () => {
      wsHandler?.({
        type: 'conversation_deleted',
        content: { conversation_id: 'conversation-1' },
      });
    });
    expect(screen.queryByText('Inbox summary')).not.toBeInTheDocument();

    await act(async () => {
      wsHandler?.({
        type: 'notification_added',
        content: { type: 'job_complete' },
      });
    });

    expect(await screen.findByText('Inbox summary (retry)')).toBeInTheDocument();
    expect(mockedApi.getScheduledJobConversations).toHaveBeenCalledTimes(2);
  });

  test('shows an explicit error state when scheduled-job data fails to load', async () => {
    mockedApi.getScheduledJobConversations.mockRejectedValueOnce(new Error('Failed to fetch job conversations'));

    render(<ScheduledJobsResults />);

    expect(await screen.findByText('Failed to fetch job conversations')).toBeInTheDocument();
  });
});
