import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import TitleBar from '../../components/TitleBar';

const navigateMock = vi.fn();
const createTabMock = vi.fn();

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
  useLocation: () => ({ pathname: '/' }),
}));

vi.mock('../../contexts/TabContext', () => ({
  useTabs: () => ({
    createTab: createTabMock,
  }),
}));

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: vi.fn(),
    subscribe: vi.fn(() => vi.fn()),
    isConnected: true,
  }),
}));

describe('TitleBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.electronAPI = {
      setMiniMode: vi.fn().mockResolvedValue(undefined),
    } as unknown as Window['electronAPI'];
  });

  test('navigates to settings/history/album/home via nav controls', () => {
    render(<TitleBar setMini={vi.fn()} />);

    fireEvent.click(document.querySelector('.settingsButton') as Element);
    fireEvent.click(document.querySelector('.chatHistoryButton') as Element);
    fireEvent.click(document.querySelector('.recordedMeetingsAlbumButton') as Element);
    fireEvent.click(document.querySelector('.blank-space-to-drag') as Element);

    expect(navigateMock).toHaveBeenCalledWith('/settings');
    expect(navigateMock).toHaveBeenCalledWith('/history');
    expect(navigateMock).toHaveBeenCalledWith('/album');
    expect(navigateMock).toHaveBeenCalledWith('/');
  });

  test('starts a new chat when createTab returns id', () => {
    createTabMock.mockReturnValue('tab-123');
    render(<TitleBar setMini={vi.fn()} />);

    fireEvent.click(screen.getByTitle('Start new chat'));

    expect(navigateMock).toHaveBeenCalledWith('/', { state: { newChat: true, tabId: 'tab-123' } });
  });

  test('does not navigate when createTab returns null', () => {
    createTabMock.mockReturnValue(null);
    render(<TitleBar setMini={vi.fn()} />);

    fireEvent.click(screen.getByTitle('Start new chat'));
    expect(navigateMock).not.toHaveBeenCalled();
  });

  test('enters mini mode from logo click', () => {
    const setMini = vi.fn();
    render(<TitleBar setMini={setMini} />);

    fireEvent.click(screen.getByTitle('Mini mode'));

    expect(setMini).toHaveBeenCalledWith(true);
    expect(window.electronAPI?.setMiniMode).not.toHaveBeenCalled();
  });
});

