/**
 * Character-drain streaming animation hook.
 *
 * Buffers incoming text chunks into a queue and drains them at a consistent
 * pace using requestAnimationFrame, creating a smooth character-by-character
 * rendering effect independent of network chunk delivery.
 *
 * Key features:
 * - Character queue decouples network delivery from display speed
 * - rAF drain loop runs at ~60fps, pulling CHARS_PER_FRAME characters per frame
 * - Automatic cleanup on unmount or when streaming ends
 * - Flush callback for instant completion when stream finishes
 */
import { useState, useRef, useCallback, useEffect } from 'react';

/** Number of characters to drain per animation frame (~60fps = 180 chars/sec) */
const CHARS_PER_FRAME = 3;

interface UseStreamingAnimationOptions {
  /** Full raw text from the stream (updated as chunks arrive) */
  rawText: string;
  /** Whether streaming is currently active */
  isStreaming: boolean;
  /** Called when animation catches up to rawText during streaming */
  onCatchUp?: () => void;
}

interface UseStreamingAnimationReturn {
  /** The displayed text (may lag behind rawText during streaming) */
  displayedText: string;
  /** Whether the animation is still draining characters */
  isDraining: boolean;
  /** Instantly flush all remaining characters to display */
  flush: () => void;
}

export function useStreamingAnimation({
  rawText,
  isStreaming,
  onCatchUp,
}: UseStreamingAnimationOptions): UseStreamingAnimationReturn {
  // Initialize displayedText with existing rawText on mount.
  // This ensures pre-existing content (e.g., after tab switch) is shown immediately,
  // and only NEW characters that arrive after mount will be animated.
  const [displayedText, setDisplayedText] = useState(() => rawText);

  // Track the last length we've "seen" to detect new characters.
  // Initialize to current rawText length so we don't re-drain existing content.
  const lastProcessedLengthRef = useRef(rawText.length);

  // Track the previous rawText to detect content replacement (not just growth)
  const prevRawTextRef = useRef(rawText);

  // Character queue: stores characters waiting to be displayed
  const queueRef = useRef<string[]>([]);

  // rAF handle for cleanup
  const rafRef = useRef<number | null>(null);

  // Track if we're actively draining
  const [isDraining, setIsDraining] = useState(false);

  // Stable refs for callbacks to avoid stale closures
  const isStreamingRef = useRef(isStreaming);
  const onCatchUpRef = useRef(onCatchUp);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    onCatchUpRef.current = onCatchUp;
  }, [onCatchUp]);

  // Drain loop: pulls characters from queue and appends to displayedText
  const drainLoop = useCallback(() => {
    const queue = queueRef.current;

    if (queue.length === 0) {
      // Queue empty - stop draining
      setIsDraining(false);
      rafRef.current = null;

      // Notify if we caught up while still streaming
      if (isStreamingRef.current && onCatchUpRef.current) {
        onCatchUpRef.current();
      }
      return;
    }

    // Pull CHARS_PER_FRAME characters from the front of the queue
    const chars = queue.splice(0, CHARS_PER_FRAME);
    setDisplayedText((prev) => prev + chars.join(''));

    // Schedule next frame
    rafRef.current = requestAnimationFrame(drainLoop);
  }, []);

  // Start the drain loop if not already running
  const startDrainLoop = useCallback(() => {
    if (rafRef.current === null && queueRef.current.length > 0) {
      setIsDraining(true);
      rafRef.current = requestAnimationFrame(drainLoop);
    }
  }, [drainLoop]);

  // When rawText changes, push new characters to the queue
  useEffect(() => {
    const prevRawText = prevRawTextRef.current;
    const prevLength = lastProcessedLengthRef.current;
    const newLength = rawText.length;

    // Update prev ref for next comparison
    prevRawTextRef.current = rawText;

    if (newLength > prevLength) {
      // Check if this is a content replacement (tab switch) vs. incremental growth.
      // Content replacement: the new text is longer but doesn't start with the previous text.
      // This happens when switching tabs and the component receives entirely different content.
      const isContentReplacement = prevRawText.length > 0 && !rawText.startsWith(prevRawText);

      if (isContentReplacement) {
        // Content was replaced (e.g., tab switch) - show new content immediately
        queueRef.current = [];
        lastProcessedLengthRef.current = newLength;
        setDisplayedText(rawText);
        setIsDraining(false);
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
        return;
      }

      // Normal incremental growth - extract new characters and push to queue
      const newChars = rawText.slice(prevLength).split('');
      queueRef.current.push(...newChars);
      lastProcessedLengthRef.current = newLength;

      // Start draining if not already
      startDrainLoop();
    } else if (newLength < prevLength) {
      // Text was reset (new stream started) - reset everything and animate new content
      queueRef.current = [];
      lastProcessedLengthRef.current = 0;
      setDisplayedText('');
      setIsDraining(false);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      // If the new text is non-empty, queue those characters for draining
      if (newLength > 0) {
        const newChars = rawText.split('');
        queueRef.current.push(...newChars);
        lastProcessedLengthRef.current = newLength;
        startDrainLoop();
      }
    }
  }, [rawText, startDrainLoop]);

  // Flush: instantly display all remaining characters
  const flush = useCallback(() => {
    // Cancel any pending animation frame
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    // Drain all remaining characters at once
    const queue = queueRef.current;
    if (queue.length > 0) {
      setDisplayedText((prev) => prev + queue.join(''));
      queueRef.current = [];
    }

    setIsDraining(false);
  }, []);

  // Auto-flush when streaming stops
  useEffect(() => {
    if (!isStreaming && queueRef.current.length > 0) {
      flush();
    }
  }, [isStreaming, flush]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      queueRef.current = [];
    };
  }, []);

  return {
    displayedText,
    isDraining,
    flush,
  };
}
