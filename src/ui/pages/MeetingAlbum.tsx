import React, { useState, useEffect } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import TitleBar from '../components/TitleBar';
import { XIcon } from '../components/icons/AppIcons';
import '../CSS/pages/MeetingAlbum.css';

interface MeetingRecordingSummary {
  id: string;
  title: string;
  started_at: number;
  ended_at: number | null;
  duration_seconds: number | null;
  status: string;
}

interface ProcessingProgress {
  recording_id: string;
  step: string;
  percentage: number;
  estimated_remaining_seconds: number;
}

const MeetingAlbum: React.FC = () => {
  const { setMini } = useOutletContext<{
    setMini: (val: boolean) => void;
  }>();
  const navigate = useNavigate();
  const { send: sendMessage, subscribe } = useWebSocket();

  const [recordings, setRecordings] = useState<MeetingRecordingSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [processingProgress, setProcessingProgress] = useState<Record<string, ProcessingProgress>>({});

  // Subscribe first, then send the initial fetch — avoids a race where the
  // server responds before the listener is installed.
  useEffect(() => {
    const unsubscribe = subscribe((msg) => {
      if (msg.type === 'meeting_recordings_list') {
        setRecordings(msg.content as MeetingRecordingSummary[] || []);
      } else if (msg.type === 'meeting_recording_deleted') {
        const content = msg.content as { recording_id: string };
        setRecordings((prev: MeetingRecordingSummary[]) =>
          prev.filter((r) => r.id !== content.recording_id)
        );
      } else if (msg.type === 'meeting_processing_progress') {
        const progress = msg.content as ProcessingProgress;
        if (progress.step === 'complete') {
          // Processing finished — refresh list
          setProcessingProgress((prev) => {
            const next = { ...prev };
            delete next[progress.recording_id];
            return next;
          });
          sendMessage({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
        } else {
          setProcessingProgress((prev) => ({
            ...prev,
            [progress.recording_id]: progress,
          }));
        }
      }
    });

    sendMessage({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
    return unsubscribe;
  }, [subscribe, sendMessage]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      sendMessage({ type: 'search_meeting_recordings', query: searchQuery });
    } else {
      sendMessage({ type: 'get_meeting_recordings', limit: 50, offset: 0 });
    }
  };

  const handleDelete = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    sendMessage({ type: 'delete_meeting_recording', recording_id: id });
  };

  const formatDate = (timestamp: number) => {
    const d = new Date(timestamp * 1000);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const formatTime = (timestamp: number) => {
    const d = new Date(timestamp * 1000);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const statusBadge = (status: string) => {
    const theme: Record<string, { color: string; background: string }> = {
      recording: {
        color: 'var(--color-red)',
        background: 'var(--color-red-soft)',
      },
      processing: {
        color: 'var(--color-yellow)',
        background: 'var(--color-yellow-soft)',
      },
      ready: {
        color: 'var(--color-green)',
        background: 'var(--color-green-soft)',
      },
      partial: {
        color: 'var(--color-yellow)',
        background: 'var(--color-yellow-soft)',
      },
    };
    const currentTheme = theme[status] ?? {
      color: 'var(--color-text-dim)',
      background: 'var(--color-surface)',
    };

    return (
      <span
        style={{
          fontSize: '0.65rem',
          padding: '2px 6px',
          borderRadius: '4px',
          background: currentTheme.background,
          color: currentTheme.color,
          textTransform: 'uppercase',
          fontWeight: 600,
          letterSpacing: '0.5px',
        }}
      >
        {status}
      </span>
    );
  };

  // Group recordings by date
  const groupedRecordings: { date: string; items: MeetingRecordingSummary[] }[] = [];
  let currentGroup: { date: string; items: MeetingRecordingSummary[] } | null = null;

  for (const rec of recordings) {
    const dateStr = formatDate(rec.started_at);
    if (!currentGroup || currentGroup.date !== dateStr) {
      currentGroup = { date: dateStr, items: [] };
      groupedRecordings.push(currentGroup);
    }
    currentGroup.items.push(rec);
  }

  return (
    <>
      <TitleBar setMini={setMini} />
      <div className="meeting-album-container">
        <div className="meeting-album-search-box-container">
          <form className="meeting-album-search-box-form" onSubmit={handleSearch}>
            <input
              className="meeting-album-search-box-input"
              type="text"
              placeholder="Search recordings..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </form>
        </div>

        {/* <div className="meeting-album-list-title">
          <span>Recordings</span>
        </div> */}

        <div className="meeting-album-list-container">
          {recordings.length === 0 ? (
            <div className="meeting-album-empty-state">
              No meetings recorded yet
            </div>
          ) : (
            groupedRecordings.map((group) => (
              <React.Fragment key={group.date}>
                <div className="meeting-album-date-separator">
                  <span>{group.date}</span>
                </div>
                {group.items.map((rec) => (
                  <div
                    key={rec.id}
                    className="meeting-album-list-item"
                    onClick={() => navigate(`/recording/${rec.id}`)}
                  >
                    <div className="meeting-album-list-item-description">
                      {rec.title || 'Untitled Recording'}
                    </div>
                    <div className="meeting-album-list-item-date-section">
                      {statusBadge(rec.status)}
                      {rec.status === 'processing' && processingProgress[rec.id] && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                          <div style={{
                            flex: 1, height: 4, background: 'var(--color-surface)',
                            borderRadius: 2, overflow: 'hidden', minWidth: 40
                          }}>
                            <div style={{
                              width: `${processingProgress[rec.id].percentage}%`,
                              height: '100%', background: 'var(--color-yellow)',
                              borderRadius: 2, transition: 'width 0.5s ease'
                            }} />
                          </div>
                          <span style={{ fontSize: '0.65rem', color: 'var(--color-text-dim)', whiteSpace: 'nowrap' }}>
                            {processingProgress[rec.id].step}
                          </span>
                        </div>
                      )}
                      <span className="meeting-album-list-item-time">
                        {formatDuration(rec.duration_seconds)} · {formatTime(rec.started_at)}
                      </span>
                      <button
                        type="button"
                        className="meeting-album-delete-btn"
                        onClick={(e) => handleDelete(rec.id, e)}
                        title="Delete recording"
                        aria-label={`Delete ${rec.title || 'recording'}`}
                      >
                        <XIcon size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </React.Fragment>
            ))
          )}
        </div>
      </div>
    </>
  );
};

export default MeetingAlbum;

