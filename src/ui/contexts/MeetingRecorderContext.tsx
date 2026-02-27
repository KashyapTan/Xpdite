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

export interface TranscriptChunk {
    text: string;
    start_time: number;
    end_time: number;
}

interface MeetingRecorderState {
    isRecording: boolean;
    isPending: boolean;
    recordingId: string | null;
    liveTranscript: TranscriptChunk[];
    recordingDuration: number;
    startedAt: number | null;
    error: string | null;
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
    const isPendingRef = useRef(false);
    const [recordingId, setRecordingId] = useState<string | null>(null);
    const [liveTranscript, setLiveTranscript] = useState<TranscriptChunk[]>([]);
    const [recordingDuration, setRecordingDuration] = useState(0);
    const [startedAt, setStartedAt] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);

    const durationIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const sendMessage = useCallback((msg: Record<string, unknown>) => {
        wsSend(msg);
    }, [wsSend]);

    const { startCapture, stopCapture } = useAudioCapture(sendMessage);

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

    const startRecording = useCallback(async () => {
        if (isRecording || isPendingRef.current) return;
        setError(null);
        isPendingRef.current = true;

        try {
            // Start audio capture first
            await startCapture();

            // Tell backend to start recording
            sendMessage({ type: 'meeting_start_recording' });
        } catch (err) {
            console.error('Failed to start recording:', err);
            const message = err instanceof Error ? err.message : 'Failed to start audio capture';
            setError(message);
            stopCapture();
        } finally {
            isPendingRef.current = false;
        }
    }, [isRecording, startCapture, sendMessage, stopCapture]);

    const stopRecording = useCallback(async () => {
        if (!isRecording) return;

        // Stop audio capture
        stopCapture();

        // Tell backend to stop recording
        sendMessage({ type: 'meeting_stop_recording' });
    }, [isRecording, stopCapture, sendMessage]);

    const clearTranscript = useCallback(() => {
        setLiveTranscript([]);
    }, []);

    const clearError = useCallback(() => {
        setError(null);
    }, []);

    // Handle incoming WS messages for recording state
    // This will be called from the parent component that manages WS
    const handleRecordingStarted = useCallback((data: { recording_id: string; started_at: number }) => {
        setIsRecording(true);
        setRecordingId(data.recording_id);
        setStartedAt(data.started_at);
        setRecordingDuration(0);
        setLiveTranscript([]);
    }, []);

    const handleRecordingStopped = useCallback(() => {
        setIsRecording(false);
        setRecordingId(null);
        setStartedAt(null);
        if (durationIntervalRef.current) {
            clearInterval(durationIntervalRef.current);
            durationIntervalRef.current = null;
        }
    }, []);

    const handleTranscriptChunk = useCallback((chunk: TranscriptChunk) => {
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
                    setError(typeof content === 'object' && content !== null && 'error' in content
                        ? String((content as { error: string }).error)
                        : 'Recording error');
                    break;
                default:
                    break;
            }
        });
    }, [subscribe]);

    return (
        <MeetingRecorderContext.Provider
            value={{
                isRecording,
                isPending: isPendingRef.current,
                recordingId,
                liveTranscript,
                recordingDuration,
                startedAt,
                error,
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

export function useMeetingRecorder(): MeetingRecorderContextValue {
    const ctx = useContext(MeetingRecorderContext);
    if (!ctx) {
        throw new Error('useMeetingRecorder must be used within MeetingRecorderProvider');
    }
    return ctx;
}
