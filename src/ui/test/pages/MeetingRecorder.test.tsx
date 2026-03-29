import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import MeetingRecorder from '../../pages/MeetingRecorder';

const {
  setMiniMock,
  navigateMock,
  startRecordingMock,
  stopRecordingMock,
  clearErrorMock,
} = vi.hoisted(() => ({
  setMiniMock: vi.fn(),
  navigateMock: vi.fn(),
  startRecordingMock: vi.fn(),
  stopRecordingMock: vi.fn(),
  clearErrorMock: vi.fn(),
}));

type TranscriptChunk = {
  text: string;
  start_time: number;
  end_time: number;
};

type PendingAction = 'starting' | 'stopping' | null;

type RecorderMockState = {
  isRecording: boolean;
  isRecordingUi: boolean;
  isPending: boolean;
  pendingAction: PendingAction;
  liveTranscript: TranscriptChunk[];
  recordingDuration: number;
  visualizerBars: number[];
  startRecording: () => Promise<void> | void;
  stopRecording: () => Promise<void> | void;
  error: string | null;
  clearError: () => void;
};

let recorderState: RecorderMockState;

const buildRecorderState = (overrides: Partial<RecorderMockState> = {}): RecorderMockState => ({
  isRecording: false,
  isRecordingUi: false,
  isPending: false,
  pendingAction: null,
  liveTranscript: [],
  recordingDuration: 0,
  visualizerBars: [0.2, 0.3, 0.25],
  startRecording: startRecordingMock,
  stopRecording: stopRecordingMock,
  error: null,
  clearError: clearErrorMock,
  ...overrides,
});

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useOutletContext: () => ({ setMini: setMiniMock }),
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../contexts/MeetingRecorderContext', () => ({
  MeetingRecorderProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useMeetingRecorder: () => recorderState,
}));

vi.mock('../../components/TitleBar', () => ({
  default: () => <div data-testid="title-bar">TitleBar</div>,
}));

vi.mock('../../components/icons/AppIcons', () => ({
  RecordIcon: () => <span data-testid="record-icon" aria-hidden="true" />,
  StopSquareIcon: () => <span data-testid="stop-icon" aria-hidden="true" />,
  XIcon: () => <span data-testid="x-icon" aria-hidden="true" />,
}));

vi.mock('../../components/input/ModeSelector', () => ({
  ModeSelector: ({ onFullscreenMode, onPrecisionMode, onMeetingMode }: {
    onFullscreenMode: () => void;
    onPrecisionMode: () => void;
    onMeetingMode: () => void;
  }) => (
    <div data-testid="mode-selector">
      <button type="button" onClick={onFullscreenMode}>fullscreen mode</button>
      <button type="button" onClick={onPrecisionMode}>precision mode</button>
      <button type="button" onClick={onMeetingMode}>meeting mode</button>
    </div>
  ),
}));

describe('MeetingRecorder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    recorderState = buildRecorderState();
  });

  test('renders initial standby UI state', () => {
    render(<MeetingRecorder />);

    expect(screen.getByTestId('title-bar')).toBeInTheDocument();
    expect(screen.getByText('Live Transcript')).toBeInTheDocument();
    expect(screen.getByText('Standby')).toBeInTheDocument();
    expect(screen.getByText('Press Start Recording to begin')).toBeInTheDocument();
    expect(screen.getByText('00:00')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Recording' })).toBeEnabled();
  });

  test('uses start action while idle and stop action while recording', () => {
    recorderState = buildRecorderState({ isRecordingUi: false, isRecording: false });
    const { rerender } = render(<MeetingRecorder />);

    fireEvent.click(screen.getByRole('button', { name: 'Start Recording' }));
    expect(startRecordingMock).toHaveBeenCalledTimes(1);
    expect(stopRecordingMock).not.toHaveBeenCalled();

    recorderState = buildRecorderState({ isRecordingUi: true, isRecording: true });
    rerender(<MeetingRecorder />);

    fireEvent.click(screen.getByRole('button', { name: 'Stop Recording' }));
    expect(stopRecordingMock).toHaveBeenCalledTimes(1);
  });

  test('disables recording button while pending', () => {
    recorderState = buildRecorderState({
      isPending: true,
      pendingAction: 'starting',
      isRecordingUi: true,
    });

    render(<MeetingRecorder />);

    const button = screen.getByRole('button', { name: 'Starting...' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');

    fireEvent.click(button);
    expect(startRecordingMock).not.toHaveBeenCalled();
    expect(stopRecordingMock).not.toHaveBeenCalled();
  });

  test('renders transcript chunks with formatted timestamps', () => {
    recorderState = buildRecorderState({
      liveTranscript: [
        { start_time: 3.4, end_time: 5.1, text: 'Opening updates' },
        { start_time: 61.9, end_time: 65.2, text: 'Action items reviewed' },
      ],
    });

    render(<MeetingRecorder />);

    expect(screen.getByText('[00:03]')).toBeInTheDocument();
    expect(screen.getByText('Opening updates')).toBeInTheDocument();
    expect(screen.getByText('[01:01]')).toBeInTheDocument();
    expect(screen.getByText('Action items reviewed')).toBeInTheDocument();
    expect(screen.queryByText('Press Start Recording to begin')).not.toBeInTheDocument();
  });

  test('mode selector callbacks navigate for fullscreen and precision modes', () => {
    render(<MeetingRecorder />);

    fireEvent.click(screen.getByRole('button', { name: 'fullscreen mode' }));
    fireEvent.click(screen.getByRole('button', { name: 'precision mode' }));
    fireEvent.click(screen.getByRole('button', { name: 'meeting mode' }));

    expect(navigateMock).toHaveBeenCalledTimes(2);
    expect(navigateMock).toHaveBeenNthCalledWith(1, '/', { state: { selectedCaptureMode: 'fullscreen' } });
    expect(navigateMock).toHaveBeenNthCalledWith(2, '/', { state: { selectedCaptureMode: 'precision' } });
  });
});
