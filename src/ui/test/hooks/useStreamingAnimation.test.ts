/**
 * Tests for useStreamingAnimation hook.
 */
import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useStreamingAnimation } from '../../hooks/useStreamingAnimation';

describe('useStreamingAnimation', () => {
  // Mock requestAnimationFrame/cancelAnimationFrame
  let rafCallbacks: Array<() => void> = [];
  let rafId = 0;

  beforeEach(() => {
    rafCallbacks = [];
    rafId = 0;

    vi.stubGlobal('requestAnimationFrame', (cb: () => void) => {
      rafCallbacks.push(cb);
      return ++rafId;
    });

    vi.stubGlobal('cancelAnimationFrame', () => {
      // In tests, we just track that cancel was called
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // Helper to flush all pending rAF callbacks (simulates frames)
  function flushRafCallbacks() {
    while (rafCallbacks.length > 0) {
      const cb = rafCallbacks.shift()!;
      cb();
    }
  }

  // Helper to run N frames
  function runFrames(n: number) {
    for (let i = 0; i < n; i++) {
      if (rafCallbacks.length > 0) {
        const cb = rafCallbacks.shift()!;
        cb();
      }
    }
  }

  describe('initial state', () => {
    test('should have empty displayedText initially', () => {
      const { result } = renderHook(() =>
        useStreamingAnimation({
          rawText: '',
          isStreaming: false,
        }),
      );

      expect(result.current.displayedText).toBe('');
      expect(result.current.isDraining).toBe(false);
    });

    test('should not start draining when rawText is empty', () => {
      renderHook(() =>
        useStreamingAnimation({
          rawText: '',
          isStreaming: true,
        }),
      );

      expect(rafCallbacks.length).toBe(0);
    });
  });

  describe('character draining', () => {
    test('should start draining when rawText changes during streaming', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // Add some text
      rerender({ rawText: 'Hello', isStreaming: true });

      // rAF should be scheduled
      expect(rafCallbacks.length).toBe(1);
      expect(result.current.isDraining).toBe(true);
    });

    test('should drain 3 characters per frame (CHARS_PER_FRAME)', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // Add 9 characters
      rerender({ rawText: 'abcdefghi', isStreaming: true });

      // First frame: drain 'abc'
      act(() => runFrames(1));
      expect(result.current.displayedText).toBe('abc');

      // Second frame: drain 'def'
      act(() => runFrames(1));
      expect(result.current.displayedText).toBe('abcdef');

      // Third frame: drain 'ghi'
      act(() => runFrames(1));
      expect(result.current.displayedText).toBe('abcdefghi');
    });

    test('should stop draining when queue is empty', async () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      rerender({ rawText: 'abc', isStreaming: true });

      // Drain all characters
      act(() => flushRafCallbacks());

      expect(result.current.displayedText).toBe('abc');
      expect(result.current.isDraining).toBe(false);
    });
  });

  describe('flush behavior', () => {
    test('should instantly display all remaining characters when flush is called', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      rerender({ rawText: 'Hello World!', isStreaming: true });

      // Don't drain any characters yet
      expect(result.current.displayedText).toBe('');

      // Call flush
      act(() => {
        result.current.flush();
      });

      // All characters should appear instantly
      expect(result.current.displayedText).toBe('Hello World!');
      expect(result.current.isDraining).toBe(false);
    });

    test('should auto-flush when streaming stops', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // Start streaming some text
      rerender({ rawText: 'Hello World!', isStreaming: true });

      // Drain only some characters
      act(() => runFrames(1)); // 'Hel'
      expect(result.current.displayedText).toBe('Hel');

      // Stop streaming - should auto-flush remaining
      act(() => {
        rerender({ rawText: 'Hello World!', isStreaming: false });
      });

      expect(result.current.displayedText).toBe('Hello World!');
      expect(result.current.isDraining).toBe(false);
    });
  });

  describe('stream reset', () => {
    test('should reset state when rawText shrinks (new stream started)', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // First stream
      rerender({ rawText: 'First stream content', isStreaming: true });
      act(() => flushRafCallbacks());
      expect(result.current.displayedText).toBe('First stream content');

      // New stream starts with shorter text (reset detected)
      act(() => {
        rerender({ rawText: 'New', isStreaming: true });
      });

      // State should be reset
      expect(result.current.displayedText).toBe('');

      // Then drain the new content
      act(() => flushRafCallbacks());
      expect(result.current.displayedText).toBe('New');
    });
  });

  describe('onCatchUp callback', () => {
    test('should call onCatchUp when queue empties during streaming', async () => {
      const onCatchUp = vi.fn();

      const { rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming, onCatchUp }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      rerender({ rawText: 'abc', isStreaming: true });

      // Drain all characters
      act(() => flushRafCallbacks());

      expect(onCatchUp).toHaveBeenCalledTimes(1);
    });

    test('should not call onCatchUp when streaming is false', () => {
      const onCatchUp = vi.fn();

      const { rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming, onCatchUp }),
        {
          initialProps: { rawText: '', isStreaming: false },
        },
      );

      rerender({ rawText: 'abc', isStreaming: false });

      // Flush runs because isStreaming is false
      expect(onCatchUp).not.toHaveBeenCalled();
    });
  });

  describe('cleanup', () => {
    test('should cancel rAF on unmount', () => {
      const cancelSpy = vi.fn();
      vi.stubGlobal('cancelAnimationFrame', cancelSpy);

      const { rerender, unmount } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // Start draining
      rerender({ rawText: 'Hello World!', isStreaming: true });

      // Unmount should cancel the pending rAF
      unmount();

      expect(cancelSpy).toHaveBeenCalled();
    });
  });

  describe('non-streaming mode', () => {
    test('should immediately flush content when isStreaming is false (history messages)', () => {
      const { result } = renderHook(() =>
        useStreamingAnimation({
          rawText: 'Pre-existing content',
          isStreaming: false,
        }),
      );

      // When isStreaming is false, content should be flushed immediately
      // This is the desired behavior for rendering history messages
      expect(result.current.displayedText).toBe('Pre-existing content');
      expect(result.current.isDraining).toBe(false);
    });
  });

  describe('tab switching (remount with existing content)', () => {
    test('should show existing content immediately on mount during streaming', () => {
      // Simulates: user switches away and back to a tab that was mid-stream
      // The component remounts with existing rawText and isStreaming=true
      const { result } = renderHook(() =>
        useStreamingAnimation({
          rawText: 'Already streamed content',
          isStreaming: true,
        }),
      );

      // Existing content should appear immediately, not be re-drained
      expect(result.current.displayedText).toBe('Already streamed content');
      expect(result.current.isDraining).toBe(false);
      expect(rafCallbacks.length).toBe(0); // No draining scheduled
    });

    test('should only animate NEW characters after remount', () => {
      // Mount with existing content
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: 'Hello', isStreaming: true },
        },
      );

      // Existing content shown immediately
      expect(result.current.displayedText).toBe('Hello');
      expect(rafCallbacks.length).toBe(0);

      // New content arrives
      rerender({ rawText: 'Hello World', isStreaming: true });

      // Only " World" (6 new chars) should be queued for draining
      expect(rafCallbacks.length).toBe(1);

      // Drain the new characters
      act(() => runFrames(1)); // 3 chars: ' Wo'
      expect(result.current.displayedText).toBe('Hello Wo');

      act(() => runFrames(1)); // 3 chars: 'rld'
      expect(result.current.displayedText).toBe('Hello World');
    });

    test('should show content immediately when rawText is replaced entirely (tab switch)', () => {
      // Mount with content from tab A
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: 'Content from Tab A', isStreaming: true },
        },
      );

      expect(result.current.displayedText).toBe('Content from Tab A');

      // User switches to Tab B which has completely different content (longer)
      // This simulates the rerender that happens when tab content changes
      rerender({ rawText: 'Completely different content from Tab B', isStreaming: true });

      // Content should appear immediately without draining
      expect(result.current.displayedText).toBe('Completely different content from Tab B');
      expect(result.current.isDraining).toBe(false);
      expect(rafCallbacks.length).toBe(0); // No draining scheduled
    });

    test('should handle switching between tabs with different streaming states', () => {
      // Tab A is streaming
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: 'Tab A content', isStreaming: true },
        },
      );

      expect(result.current.displayedText).toBe('Tab A content');

      // Switch to Tab B which is not streaming (history)
      rerender({ rawText: 'Tab B historical content', isStreaming: false });

      // Should show immediately (content replacement + not streaming)
      expect(result.current.displayedText).toBe('Tab B historical content');
      expect(result.current.isDraining).toBe(false);

      // Switch back to Tab A which is still streaming with more content
      rerender({ rawText: 'Tab A different content now', isStreaming: true });

      // Should show immediately (content replacement)
      expect(result.current.displayedText).toBe('Tab A different content now');
      expect(result.current.isDraining).toBe(false);
    });
  });

  describe('accumulated chunks', () => {
    test('should handle multiple rapid rawText updates', () => {
      const { result, rerender } = renderHook(
        ({ rawText, isStreaming }) =>
          useStreamingAnimation({ rawText, isStreaming }),
        {
          initialProps: { rawText: '', isStreaming: true },
        },
      );

      // Simulate rapid chunks arriving
      rerender({ rawText: 'He', isStreaming: true });
      rerender({ rawText: 'Hell', isStreaming: true });
      rerender({ rawText: 'Hello', isStreaming: true });

      // All characters should be queued
      // After first frame, we should have 3 chars
      act(() => runFrames(1));
      expect(result.current.displayedText).toBe('Hel');

      // After second frame, remaining 2 chars
      act(() => runFrames(1));
      expect(result.current.displayedText).toBe('Hello');
    });
  });
});
