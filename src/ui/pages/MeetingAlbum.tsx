import React, { useState, useEffect } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import TitleBar from '../components/TitleBar';
import '../CSS/ChatHistory.css'; // Reuse chat history styles

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
    const colors: Record<string, string> = {
      recording: '#ff5050',
      processing: '#ffaa00',
      ready: '#50cc50',
      partial: '#6699ff',
    };
    return (
      <span
        style={{
          fontSize: '0.65rem',
          padding: '2px 6px',
          borderRadius: '4px',
          background: `${colors[status] || '#888'}22`,
          color: colors[status] || '#888',
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
    <div style={{ padding: '2rem', width: '100%', height: '100%', position: 'relative' }}>
      <TitleBar onClearContext={() => { }} setMini={setMini} />

      <div className="chat-history-container">
        <div className="chat-history-search-box-container">
          <form className="chat-history-search-box-form" onSubmit={handleSearch}>
            <input
              className="chat-history-search-box-input"
              type="text"
              placeholder="Search recordings..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </form>
        </div>

        <div className="chat-history-list-title">
          <span>Recordings</span>
        </div>

        <div className="chat-history-list-container">
          {recordings.length === 0 ? (
            <div className="chat-history-empty-state">
              No meetings recorded yet
            </div>
          ) : (
            groupedRecordings.map((group) => (
              <React.Fragment key={group.date}>
                <div className="chat-history-date-separator">
                  <span>{group.date}</span>
                </div>
                {group.items.map((rec) => (
                  <div
                    key={rec.id}
                    className="chat-history-list-item"
                    onClick={() => navigate(`/recording/${rec.id}`)}
                  >
                    <div className="chat-history-list-item-description">
                      {rec.title || 'Untitled Recording'}
                    </div>
                    <div className="chat-history-list-item-date-section">
                      {statusBadge(rec.status)}
                      {rec.status === 'processing' && processingProgress[rec.id] && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                          <div style={{
                            flex: 1, height: 4, background: 'rgba(255,255,255,0.08)',
                            borderRadius: 2, overflow: 'hidden', minWidth: 40
                          }}>
                            <div style={{
                              width: `${processingProgress[rec.id].percentage}%`,
                              height: '100%', background: '#ffaa00',
                              borderRadius: 2, transition: 'width 0.5s ease'
                            }} />
                          </div>
                          <span style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap' }}>
                            {processingProgress[rec.id].step}
                          </span>
                        </div>
                      )}
                      <span className="chat-history-list-item-time">
                        {formatDuration(rec.duration_seconds)} · {formatTime(rec.started_at)}
                      </span>
                      <button
                        className="chat-history-delete-btn"
                        onClick={(e) => handleDelete(rec.id, e)}
                        title="Delete recording"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                ))}
              </React.Fragment>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default MeetingAlbum;
