import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

const navigateMock = vi.fn();
const subscribeMock = vi.fn();
const notificationsApiMock = {
  getNotifications: vi.fn(),
  getNotificationCount: vi.fn(),
  dismissNotification: vi.fn(),
  dismissAllNotifications: vi.fn(),
};

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    subscribe: subscribeMock,
  }),
}));

vi.mock('../../services/api', () => ({
  api: notificationsApiMock,
}));

describe('NotificationBell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    notificationsApiMock.getNotificationCount.mockResolvedValue({ count: 3 });
    notificationsApiMock.getNotifications.mockResolvedValue({
      notifications: [
        {
          id: 'notif-1',
          type: 'job_complete',
          title: 'Queued run ready',
          body: 'Your scheduled job finished.',
          payload: { conversation_id: 'conv-1' },
          created_at: Math.floor(Date.now() / 1000),
        },
      ],
      unread_count: 3,
    });
    notificationsApiMock.dismissNotification.mockResolvedValue(undefined);
    notificationsApiMock.dismissAllNotifications.mockResolvedValue(undefined);

    window.requestIdleCallback = vi.fn((callback: IdleRequestCallback) => {
      callback({
        didTimeout: false,
        timeRemaining: () => 50,
      } as IdleDeadline);
      return 1;
    }) as typeof window.requestIdleCallback;
    window.cancelIdleCallback = vi.fn() as typeof window.cancelIdleCallback;
  });

  test('loads unread counts on idle and fetches notifications when opened', async () => {
    const { default: NotificationBell } = await import('../../components/NotificationBell');

    render(<NotificationBell />);

    const bellButton = await screen.findByTitle('3 notifications');
    expect(screen.getByText('3')).toBeInTheDocument();

    fireEvent.click(bellButton);

    expect(await screen.findByText('Queued run ready')).toBeInTheDocument();
    expect(notificationsApiMock.getNotifications).toHaveBeenCalled();
  });

  test('navigates to the related conversation when a notification is clicked', async () => {
    const { default: NotificationBell } = await import('../../components/NotificationBell');

    render(<NotificationBell />);

    fireEvent.click(await screen.findByTitle('3 notifications'));
    fireEvent.click(await screen.findByText('Queued run ready'));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/?conversation=conv-1');
    });
  });
});
