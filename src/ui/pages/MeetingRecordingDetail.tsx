import React, { useState, useEffect } from 'react';
import { useOutletContext, useParams } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import { api } from '../services/api';
import {
    CalendarIcon,
    CheckIcon,
    ClipboardListIcon,
    HourglassIcon,
    MailIcon,
    RecordIcon,
    XIcon,
} from '../components/icons/AppIcons';
import TitleBar from '../components/TitleBar';
import '../CSS/pages/MeetingRecordingDetail.css';

interface MeetingRecording {
    id: string;
    title: string;
    started_at: number;
    ended_at: number | null;
    duration_seconds: number | null;
    status: string;
    tier1_transcript: string;
    tier2_transcript_json: string | Tier2Segment[] | null;
    ai_summary: string | null;
    ai_actions_json: string | ActionSuggestion[] | null;
    ai_title_generated: boolean;
}

interface ProcessingProgress {
    recording_id: string;
    step: string;
    percentage: number;
    estimated_remaining_seconds: number;
}

interface Tier2Segment {
    start: number;
    end: number;
    text: string;
    speaker?: string;
}

interface ActionSuggestion {
    type: 'calendar_event' | 'email' | 'task';
    title?: string;
    date?: string;
    time?: string;
    duration_minutes?: number;
    description?: string;
    to?: string;
    subject?: string;
    body?: string;
    assignee?: string;
    due_date?: string;
}

