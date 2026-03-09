/**
 * MeetingRecorderContext.
 *
 * Global React context that persists recording state across route changes.
 * Wraps the app so the recording indicator is visible on all pages.
 *
 * Uses WebSocketContext directly for send/receive — no window globals.
 */
import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { useAudioCapture } from '../hooks/useAudioCapture';
import { useWebSocket } from './WebSocketContext';

// ---- Types ----

const DEFAULT_VISUALIZER_BARS = Array.from({ length: 24 }, () => 0.12);
const RECORDING_ACK_TIMEOUT_MS = 10000;

type PendingRecordingAction = 'starting' | 'stopping' | null;

export interface TranscriptChunk {
    text: string;
    start_time: number;
    end_time: number;
}

interface MeetingRecorderState {
    isRecording: boolean;
    isRecordingUi: boolean;
    isPending: boolean;
    pendingAction: PendingRecordingAction;
    recordingId: string | null;
    liveTranscript: TranscriptChunk[];
    recordingDuration: number;
    startedAt: number | null;
    error: string | null;
    visualizerBars: number[];
}

interface MeetingRecorderActions {
    startRecording: () => Promise<void>;
    stopRecording: () => Promise<void>;
    clearTranscript: () => void;
    clearError: () => void;
}

type MeetingRecorderContextValue = MeetingRecorderState & MeetingRecorderActions;

const MeetingRecorderContext = createContext<MeetingRecorderContextValue | null>(null);

// ---- Provider ----

interface ProviderProps {
    children: React.ReactNode;
}

