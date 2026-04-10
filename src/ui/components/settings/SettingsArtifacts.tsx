import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTabs } from '../../contexts/TabContext';
import { ArtifactModal } from '../ArtifactModal';
import { RotateCcwIcon } from '../icons/AppIcons';
import { api } from '../../services/api';
import type { ArtifactListResponse, ArtifactRecord } from '../../services/api';
import type { ArtifactBlockData, ArtifactKind } from '../../types';
import '../../CSS/settings/SettingsArtifacts.css';

const PAGE_SIZE = 24;

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
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value?: number): string {
  if (!value) {
    return 'Unknown';
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(value >= 1_000_000_000_000 ? value : value * 1000);
}

type TypeFilter = 'all' | ArtifactKind;

export default function SettingsArtifacts() {
  const navigate = useNavigate();
  const { createTab } = useTabs();
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactBlockData | null>(null);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 200);

    return () => window.clearTimeout(timeoutId);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    void api.listArtifacts({
      query: debouncedQuery,
      type: typeFilter === 'all' ? undefined : typeFilter,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((response: ArtifactListResponse) => {
        if (cancelled) {
          return;
        }
        setArtifacts(response.artifacts);
        setTotal(response.total);
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load artifacts');
          setArtifacts([]);
          setTotal(0);
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
  }, [debouncedQuery, page, typeFilter]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  useEffect(() => {
    setPage(1);
  }, [typeFilter]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const refreshSelectedPage = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.listArtifacts({
        query: debouncedQuery,
        type: typeFilter === 'all' ? undefined : typeFilter,
        page,
        pageSize: PAGE_SIZE,
      });
      setArtifacts(response.artifacts);
      setTotal(response.total);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load artifacts');
    } finally {
      setLoading(false);
    }
  };

  const openConversation = (conversationId: string) => {
    const tabId = createTab();
    if (!tabId) {
      return;
    }
    navigate('/', { state: { conversationId, tabId } });
  };

  return (
    <div className="settings-artifacts">
      <div className="settings-artifacts-header">
        <div className="settings-artifacts-header-row">
          <div className="settings-artifacts-header-copy">
            <h2>Artifacts</h2>
            <p>Browse generated code, markdown, and HTML artifacts. Open any artifact to inspect, edit, or delete it.</p>
            <div className="settings-artifacts-summary">
              {/* {loading ? 'Refreshing artifact library…' : `${total} artifact${total === 1 ? '' : 's'} indexed`} */}
            </div>
          </div>
        </div>
        {/* <div className="settings-artifacts-hint">Filter by type or title</div> */}
      </div>

      <div className="settings-artifacts-toolbar">
        <div className="settings-artifacts-filters">
          <input
            type="search"
            placeholder="Search artifacts..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}>
            <option value="all">All types</option>
            <option value="code">Code</option>
            <option value="markdown">Markdown</option>
            <option value="html">HTML</option>
          </select>
          <button
            type="button"
            className="secondary-button settings-artifacts-refresh"
            onClick={() => void refreshSelectedPage()}
            disabled={loading}
            title={loading ? 'Refreshing artifacts...' : 'Refresh artifacts'}
            aria-label={loading ? 'Refreshing artifacts' : 'Refresh artifacts'}
          >
            <RotateCcwIcon className={loading ? 'spin' : undefined} size={14} />
          </button>
        </div>
      </div>

      {error ? <div className="settings-artifacts-error">{error}</div> : null}

      {loading ? <div className="settings-artifacts-empty">Loading artifacts...</div> : null}

      {!loading && artifacts.length === 0 ? (
        <div className="settings-artifacts-empty">
          No artifacts found for the current filters.
        </div>
      ) : null}

      {!loading && artifacts.length > 0 ? (
        <>
          <div className="settings-artifacts-list">
            {artifacts.map((artifact) => (
              <button
                type="button"
                key={artifact.id}
                className="settings-artifacts-item"
                onClick={() => setSelectedArtifact(toArtifactBlockData(artifact))}
              >
                <div className="settings-artifacts-item-top">
                  <div className="settings-artifacts-item-title-group">
                    <strong>{artifact.title}</strong>
                    <div className="settings-artifacts-item-meta">
                      <span>{artifact.type}</span>
                      {artifact.language ? <span>{artifact.language}</span> : null}
                      <span>{formatBytes(artifact.sizeBytes)}</span>
                      <span>{artifact.lineCount} lines</span>
                    </div>
                  </div>
                  <div className="settings-artifacts-item-status-group">
                    <span className={`settings-artifacts-status status-${artifact.status}`}>
                      {artifact.status}
                    </span>
                  </div>
                </div>
                <div className="settings-artifacts-item-footer">
                  <span>{formatDate(artifact.updatedAt)}</span>
                  {artifact.conversationId ? <span>Linked to conversation</span> : <span>Standalone artifact</span>}
                </div>
              </button>
            ))}
          </div>

          <div className="settings-artifacts-pagination">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1}
            >
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              disabled={page >= totalPages}
            >
              Next
            </button>
          </div>
        </>
      ) : null}

      {selectedArtifact ? (
        <ArtifactModal
          artifact={selectedArtifact}
          onClose={() => setSelectedArtifact(null)}
          onUpdated={(updatedArtifact) => {
            setSelectedArtifact(updatedArtifact);
            setArtifacts((currentArtifacts) =>
              currentArtifacts.map((artifact) =>
                artifact.id === updatedArtifact.artifactId
                  ? {
                      ...artifact,
                      title: updatedArtifact.title,
                      language: updatedArtifact.language,
                      sizeBytes: updatedArtifact.sizeBytes,
                      lineCount: updatedArtifact.lineCount,
                      status: updatedArtifact.status,
                      content: updatedArtifact.content,
                      conversationId: updatedArtifact.conversationId,
                      messageId: updatedArtifact.messageId,
                      createdAt: updatedArtifact.createdAt,
                      updatedAt: updatedArtifact.updatedAt,
                    }
                  : artifact,
              ),
            );
          }}
          onDeleted={() => {
            setSelectedArtifact(null);
            void refreshSelectedPage();
          }}
          onOpenConversation={openConversation}
        />
      ) : null}
    </div>
  );
}
