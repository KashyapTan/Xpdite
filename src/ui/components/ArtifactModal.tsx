import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../services/api';
import type { ArtifactRecord } from '../services/api';
import type { ArtifactBlockData, ArtifactKind } from '../types';
import { copyToClipboard } from '../utils/clipboard';
import '../CSS/ArtifactModal.css';

type PreviewMode = 'preview' | 'source';

interface ArtifactModalProps {
  artifact: ArtifactBlockData;
  onClose: () => void;
  onUpdated?: (artifact: ArtifactBlockData) => void;
  onDeleted?: (artifactId: string) => void;
  onOpenConversation?: (conversationId: string) => void;
}

function toArtifactBlockData(artifact: ArtifactRecord): ArtifactBlockData {
  return {
    artifactId: artifact.id,
    artifactType: artifact.type,
    title: artifact.title,
    language: artifact.language,
    sizeBytes: artifact.sizeBytes,
    lineCount: artifact.lineCount,
    status: artifact.status,
    content: artifact.content,
    conversationId: artifact.conversationId,
    messageId: artifact.messageId,
    createdAt: artifact.createdAt,
    updatedAt: artifact.updatedAt,
  };
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

function getDefaultPreviewMode(artifactType: ArtifactKind): PreviewMode {
  return artifactType === 'html' || artifactType === 'markdown' ? 'preview' : 'source';
}

function getStatusLabel(status: ArtifactBlockData['status']): string {
  return `${status.slice(0, 1).toUpperCase()}${status.slice(1)}`;
}

function renderSourceView(artifact: ArtifactBlockData, content: string) {
  return (
    <pre className={`artifact-modal-source artifact-modal-source-${artifact.artifactType}`}>
      <code>{content || ''}</code>
    </pre>
  );
}

function renderPreview(artifact: ArtifactBlockData, content: string, previewMode: PreviewMode) {
  if (artifact.artifactType === 'code' || previewMode === 'source') {
    return renderSourceView(artifact, content);
  }

  if (artifact.artifactType === 'markdown') {
    return (
      <div className="artifact-modal-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {content || ''}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <iframe
      title={artifact.title}
      className="artifact-modal-html-frame"
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={content || ''}
    />
  );
}

function PreviewModeControls({
  artifactType,
  previewMode,
  onChange,
}: {
  artifactType: ArtifactKind;
  previewMode: PreviewMode;
  onChange: (mode: PreviewMode) => void;
}) {
  if (artifactType !== 'markdown' && artifactType !== 'html') {
    return null;
  }

  return (
    <div className="artifact-modal-tab-strip">
      <button
        type="button"
        className={previewMode === 'preview' ? 'active' : ''}
        onClick={() => onChange('preview')}
      >
        Preview
      </button>
      <button
        type="button"
        className={previewMode === 'source' ? 'active' : ''}
        onClick={() => onChange('source')}
      >
        Source
      </button>
    </div>
  );
}

export function ArtifactModal({
  artifact,
  onClose,
  onUpdated,
  onDeleted,
  onOpenConversation,
}: ArtifactModalProps) {
  const [resolvedArtifact, setResolvedArtifact] = useState<ArtifactBlockData>(artifact);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [previewMode, setPreviewMode] = useState<PreviewMode>(getDefaultPreviewMode(artifact.artifactType));
  const [draftTitle, setDraftTitle] = useState(artifact.title);
  const [draftLanguage, setDraftLanguage] = useState(artifact.language ?? '');
  const [draftContent, setDraftContent] = useState(artifact.content ?? '');
  const [savePending, setSavePending] = useState(false);
  const [deletePending, setDeletePending] = useState(false);

  useEffect(() => {
    setResolvedArtifact(artifact);
    setPreviewMode(getDefaultPreviewMode(artifact.artifactType));
    setDraftTitle(artifact.title);
    setDraftLanguage(artifact.language ?? '');
    setDraftContent(artifact.content ?? '');
    setIsEditing(false);
  }, [artifact]);

  useEffect(() => {
    if (
      resolvedArtifact.status !== 'ready'
      || resolvedArtifact.content !== undefined
      || !resolvedArtifact.artifactId
    ) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError('');

    void api.getArtifact(resolvedArtifact.artifactId)
      .then((detail) => {
        if (cancelled) {
          return;
        }

        const nextArtifact = toArtifactBlockData(detail);
        setResolvedArtifact(nextArtifact);
        setDraftTitle(nextArtifact.title);
        setDraftLanguage(nextArtifact.language ?? '');
        setDraftContent(nextArtifact.content ?? '');
        onUpdated?.(nextArtifact);
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load artifact');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [onUpdated, resolvedArtifact]);

  const canSave = useMemo(() => {
    if (resolvedArtifact.status !== 'ready') {
      return false;
    }

    return (
      draftTitle.trim().length > 0
      && (
        draftTitle.trim() !== resolvedArtifact.title
        || draftContent !== (resolvedArtifact.content ?? '')
        || (
          resolvedArtifact.artifactType === 'code'
          && draftLanguage.trim() !== (resolvedArtifact.language ?? '')
        )
      )
    );
  }, [draftContent, draftLanguage, draftTitle, resolvedArtifact]);

  const handleSave = async () => {
    if (!canSave || savePending) {
      return;
    }

    setSavePending(true);
    setError('');
    try {
      const updated = await api.updateArtifact(resolvedArtifact.artifactId, {
        title: draftTitle.trim(),
        content: draftContent,
        language: resolvedArtifact.artifactType === 'code'
          ? draftLanguage.trim() || undefined
          : undefined,
      });
      const nextArtifact = toArtifactBlockData(updated);
      setResolvedArtifact(nextArtifact);
      setDraftTitle(nextArtifact.title);
      setDraftLanguage(nextArtifact.language ?? '');
      setDraftContent(nextArtifact.content ?? '');
      setIsEditing(false);
      onUpdated?.(nextArtifact);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save artifact');
    } finally {
      setSavePending(false);
    }
  };

  const handleDelete = async () => {
    if (deletePending || resolvedArtifact.status === 'deleted') {
      return;
    }

    if (!window.confirm(`Delete artifact "${resolvedArtifact.title}"?`)) {
      return;
    }

    setDeletePending(true);
    setError('');
    try {
      await api.deleteArtifact(resolvedArtifact.artifactId);
      onDeleted?.(resolvedArtifact.artifactId);
      onClose();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Failed to delete artifact');
    } finally {
      setDeletePending(false);
    }
  };

  const renderReadView = () => {
    if (resolvedArtifact.status === 'deleted') {
      return (
        <div className="artifact-modal-tombstone">
          This artifact has been deleted. Existing chat references remain as tombstones.
        </div>
      );
    }

    return (
      <div className="artifact-modal-read-view">
        <div className="artifact-modal-view-controls">
          <PreviewModeControls
            artifactType={resolvedArtifact.artifactType}
            previewMode={previewMode}
            onChange={setPreviewMode}
          />
          <button
            type="button"
            className="artifact-modal-copy-button"
            onClick={() => void copyToClipboard(resolvedArtifact.content ?? '')}
          >
            Copy
          </button>
        </div>
        <div className="artifact-modal-preview-surface">
          {renderPreview(resolvedArtifact, resolvedArtifact.content ?? '', previewMode)}
        </div>
      </div>
    );
  };

  const renderEditPreview = () => {
    const previewArtifact: ArtifactBlockData = {
      ...resolvedArtifact,
      title: draftTitle,
      language: resolvedArtifact.artifactType === 'code'
        ? draftLanguage.trim() || undefined
        : undefined,
      content: draftContent,
    };

    return (
      <div className="artifact-modal-edit-grid">
        <div className="artifact-modal-field">
          <label htmlFor="artifact-title">Title</label>
          <input
            id="artifact-title"
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
          />
        </div>
        {resolvedArtifact.artifactType === 'code' && (
          <div className="artifact-modal-field">
            <label htmlFor="artifact-language">Language</label>
            <input
              id="artifact-language"
              value={draftLanguage}
              onChange={(event) => setDraftLanguage(event.target.value)}
            />
          </div>
        )}
        <div className="artifact-modal-editor-pane">
          <label htmlFor="artifact-content">Content</label>
          <textarea
            id="artifact-content"
            className="artifact-modal-editor"
            value={draftContent}
            onChange={(event) => setDraftContent(event.target.value)}
            spellCheck={resolvedArtifact.artifactType === 'markdown'}
          />
        </div>
        <div className="artifact-modal-preview-pane">
          <div className="artifact-modal-preview-pane-header">
            <span className="artifact-modal-preview-header">
              {previewMode === 'source' || resolvedArtifact.artifactType === 'code'
                ? 'Source preview'
                : 'Live preview'}
            </span>
            <PreviewModeControls
              artifactType={resolvedArtifact.artifactType}
              previewMode={previewMode}
              onChange={setPreviewMode}
            />
          </div>
          <div className="artifact-modal-preview-surface">
            {renderPreview(previewArtifact, draftContent, previewMode)}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="artifact-modal-overlay" onClick={onClose}>
      <div className="artifact-modal-shell" onClick={(event) => event.stopPropagation()}>
        <div className="artifact-modal-header">
          <div>
            <h3>{resolvedArtifact.title}</h3>
            <div className="artifact-modal-meta">
              <span>{resolvedArtifact.artifactType}</span>
              {resolvedArtifact.language ? <span>{resolvedArtifact.language}</span> : null}
              <span>{formatBytes(resolvedArtifact.sizeBytes)}</span>
              <span>{resolvedArtifact.lineCount} lines</span>
              <span className={`artifact-status artifact-status-${resolvedArtifact.status}`}>
                {getStatusLabel(resolvedArtifact.status)}
              </span>
            </div>
          </div>
          <button type="button" className="artifact-modal-close" onClick={onClose}>
            &times;
          </button>
        </div>

        {error ? <div className="artifact-modal-error">{error}</div> : null}
        {loading ? <div className="artifact-modal-loading">Loading artifact…</div> : null}

        <div className="artifact-modal-body">
          {!loading && (isEditing ? renderEditPreview() : renderReadView())}
        </div>

        <div className="artifact-modal-footer">
          {resolvedArtifact.conversationId && onOpenConversation ? (
            <button
              type="button"
              className="artifact-modal-secondary"
              onClick={() => onOpenConversation(resolvedArtifact.conversationId!)}
            >
              Open Conversation
            </button>
          ) : (
            <div />
          )}
          <div className="artifact-modal-footer-actions">
            {resolvedArtifact.status === 'ready' && !isEditing ? (
              <button
                type="button"
                className="artifact-modal-secondary"
                onClick={() => setIsEditing(true)}
              >
                Edit
              </button>
            ) : null}
            {resolvedArtifact.status === 'ready' && isEditing ? (
              <>
                <button
                  type="button"
                  className="artifact-modal-secondary"
                  onClick={() => {
                    setIsEditing(false);
                    setDraftTitle(resolvedArtifact.title);
                    setDraftLanguage(resolvedArtifact.language ?? '');
                    setDraftContent(resolvedArtifact.content ?? '');
                    setPreviewMode(getDefaultPreviewMode(resolvedArtifact.artifactType));
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="artifact-modal-primary"
                  disabled={!canSave || savePending}
                  onClick={() => void handleSave()}
                >
                  {savePending ? 'Saving…' : 'Save'}
                </button>
              </>
            ) : null}
            {resolvedArtifact.status !== 'deleted' ? (
              <button
                type="button"
                className="artifact-modal-danger"
                onClick={() => void handleDelete()}
                disabled={deletePending}
              >
                {deletePending ? 'Deleting…' : 'Delete'}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ArtifactModal;
