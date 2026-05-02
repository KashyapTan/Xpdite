import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import BootScreen from '../../../components/boot/BootScreen';
import type { BootState } from '../../../contexts/BootContext';

const useBootContextMock = vi.fn();
vi.mock('../../../contexts/BootContext', () => ({
  useBootContext: () => useBootContextMock(),
}));

function makeBootState(overrides: Partial<BootState> = {}): BootState {
  return {
    phase: 'starting',
    message: 'Starting up',
    progress: 12,
    ...overrides,
  };
}

describe('BootScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('does not render during normal startup', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'connecting_tools', progress: 44 }),
      isReady: false,
      retry: vi.fn(),
    });

    const { container } = render(<BootScreen />);
    expect(container.firstChild).toBeNull();
  });

  test('does not render when ready', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'ready', progress: 100 }),
      isReady: true,
      retry: vi.fn(),
    });

    const { container } = render(<BootScreen />);
    expect(container.firstChild).toBeNull();
  });

  test('renders error details and retry button in error phase', () => {
    const retry = vi.fn();
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'error', error: 'IPC unavailable', progress: 0 }),
      isReady: false,
      retry,
    });

    render(<BootScreen />);
    expect(screen.getByText('Startup failed')).toBeInTheDocument();
    expect(screen.getByText('IPC unavailable')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

