import React, { useEffect, useMemo, useRef, useState } from 'react';
import '../../CSS/SettingsMemory.css';
import { api } from '../../services/api';
import type { MemoryDetail, MemorySummary } from '../../types';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

type EditorState = {
  path: string;
  title: string;
  category: string;
  importance: string;
  tags: string;
  abstract: string;
  body: string;
};

const DEFAULT_FOLDER_ORDER = ['profile', 'semantic', 'episodic', 'procedural'];

function formatTimestamp(value: string): string {
  if (!value) {
    return 'Never';
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed);
}

function buildFolderGroups(memories: MemorySummary[]): Array<{ folder: string; items: MemorySummary[] }> {
  const grouped = new Map<string, MemorySummary[]>();

  for (const memory of memories) {
    const folder = memory.folder || '(root)';
    const existing = grouped.get(folder) ?? [];
    existing.push(memory);
    grouped.set(folder, existing);
  }

  return [...grouped.entries()]
    .sort(([left], [right]) => {
      const leftIndex = DEFAULT_FOLDER_ORDER.indexOf(left);
      const rightIndex = DEFAULT_FOLDER_ORDER.indexOf(right);
      if (leftIndex !== -1 || rightIndex !== -1) {
        if (leftIndex === -1) return 1;
        if (rightIndex === -1) return -1;
        return leftIndex - rightIndex;
      }
      return left.localeCompare(right);
    })
    .map(([folder, items]) => ({
      folder,
      items: [...items].sort((a, b) => a.path.localeCompare(b.path)),
    }));
}

