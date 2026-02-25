/**
 * Screenshot management hook.
 * 
 * Manages screenshot state and provides actions for screenshot operations.
 */
import { useState, useRef, useCallback } from 'react';
import type { Screenshot, CaptureMode, ScreenshotSnapshot } from '../types';

interface UseScreenshotsReturn {
  // State
  screenshots: Screenshot[];
  captureMode: CaptureMode;
  meetingRecordingMode: boolean;
  
  // Ref for WebSocket callbacks
  screenshotsRef: React.RefObject<Screenshot[]>;
  
  // Actions
  addScreenshot: (screenshot: Screenshot) => void;
  removeScreenshot: (id: string) => void;
  clearScreenshots: () => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setMeetingRecordingMode: (enabled: boolean) => void;
  getImageData: () => Array<{name: string; thumbnail: string}>;
  getSnapshot: () => ScreenshotSnapshot;
  restoreSnapshot: (snapshot: ScreenshotSnapshot) => void;
}

export function useScreenshots(): UseScreenshotsReturn {
  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('precision');
  const [meetingRecordingMode, setMeetingRecordingMode] = useState(false);
  
  // Ref for WebSocket callbacks
  const screenshotsRef = useRef<Screenshot[]>([]);

  const addScreenshot = useCallback((screenshot: Screenshot) => {
    setScreenshots(prev => {
      const updated = [...prev, screenshot];
      screenshotsRef.current = updated;
      return updated;
    });
  }, []);

  const removeScreenshot = useCallback((id: string) => {
    setScreenshots(prev => {
      const updated = prev.filter(ss => ss.id !== id);
      screenshotsRef.current = updated;
      return updated;
    });
  }, []);

  const clearScreenshots = useCallback(() => {
    setScreenshots([]);
    screenshotsRef.current = [];
  }, []);

  const getImageData = useCallback(() => {
    return screenshotsRef.current.map(ss => ({
      name: ss.name,
      thumbnail: ss.thumbnail
    }));
  }, []);

  const getSnapshot = useCallback((): ScreenshotSnapshot => ({
    screenshots: [...screenshotsRef.current],
    captureMode,
    meetingRecordingMode,
  }), [captureMode, meetingRecordingMode]);

  const restoreSnapshot = useCallback((s: ScreenshotSnapshot) => {
    setScreenshots(s.screenshots);
    screenshotsRef.current = [...s.screenshots];
    setCaptureMode(s.captureMode);
    setMeetingRecordingMode(s.meetingRecordingMode);
  }, []);

  return {
    screenshots,
    captureMode,
    meetingRecordingMode,
    screenshotsRef,
    addScreenshot,
    removeScreenshot,
    clearScreenshots,
    setCaptureMode,
    setMeetingRecordingMode,
    getImageData,
    getSnapshot,
    restoreSnapshot,
  };
}
