import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

import { Layout } from '../../components/Layout';

vi.mock('../../contexts/WebSocketContext', () => ({
  WebSocketProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('../../hooks', () => ({
  useTabKeyboardShortcuts: vi.fn(),
}));

vi.mock('../../components/boot/BootScreen', () => ({
  default: () => <div data-testid="boot-screen">boot</div>,
}));

vi.mock('react-router-dom', () => ({
  Outlet: ({
    context,
  }: {
    context: {
      setMini: (val: boolean) => Promise<void>;
      setIsHidden: (val: boolean) => void;
      isHidden: boolean;
    };
  }) => (
    <div>
      <button data-testid="set-mini-true" onClick={() => void context.setMini(true)}>
        set-mini
      </button>
      <button data-testid="set-hidden-true" onClick={() => context.setIsHidden(true)}>
        set-hidden
      </button>
      <span data-testid="hidden-value">{String(context.isHidden)}</span>
    </div>
  ),
}));

describe('Layout', () => {
  beforeEach(() => {
    window.electronAPI = {
      setMiniMode: vi.fn().mockResolvedValue(undefined),
    } as unknown as Window['electronAPI'];
  });

  test('renders boot screen and default normal mode', () => {
    const { container } = render(<Layout />);

    expect(screen.getByTestId('boot-screen')).toBeInTheDocument();
    const appWrapper = container.querySelector('.app-wrapper');
    expect(appWrapper).toHaveClass('normal-mode');
  });

  test('toggles into mini mode through outlet context and calls electron API', async () => {
    const { container } = render(<Layout />);

    fireEvent.click(screen.getByTestId('set-mini-true'));

    await waitFor(() => {
      const appWrapper = container.querySelector('.app-wrapper');
      expect(appWrapper).toHaveClass('mini-mode');
    });
    expect(window.electronAPI?.setMiniMode).toHaveBeenCalledWith(true);
  });

  test('restores from mini mode when clicking mini container and updates hidden state', async () => {
    const { container } = render(<Layout />);

    fireEvent.click(screen.getByTestId('set-mini-true'));
    fireEvent.click(screen.getByTestId('set-hidden-true'));

    await waitFor(() => {
      const body = container.querySelector('.container');
      expect(body).toHaveStyle({ opacity: '0' });
    });

    fireEvent.click(screen.getByTitle('Restore Xpdite'));

    await waitFor(() => {
      const appWrapper = container.querySelector('.app-wrapper');
      expect(appWrapper).toHaveClass('normal-mode');
    });
    expect(window.electronAPI?.setMiniMode).toHaveBeenCalledWith(false);
  });
});

