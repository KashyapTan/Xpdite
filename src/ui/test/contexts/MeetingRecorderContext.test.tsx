import React from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { MeetingRecorderProvider, useMeetingRecorder } from '../../contexts/MeetingRecorderContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { useAudioCapture } from '../../hooks/useAudioCapture';

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: vi.fn(),
}));

vi.mock('../../hooks/useAudioCapture', () => ({
  useAudioCapture: vi.fn(),
}));

type WsMessage = Record<string, unknown>;
type WsSubscriber = (data: WsMessage) => void;

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MeetingRecorderProvider>{children}</MeetingRecorderProvider>
);

describe('MeetingRecorderContext', () => {
  let wsHandler: WsSubscriber | null;
  let wsSendMock: ReturnType<typeof vi.fn<(msg: Record<string, unknown>) => void>>;
  let startCaptureMock: ReturnType<typeof vi.fn<() => Promise<void>>>;
  let stopCaptureMock: ReturnType<typeof vi.fn<() => void>>;

  const mockedUseWebSocket = vi.mocked(useWebSocket);
  const mockedUseAudioCapture = vi.mocked(useAudioCapture);

  const emitWsMessage = (message: WsMessage) => {
    if (!wsHandler) {
      throw new Error('WebSocket subscriber was not registered');
    }
    act(() => {
      wsHandler?.(message);
    });
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    wsHandler = null;
    wsSendMock = vi.fn<(msg: Record<string, unknown>) => void>();
    startCaptureMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
    stopCaptureMock = vi.fn<() => void>();

    mockedUseWebSocket.mockReturnValue({
      send: wsSendMock,
      subscribe: vi.fn((handler: WsSubscriber) => {
        wsHandler = handler;
        return () => {};
      }),
      isConnected: true,
    });

    mockedUseAudioCapture.mockReturnValue({
      startCapture: startCaptureMock,
      stopCapture: stopCaptureMock,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('transitions startRecording from pending to started after ack', async () => {
    const { result } = renderHook(() => useMeetingRecorder(), { wrapper });

    await act(async () => {
      await result.current.startRecording();
    });

    expect(startCaptureMock).toHaveBeenCalledTimes(1);
    expect(wsSendMock).toHaveBeenCalledWith({ type: 'meeting_start_recording' });
    expect(result.current.isPending).toBe(true);
    expect(result.current.pendingAction).toBe('starting');
    expect(result.current.isRecording).toBe(false);
    expect(result.current.isRecordingUi).toBe(true);

    emitWsMessage({
      type: 'meeting_recording_started',
      content: { recording_id: 'rec-123', started_at: 1710000000 },
    });

    expect(result.current.isPending).toBe(false);
    expect(result.current.pendingAction).toBeNull();
    expect(result.current.isRecording).toBe(true);
    expect(result.current.isRecordingUi).toBe(true);
    expect(result.current.recordingId).toBe('rec-123');
    expect(result.current.startedAt).toBe(1710000000);
    expect(result.current.error).toBeNull();
  });

  test('handles startCapture failure and resets state', async () => {
    startCaptureMock.mockRejectedValueOnce(new Error('Microphone permission denied'));
    const { result } = renderHook(() => useMeetingRecorder(), { wrapper });

    await act(async () => {
      await result.current.startRecording();
    });

    expect(wsSendMock).not.toHaveBeenCalled();
    expect(stopCaptureMock).toHaveBeenCalledTimes(1);
    expect(result.current.isPending).toBe(false);
    expect(result.current.pendingAction).toBeNull();
    expect(result.current.isRecording).toBe(false);
    expect(result.current.startedAt).toBeNull();
    expect(result.current.recordingDuration).toBe(0);
    expect(result.current.error).toBe('Microphone permission denied');
  });

  test('accepts transcript chunks only after recording-start ack', async () => {
    const { result } = renderHook(() => useMeetingRecorder(), { wrapper });

    emitWsMessage({
      type: 'meeting_transcript_chunk',
      content: { text: 'before start', start_time: 0, end_time: 1 },
    });
    expect(result.current.liveTranscript).toEqual([]);

    await act(async () => {
      await result.current.startRecording();
    });

    emitWsMessage({
      type: 'meeting_transcript_chunk',
      content: { text: 'during pending', start_time: 1, end_time: 2 },
    });
    expect(result.current.liveTranscript).toEqual([]);

    emitWsMessage({
      type: 'meeting_recording_started',
      content: { recording_id: 'rec-456', started_at: 1710000100 },
    });

    emitWsMessage({
      type: 'meeting_transcript_chunk',
      content: { text: 'accepted', start_time: 2, end_time: 3 },
    });

    expect(result.current.liveTranscript).toEqual([
      { text: 'accepted', start_time: 2, end_time: 3 },
    ]);
  });

  test('transitions stopRecording from pending to stopped after ack', async () => {
    const { result } = renderHook(() => useMeetingRecorder(), { wrapper });

    await act(async () => {
      await result.current.startRecording();
    });

    emitWsMessage({
      type: 'meeting_recording_started',
      content: { recording_id: 'rec-789', started_at: 1710000200 },
    });

    await act(async () => {
      await result.current.stopRecording();
    });

    expect(stopCaptureMock).toHaveBeenCalledTimes(1);
    expect(wsSendMock).toHaveBeenCalledWith({ type: 'meeting_stop_recording' });
    expect(result.current.isPending).toBe(true);
    expect(result.current.pendingAction).toBe('stopping');
    expect(result.current.isRecording).toBe(true);
    expect(result.current.isRecordingUi).toBe(false);

    emitWsMessage({ type: 'meeting_recording_stopped', content: null });

    expect(result.current.isPending).toBe(false);
    expect(result.current.pendingAction).toBeNull();
    expect(result.current.isRecording).toBe(false);
    expect(result.current.isRecordingUi).toBe(false);
    expect(result.current.recordingId).toBeNull();
    expect(result.current.startedAt).toBeNull();
    expect(result.current.recordingDuration).toBe(0);
    expect(result.current.liveTranscript).toEqual([]);
  });

  test('times out pending startRecording and surfaces timeout error', async () => {
    const { result } = renderHook(() => useMeetingRecorder(), { wrapper });

    await act(async () => {
      await result.current.startRecording();
    });

    expect(result.current.pendingAction).toBe('starting');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(stopCaptureMock).toHaveBeenCalledTimes(1);
    expect(result.current.isPending).toBe(false);
    expect(result.current.pendingAction).toBeNull();
    expect(result.current.isRecording).toBe(false);
    expect(result.current.recordingId).toBeNull();
    expect(result.current.startedAt).toBeNull();
    expect(result.current.recordingDuration).toBe(0);
    expect(result.current.error).toBe('Recording did not start in time. Please try again.');
  });
});
