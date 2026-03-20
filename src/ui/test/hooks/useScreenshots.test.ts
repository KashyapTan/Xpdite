/**
 * Tests for useScreenshots hook.
 */
import { describe, expect, test } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useScreenshots } from '../../hooks/useScreenshots';
import type { Screenshot, ScreenshotSnapshot, CaptureMode } from '../../types';

describe('useScreenshots', () => {
  describe('initial state', () => {
    test('should have correct initial values', () => {
      const { result } = renderHook(() => useScreenshots());

      expect(result.current.screenshots).toEqual([]);
      expect(result.current.captureMode).toBe('precision');
      expect(result.current.meetingRecordingMode).toBe(false);
    });

    test('should initialize ref with empty array', () => {
      const { result } = renderHook(() => useScreenshots());

      expect(result.current.screenshotsRef.current).toEqual([]);
    });
  });

  describe('addScreenshot', () => {
    test('should add a screenshot to the list', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = {
        id: 'ss-1',
        name: 'Screenshot 1',
        thumbnail: 'data:image/png;base64,abc123',
      };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshots).toHaveLength(1);
      expect(result.current.screenshots[0]).toEqual(screenshot);
    });

    test('should append screenshots maintaining order', () => {
      const { result } = renderHook(() => useScreenshots());

      const ss1: Screenshot = { id: 'ss-1', name: 'First', thumbnail: 'thumb1' };
      const ss2: Screenshot = { id: 'ss-2', name: 'Second', thumbnail: 'thumb2' };
      const ss3: Screenshot = { id: 'ss-3', name: 'Third', thumbnail: 'thumb3' };

      act(() => {
        result.current.addScreenshot(ss1);
      });
      act(() => {
        result.current.addScreenshot(ss2);
      });
      act(() => {
        result.current.addScreenshot(ss3);
      });

      expect(result.current.screenshots).toHaveLength(3);
      expect(result.current.screenshots[0].id).toBe('ss-1');
      expect(result.current.screenshots[1].id).toBe('ss-2');
      expect(result.current.screenshots[2].id).toBe('ss-3');
    });

    test('should update ref when adding screenshot', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = {
        id: 'ss-ref',
        name: 'Ref Test',
        thumbnail: 'data:image/png;base64,xyz',
      };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshotsRef.current).toHaveLength(1);
      expect(result.current.screenshotsRef.current[0]).toEqual(screenshot);
    });

    test('should keep state and ref in sync', () => {
      const { result } = renderHook(() => useScreenshots());

      const ss1: Screenshot = { id: 'ss-sync-1', name: 'Sync1', thumbnail: 't1' };
      const ss2: Screenshot = { id: 'ss-sync-2', name: 'Sync2', thumbnail: 't2' };

      act(() => {
        result.current.addScreenshot(ss1);
        result.current.addScreenshot(ss2);
      });

      expect(result.current.screenshots).toEqual(result.current.screenshotsRef.current);
    });
  });

  describe('removeScreenshot', () => {
    test('should remove screenshot by id', () => {
      const { result } = renderHook(() => useScreenshots());

      const ss1: Screenshot = { id: 'ss-1', name: 'First', thumbnail: 't1' };
      const ss2: Screenshot = { id: 'ss-2', name: 'Second', thumbnail: 't2' };
      const ss3: Screenshot = { id: 'ss-3', name: 'Third', thumbnail: 't3' };

      act(() => {
        result.current.addScreenshot(ss1);
        result.current.addScreenshot(ss2);
        result.current.addScreenshot(ss3);
      });

      act(() => {
        result.current.removeScreenshot('ss-2');
      });

      expect(result.current.screenshots).toHaveLength(2);
      expect(result.current.screenshots.find(s => s.id === 'ss-2')).toBeUndefined();
      expect(result.current.screenshots[0].id).toBe('ss-1');
      expect(result.current.screenshots[1].id).toBe('ss-3');
    });

    test('should update ref when removing screenshot', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = { id: 'ss-remove', name: 'Remove', thumbnail: 't' };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshotsRef.current).toHaveLength(1);

      act(() => {
        result.current.removeScreenshot('ss-remove');
      });

      expect(result.current.screenshotsRef.current).toHaveLength(0);
    });

    test('should handle removing non-existent screenshot', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = { id: 'ss-1', name: 'Test', thumbnail: 't' };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      act(() => {
        result.current.removeScreenshot('non-existent-id');
      });

      // Should not throw and should not change the list
      expect(result.current.screenshots).toHaveLength(1);
      expect(result.current.screenshots[0].id).toBe('ss-1');
    });

    test('should handle removing from empty list', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.removeScreenshot('any-id');
      });

      expect(result.current.screenshots).toHaveLength(0);
    });
  });

  describe('clearScreenshots', () => {
    test('should remove all screenshots', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'One', thumbnail: 't1' });
        result.current.addScreenshot({ id: 'ss-2', name: 'Two', thumbnail: 't2' });
        result.current.addScreenshot({ id: 'ss-3', name: 'Three', thumbnail: 't3' });
      });

      expect(result.current.screenshots).toHaveLength(3);

      act(() => {
        result.current.clearScreenshots();
      });

      expect(result.current.screenshots).toHaveLength(0);
      expect(result.current.screenshots).toEqual([]);
    });

    test('should clear ref as well', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'Test', thumbnail: 't' });
      });

      act(() => {
        result.current.clearScreenshots();
      });

      expect(result.current.screenshotsRef.current).toEqual([]);
    });

    test('should be safe to call on empty list', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.clearScreenshots();
      });

      expect(result.current.screenshots).toEqual([]);
    });
  });

  describe('meetingRecordingMode', () => {
    test('should toggle meeting recording mode', () => {
      const { result } = renderHook(() => useScreenshots());

      expect(result.current.meetingRecordingMode).toBe(false);

      act(() => {
        result.current.setMeetingRecordingMode(true);
      });

      expect(result.current.meetingRecordingMode).toBe(true);

      act(() => {
        result.current.setMeetingRecordingMode(false);
      });

      expect(result.current.meetingRecordingMode).toBe(false);
    });

    test('should not affect screenshots when toggling', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'Test', thumbnail: 't' });
      });

      act(() => {
        result.current.setMeetingRecordingMode(true);
      });

      expect(result.current.screenshots).toHaveLength(1);
      expect(result.current.meetingRecordingMode).toBe(true);
    });
  });

  describe('captureMode', () => {
    test('should change capture mode', () => {
      const { result } = renderHook(() => useScreenshots());

      expect(result.current.captureMode).toBe('precision');

      act(() => {
        result.current.setCaptureMode('fullscreen');
      });

      expect(result.current.captureMode).toBe('fullscreen');

      act(() => {
        result.current.setCaptureMode('none');
      });

      expect(result.current.captureMode).toBe('none');

      act(() => {
        result.current.setCaptureMode('precision');
      });

      expect(result.current.captureMode).toBe('precision');
    });

    test('should support all capture mode values', () => {
      const { result } = renderHook(() => useScreenshots());

      const modes: CaptureMode[] = ['fullscreen', 'precision', 'none'];

      for (const mode of modes) {
        act(() => {
          result.current.setCaptureMode(mode);
        });
        expect(result.current.captureMode).toBe(mode);
      }
    });
  });

  describe('getImageData', () => {
    test('should return array of name/thumbnail objects', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'Image 1', thumbnail: 'thumb1' });
        result.current.addScreenshot({ id: 'ss-2', name: 'Image 2', thumbnail: 'thumb2' });
      });

      const imageData = result.current.getImageData();

      expect(imageData).toHaveLength(2);
      expect(imageData[0]).toEqual({ name: 'Image 1', thumbnail: 'thumb1' });
      expect(imageData[1]).toEqual({ name: 'Image 2', thumbnail: 'thumb2' });
    });

    test('should return empty array when no screenshots', () => {
      const { result } = renderHook(() => useScreenshots());

      const imageData = result.current.getImageData();

      expect(imageData).toEqual([]);
    });

    test('should use ref for data (avoid stale closures)', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'Test', thumbnail: 'data' });
      });

      // getImageData uses screenshotsRef.current
      const imageData = result.current.getImageData();
      expect(imageData).toHaveLength(1);
    });

    test('should not include id in returned data', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-secret', name: 'Test', thumbnail: 'thumb' });
      });

      const imageData = result.current.getImageData();
      expect(imageData[0]).not.toHaveProperty('id');
      expect(Object.keys(imageData[0])).toEqual(['name', 'thumbnail']);
    });
  });

  describe('getSnapshot / restoreSnapshot', () => {
    test('should capture current state as snapshot', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'ss-1', name: 'Snap', thumbnail: 't' });
        result.current.setCaptureMode('fullscreen');
        result.current.setMeetingRecordingMode(true);
      });

      let snapshot: ScreenshotSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      expect(snapshot!.screenshots).toHaveLength(1);
      expect(snapshot!.screenshots[0].id).toBe('ss-1');
      expect(snapshot!.captureMode).toBe('fullscreen');
      expect(snapshot!.meetingRecordingMode).toBe(true);
    });

    test('should restore state from snapshot', () => {
      const { result } = renderHook(() => useScreenshots());

      const snapshot: ScreenshotSnapshot = {
        screenshots: [
          { id: 'restored-1', name: 'Restored', thumbnail: 'thumb-restored' },
          { id: 'restored-2', name: 'Restored 2', thumbnail: 'thumb-restored-2' },
        ],
        captureMode: 'none',
        meetingRecordingMode: true,
      };

      act(() => {
        result.current.restoreSnapshot(snapshot);
      });

      expect(result.current.screenshots).toHaveLength(2);
      expect(result.current.screenshots[0].id).toBe('restored-1');
      expect(result.current.screenshots[1].id).toBe('restored-2');
      expect(result.current.captureMode).toBe('none');
      expect(result.current.meetingRecordingMode).toBe(true);
    });

    test('should restore ref as well', () => {
      const { result } = renderHook(() => useScreenshots());

      const snapshot: ScreenshotSnapshot = {
        screenshots: [{ id: 'ref-test', name: 'RefTest', thumbnail: 't' }],
        captureMode: 'precision',
        meetingRecordingMode: false,
      };

      act(() => {
        result.current.restoreSnapshot(snapshot);
      });

      expect(result.current.screenshotsRef.current).toHaveLength(1);
      expect(result.current.screenshotsRef.current[0].id).toBe('ref-test');
    });

    test('snapshot and restore should be symmetric', () => {
      const { result } = renderHook(() => useScreenshots());

      // Set up state
      act(() => {
        result.current.addScreenshot({ id: 'sym-1', name: 'Sym', thumbnail: 'sym-t' });
        result.current.setCaptureMode('fullscreen');
        result.current.setMeetingRecordingMode(true);
      });

      // Take snapshot
      let snapshot: ScreenshotSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      // Clear state
      act(() => {
        result.current.clearScreenshots();
        result.current.setCaptureMode('precision');
        result.current.setMeetingRecordingMode(false);
      });

      // Verify cleared
      expect(result.current.screenshots).toHaveLength(0);
      expect(result.current.captureMode).toBe('precision');

      // Restore
      act(() => {
        result.current.restoreSnapshot(snapshot!);
      });

      // Verify restored
      expect(result.current.screenshots).toHaveLength(1);
      expect(result.current.screenshots[0].id).toBe('sym-1');
      expect(result.current.captureMode).toBe('fullscreen');
      expect(result.current.meetingRecordingMode).toBe(true);
    });

    test('should create independent snapshot copy', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'orig', name: 'Original', thumbnail: 't' });
      });

      let snapshot: ScreenshotSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      // Modify state after snapshot
      act(() => {
        result.current.addScreenshot({ id: 'new', name: 'New', thumbnail: 't2' });
      });

      // Snapshot should be unchanged
      expect(snapshot!.screenshots).toHaveLength(1);
      expect(result.current.screenshots).toHaveLength(2);
    });
  });

  describe('screenshot ordering', () => {
    test('should maintain FIFO order', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshots: Screenshot[] = [
        { id: 'first', name: '1', thumbnail: 't1' },
        { id: 'second', name: '2', thumbnail: 't2' },
        { id: 'third', name: '3', thumbnail: 't3' },
        { id: 'fourth', name: '4', thumbnail: 't4' },
      ];

      act(() => {
        screenshots.forEach(ss => result.current.addScreenshot(ss));
      });

      expect(result.current.screenshots.map(s => s.id)).toEqual([
        'first',
        'second',
        'third',
        'fourth',
      ]);
    });

    test('should preserve order after removal', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: 'a', name: 'A', thumbnail: 't' });
        result.current.addScreenshot({ id: 'b', name: 'B', thumbnail: 't' });
        result.current.addScreenshot({ id: 'c', name: 'C', thumbnail: 't' });
        result.current.addScreenshot({ id: 'd', name: 'D', thumbnail: 't' });
      });

      act(() => {
        result.current.removeScreenshot('b');
      });

      expect(result.current.screenshots.map(s => s.id)).toEqual(['a', 'c', 'd']);
    });

    test('should preserve order in getImageData', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        result.current.addScreenshot({ id: '1', name: 'First', thumbnail: 't1' });
        result.current.addScreenshot({ id: '2', name: 'Second', thumbnail: 't2' });
        result.current.addScreenshot({ id: '3', name: 'Third', thumbnail: 't3' });
      });

      const imageData = result.current.getImageData();
      expect(imageData.map(i => i.name)).toEqual(['First', 'Second', 'Third']);
    });
  });

  describe('edge cases', () => {
    test('should handle screenshots with special characters in name', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = {
        id: 'special',
        name: 'Screenshot <with> "special" & chars',
        thumbnail: 'data:image/png;base64,abc',
      };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshots[0].name).toBe('Screenshot <with> "special" & chars');
    });

    test('should handle large base64 thumbnails', () => {
      const { result } = renderHook(() => useScreenshots());

      const largeBase64 = 'data:image/png;base64,' + 'A'.repeat(100000);
      const screenshot: Screenshot = {
        id: 'large',
        name: 'Large Image',
        thumbnail: largeBase64,
      };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshots[0].thumbnail).toBe(largeBase64);
    });

    test('should handle rapid add/remove operations', () => {
      const { result } = renderHook(() => useScreenshots());

      act(() => {
        for (let i = 0; i < 50; i++) {
          result.current.addScreenshot({ id: `ss-${i}`, name: `SS ${i}`, thumbnail: `t${i}` });
        }
      });

      expect(result.current.screenshots).toHaveLength(50);

      act(() => {
        for (let i = 0; i < 25; i++) {
          result.current.removeScreenshot(`ss-${i * 2}`); // Remove even ids
        }
      });

      expect(result.current.screenshots).toHaveLength(25);
      // Should only have odd ids remaining
      result.current.screenshots.forEach(ss => {
        const id = parseInt(ss.id.replace('ss-', ''));
        expect(id % 2).toBe(1);
      });
    });

    test('should handle empty thumbnail', () => {
      const { result } = renderHook(() => useScreenshots());

      const screenshot: Screenshot = {
        id: 'empty-thumb',
        name: 'No Thumbnail',
        thumbnail: '',
      };

      act(() => {
        result.current.addScreenshot(screenshot);
      });

      expect(result.current.screenshots[0].thumbnail).toBe('');
    });
  });
});
