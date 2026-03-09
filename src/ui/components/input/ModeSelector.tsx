/**
 * Mode selector component.
 * 
 * Buttons for selecting capture mode (fullscreen, precision, meeting).
 */
import React from 'react';
import type { CaptureMode } from '../../types';

interface ModeSelectorProps {
  captureMode: CaptureMode;
  meetingRecordingMode: boolean;
  onFullscreenMode: () => void;
  onPrecisionMode: () => void;
  onMeetingMode: () => void;
  regionSSIcon: string;
  fullscreenSSIcon: string;
}

export function ModeSelector({
  captureMode,
  meetingRecordingMode,
  onFullscreenMode,
  onPrecisionMode,
  onMeetingMode,
  regionSSIcon,
  fullscreenSSIcon,
}: ModeSelectorProps) {
  const activeMode = meetingRecordingMode ? 'meeting' : captureMode;

  return (
    <div className="mode-selection-section" role="tablist" aria-label="Capture mode selector">
      <button
        type="button"
        className={`mode-selector-button${activeMode === 'precision' ? ' mode-selector-button-active' : ''}`}
        onClick={onPrecisionMode}
        title="Talk to a specific region of your screen"
        aria-label="Precision capture mode"
        aria-pressed={activeMode === 'precision'}
      >
        <img src={regionSSIcon} alt="Region Screenshot Mode" className="region-ss-icon" />
      </button>
      <button
        type="button"
        className={`mode-selector-button${activeMode === 'fullscreen' ? ' mode-selector-button-active' : ''}`}
        onClick={onFullscreenMode}
        title="Talk to anything on your screen"
        aria-label="Fullscreen capture mode"
        aria-pressed={activeMode === 'fullscreen'}
      >
        <img src={fullscreenSSIcon} alt="Full Screen Screenshot Mode" className="fullscreen-ss-icon" />
      </button>
      <button
        type="button"
        className={`mode-selector-button${activeMode === 'meeting' ? ' mode-selector-button-active' : ''}`}
        onClick={onMeetingMode}
        title="Meeting recorder mode"
        aria-label="Meeting recorder mode"
        aria-pressed={activeMode === 'meeting'}
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="meeting-recording-icon">
          <path d="M2 10v3"/>
          <path d="M6 6v11"/>
          <path d="M10 3v18"/>
          <path d="M14 8v7"/>
          <path d="M18 5v13"/>
          <path d="M22 10v3"/>
        </svg>
      </button>
    </div>
  );
}