function detailToEditor(detail: MemoryDetail): EditorState {
  return {
    path: detail.path,
    title: detail.title,
    category: detail.category,
    importance: String(detail.importance),
    tags: detail.tags.join(', '),
    abstract: detail.abstract,
    body: detail.body,
  };
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function toSummary(detail: MemoryDetail): MemorySummary {
  return {
    path: detail.path,
    folder: detail.folder,
    title: detail.title,
    category: detail.category,
    importance: detail.importance,
    tags: detail.tags,
    abstract: detail.abstract,
    created: detail.created,
    updated: detail.updated,
    last_accessed: detail.last_accessed,
    parse_warning: detail.parse_warning,
  };
}

const SettingsMemory: React.FC = () => {
  const [memories, setMemories] = useState<MemorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsLoadFailed, setSettingsLoadFailed] = useState(false);
  const [profileAutoInject, setProfileAutoInject] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<MemoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [error, setError] = useState('');
  const [deletePending, setDeletePending] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({});
  const detailRequestIdRef = useRef(0);

  const folderGroups = useMemo(() => buildFolderGroups(memories), [memories]);

  const syncMemorySummary = (detail: MemoryDetail) => {
    setMemories((current) => {
      const nextSummary = toSummary(detail);
      const nextItems = current.filter((item) => item.path !== detail.path);
      nextItems.push(nextSummary);
      return nextItems;
    });
  };

  const loadMemories = async (
    nextSelectedPath?: string | null,
    reloadSelectedDetail = true,
  ) => {
    try {
      setLoading(true);
      const data = await api.listMemories();
      setMemories(data);
      setExpandedFolders((current) => {
        const nextState = { ...current };
        for (const item of data) {
          const folder = item.folder || '(root)';
          if (!(folder in nextState)) {
            nextState[folder] = true;
          }
        }
        return nextState;
      });

      const preservedPath = nextSelectedPath === undefined ? selectedPath : nextSelectedPath;
      if (reloadSelectedDetail && preservedPath && data.some((item) => item.path === preservedPath)) {
        await loadDetail(preservedPath);
      } else if (preservedPath) {
        setSelectedPath((current) => (data.some((item) => item.path === preservedPath) ? current : null));
        if (!data.some((item) => item.path === preservedPath)) {
          setSelectedDetail(null);
          setEditor(null);
        }
      }
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Failed to load memories.'));
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (path: string) => {
    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;

    try {
      setDetailLoading(true);
      setError('');
      const detail = await api.getMemory(path);
      if (detailRequestIdRef.current !== requestId) {
        return;
      }
      setSelectedPath(path);
      setSelectedDetail(detail);
      setEditor(detailToEditor(detail));
      setSaveStatus('idle');
    } catch (detailError) {
      if (detailRequestIdRef.current === requestId) {
        setError(getErrorMessage(detailError, 'Failed to load memory.'));
      }
    } finally {
      if (detailRequestIdRef.current === requestId) {
        setDetailLoading(false);
      }
    }
  };

  const loadMemorySettings = async () => {
    try {
      setSettingsLoading(true);
      setSettingsLoadFailed(false);
      const settings = await api.getMemorySettings();
      setProfileAutoInject(settings.profile_auto_inject);
    } catch (settingsError) {
      setProfileAutoInject(false);
      setSettingsLoadFailed(true);
      setError(getErrorMessage(settingsError, 'Failed to load memory settings.'));
    } finally {
      setSettingsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;

    const initialize = async () => {
      setLoading(true);
      setSettingsLoading(true);
      setSettingsLoadFailed(false);
      void api.listMemories()
        .then((memoryData) => {
          if (cancelled) {
            return;
          }
          setMemories(memoryData);
          setExpandedFolders((current) => {
            const nextState = { ...current };
            for (const item of memoryData) {
              const folder = item.folder || '(root)';
              if (!(folder in nextState)) {
                nextState[folder] = true;
              }
            }
            return nextState;
          });
        })
        .catch((memoryError) => {
          if (!cancelled) {
            setError(getErrorMessage(memoryError, 'Failed to load memories.'));
          }
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });

      void api.getMemorySettings()
        .then((settings) => {
          if (!cancelled) {
            setProfileAutoInject(settings.profile_auto_inject);
          }
        })
        .catch((settingsError) => {
          if (!cancelled) {
            setProfileAutoInject(false);
            setSettingsLoadFailed(true);
            setError(getErrorMessage(settingsError, 'Failed to load memory settings.'));
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSettingsLoading(false);
          }
        });
    };

    void initialize();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggleFolder = (folder: string) => {
    setExpandedFolders((current) => ({ ...current, [folder]: !current[folder] }));
  };

  const handleProfileToggle = async (checked: boolean) => {
    if (settingsSaving) {
      return;
    }

    setProfileAutoInject(checked);
    setSettingsSaving(true);
    try {
      await api.setMemorySettings({ profile_auto_inject: checked });
    } catch (toggleError) {
      setProfileAutoInject(!checked);
      setError(getErrorMessage(toggleError, 'Failed to update memory settings.'));
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleEditorChange = (field: keyof EditorState, value: string) => {
    setEditor((current) => (current ? { ...current, [field]: value } : current));
    setSaveStatus('idle');
  };

  const handleSave = async () => {
    if (!editor) {
      return;
    }

    const numericImportance = Number(editor.importance);
    if (Number.isNaN(numericImportance) || numericImportance < 0 || numericImportance > 1) {
      setError('Importance must be a number between 0.0 and 1.0.');
      setSaveStatus('error');
      return;
    }

    setSaveStatus('saving');
    setError('');

    try {
      const updated = await api.updateMemory({
        path: editor.path,
        title: editor.title.trim(),
        category: editor.category.trim(),
        importance: numericImportance,
        tags: editor.tags.split(',').map((value) => value.trim()).filter(Boolean),
        abstract: editor.abstract.trim(),
        body: editor.body,
      });
      setSelectedDetail(updated);
      setSelectedPath(updated.path);
      setEditor(detailToEditor(updated));
      syncMemorySummary(updated);
      setSaveStatus('saved');
      window.setTimeout(() => setSaveStatus('idle'), 2000);
    } catch (saveError) {
      setSaveStatus('error');
      setError(getErrorMessage(saveError, 'Failed to save memory.'));
    }
  };

  const handleDelete = async () => {
    if (!selectedPath || deletePending) {
      return;
    }

    if (!window.confirm(`Delete memory '${selectedPath}'?`)) {
      return;
    }

    try {
      setDeletePending(true);
      await api.deleteMemory(selectedPath);
      setSelectedPath(null);
      setSelectedDetail(null);
      setEditor(null);
      setSaveStatus('idle');
      await loadMemories(null);
    } catch (deleteError) {
      setError(getErrorMessage(deleteError, 'Failed to delete memory.'));
    } finally {
      setDeletePending(false);
    }
  };

  const handleClearAll = async () => {
    if (clearPending) {
      return;
    }

    if (!window.confirm('Clear all memories? This deletes every memory file.')) {
      return;
    }

    try {
      setClearPending(true);
      await api.clearAllMemories();
      setSelectedPath(null);
      setSelectedDetail(null);
      setEditor(null);
      setSaveStatus('idle');
      await loadMemories(null);
    } catch (clearError) {
      setError(getErrorMessage(clearError, 'Failed to clear memories.'));
    } finally {
      setClearPending(false);
    }
  };

  return (
    <div className="settings-memory">
      <div className="settings-memory-header">
        <div>
          <h2>Memory</h2>
          <p>Browse long-term memories stored under <code>user_data/memory</code>, edit structured metadata, and control profile auto-injection.</p>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => void Promise.allSettled([loadMemories(selectedPath, false), loadMemorySettings()])}
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      <div className="settings-memory-toggle-card">
        <div>
          <h3>Profile Auto-Inject</h3>
          <p>Inject <code>profile/user_profile.md</code> into the system prompt when it exists. That memory is sent to the active model, including cloud providers when you use them.</p>
        </div>
        <label className="settings-memory-toggle">
          <input
            type="checkbox"
            checked={profileAutoInject}
            onChange={(event) => void handleProfileToggle(event.target.checked)}
            disabled={settingsLoading || settingsLoadFailed || settingsSaving}
            aria-label="Profile auto-inject"
          />
          <span>{profileAutoInject ? 'On' : 'Off'}</span>
        </label>
      </div>

      {error ? <div className="settings-memory-error">{error}</div> : null}

      <div className="settings-memory-body">
        <div className="settings-memory-browser">
          <div className="settings-memory-browser-header">
            <h3>Memory Browser</h3>
            <span>{memories.length} file(s)</span>
          </div>

          {loading ? <div className="settings-memory-empty">Loading memories...</div> : null}

          {!loading && folderGroups.length === 0 ? (
            <div className="settings-memory-empty">No memories saved yet. Use chat memory tools or create <code>profile/user_profile.md</code> to get started.</div>
          ) : null}

          {!loading && folderGroups.length > 0 ? (
            <div className="settings-memory-groups">
              {folderGroups.map(({ folder, items }) => {
                const expanded = expandedFolders[folder] ?? true;
                return (
                  <section key={folder} className="settings-memory-folder">
                    <button
                      type="button"
                      className="settings-memory-folder-toggle"
                      onClick={() => handleToggleFolder(folder)}
                    >
                      <span>{expanded ? '[-]' : '[+]'}</span>
                      <span>{folder}</span>
                      <span>{items.length}</span>
                    </button>

                    {expanded ? (
                      <div className="settings-memory-list">
                        {items.map((memory) => (
                          <button
                            type="button"
                            key={memory.path}
                            className={`settings-memory-item ${selectedPath === memory.path ? 'selected' : ''}`}
                            onClick={() => void loadDetail(memory.path)}
                          >
                            <div className="settings-memory-item-top">
                              <strong>{memory.title}</strong>
                              <span>{memory.importance.toFixed(2)}</span>
                            </div>
                            <div className="settings-memory-item-path">{memory.path}</div>
                            <div className="settings-memory-item-abstract">{memory.abstract}</div>
                            <div className="settings-memory-item-meta">
                              <span>Accessed {formatTimestamp(memory.last_accessed)}</span>
                              {memory.parse_warning ? <span className="settings-memory-warning">Parse warning</span> : null}
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          ) : null}

          <div className="settings-memory-danger">
            <h3>Danger Zone</h3>
            <p>Remove every saved memory file and recreate the default folder layout.</p>
            <button
              type="button"
              className="settings-memory-danger-button"
              onClick={() => void handleClearAll()}
              disabled={clearPending}
            >
              {clearPending ? 'Clearing...' : 'Clear All Memories'}
            </button>
          </div>
        </div>

        <div className="settings-memory-editor">
          <div className="settings-memory-editor-header">
            <h3>Memory Editor</h3>
            {selectedDetail ? <span>Updated {formatTimestamp(selectedDetail.updated)}</span> : null}
          </div>

          {!editor ? (
            <div className="settings-memory-empty">Select a memory file to inspect and edit it.</div>
          ) : (
            <div className="settings-memory-form">
              <div className="settings-memory-field">
                <label htmlFor="memory-path">Path</label>
                <input id="memory-path" value={editor.path} readOnly />
              </div>

              <div className="settings-memory-grid">
                <div className="settings-memory-field">
                  <label htmlFor="memory-title">Title</label>
                  <input
                    id="memory-title"
                    value={editor.title}
                    onChange={(event) => handleEditorChange('title', event.target.value)}
                    disabled={detailLoading}
                  />
                </div>

                <div className="settings-memory-field">
                  <label htmlFor="memory-category">Category</label>
                  <input
                    id="memory-category"
                    value={editor.category}
                    onChange={(event) => handleEditorChange('category', event.target.value)}
                    disabled={detailLoading}
                  />
                </div>

                <div className="settings-memory-field">
                  <label htmlFor="memory-importance">Importance</label>
                  <input
                    id="memory-importance"
                    value={editor.importance}
                    onChange={(event) => handleEditorChange('importance', event.target.value)}
                    disabled={detailLoading}
                  />
                </div>

                <div className="settings-memory-field">
                  <label htmlFor="memory-tags">Tags</label>
                  <input
                    id="memory-tags"
                    value={editor.tags}
                    onChange={(event) => handleEditorChange('tags', event.target.value)}
                    disabled={detailLoading}
                  />
                </div>
              </div>

              <div className="settings-memory-field">
                <label htmlFor="memory-abstract">Abstract</label>
                <textarea
                  id="memory-abstract"
                  value={editor.abstract}
                  onChange={(event) => handleEditorChange('abstract', event.target.value)}
                  rows={3}
                  disabled={detailLoading}
                />
              </div>

              <div className="settings-memory-field">
                <label htmlFor="memory-body">Body</label>
                <textarea
                  id="memory-body"
                  className="settings-memory-body-input"
                  value={editor.body}
                  onChange={(event) => handleEditorChange('body', event.target.value)}
                  rows={16}
                  disabled={detailLoading}
                />
              </div>

              <div className="settings-memory-editor-meta">
                <span>Created {formatTimestamp(selectedDetail?.created ?? '')}</span>
                <span>Last accessed {formatTimestamp(selectedDetail?.last_accessed ?? '')}</span>
              </div>

              <div className="settings-memory-actions">
                <button
                  type="button"
                  className="settings-memory-delete-button"
                  onClick={() => void handleDelete()}
                  disabled={detailLoading || saveStatus === 'saving' || deletePending}
                >
                  {deletePending ? 'Deleting...' : 'Delete'}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => void handleSave()}
                  disabled={detailLoading || saveStatus === 'saving'}
                >
                  {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : 'Save'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsMemory;
