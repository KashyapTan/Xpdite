import type { YouTubeTranscriptionApprovalBlock } from '../../types';

interface InlineYouTubeApprovalBlockProps {
  approval: YouTubeTranscriptionApprovalBlock;
  onRespond?: (requestId: string, approved: boolean) => void;
}

export function InlineYouTubeApprovalBlock({
  approval,
  onRespond,
}: InlineYouTubeApprovalBlockProps) {
  const {
    requestId,
    title,
    channel,
    duration,
    url,
    noCaptionsReason,
    audioSizeEstimate,
    downloadTimeEstimate,
    transcriptionTimeEstimate,
    totalTimeEstimate,
    whisperModel,
    computeBackend,
    playlistNote,
    status,
  } = approval;

  return (
    <div className={`youtube-inline-approval status-${status}`}>
      <div className="youtube-inline-approval-header">
        <span className="youtube-inline-approval-badge">YOUTUBE</span>
        <span className="youtube-inline-approval-title">Fallback transcription approval</span>
      </div>

      <div className="youtube-inline-approval-total-label">Estimated total time</div>
      <div className="youtube-inline-approval-total-value">{totalTimeEstimate}</div>

      <div className="youtube-inline-approval-grid">
        <div><span>Title:</span> {title}</div>
        <div><span>Channel:</span> {channel}</div>
        <div><span>Duration:</span> {duration}</div>
        <div><span>Audio size:</span> {audioSizeEstimate}</div>
        <div><span>Download:</span> {downloadTimeEstimate}</div>
        <div><span>Transcription:</span> {transcriptionTimeEstimate}</div>
        <div><span>Model:</span> {whisperModel}</div>
        <div><span>Backend:</span> {computeBackend}</div>
      </div>

      {playlistNote && (
        <div className="youtube-inline-approval-note">{playlistNote}</div>
      )}

      <div className="youtube-inline-approval-reason">{noCaptionsReason}</div>

      <a
        className="youtube-inline-approval-link"
        href={url}
        target="_blank"
        rel="noreferrer"
      >
        {url}
      </a>

      {status === 'pending' && onRespond && (
        <div className="youtube-inline-approval-actions">
          <button
            className="btn-deny"
            onClick={() => onRespond(requestId, false)}
          >
            Deny
          </button>
          <button
            className="btn-allow"
            onClick={() => onRespond(requestId, true)}
          >
            Allow
          </button>
        </div>
      )}

      {status === 'approved' && (
        <div className="youtube-inline-approval-status approved">
          Approved. Starting transcription...
        </div>
      )}

      {status === 'denied' && (
        <div className="youtube-inline-approval-status denied">
          Denied. Transcription fallback was not run.
        </div>
      )}
    </div>
  );
}