export const MeetingRecorderProvider: React.FC<ProviderProps> = ({ children }) => {
    const { send: wsSend, subscribe } = useWebSocket();

    const [isRecording, setIsRecording] = useState(false);
    const [pendingAction, setPendingAction] = useState<PendingRecordingAction>(null);
    const [recordingId, setRecordingId] = useState<string | null>(null);
    const [liveTranscript, setLiveTranscript] = useState<TranscriptChunk[]>([]);
    const [recordingDuration, setRecordingDuration] = useState(0);
    const [startedAt, setStartedAt] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [visualizerBars, setVisualizerBars] = useState<number[]>(DEFAULT_VISUALIZER_BARS);

    const durationIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const pendingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const shouldAcceptTranscriptRef = useRef(false);

    const sendMessage = useCallback((msg: Record<string, unknown>) => {
        wsSend(msg);
    }, [wsSend]);

    const handleVisualizerFrame = useCallback((levels: number[]) => {
        setVisualizerBars(levels.length > 0 ? levels : DEFAULT_VISUALIZER_BARS);
    }, []);

    const { startCapture, stopCapture } = useAudioCapture(sendMessage, handleVisualizerFrame);
    const isRecordingUi = pendingAction === 'starting' || (isRecording && pendingAction !== 'stopping');

    const clearPendingTimeout = useCallback(() => {
        if (pendingTimeoutRef.current) {
            clearTimeout(pendingTimeoutRef.current);
            pendingTimeoutRef.current = null;
        }
    }, []);

    const schedulePendingTimeout = useCallback((nextAction: Exclude<PendingRecordingAction, null>) => {
        clearPendingTimeout();
        pendingTimeoutRef.current = setTimeout(() => {
            setPendingAction(null);
            setIsRecording(false);
            setRecordingId(null);
            setStartedAt(null);
            setRecordingDuration(0);
            setVisualizerBars(DEFAULT_VISUALIZER_BARS);
            if (nextAction === 'starting') {
                stopCapture();
            }
            setError(
                nextAction === 'starting'
                    ? 'Recording did not start in time. Please try again.'
                    : 'Recording did not stop in time. Please try again.'
            );
        }, RECORDING_ACK_TIMEOUT_MS);
    }, [clearPendingTimeout, stopCapture]);

    // Duration timer
    useEffect(() => {
        if (isRecording && startedAt) {
            durationIntervalRef.current = setInterval(() => {
                setRecordingDuration(Math.floor((Date.now() / 1000) - startedAt));
            }, 1000);
        }
        return () => {
            if (durationIntervalRef.current) {
                clearInterval(durationIntervalRef.current);
                durationIntervalRef.current = null;
            }
        };
    }, [isRecording, startedAt]);

    useEffect(() => {
        return () => {
            clearPendingTimeout();
        };
    }, [clearPendingTimeout]);

    const startRecording = useCallback(async () => {
        if (isRecording || pendingAction !== null) return;
        setError(null);
        shouldAcceptTranscriptRef.current = false;
        setPendingAction('starting');
        setRecordingDuration(0);
        setLiveTranscript([]);
        schedulePendingTimeout('starting');

        try {
            // Start audio capture first
            await startCapture();

            // Tell backend to start recording
            sendMessage({ type: 'meeting_start_recording' });
        } catch (err) {
            console.error('Failed to start recording:', err);
            const message = err instanceof Error ? err.message : 'Failed to start audio capture';
            setError(message);
            clearPendingTimeout();
            setPendingAction(null);
            setIsRecording(false);
            setStartedAt(null);
            setRecordingDuration(0);
            stopCapture();
        }
    }, [isRecording, pendingAction, startCapture, sendMessage, stopCapture, schedulePendingTimeout, clearPendingTimeout]);

    const stopRecording = useCallback(async () => {
        if ((!isRecording && pendingAction !== 'starting') || pendingAction === 'stopping') return;

        shouldAcceptTranscriptRef.current = false;
        setPendingAction('stopping');
        setStartedAt(null);
        setRecordingDuration(0);
        setLiveTranscript([]);
        setVisualizerBars(DEFAULT_VISUALIZER_BARS);
        schedulePendingTimeout('stopping');

        // Stop audio capture
        stopCapture();

        // Tell backend to stop recording
        sendMessage({ type: 'meeting_stop_recording' });
    }, [isRecording, pendingAction, stopCapture, sendMessage, schedulePendingTimeout]);

    const clearTranscript = useCallback(() => {
        setLiveTranscript([]);
    }, []);

    const clearError = useCallback(() => {
        setError(null);
    }, []);

    // Handle incoming WS messages for recording state
    // This will be called from the parent component that manages WS
    const handleRecordingStarted = useCallback((data: { recording_id: string; started_at: number }) => {
        clearPendingTimeout();
        shouldAcceptTranscriptRef.current = true;
        setPendingAction(null);
        setIsRecording(true);
        setRecordingId(data.recording_id);
        setStartedAt(data.started_at);
        setRecordingDuration(0);
        setLiveTranscript([]);
    }, [clearPendingTimeout]);

    const handleRecordingStopped = useCallback(() => {
        clearPendingTimeout();
        shouldAcceptTranscriptRef.current = false;
        setPendingAction(null);
        setIsRecording(false);
        setRecordingId(null);
        setStartedAt(null);
        setRecordingDuration(0);
        setLiveTranscript([]);
        setVisualizerBars(DEFAULT_VISUALIZER_BARS);
        if (durationIntervalRef.current) {
            clearInterval(durationIntervalRef.current);
            durationIntervalRef.current = null;
        }
    }, [clearPendingTimeout]);

    const handleTranscriptChunk = useCallback((chunk: TranscriptChunk) => {
        if (!shouldAcceptTranscriptRef.current) {
            return;
        }
        setLiveTranscript((prev) => [...prev, chunk]);
    }, []);

    // Expose handlers via ref so the subscription callback always has the latest versions.
    const handlersRef = useRef({ handleRecordingStarted, handleRecordingStopped, handleTranscriptChunk });
    handlersRef.current = { handleRecordingStarted, handleRecordingStopped, handleTranscriptChunk };

    // Subscribe to the shared WebSocket for meeting recording messages.
    useEffect(() => {
        return subscribe((data) => {
            const content = typeof data.content === 'string'
                ? (() => { try { return JSON.parse(data.content as string); } catch { return data.content; } })()
                : data.content;

            switch (data.type) {
                case 'meeting_recording_started':
                    handlersRef.current.handleRecordingStarted(content as { recording_id: string; started_at: number });
                    break;
                case 'meeting_recording_stopped':
                    handlersRef.current.handleRecordingStopped();
                    break;
                case 'meeting_transcript_chunk':
                    handlersRef.current.handleTranscriptChunk(content as TranscriptChunk);
                    break;
                case 'meeting_recording_error':
                    clearPendingTimeout();
                    shouldAcceptTranscriptRef.current = false;
                    setPendingAction(null);
                    setIsRecording(false);
                    setRecordingId(null);
                    setStartedAt(null);
                    setRecordingDuration(0);
                    setLiveTranscript([]);
                    setVisualizerBars(DEFAULT_VISUALIZER_BARS);
                    setError(typeof content === 'object' && content !== null && 'error' in content
                        ? String((content as { error: string }).error)
                        : 'Recording error');
                    break;
                default:
                    break;
            }
        });
    }, [subscribe, clearPendingTimeout]);

    return (
        <MeetingRecorderContext.Provider
            value={{
                isRecording,
                isRecordingUi,
                isPending: pendingAction !== null,
                pendingAction,
                recordingId,
                liveTranscript,
                recordingDuration,
                startedAt,
                error,
                visualizerBars,
                startRecording,
                stopRecording,
                clearTranscript,
                clearError,
            }}
        >
            {children}
        </MeetingRecorderContext.Provider>
    );
};

// ---- Hook ----

// eslint-disable-next-line react-refresh/only-export-components
export function useMeetingRecorder(): MeetingRecorderContextValue {
    const ctx = useContext(MeetingRecorderContext);
    if (!ctx) {
        throw new Error('useMeetingRecorder must be used within MeetingRecorderProvider');
    }
    return ctx;
}
