import { useEffect, useState } from 'react';
import type { ArtifactBlockData } from '../../types';
import { ArtifactModal } from '../ArtifactModal';
import '../../CSS/InlineArtifact.css';

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

  useEffect(() => {
    setLocalArtifact(artifact);
  }, [artifact]);

  const isReady = localArtifact.status === 'ready';
  const isDeleted = localArtifact.status === 'deleted';
  const isStreaming = localArtifact.status === 'streaming';

  return (
    <>
      <div className={`inline-artifact-card status-${localArtifact.status}`}>
        <div className="inline-artifact-card-header">
          <div>
            <div className="inline-artifact-card-title">{localArtifact.title}</div>
            <div className="inline-artifact-card-meta">
              <span>{localArtifact.artifactType}</span>
              {localArtifact.language ? <span>{localArtifact.language}</span> : null}
              {!isDeleted ? <span>{formatBytes(localArtifact.sizeBytes)}</span> : null}
              {!isDeleted ? <span>{localArtifact.lineCount} lines</span> : null}
            </div>
          </div>
          <span className={`inline-artifact-status inline-artifact-status-${localArtifact.status}`}>
            {localArtifact.status}
          </span>
        </div>

        {isStreaming ? (
          <div className="inline-artifact-placeholder">
            Waiting for artifact content to finish streaming…
          </div>
        ) : null}

        {isDeleted ? (
          <div className="inline-artifact-placeholder">
            This artifact was deleted. The chat keeps a tombstone so the original response still makes sense.
          </div>
        ) : null}

        {isReady ? (
          <div className="inline-artifact-actions">
            <button type="button" onClick={() => setIsModalOpen(true)}>
              Open
            </button>
          </div>
        ) : null}
      </div>

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
