/**
 * FilePickerMenu - Dropdown menu for @ file attachment picker.
 *
 * Displays a searchable file picker with:
 * - Global ranked file results
 * - File list with icons
 * - Keyboard selection support
 * - Search results with relevance sorting
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { api, type FileEntry } from '../../services/api';
import '../../CSS/input/FilePickerMenu.css';

// File type to extension badge color mapping.
// Keep this deliberately small so attachments still fit the app palette.
const EXTENSION_COLORS: Record<string, string> = {
  // Code
  ts: 'var(--color-text-muted)',
  tsx: 'var(--color-text-muted)',
  js: 'var(--color-text-muted)',
  jsx: 'var(--color-text-muted)',
  py: 'var(--color-text-muted)',
  rs: 'var(--color-text-muted)',
  go: 'var(--color-text-muted)',
  java: 'var(--color-text-muted)',
  c: 'var(--color-text-muted)',
  cpp: 'var(--color-text-muted)',
  h: 'var(--color-text-muted)',
  hpp: 'var(--color-text-muted)',
  rb: 'var(--color-text-muted)',
  php: 'var(--color-text-muted)',
  swift: 'var(--color-text-muted)',
  kt: 'var(--color-text-muted)',
  html: 'var(--color-text-muted)',
  css: 'var(--color-text-muted)',
  scss: 'var(--color-text-muted)',
  sh: 'var(--color-text-muted)',
  bash: 'var(--color-text-muted)',
  zsh: 'var(--color-text-muted)',
  ps1: 'var(--color-text-muted)',
  bat: 'var(--color-text-muted)',
  // Data / config
  json: 'var(--color-green)',
  yaml: 'var(--color-green)',
  yml: 'var(--color-green)',
  toml: 'var(--color-green)',
  xml: 'var(--color-green)',
  csv: 'var(--color-green)',
  // Media / docs
  md: 'var(--color-text-muted)',
  txt: 'var(--color-text-muted)',
  doc: 'var(--color-text-muted)',
  docx: 'var(--color-text-muted)',
  pdf: 'var(--color-yellow)',
  png: 'var(--color-yellow)',
  jpg: 'var(--color-yellow)',
  jpeg: 'var(--color-yellow)',
  gif: 'var(--color-yellow)',
  svg: 'var(--color-yellow)',
  webp: 'var(--color-yellow)',
};

function getExtensionColor(extension: string | null): string {
  if (!extension) return 'var(--color-text-muted)';
  return EXTENSION_COLORS[extension.toLowerCase()] || 'var(--color-text-muted)';
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// File icon as inline SVG
const FileIcon = () => (
  <svg className="file-picker-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z" />
  </svg>
);

interface FilePickerMenuProps {
  searchQuery: string;
  position: { top: number; left: number };
  selectedIndex: number;
  onSelect: (entry: FileEntry) => void;
  onClose: () => void;
  onSelectedIndexChange: (index: number) => void;
  onEntriesChange?: (entries: FileEntry[]) => void;
}

const FilePickerMenu: React.FC<FilePickerMenuProps> = ({
  searchQuery,
  position,
  selectedIndex,
  onSelect,
  onClose,
  onSelectedIndexChange,
  onEntriesChange,
}) => {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestSeqRef = useRef(0);
  const lastRequestedKeyRef = useRef<string>('');

  // Fetch files from API
  const fetchFiles = useCallback(async (query: string) => {
    const requestSeq = ++requestSeqRef.current;
    setIsLoading(true);
    setError(null);

    try {
      const result = await api.browseFiles(query || undefined);
      if (requestSeq !== requestSeqRef.current) {
        return;
      }
      setEntries(result.entries);
      onEntriesChange?.(result.entries);
      onSelectedIndexChange(0); // Reset selection on new results
    } catch (err) {
      if (requestSeq !== requestSeqRef.current) {
        return;
      }
      setError(err instanceof Error ? err.message : 'Failed to load files');
      setEntries([]);
      onEntriesChange?.([]);
    } finally {
      if (requestSeq === requestSeqRef.current) {
        setIsLoading(false);
      }
    }
  }, [onEntriesChange, onSelectedIndexChange]);

  // Debounced fetch when search query changes
  useEffect(() => {
    const requestKey = searchQuery;
    if (requestKey === lastRequestedKeyRef.current) {
      return;
    }

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      lastRequestedKeyRef.current = requestKey;
      fetchFiles(searchQuery);
    }, 90);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [searchQuery, fetchFiles]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && entries.length > 0) {
      const selectedElement = listRef.current.querySelector('.file-picker-item.selected');
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex, entries.length]);

  // Handle item click
  const handleItemClick = useCallback((entry: FileEntry) => {
    onSelect(entry);
  }, [onSelect]);

  return (
    <div
      className="file-picker-menu"
      style={{
        bottom: 'calc(100% + 10px)',
        left: `${position.left}px`,
      }}
      onMouseDown={(e) => e.preventDefault()}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
        }
      }}
    >
      {/* Loading state */}
      {isLoading && entries.length === 0 && (
        <div className="file-picker-loading">
          <span className="file-picker-spinner" />
          Loading...
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="file-picker-error">{error}</div>
      )}

      {/* Empty state */}
      {!isLoading && !error && entries.length === 0 && (
        <div className="file-picker-empty">
          {searchQuery ? `No files found matching "${searchQuery}"` : 'Type after @ to search files'}
        </div>
      )}

      {/* File list */}
      {!error && entries.length > 0 && (
        <div className="file-picker-list" ref={listRef}>
          {entries.map((entry, index) => (
            <button
              key={entry.path}
              type="button"
              className={`file-picker-item ${index === selectedIndex ? 'selected' : ''}`}
              onClick={() => handleItemClick(entry)}
              onMouseEnter={() => onSelectedIndexChange(index)}
            >
              <div className="file-picker-item-icon">
                <FileIcon />
              </div>
              <div className="file-picker-item-info">
                <div className="file-picker-item-name" title={entry.name}>{entry.name}</div>
                <div className="file-picker-item-path" title={entry.relative_path}>{entry.relative_path}</div>
              </div>
              {!entry.is_directory && (
                <div className="file-picker-item-meta">
                  {entry.extension && (
                    <span
                      className="file-picker-item-ext"
                      style={{ backgroundColor: getExtensionColor(entry.extension) }}
                    >
                      .{entry.extension}
                    </span>
                  )}
                  {entry.size !== null && (
                    <span className="file-picker-item-size">
                      {formatFileSize(entry.size)}
                    </span>
                  )}
                </div>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Footer hint */}
      <div className="file-picker-footer">
        <span>↑↓ navigate</span>
        <span>↵ select</span>
        <span>esc close</span>
      </div>
    </div>
  );
};

export default FilePickerMenu;
