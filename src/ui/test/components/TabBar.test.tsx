import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import TabBar from '../../components/TabBar';

const useTabsMock = vi.fn();
vi.mock('../../contexts/TabContext', () => ({
  useTabs: () => useTabsMock(),
}));

describe('TabBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('returns null when there is only one tab', () => {
    useTabsMock.mockReturnValue({
      tabs: [{ id: 'default', title: 'Chat' }],
      activeTabId: 'default',
      closeTab: vi.fn(),
      switchTab: vi.fn(),
    });

    const { container } = render(<TabBar wsSend={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders tabs and active state when multiple tabs exist', () => {
    useTabsMock.mockReturnValue({
      tabs: [
        { id: 'default', title: 'Chat' },
        { id: 'tab-1', title: 'New Chat' },
      ],
      activeTabId: 'tab-1',
      closeTab: vi.fn(),
      switchTab: vi.fn(),
    });

    const { container } = render(<TabBar wsSend={vi.fn()} />);
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.getByText('New Chat')).toBeInTheDocument();
    expect(container.querySelector('.tab-bar-tab.active')).toHaveAttribute('title', 'New Chat');
  });

  test('switches tab on tab click', () => {
    const switchTab = vi.fn();
    useTabsMock.mockReturnValue({
      tabs: [
        { id: 'default', title: 'Chat' },
        { id: 'tab-1', title: 'New Chat' },
      ],
      activeTabId: 'default',
      closeTab: vi.fn(),
      switchTab,
    });

    render(<TabBar wsSend={vi.fn()} />);
    fireEvent.click(screen.getByTitle('New Chat'));
    expect(switchTab).toHaveBeenCalledWith('tab-1');
  });

  test('closes tab and notifies backend when close button is clicked', () => {
    const wsSend = vi.fn();
    const closeTab = vi.fn();
    useTabsMock.mockReturnValue({
      tabs: [
        { id: 'default', title: 'Chat' },
        { id: 'tab-1', title: 'New Chat' },
      ],
      activeTabId: 'default',
      closeTab,
      switchTab: vi.fn(),
    });

    render(<TabBar wsSend={wsSend} />);
    fireEvent.click(screen.getByLabelText('Close New Chat'));

    expect(wsSend).toHaveBeenCalledWith({ type: 'tab_closed', tab_id: 'tab-1' });
    expect(closeTab).toHaveBeenCalledWith('tab-1');
  });
});

