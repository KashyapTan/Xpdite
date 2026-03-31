/**
 * Character-drain streaming animation hook.
 *
 * Incoming text is buffered and drained on rAF ticks. Drain speed adapts to
 * backlog size, and React state commits are throttled for large backlogs to
 * reduce markdown reparse pressure while preserving smooth live output.
 */
import { useState, useRef, useCallback, useEffect } from 'react';

const BASE_CHARS_PER_TICK = 4;
const COMMIT_INTERVAL_MS = 48;
const LARGE_BACKLOG_COMMIT_THRESHOLD = 120;
const CHUNK_COMPACT_THRESHOLD = 32;
const STREAM_DEBUG_FLAG = 'xpdite_stream_debug';

function charsPerTick(backlog: number): number {
  if (backlog >= 4000) return 192;
  if (backlog >= 2000) return 128;
  if (backlog >= 1000) return 96;
  if (backlog >= 500) return 64;
  if (backlog >= 200) return 40;
  if (backlog >= 80) return 20;
  if (backlog >= 40) return 12;
  return BASE_CHARS_PER_TICK;
}

function nowMs(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
}

function isStreamDebugEnabled(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  try {
    return window.localStorage.getItem(STREAM_DEBUG_FLAG) === '1';
  } catch {
    return false;
  }
}

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
  const [displayedTextState, setDisplayedTextState] = useState(() => rawText);
  const displayedTextRef = useRef(rawText);

  const lastProcessedLengthRef = useRef(rawText.length);
  const prevRawTextRef = useRef(rawText);

  const pendingChunksRef = useRef<string[]>([]);
  const pendingChunkIndexRef = useRef(0);
  const pendingChunkOffsetRef = useRef(0);
  const pendingLengthRef = useRef(0);

  const displayBufferRef = useRef(rawText);
  const rafRef = useRef<number | null>(null);
  const lastFrameTimeRef = useRef(0);
  const lastCommitTimeRef = useRef(-COMMIT_INTERVAL_MS);

  const [isDraining, setIsDraining] = useState(false);

  const isStreamingRef = useRef(isStreaming);
  const onCatchUpRef = useRef(onCatchUp);
  const debugEnabledRef = useRef(false);
  const debugStartedAtRef = useRef<number | null>(null);
  const debugMaxBacklogRef = useRef(0);
  const debugDrainedCharsRef = useRef(0);
  const debugCommitCountRef = useRef(0);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    onCatchUpRef.current = onCatchUp;
  }, [onCatchUp]);

  useEffect(() => {
    debugEnabledRef.current = isStreamDebugEnabled();
  }, []);

  const commitDisplayedText = useCallback((nextText: string) => {
    if (displayedTextRef.current === nextText) {
      return;
    }

    displayedTextRef.current = nextText;
    setDisplayedTextState(nextText);
    if (debugEnabledRef.current) {
      debugCommitCountRef.current += 1;
    }
  }, []);

  const clearPendingQueue = useCallback(() => {
    pendingChunksRef.current = [];
    pendingChunkIndexRef.current = 0;
    pendingChunkOffsetRef.current = 0;
    pendingLengthRef.current = 0;
  }, []);

  const compactPendingQueue = useCallback(() => {
    const chunkIndex = pendingChunkIndexRef.current;
    const chunks = pendingChunksRef.current;
    if (chunkIndex < CHUNK_COMPACT_THRESHOLD || chunkIndex < chunks.length / 2) {
      return;
    }

    pendingChunksRef.current = chunks.slice(chunkIndex);
    pendingChunkIndexRef.current = 0;
  }, []);

  const drainChars = useCallback((maxChars: number): string => {
    if (maxChars <= 0 || pendingLengthRef.current <= 0) {
      return '';
    }

    let remaining = maxChars;
    const drainedParts: string[] = [];

    while (remaining > 0 && pendingLengthRef.current > 0) {
      const chunks = pendingChunksRef.current;
      const chunk = chunks[pendingChunkIndexRef.current];
      if (chunk === undefined) {
        clearPendingQueue();
        break;
      }

      const offset = pendingChunkOffsetRef.current;
      const available = chunk.length - offset;
      if (available <= 0) {
        pendingChunkIndexRef.current += 1;
        pendingChunkOffsetRef.current = 0;
        compactPendingQueue();
        continue;
      }

      const take = Math.min(remaining, available);
      drainedParts.push(chunk.slice(offset, offset + take));
      pendingChunkOffsetRef.current += take;
      pendingLengthRef.current -= take;
      remaining -= take;

      if (pendingChunkOffsetRef.current >= chunk.length) {
        pendingChunkIndexRef.current += 1;
        pendingChunkOffsetRef.current = 0;
        compactPendingQueue();
      }
    }

    return drainedParts.join('');
  }, [clearPendingQueue, compactPendingQueue]);

  const drainAllChars = useCallback(() => {
    return drainChars(pendingLengthRef.current);
  }, [drainChars]);

  const finishDebugCycle = useCallback((reason: string) => {
    if (!debugEnabledRef.current) {
      return;
    }

    const startedAt = debugStartedAtRef.current;
    if (startedAt !== null) {
      const duration = nowMs() - startedAt;
      console.debug(
        `[stream-animation] ${reason}: drained=${debugDrainedCharsRef.current} max_backlog=${debugMaxBacklogRef.current} commits=${debugCommitCountRef.current} duration_ms=${Math.round(duration)}`,
      );
    }

    debugStartedAtRef.current = null;
    debugMaxBacklogRef.current = 0;
    debugDrainedCharsRef.current = 0;
    debugCommitCountRef.current = 0;
  }, []);

  const cancelDrainLoop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const stopDraining = useCallback((reason: string) => {
    cancelDrainLoop();
    setIsDraining(false);
    finishDebugCycle(reason);
  }, [cancelDrainLoop, finishDebugCycle]);

  const queueText = useCallback((text: string) => {
    if (!text) {
      return;
    }

    pendingChunksRef.current.push(text);
    pendingLengthRef.current += text.length;

    if (debugEnabledRef.current) {
      if (debugStartedAtRef.current === null) {
        debugStartedAtRef.current = nowMs();
      }
      if (pendingLengthRef.current > debugMaxBacklogRef.current) {
        debugMaxBacklogRef.current = pendingLengthRef.current;
      }
    }
  }, []);

  const drainLoop = useCallback((frameTime?: number) => {
    const resolvedTime = Number.isFinite(frameTime)
      ? Number(frameTime)
      : lastFrameTimeRef.current + 16;
    lastFrameTimeRef.current = resolvedTime;

    const backlogBefore = pendingLengthRef.current;
    if (backlogBefore <= 0) {
      stopDraining('queue-empty');
      if (isStreamingRef.current && onCatchUpRef.current) {
        onCatchUpRef.current();
      }
      return;
    }

    const drained = drainChars(charsPerTick(backlogBefore));
    if (drained) {
      displayBufferRef.current += drained;
      if (debugEnabledRef.current) {
        debugDrainedCharsRef.current += drained.length;
        if (pendingLengthRef.current > debugMaxBacklogRef.current) {
          debugMaxBacklogRef.current = pendingLengthRef.current;
        }
      }
    }

    const shouldCommit = pendingLengthRef.current === 0
      || backlogBefore <= LARGE_BACKLOG_COMMIT_THRESHOLD
      || (resolvedTime - lastCommitTimeRef.current) >= COMMIT_INTERVAL_MS;

    if (shouldCommit) {
      commitDisplayedText(displayBufferRef.current);
      lastCommitTimeRef.current = resolvedTime;
    }

    if (pendingLengthRef.current <= 0) {
      stopDraining('queue-empty');
      if (isStreamingRef.current && onCatchUpRef.current) {
        onCatchUpRef.current();
      }
      return;
    }

    rafRef.current = requestAnimationFrame(drainLoop);
  }, [commitDisplayedText, drainChars, stopDraining]);

  const startDrainLoop = useCallback(() => {
    if (rafRef.current === null && pendingLengthRef.current > 0) {
      setIsDraining(true);
      lastCommitTimeRef.current = lastFrameTimeRef.current - COMMIT_INTERVAL_MS;
      rafRef.current = requestAnimationFrame(drainLoop);
    }
  }, [drainLoop]);

  useEffect(() => {
    const prevRawText = prevRawTextRef.current;
    const prevLength = lastProcessedLengthRef.current;
    const newLength = rawText.length;

    prevRawTextRef.current = rawText;

    if (newLength > prevLength) {
      const isContentReplacement = prevRawText.length > 0 && !rawText.startsWith(prevRawText);

      if (isContentReplacement) {
        stopDraining('content-replaced');
        clearPendingQueue();
        displayBufferRef.current = rawText;
        lastProcessedLengthRef.current = newLength;
        commitDisplayedText(rawText);
        return;
      }

      queueText(rawText.slice(prevLength));
      lastProcessedLengthRef.current = newLength;
      startDrainLoop();
    } else if (newLength < prevLength) {
      stopDraining('text-reset');
      clearPendingQueue();
      displayBufferRef.current = '';
      lastProcessedLengthRef.current = 0;
      commitDisplayedText('');

      if (newLength > 0) {
        queueText(rawText);
        lastProcessedLengthRef.current = newLength;
        startDrainLoop();
      }
    }
  }, [
    clearPendingQueue,
    commitDisplayedText,
    queueText,
    rawText,
    startDrainLoop,
    stopDraining,
  ]);

  const flush = useCallback(() => {
    cancelDrainLoop();

    const remaining = drainAllChars();
    if (remaining) {
      displayBufferRef.current += remaining;
    }

    commitDisplayedText(displayBufferRef.current);
    setIsDraining(false);
    finishDebugCycle('flush');
  }, [cancelDrainLoop, commitDisplayedText, drainAllChars, finishDebugCycle]);

  useEffect(() => {
    if (!isStreaming && pendingLengthRef.current > 0) {
      flush();
    }
  }, [isStreaming, flush]);

  useEffect(() => {
    return () => {
      cancelDrainLoop();
      clearPendingQueue();
      finishDebugCycle('unmount');
    };
  }, [cancelDrainLoop, clearPendingQueue, finishDebugCycle]);

  return {
    displayedText: displayedTextState,
    isDraining,
    flush,
  };
}
