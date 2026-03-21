import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act } from 'react';
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
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  test('renders phase label and progress in non-error mode', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'connecting_tools', progress: 44 }),
      isReady: false,
      retry: vi.fn(),
    });

    render(<BootScreen />);
    expect(screen.getByText('Connecting tools')).toBeInTheDocument();
    expect(screen.getByText('44%')).toBeInTheDocument();
  });

  test('clamps progress between 5 and 100', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ progress: 0 }),
      isReady: false,
      retry: vi.fn(),
    });
    const { rerender } = render(<BootScreen />);
    expect(screen.getByText('5%')).toBeInTheDocument();

    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ progress: 140 }),
      isReady: false,
      retry: vi.fn(),
    });
    rerender(<BootScreen />);
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  test('shows fallback phase label for unknown phase value', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'unexpected_phase' as BootState['phase'] }),
      isReady: false,
      retry: vi.fn(),
    });

    render(<BootScreen />);
    expect(screen.getByText('Starting')).toBeInTheDocument();
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

  test('fades out and unmounts when ready', () => {
    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'ready', progress: 100 }),
      isReady: false,
      retry: vi.fn(),
    });
    const { rerender, container } = render(<BootScreen />);
    expect(container.querySelector('.boot-screen')).toBeInTheDocument();

    useBootContextMock.mockReturnValue({
      bootState: makeBootState({ phase: 'ready', progress: 100 }),
      isReady: true,
      retry: vi.fn(),
    });
    rerender(<BootScreen />);
    expect(container.querySelector('.boot-screen--fading')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(251);
    });
    rerender(<BootScreen />);
    expect(container.firstChild).toBeNull();
  });
});

