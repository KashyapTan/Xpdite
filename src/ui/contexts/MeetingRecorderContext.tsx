/**
 * MeetingRecorderContext.
 *
 * Global React context that persists recording state across route changes.
 * Wraps the app so the recording indicator is visible on all pages.
 */
import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { useAudioCapture } from '../hooks/useAudioCapture';

// ---- Types ----

export interface TranscriptChunk {
    text: string;
    start_time: number;
    end_time: number;
}

interface MeetingRecorderState {
    isRecording: boolean;
    recordingId: string | null;
    liveTranscript: TranscriptChunk[];
    recordingDuration: number;
    startedAt: number | null;
}

interface MeetingRecorderActions {
    startRecording: () => Promise<void>;
    stopRecording: () => Promise<void>;
    clearTranscript: () => void;
}

type MeetingRecorderContextValue = MeetingRecorderState & MeetingRecorderActions;

const MeetingRecorderContext = createContext<MeetingRecorderContextValue | null>(null);

// ---- Provider ----

interface ProviderProps {
    children: React.ReactNode;
}

export const MeetingRecorderProvider: React.FC<ProviderProps> = ({ children }) => {
    // Use the global WS send function exposed by App.tsx
    const getSendMessage = useCallback(() => {
        return (window as any).__xpditeWsSend as ((msg: Record<string, unknown>) => void) | undefined;
    }, []);
    const [isRecording, setIsRecording] = useState(false);
    const [recordingId, setRecordingId] = useState<string | null>(null);
    const [liveTranscript, setLiveTranscript] = useState<TranscriptChunk[]>([]);
    const [recordingDuration, setRecordingDuration] = useState(0);
    const [startedAt, setStartedAt] = useState<number | null>(null);

    const durationIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const sendMessage = useCallback((msg: Record<string, unknown>) => {
        const fn = getSendMessage();
        if (fn) fn(msg);
    }, [getSendMessage]);

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
        if (isRecording) return;

        try {
            // Start audio capture first
            await startCapture();

            // Tell backend to start recording
            sendMessage({ type: 'meeting_start_recording' });
        } catch (err) {
            console.error('Failed to start recording:', err);
            stopCapture();
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

    // Expose handlers via ref so WebSocket handler can call them
    const handlersRef = useRef({ handleRecordingStarted, handleRecordingStopped, handleTranscriptChunk });
    handlersRef.current = { handleRecordingStarted, handleRecordingStopped, handleTranscriptChunk };

    // Register a global handler for meeting WS messages
    useEffect(() => {
        (window as any).__meetingRecorderHandlers = handlersRef.current;
        return () => {
            delete (window as any).__meetingRecorderHandlers;
        };
    }, []);

    return (
        <MeetingRecorderContext.Provider
            value={{
                isRecording,
                recordingId,
                liveTranscript,
                recordingDuration,
                startedAt,
                startRecording,
                stopRecording,
                clearTranscript,
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