const MeetingRecordingDetail: React.FC = () => {
    const { setMini } = useOutletContext<{
        setMini: (val: boolean) => void;
    }>();
    const { id } = useParams<{ id: string }>();
    const { send: sendMessage, subscribe } = useWebSocket();

    const [recording, setRecording] = useState<MeetingRecording | null>(null);
    const [loading, setLoading] = useState(true);
    const [processingProgress, setProcessingProgress] = useState<ProcessingProgress | null>(null);

    // AI Analysis state
    const [analyzing, setAnalyzing] = useState(false);
    const [analysisError, setAnalysisError] = useState<string | null>(null);
    const [aiSummary, setAiSummary] = useState<string | null>(null);
    const [aiActions, setAiActions] = useState<ActionSuggestion[]>([]);
    const [editingActions, setEditingActions] = useState<Record<number, ActionSuggestion>>({});
    const [actionResults, setActionResults] = useState<Record<number, { success: boolean; result: string }>>({});

    // Model selection state
    const [enabledModels, setEnabledModels] = useState<string[]>([]);
    const [selectedModel, setSelectedModel] = useState<string>('');

    // Load recording detail
    useEffect(() => {
        if (id) {
            sendMessage({ type: 'load_meeting_recording', recording_id: id });
        }

        // Fetch enabled models for the analysis model picker
        api.getEnabledModels().then((models) => {
            setEnabledModels(models);
            if (models.length > 0) setSelectedModel(models[0]);
        });

        return subscribe((msg) => {
            if (msg.type === 'meeting_recording_loaded' && msg.content) {
                const rec = msg.content as MeetingRecording;
                setRecording(rec);
                setLoading(false);
                // Restore existing analysis
                if (rec.ai_summary) setAiSummary(rec.ai_summary);
                if (rec.ai_actions_json) {
                    try {
                        const actions = typeof rec.ai_actions_json === 'string'
                            ? JSON.parse(rec.ai_actions_json)
                            : rec.ai_actions_json;
                        if (Array.isArray(actions)) setAiActions(actions);
                    } catch { /* ignore */ }
                }
            } else if (msg.type === 'meeting_processing_progress') {
                const progress = msg.content as ProcessingProgress;
                if (progress.recording_id === id) {
                    if (progress.step === 'complete') {
                        setProcessingProgress(null);
                        sendMessage({ type: 'load_meeting_recording', recording_id: id });
                    } else {
                        setProcessingProgress(progress);
                    }
                }
            } else if (msg.type === 'meeting_analysis_started') {
                const content = msg.content as { recording_id?: string } | null;
                if (content?.recording_id === id) setAnalyzing(true);
            } else if (msg.type === 'meeting_analysis_complete') {
                const content = msg.content as { recording_id?: string; summary?: string; actions?: ActionSuggestion[] } | null;
                if (content?.recording_id === id) {
                    setAnalyzing(false);
                    setAnalysisError(null);
                    setAiSummary(content.summary || null);
                    setAiActions(content.actions || []);
                }
            } else if (msg.type === 'meeting_analysis_error') {
                const content = msg.content as { recording_id?: string; error?: string } | null;
                if (content?.recording_id === id) {
                    setAnalyzing(false);
                    setAnalysisError(content.error || 'Unknown error');
                }
            } else if (msg.type === 'meeting_action_result') {
                const content = msg.content as { recording_id?: string; action_index?: number; success: boolean; result: string } | null;
                if (content?.recording_id === id) {
                    const idx = content.action_index ?? 0;
                    setActionResults((prev) => ({
                        ...prev,
                        [idx]: {
                            success: content.success,
                            result: content.result,
                        },
                    }));
                }
            }
        });
    }, [sendMessage, subscribe, id]);

    const handleSummarize = () => {
        if (!id) return;
        setAnalyzing(true);
        setAnalysisError(null);
        sendMessage({
            type: 'meeting_generate_analysis',
            recording_id: id,
            model: selectedModel || undefined,
        });
    };

    const handleExecuteAction = (idx: number) => {
        if (!id) return;
        const action = editingActions[idx] || aiActions[idx];
        sendMessage({ type: 'meeting_execute_action', recording_id: id, action, action_index: idx });
    };

    const updateActionField = (idx: number, field: string, value: string | number) => {
        const current = editingActions[idx] || { ...aiActions[idx] };
        setEditingActions((prev) => ({
            ...prev,
            [idx]: { ...current, [field]: value },
        }));
    };

    // --- Formatting helpers ---
    const formatDate = (ts: number) =>
        new Date(ts * 1000).toLocaleString('en-US', {
            weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });

    const formatDuration = (seconds: number | null) => {
        if (!seconds) return '--:--';
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    const formatTimestamp = (seconds: number) => {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    const statusColor: Record<string, string> = {
        recording: 'var(--color-red)',
        processing: 'var(--color-yellow)',
        ready: 'var(--color-green)',
        partial: 'var(--color-yellow)',
    };

    // --- Tier 2 transcript ---
    const getTier2Segments = (): Tier2Segment[] => {
        if (!recording?.tier2_transcript_json) return [];
        try {
            const data = typeof recording.tier2_transcript_json === 'string'
                ? JSON.parse(recording.tier2_transcript_json)
                : recording.tier2_transcript_json;
            return Array.isArray(data) ? data : [];
        } catch { return []; }
    };

    const tier2Segments = recording ? getTier2Segments() : [];
    const hasTier2 = tier2Segments.length > 0;

    const groupedSegments: { speaker: string; segments: Tier2Segment[] }[] = [];
    for (const seg of tier2Segments) {
        const speaker = seg.speaker || 'Unknown';
        const lastGroup = groupedSegments[groupedSegments.length - 1];
        if (lastGroup && lastGroup.speaker === speaker) lastGroup.segments.push(seg);
        else groupedSegments.push({ speaker, segments: [seg] });
    }

    const speakerColors: Record<string, string> = {};
    const palette = [
        'var(--color-text)',
        'var(--color-text-muted)',
        'var(--color-yellow)',
        'var(--color-green)',
        'var(--color-red)',
        'var(--color-terminal-ansi-cyan)',
        'var(--color-text)',
    ];
    let colorIdx = 0;
    for (const group of groupedSegments) {
        if (!(group.speaker in speakerColors)) {
            speakerColors[group.speaker] = palette[colorIdx % palette.length];
            colorIdx++;
        }
    }

    const canAnalyze = recording && (recording.status === 'ready' || recording.status === 'partial');

    // --- Action card rendering ---
    const renderActionCard = (action: ActionSuggestion, idx: number) => {
        const edited = editingActions[idx] || action;
        const result = actionResults[idx];
        const typeTheme = action.type === 'calendar_event'
            ? {
                label: 'Calendar Event',
                Icon: CalendarIcon,
                color: 'var(--color-text)',
                background: 'var(--color-surface-strong)',
            }
            : action.type === 'email'
                ? {
                    label: 'Email Draft',
                    Icon: MailIcon,
                    color: 'var(--color-yellow)',
                    background: 'var(--color-yellow-soft)',
                }
                : {
                    label: 'Task',
                    Icon: ClipboardListIcon,
                    color: 'var(--color-green)',
                    background: 'var(--color-green-soft)',
                };
        const canExecute = action.type === 'calendar_event' || action.type === 'email';

        return (
            <div key={idx} className="meeting-action-card" style={{ borderLeftColor: typeTheme.color }}>
                <div className="meeting-action-card-header">
                    <span className="meeting-action-type" style={{ color: typeTheme.color }}>
                        <typeTheme.Icon size={14} className="meeting-action-type-icon" />
                        <span>{typeTheme.label}</span>
                    </span>
                    {result && (
                        <span className={`meeting-action-result ${result.success ? 'success' : 'error'}`}>
                            {result.success
                                ? <CheckIcon size={12} className="meeting-action-result-icon" />
                                : <XIcon size={12} className="meeting-action-result-icon" />}
                            <span>{result.success ? 'Done' : 'Failed'}</span>
                        </span>
                    )}
                </div>

                {action.type === 'calendar_event' && (
                    <div className="meeting-action-fields">
                        <label>Title</label>
                        <input value={edited.title || ''} onChange={(e) => updateActionField(idx, 'title', e.target.value)} />
                        <div className="meeting-action-row">
                            <div>
                                <label>Date</label>
                                <input type="date" value={edited.date || ''} onChange={(e) => updateActionField(idx, 'date', e.target.value)} />
                            </div>
                            <div>
                                <label>Time</label>
                                <input type="time" value={edited.time || ''} onChange={(e) => updateActionField(idx, 'time', e.target.value)} />
                            </div>
                            <div>
                                <label>Duration (min)</label>
                                <input type="number" value={edited.duration_minutes || 30} onChange={(e) => updateActionField(idx, 'duration_minutes', parseInt(e.target.value))} />
                            </div>
                        </div>
                        <label>Description</label>
                        <textarea value={edited.description || ''} onChange={(e) => updateActionField(idx, 'description', e.target.value)} rows={2} />
                    </div>
                )}

                {action.type === 'email' && (
                    <div className="meeting-action-fields">
                        <label>To</label>
                        <input value={edited.to || ''} onChange={(e) => updateActionField(idx, 'to', e.target.value)} />
                        <label>Subject</label>
                        <input value={edited.subject || ''} onChange={(e) => updateActionField(idx, 'subject', e.target.value)} />
                        <label>Body</label>
                        <textarea value={edited.body || ''} onChange={(e) => updateActionField(idx, 'body', e.target.value)} rows={3} />
                    </div>
                )}

                {action.type === 'task' && (
                    <div className="meeting-action-fields">
                        <label>Description</label>
                        <div className="meeting-action-readonly">{action.description}</div>
                        {action.assignee && <><label>Assignee</label><div className="meeting-action-readonly">{action.assignee}</div></>}
                        {action.due_date && <><label>Due Date</label><div className="meeting-action-readonly">{action.due_date}</div></>}
                    </div>
                )}

                {canExecute && !result?.success && (
                    <button className="meeting-action-execute" style={{ background: typeTheme.background, color: typeTheme.color }}
                        onClick={() => handleExecuteAction(idx)}>
                        {action.type === 'calendar_event' ? 'Create Event' : 'Create Draft'}
                    </button>
                )}
            </div>
        );
    };

    return (
        <>
            <TitleBar setMini={setMini} />
            <div className="meeting-detail-content">
                {/* <button className="meeting-detail-back" onClick={() => navigate('/album')}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M19 12H5" />
                        <path d="M12 19l-7-7 7-7" />
                    </svg>
                </button> */}

                {loading ? (
                    <div className="meeting-detail-loading">Loading...</div>
                ) : recording ? (
                    <>
                        {/* Header */}
                        <div className="meeting-detail-header">
                            <h2 className="meeting-detail-title">{recording.title || 'Untitled Recording'}</h2>
                            <div className="meeting-detail-meta">
                                <span className="meeting-detail-status" style={{ color: statusColor[recording.status] || 'var(--color-text-dim)' }}>
                                    {recording.status.toUpperCase()}
                                </span>
                                <span className="meeting-detail-date">{formatDate(recording.started_at)}</span>
                                <span className="meeting-detail-duration">Duration: {formatDuration(recording.duration_seconds)}</span>
                            </div>
                        </div>

                        {/* Status Banners */}
                        {recording.status === 'recording' && (
                            <div className="meeting-detail-banner recording">
                                <RecordIcon size={12} className="meeting-detail-banner-icon" />
                                <span>Recording in progress</span>
                            </div>
                        )}
                        {recording.status === 'processing' && (
                            <div className="meeting-detail-banner processing">
                                <div className="meeting-detail-banner-processing-header" style={{ marginBottom: 6 }}>
                                    <span className="meeting-detail-banner-label">
                                        <HourglassIcon size={14} className="meeting-detail-banner-icon" />
                                        <span>Processing — {processingProgress?.step || 'starting'}...</span>
                                    </span>
                                    <span style={{ fontSize: '0.8em', opacity: 0.7 }}>
                                        {processingProgress ? `${Math.round(processingProgress.percentage)}%` : ''}
                                    </span>
                                </div>
                                <div style={{ width: '100%', height: 4, background: 'var(--color-surface)', borderRadius: 2, overflow: 'hidden' }}>
                                    <div style={{
                                        width: `${processingProgress?.percentage || 0}%`,
                                        height: '100%', background: 'var(--color-yellow)', borderRadius: 2, transition: 'width 0.5s ease'
                                    }} />
                                </div>
                            </div>
                        )}
                        {recording.status === 'partial' && !hasTier2 && (
                            <div className="meeting-detail-banner partial">
                                Live transcript available. Post-processing will generate a higher quality version.
                            </div>
                        )}

                        {/* Transcript */}
                        <div className="meeting-detail-section">
                            <h3 className="meeting-detail-section-title">
                                Transcript
                                {hasTier2 && <span style={{ fontSize: '0.7em', marginLeft: 8, color: 'var(--color-text-dim)' }}>Enhanced</span>}
                            </h3>
                            <div className="meeting-detail-transcript">
                                {hasTier2 ? (
                                    <div className="meeting-detail-tier2-transcript">
                                        {groupedSegments.map((group, gi) => (
                                            <div key={gi} className="meeting-detail-speaker-block">
                                                <div className="meeting-detail-speaker-label" style={{ color: speakerColors[group.speaker] }}>
                                                    {group.speaker}
                                                    <span className="meeting-detail-speaker-time">{formatTimestamp(group.segments[0].start)}</span>
                                                </div>
                                                <div className="meeting-detail-speaker-text">{group.segments.map((seg) => seg.text).join(' ')}</div>
                                            </div>
                                        ))}
                                    </div>
                                ) : recording.tier1_transcript ? (
                                    <pre className="meeting-detail-transcript-text">{recording.tier1_transcript}</pre>
                                ) : (
                                    <div className="meeting-detail-empty">No transcript available</div>
                                )}
                            </div>
                        </div>

                        {/* AI Analysis */}
                        <div className="meeting-detail-section">
                            <h3 className="meeting-detail-section-title">Xpdite Analysis</h3>

                            {!aiSummary && !analyzing && canAnalyze && (
                                <div className="meeting-detail-analysis-prompt">
                                    <select
                                        className="meeting-detail-model-select"
                                        value={selectedModel}
                                        onChange={(e) => setSelectedModel(e.target.value)}
                                    >
                                        {enabledModels.length === 0 && (
                                            <option value="" disabled>No models enabled</option>
                                        )}
                                        {enabledModels.map((modelName) => (
                                            <option key={modelName} value={modelName}>{modelName}</option>
                                        ))}
                                    </select>
                                    <button className="meeting-detail-summarize-btn" onClick={handleSummarize} disabled={analyzing || !selectedModel}>
                                        Summarize Recording
                                    </button>
                                    {!hasTier2 && recording.tier1_transcript && (
                                        <span className="meeting-detail-analysis-note">Based on live transcript (may be less accurate)</span>
                                    )}
                                </div>
                            )}

                            {analyzing && (
                                <div className="meeting-detail-analysis-loading">
                                    <div className="meeting-detail-spinner" />
                                    <span>Analyzing transcript...</span>
                                </div>
                            )}

                            {analysisError && (
                                <div className="meeting-detail-banner" style={{ background: 'var(--color-red-soft)', color: 'var(--color-red)', border: '1px solid var(--color-red-soft)' }}>
                                    Analysis failed: {analysisError}
                                    <button className="meeting-detail-retry-btn" onClick={handleSummarize}>Retry</button>
                                </div>
                            )}

                            {aiSummary && (
                                <>
                                    <div className="meeting-detail-ai-summary">{aiSummary}</div>

                                    {aiActions.length > 0 && (
                                        <div className="meeting-detail-actions">
                                            <h4 className="meeting-detail-actions-title">Suggested Actions</h4>
                                            {aiActions.map((action, idx) => renderActionCard(action, idx))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </>
                ) : (
                    <div className="meeting-detail-loading">Recording not found</div>
                )}
            </div>
        </>
    );
};

export default MeetingRecordingDetail;

