/**
 * Screenshot chips component.
 * 
 * Displays screenshot thumbnails as removable chips.
 */
import React from 'react';
import { CameraIcon, XIcon } from '../icons/AppIcons';
import type { Screenshot } from '../../types';

interface ScreenshotChipsProps {
  screenshots: Screenshot[];
  onRemove: (id: string) => void;
}

export function ScreenshotChips({ screenshots, onRemove }: ScreenshotChipsProps) {
  if (screenshots.length === 0) {
    return null;
  }

  return (
    <div className="context-chips">
      {screenshots.map((ss, index) => (
        <div key={ss.id} className="context-chip">
          <div className="chip-preview">
            {ss.thumbnail ? (
              <img
                src={`data:image/png;base64,${ss.thumbnail}`}
                alt={ss.name}
                className="chip-thumb"
              />
            ) : (
              <CameraIcon size={12} className="chip-icon" />
            )}
          </div>
          <span className="chip-name">SS{index + 1}</span>
          <button
            type="button"
            className="chip-remove"
            onClick={() => onRemove(ss.id)}
            title="Remove screenshot"
            aria-label={`Remove ${ss.name || `screenshot ${index + 1}`}`}
          >
            <XIcon size={12} />
          </button>
          {/* Hover preview popup */}
          <div className="chip-hover-preview">
            {ss.thumbnail && (
              <img
                src={`data:image/png;base64,${ss.thumbnail}`}
                alt={ss.name}
                className="hover-preview-img"
              />
            )}
            <span className="hover-preview-name">{ss.name}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
