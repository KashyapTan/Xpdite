import { useEffect, useMemo, useRef, useState } from 'react';
import type { ArtifactBlockData } from '../../types';
import { ArtifactModal } from '../ArtifactModal';
import '../../CSS/InlineArtifact.css';

function countLines(content?: string): number {
  if (!content) {
    return 0;
  }

  return content.split('\n').length;
}

function measureBytes(content?: string): number {
  if (!content) {
    return 0;
  }

  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(content).length;
  }

  return content.length;
}

function formatBytes(sizeBytes: number): string {
  if (!sizeBytes) {
    return '0 B';
  }

  const units = ['B', 'KB', 'MB', 'GB'];
  let value = sizeBytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

interface InlineArtifactBlockProps {
  artifact: ArtifactBlockData;
  onArtifactUpdated?: (artifact: ArtifactBlockData) => void;
  onArtifactDeleted?: (artifactId: string) => void;
}

export function InlineArtifactBlock({
  artifact,
  onArtifactUpdated,
  onArtifactDeleted,
}: InlineArtifactBlockProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [localArtifact, setLocalArtifact] = useState(artifact);
  const previewRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    setLocalArtifact(artifact);
  }, [artifact]);

  useEffect(() => {
    if (!previewRef.current || localArtifact.status !== 'streaming') {
      return;
    }

    previewRef.current.scrollTop = previewRef.current.scrollHeight;
  }, [localArtifact.content, localArtifact.status]);

  const isReady = localArtifact.status === 'ready';
  const isDeleted = localArtifact.status === 'deleted';
  const isStreaming = localArtifact.status === 'streaming';
  const artifactContent = localArtifact.content ?? '';
  const displaySizeBytes = localArtifact.sizeBytes || measureBytes(artifactContent);
  const displayLineCount = localArtifact.lineCount || countLines(artifactContent);
  const hasPreview = !isDeleted && artifactContent.length > 0;
  const previewLabel = useMemo(() => {
    if (isStreaming) {
      return 'Live content';
    }
    if (localArtifact.artifactType === 'html') {
      return 'HTML source';
    }
    if (localArtifact.artifactType === 'markdown') {
      return 'Markdown source';
    }
    return 'Source preview';
  }, [isStreaming, localArtifact.artifactType]);
  const statusLabel = `${localArtifact.status.slice(0, 1).toUpperCase()}${localArtifact.status.slice(1)}`;
  const canOpen = isReady;

  const cardContent = (
    <>
      <div className="inline-artifact-card-header">
        <div>
          <div className="inline-artifact-card-title">{localArtifact.title}</div>
          <div className="inline-artifact-card-meta">
            <span>{localArtifact.artifactType}</span>
            {localArtifact.language ? <span>{localArtifact.language}</span> : null}
            {!isDeleted ? <span>{formatBytes(displaySizeBytes)}</span> : null}
            {!isDeleted ? <span>{displayLineCount} lines</span> : null}
            <span className={`inline-artifact-status inline-artifact-status-${localArtifact.status}`}>
              {statusLabel}
            </span>
          </div>
        </div>
      </div>

      {hasPreview ? (
        <div className="inline-artifact-preview-shell">
          <div className="inline-artifact-preview-header">
            <span>{previewLabel}</span>
            {isStreaming ? <span className="inline-artifact-preview-live">Updating</span> : null}
            {isReady ? <span className="inline-artifact-preview-open-hint">Click to open</span> : null}
          </div>
          <pre
            ref={previewRef}
            className={`inline-artifact-preview ${isStreaming ? 'is-streaming' : ''}`}
          >
            {artifactContent}
          </pre>
        </div>
      ) : null}

      {isStreaming && !hasPreview ? (
        <div className="inline-artifact-placeholder">
          Artifact content is opening. Live output will appear here as soon as the model emits it.
        </div>
      ) : null}

      {isDeleted ? (
        <div className="inline-artifact-placeholder">
          This artifact was deleted
        </div>
      ) : null}
    </>
  );

  return (
    <>
      {canOpen ? (
        <button
          type="button"
          className={`inline-artifact-card inline-artifact-card-button status-${localArtifact.status}`}
          onClick={() => setIsModalOpen(true)}
        >
          {cardContent}
        </button>
      ) : (
        <div className={`inline-artifact-card status-${localArtifact.status}`}>
          {cardContent}
        </div>
      )}

      {isModalOpen ? (
        <ArtifactModal
          artifact={localArtifact}
          onClose={() => setIsModalOpen(false)}
          onUpdated={(updatedArtifact) => {
            setLocalArtifact(updatedArtifact);
            onArtifactUpdated?.(updatedArtifact);
          }}
          onDeleted={(artifactId) => {
            setLocalArtifact((current) =>
              current.artifactId === artifactId
                ? { ...current, status: 'deleted', content: undefined }
                : current,
            );
            onArtifactDeleted?.(artifactId);
          }}
        />
      ) : null}
    </>
  );
}

export default InlineArtifactBlock;
