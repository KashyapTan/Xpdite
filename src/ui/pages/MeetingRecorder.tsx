import React, { useRef, useEffect } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import { RecordIcon, StopSquareIcon, XIcon } from '../components/icons/AppIcons';
import TitleBar from '../components/TitleBar';
import { ModeSelector } from '../components/input/ModeSelector';
import { useMeetingRecorder } from '../contexts/MeetingRecorderContext';
import regionSSIcon from '../assets/region-screen-shot-icon.svg';
import fullscreenSSIcon from '../assets/entire-screen-shot-icon.svg';
import '../CSS/MeetingRecorder.css';

const MeetingRecorder: React.FC = () => {
    const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
    const navigate = useNavigate();
    const {
        isRecording,
        isRecordingUi,
        isPending,
        pendingAction,
        liveTranscript,
        recordingDuration,
        visualizerBars,
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

    const recordButtonLabel = pendingAction === 'starting'
        ? 'Starting...'
        : pendingAction === 'stopping'
            ? 'Stopping...'
            : isRecordingUi
                ? 'Stop Recording'
                : 'Start Recording';

    const transcriptEmptyState = pendingAction === 'starting'
        ? 'Starting audio capture... transcript will appear here'
        : isRecordingUi
            ? 'Listening... transcript will appear here'
            : 'Press Start Recording to begin';

    const transcriptStatus = pendingAction === 'starting'
        ? 'Starting...'
        : pendingAction === 'stopping'
            ? 'Stopping...'
            : isRecordingUi
                ? 'Live'
                : 'Standby';

    return (
        <div className="meeting-recorder-container">
            <TitleBar setMini={setMini} />

            <div className="meeting-recorder-content">
                {error && (
                    <div className="meeting-recorder-error" role="alert" onClick={clearError}>
                        {error}
                        <XIcon size={14} className="meeting-recorder-error-dismiss" />
                    </div>
                )}

                <section className="meeting-recorder-control-panel">
                    <div className="meeting-recorder-controls">
                        <button
                            className={`meeting-record-btn ${isRecordingUi ? 'recording' : ''}`}
                            onClick={isRecordingUi ? stopRecording : startRecording}
                            disabled={isPending}
                            aria-busy={isPending}
                        >
                            <span className="meeting-record-btn-icon">
                                {isRecording || pendingAction === 'stopping'
                                    ? <StopSquareIcon size={10} />
                                    : <RecordIcon size={12} />}
                            </span>
                            <span className="meeting-record-btn-label">{recordButtonLabel}</span>
                        </button>
                    </div>

                    <div className={`meeting-recorder-visualizer ${isRecordingUi ? 'active' : ''}`} aria-hidden="true">
                        {visualizerBars.map((level, index) => (
                            <span
                                key={index}
                                className="meeting-recorder-visualizer-bar"
                                style={{ '--bar-scale': level } as React.CSSProperties}
                            />
                        ))}
                    </div>
                </section>

                <section className="meeting-recorder-transcript-panel">
                    <div className="meeting-recorder-transcript-topbar">
                        <div className="meeting-recorder-transcript-heading-row">
                            <div className="meeting-recorder-transcript-header">Live Transcript</div>
                            <div className="meeting-recorder-transcript-badge">{transcriptStatus}</div>
                        </div>

                        <div className="meeting-recorder-meta-row">
                            <div className={`meeting-recorder-timer${isRecordingUi ? ' live' : ''}`}>
                                <span className={`meeting-recorder-pulse${isRecording ? ' active' : ''}`} />
                                {formatDuration(recordingDuration)}
                            </div>
                        </div>
                    </div>

                    <div
                        className="meeting-recorder-transcript"
                        ref={transcriptContainerRef}
                        onScroll={handleScroll}
                    >
                        {liveTranscript.length === 0 ? (
                            <div className="meeting-recorder-empty">{transcriptEmptyState}</div>
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
                </section>
            </div>

            <ModeSelector
                captureMode="none"
                meetingRecordingMode={true}
                onFullscreenMode={() => navigate('/', { state: { selectedCaptureMode: 'fullscreen' } })}
                onPrecisionMode={() => navigate('/', { state: { selectedCaptureMode: 'precision' } })}
                onMeetingMode={() => { /* already on recorder */ }}
                regionSSIcon={regionSSIcon}
                fullscreenSSIcon={fullscreenSSIcon}
            />
        </div>
    );
};

export default MeetingRecorder;
