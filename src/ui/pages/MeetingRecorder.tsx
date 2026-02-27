import React, { useRef, useEffect } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import { ModeSelector } from '../components/input/ModeSelector';
import { useMeetingRecorder } from '../contexts/MeetingRecorderContext';
import regionSSIcon from '../assets/region-screen-shot-icon.svg';
import fullscreenSSIcon from '../assets/entire-screen-shot-icon.svg';
import meetingRecordingIcon from '../assets/meeting-record-icon.svg';
import '../CSS/MeetingRecorder.css';

const MeetingRecorder: React.FC = () => {
    const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
    const navigate = useNavigate();
    const {
        isRecording,
        liveTranscript,
        recordingDuration,
        startRecording,
        stopRecording,
        error,
        clearError,
    } = useMeetingRecorder();

    const transcriptEndRef = useRef<HTMLDivElement>(null);
    const transcriptContainerRef = useRef<HTMLDivElement>(null);
    const userScrolledRef = useRef(false);

    // Auto-scroll transcript unless user scrolled up
    useEffect(() => {
        if (!userScrolledRef.current && transcriptEndRef.current) {
            transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [liveTranscript]);

    const handleScroll = () => {
        if (!transcriptContainerRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = transcriptContainerRef.current;
        userScrolledRef.current = scrollHeight - scrollTop - clientHeight > 50;
    };

    const formatDuration = (seconds: number) => {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    };

    return (
        <div className="meeting-recorder-container">
            <TitleBar onClearContext={() => { }} setMini={setMini} />

            <div className="meeting-recorder-content">
                {/* Recording Control */}
                <div className="meeting-recorder-controls">
                    {error && (
                        <div className="meeting-recorder-error" role="alert" onClick={clearError}>
                            {error}
                            <span className="meeting-recorder-error-dismiss">×</span>
                        </div>
                    )}
                    <button
                        className={`meeting-record-btn ${isRecording ? 'recording' : ''}`}
                        onClick={isRecording ? stopRecording : startRecording}
                    >
                        <span className="meeting-record-btn-icon">
                            {isRecording ? '■' : '●'}
                        </span>
                        <span className="meeting-record-btn-label">
                            {isRecording ? 'Stop Recording' : 'Start Recording'}
                        </span>
                    </button>

                    {isRecording && (
                        <div className="meeting-recorder-timer">
                            <span className="meeting-recorder-pulse" />
                            {formatDuration(recordingDuration)}
                        </div>
                    )}
                </div>

                {/* Live Transcript */}
                <div className="meeting-recorder-transcript-header">Live Transcript</div>
                <div
                    className="meeting-recorder-transcript"
                    ref={transcriptContainerRef}
                    onScroll={handleScroll}
                >
                    {liveTranscript.length === 0 ? (
                        <div className="meeting-recorder-empty">
                            {isRecording
                                ? 'Listening... transcript will appear here'
                                : 'Press Start Recording to begin'}
                        </div>
                    ) : (
                        liveTranscript.map((chunk, i) => (
                            <div key={i} className="meeting-transcript-chunk">
                                <span className="meeting-transcript-time">
                                    [{formatDuration(Math.floor(chunk.start_time))}]
                                </span>
                                <span className="meeting-transcript-text">{chunk.text}</span>
                            </div>
                        ))
                    )}
                    <div ref={transcriptEndRef} />
                </div>
            </div>

            <ModeSelector
                captureMode="none"
                meetingRecordingMode={true}
                onFullscreenMode={() => navigate('/')}
                onPrecisionMode={() => navigate('/')}
                onMeetingMode={() => { /* already on recorder */ }}
                regionSSIcon={regionSSIcon}
                fullscreenSSIcon={fullscreenSSIcon}
                meetingRecordingIcon={meetingRecordingIcon}
            />
        </div>
    );
};

export default MeetingRecorder;
