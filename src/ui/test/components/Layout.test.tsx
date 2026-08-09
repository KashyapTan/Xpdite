import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

import { Layout } from '../../components/Layout';

// Controllable WebSocket subscriber registry so tests can emit backend messages.
type WsHandler = (data: Record<string, unknown>) => void;
const wsHandlers = new Set<WsHandler>();
const emitWs = (data: Record<string, unknown>) => {
  act(() => {
    for (const handler of [...wsHandlers]) {
      handler(data);
    }
  });
};
const sendMock = vi.fn();

vi.mock('../../contexts/WebSocketContext', () => ({
  WebSocketProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useWebSocket: () => ({
    send: sendMock,
    subscribe: (handler: WsHandler) => {
      wsHandlers.add(handler);
      return () => wsHandlers.delete(handler);
    },
    isConnected: true,
  }),
}));

vi.mock('../../hooks', () => ({
  useTabKeyboardShortcuts: vi.fn(),
}));

const navigateMock = vi.fn();

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
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
    wsHandlers.clear();
    sendMock.mockClear();
    navigateMock.mockClear();
    window.electronAPI = {
      setMiniMode: vi.fn().mockResolvedValue(undefined),
      showInactive: vi.fn().mockResolvedValue(undefined),
      focusWindow: vi.fn().mockResolvedValue(undefined),
    } as unknown as Window['electronAPI'];
  });

  test('renders default normal mode', () => {
    const { container } = render(<Layout />);

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

  test('toggle_mini_mode hotkey message flips the window between mini and normal', async () => {
    const { container } = render(<Layout />);

    emitWs({ type: 'toggle_mini_mode' });
    await waitFor(() => {
      expect(container.querySelector('.app-wrapper')).toHaveClass('mini-mode');
    });
    expect(window.electronAPI?.setMiniMode).toHaveBeenLastCalledWith(true);

    emitWs({ type: 'toggle_mini_mode' });
    await waitFor(() => {
      expect(container.querySelector('.app-wrapper')).toHaveClass('normal-mode');
    });
    expect(window.electronAPI?.setMiniMode).toHaveBeenLastCalledWith(false);
  });

  test('auto_mode_trigger shows inactive, navigates to chat route, and never steals focus', () => {
    render(<Layout />);

    emitWs({ type: 'auto_mode_trigger', content: { prompt: 'Explain this', flash: false } });

    // Surfaced without activating; MUST NOT focus the window.
    expect(window.electronAPI?.showInactive).toHaveBeenCalledTimes(1);
    expect(window.electronAPI?.focusWindow).not.toHaveBeenCalled();

    // Handed off to the chat route with the trigger payload + a nonce.
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const [path, options] = navigateMock.mock.calls[0];
    expect(path).toBe('/');
    expect(options.state.autoTrigger).toEqual(
      expect.objectContaining({ prompt: 'Explain this' }),
    );
    expect(typeof options.state.autoTrigger.nonce).toBe('number');
  });

  test('successive auto_mode_trigger events produce strictly increasing nonces', () => {
    render(<Layout />);

    emitWs({ type: 'auto_mode_trigger', content: { prompt: 'a' } });
    emitWs({ type: 'auto_mode_trigger', content: { prompt: 'b' } });

    expect(navigateMock).toHaveBeenCalledTimes(2);
    const first = navigateMock.mock.calls[0][1].state.autoTrigger.nonce as number;
    const second = navigateMock.mock.calls[1][1].state.autoTrigger.nonce as number;
    // A wall-clock nonce could collide within the same millisecond; the
    // monotonic counter guarantees the second trigger is never dropped.
    expect(second).toBeGreaterThan(first);
  });

  test('auto_mode_trigger restores from mini but defers flash until capture completes', async () => {
    const { container } = render(<Layout />);

    // Put the window into mini first.
    emitWs({ type: 'toggle_mini_mode' });
    await waitFor(() => {
      expect(container.querySelector('.app-wrapper')).toHaveClass('mini-mode');
    });

    emitWs({ type: 'auto_mode_trigger', content: { prompt: 'x', flash: true } });

    await waitFor(() => {
      expect(container.querySelector('.app-wrapper')).toHaveClass('normal-mode');
    });
    expect(container.querySelector('.auto-mode-flash')).toBeNull();
  });

  test('auto_mode_error is surfaced without calling the focus APIs', () => {
    render(<Layout />);

    emitWs({ type: 'auto_mode_error', content: { message: 'Cloud capture blocked.' } });

    expect(window.electronAPI?.showInactive).not.toHaveBeenCalled();
    expect(window.electronAPI?.focusWindow).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith('/', {
      state: {
        autoError: expect.objectContaining({ message: 'Cloud capture blocked.' }),
      },
    });
  });
});
