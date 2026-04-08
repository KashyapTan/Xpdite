import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  type RefObject,
  useRef,
  useState,
} from 'react';
import { ChatMessage } from './ChatMessage';
import type {
  ArtifactBlockData,
  ChatMessage as ChatMessageType,
  ContentBlock,
  ToolCall,
} from '../../types';
import { estimateChatMessageHeight } from '../../utils/pretextMessageLayout';
import { logPerf } from '../../utils/perfLogger';

interface DeferredChatHistoryProps {
  chatHistory: ChatMessageType[];
  generatingModel: string;
  canSubmit: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
  onArtifactUpdated?: (artifact: ArtifactBlockData) => void;
  onArtifactDeleted?: (artifactId: string) => void;
  containerRef: RefObject<HTMLDivElement | null>;
}

type VirtualizationCycle = {
  reason: 'opened-virtualized-chat' | 'large-history-jump' | 'switched-virtualized-chat';
  startedAt: number;
  totalRows: number;
  totalChars: number;
  maxRowChars: number;
  decisionReason: string;
  estimatePassMs: number;
  startHeightVersion: number;
  containerWidth: number;
  viewportHeight: number;
};

type VirtualizationDecision = {
  enabled: boolean;
  reason: string;
  totalContentChars: number;
  maxRowChars: number;
  byRowCount: boolean;
  byTotalChars: boolean;
  bySingleRowChars: boolean;
  blockedByStabilityFloor: boolean;
};

const VIRTUALIZATION_MESSAGE_THRESHOLD = 20;
const VIRTUALIZATION_TOTAL_CHARS_THRESHOLD = 18000;
const VIRTUALIZATION_SINGLE_MESSAGE_CHARS_THRESHOLD = 4500;
const VIRTUALIZATION_STABILITY_ROW_FLOOR = 10;
const LARGE_JUMP_DELTA = 12;
const OVERSCAN_PX = 1400;
const DEFAULT_ESTIMATED_MESSAGE_HEIGHT = 280;
const MIN_VIEWPORT_HEIGHT = 240;
const MAX_VISIBLE_ROW_MEASURES = 80;

type PendingHeightUpdate = {
  height: number;
  signature: string;
};

function compactTextSignature(text: string): string {
  if (!text) {
    return '0::';
  }

  const leading = text.slice(0, 64);
  const trailing = text.slice(-64);
  return `${text.length}:${leading}:${trailing}`;
}

function approximateValueChars(value: unknown, depth = 0): number {
  if (typeof value === 'string') {
    return value.length;
  }

  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return 12;
  }

  if (value === null || value === undefined) {
    return 0;
  }

  if (depth >= 2) {
    return 32;
  }

  if (Array.isArray(value)) {
    let total = 0;
    for (const item of value) {
      total += approximateValueChars(item, depth + 1);
    }
    return total;
  }

  if (typeof value === 'object') {
    let total = 0;
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      total += key.length;
      total += approximateValueChars(entry, depth + 1);
    }
    return total;
  }

  return 0;
}

function estimateToolCallChars(toolCall: ToolCall): number {
  return toolCall.name.length
    + toolCall.server.length
    + approximateValueChars(toolCall.args)
    + approximateValueChars(toolCall.result)
    + approximateValueChars(toolCall.description)
    + approximateValueChars(toolCall.partialResult);
}

function safeStringLength(value: unknown): number {
  return typeof value === 'string' ? value.length : 0;
}

function estimateContentBlockChars(block: ContentBlock): number {
  if (block.type === 'text' || block.type === 'thinking') {
    return block.content.length;
  }

  if (block.type === 'tool_call') {
    return estimateToolCallChars(block.toolCall);
  }

  if (block.type === 'terminal_command') {
    return block.terminal.command.length
      + block.terminal.cwd.length
      + block.terminal.output.length;
  }

  if (block.type === 'artifact') {
    return block.artifact.title.length
      + (block.artifact.language?.length ?? 0)
      + (block.artifact.content?.length ?? 0);
  }

  return safeStringLength(block.approval.title)
    + safeStringLength(block.approval.channel)
    + safeStringLength(block.approval.noCaptionsReason)
    + safeStringLength(block.approval.totalTimeEstimate);
}

function estimateMessageContentChars(message: ChatMessageType): number {
  let total = message.content.length;

  if (message.thinking) {
    total += message.thinking.length;
  }

  if (message.images && message.images.length > 0) {
    total += message.images.length * 60;
  }

  if (message.contentBlocks && message.contentBlocks.length > 0) {
    for (const block of message.contentBlocks) {
      total += estimateContentBlockChars(block);
    }
    return total;
  }

  if (message.toolCalls && message.toolCalls.length > 0) {
    for (const toolCall of message.toolCalls) {
      total += estimateToolCallChars(toolCall);
    }
  }

  return total;
}

function contentBlocksMeasurementSignature(blocks: ContentBlock[] | undefined): string {
  if (!blocks || blocks.length === 0) {
    return 'none';
  }

  let textChars = 0;
  let thinkingChars = 0;
  let toolCalling = 0;
  let toolComplete = 0;
  let terminalActive = 0;
  let terminalDone = 0;
  let artifactsReady = 0;
  let artifactsDeleted = 0;
  let approvalsPending = 0;
  let approvalsResolved = 0;

  for (const block of blocks) {
    if (block.type === 'text') {
      textChars += block.content.length;
      continue;
    }

    if (block.type === 'thinking') {
      thinkingChars += block.content.length;
      continue;
    }

    if (block.type === 'tool_call') {
      if (block.toolCall.status === 'complete') {
        toolComplete += 1;
      } else {
        toolCalling += 1;
      }
      continue;
    }

    if (block.type === 'terminal_command') {
      if (block.terminal.status === 'completed' || block.terminal.status === 'denied') {
        terminalDone += 1;
      } else {
        terminalActive += 1;
      }
      continue;
    }

    if (block.type === 'artifact') {
      if (block.artifact.status === 'deleted') {
        artifactsDeleted += 1;
      } else {
        artifactsReady += 1;
      }
      continue;
    }

    if (block.approval.status === 'pending') {
      approvalsPending += 1;
    } else {
      approvalsResolved += 1;
    }
  }

  return `${blocks.length}:${textChars}:${thinkingChars}:${toolCalling}:${toolComplete}:${terminalActive}:${terminalDone}:${artifactsReady}:${artifactsDeleted}:${approvalsPending}:${approvalsResolved}`;
}

function messageLayoutSignature(
  message: ChatMessageType,
  index: number,
  selectedModel: string,
): string {
  return [
    message.messageId ?? `${message.role}-${index}`,
    String(message.timestamp ?? 0),
    compactTextSignature(message.content),
    compactTextSignature(message.thinking ?? ''),
    String(message.activeResponseIndex ?? -1),
    contentBlocksMeasurementSignature(message.contentBlocks),
    String(message.images?.length ?? 0),
    selectedModel,
  ].join('|');
}

function nowMs(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
}

function messageKey(message: ChatMessageType, index: number): string {
  return message.messageId ?? `${message.role}-${message.timestamp ?? 'na'}-${index}`;
}

function findStartIndex(positions: number[], target: number): number {
  let low = 0;
  let high = positions.length - 1;
  let answer = 0;

  while (low <= high) {
    const mid = (low + high) >> 1;
    if (positions[mid] <= target) {
      answer = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return answer;
}

function findEndIndex(positions: number[], heights: number[], target: number): number {
  let low = 0;
  let high = positions.length - 1;
  let answer = positions.length - 1;

  while (low <= high) {
    const mid = (low + high) >> 1;
    const rowEnd = positions[mid] + heights[mid];
    if (rowEnd >= target) {
      answer = mid;
      high = mid - 1;
    } else {
      low = mid + 1;
    }
  }

  return answer;
}

const MeasuredChatMessage = memo(function MeasuredChatMessage({
  index,
  message,
  selectedModel,
  actionsDisabled,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
  onArtifactUpdated,
  onArtifactDeleted,
  onHeight,
}: {
  index: number;
  message: ChatMessageType;
  selectedModel: string;
  actionsDisabled: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
  onArtifactUpdated?: (artifact: ArtifactBlockData) => void;
  onArtifactDeleted?: (artifactId: string) => void;
  onHeight: (index: number, height: number, signature: string) => void;
}) {
  const rowRef = useRef<HTMLDivElement | null>(null);
  const measurementSignature = useMemo(() => {
    return messageLayoutSignature(message, index, selectedModel);
  }, [
    index,
    message,
    selectedModel,
  ]);

  useLayoutEffect(() => {
    const node = rowRef.current;
    if (!node) {
      return;
    }

    const publishHeight = () => {
      const measured = Math.ceil(node.getBoundingClientRect().height);
      if (measured > 0) {
        onHeight(index, measured, measurementSignature);
      }
    };

    publishHeight();

    if (typeof ResizeObserver === 'undefined') {
      return;
    }

    const observer = new ResizeObserver(() => publishHeight());
    observer.observe(node);
    return () => observer.disconnect();
  }, [index, measurementSignature, onHeight]);

  return (
    <div ref={rowRef} data-virtual-row-index={index} style={{ flex: '0 0 auto' }}>
      <ChatMessage
        message={message}
        selectedModel={selectedModel}
        actionsDisabled={actionsDisabled}
        onRetryMessage={onRetryMessage}
        onEditMessage={onEditMessage}
        onSetActiveResponse={onSetActiveResponse}
        onArtifactUpdated={onArtifactUpdated}
        onArtifactDeleted={onArtifactDeleted}
      />
    </div>
  );
});

export default function DeferredChatHistory({
  chatHistory,
  generatingModel,
  canSubmit,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
  onArtifactUpdated,
  onArtifactDeleted,
  containerRef,
}: DeferredChatHistoryProps) {
  const virtualizationDecision = useMemo<VirtualizationDecision>(() => {
    let totalContentChars = 0;
    let maxRowChars = 0;

    for (const message of chatHistory) {
      const rowChars = estimateMessageContentChars(message);
      totalContentChars += rowChars;
      if (rowChars > maxRowChars) {
        maxRowChars = rowChars;
      }
    }

    const byRowCount = chatHistory.length >= VIRTUALIZATION_MESSAGE_THRESHOLD;
    const byTotalChars = totalContentChars >= VIRTUALIZATION_TOTAL_CHARS_THRESHOLD;
    const bySingleRowChars = maxRowChars >= VIRTUALIZATION_SINGLE_MESSAGE_CHARS_THRESHOLD;
    const blockedByStabilityFloor = !byRowCount
      && chatHistory.length > 0
      && chatHistory.length < VIRTUALIZATION_STABILITY_ROW_FLOOR;

    const enabled = !blockedByStabilityFloor && (byRowCount || byTotalChars || bySingleRowChars);

    let reason = 'none';
    if (byRowCount) {
      reason = 'row-count-threshold';
    } else if (byTotalChars) {
      reason = 'total-content-chars-threshold';
    } else if (bySingleRowChars) {
      reason = 'single-message-chars-threshold';
    }

    if (blockedByStabilityFloor) {
      reason = 'stability-row-floor';
    }

    return {
      enabled,
      reason,
      totalContentChars,
      maxRowChars,
      byRowCount,
      byTotalChars,
      bySingleRowChars,
      blockedByStabilityFloor,
    };
  }, [chatHistory]);

  const virtualizationEnabled = virtualizationDecision.enabled;
  const heightOverridesRef = useRef<Map<number, number>>(new Map());
  const heightOverrideSignaturesRef = useRef<Map<number, string>>(new Map());
  const rafRef = useRef<number | null>(null);
  const previousWidthRef = useRef(0);
  const previousHistoryRef = useRef<{ length: number; firstKey: string; virtualized: boolean }>({
    length: 0,
    firstKey: '',
    virtualized: false,
  });
  const previousDecisionSignatureRef = useRef('');
  const cycleRef = useRef<VirtualizationCycle | null>(null);
  const activeVisibleRangeRef = useRef({ start: 0, end: Number.MAX_SAFE_INTEGER });
  const pendingHeightUpdatesRef = useRef<Map<number, PendingHeightUpdate>>(new Map());
  const pendingHeightRafRef = useRef<number | null>(null);

  const [heightVersion, setHeightVersion] = useState(0);
  const [viewportState, setViewportState] = useState({ scrollTop: 0, height: 0, width: 0 });

  useEffect(() => {
    if (chatHistory.length > 0) {
      return;
    }
    if (heightOverridesRef.current.size > 0) {
      heightOverridesRef.current.clear();
      heightOverrideSignaturesRef.current.clear();
      setHeightVersion((current) => current + 1);
    }
    if (pendingHeightRafRef.current !== null) {
      cancelAnimationFrame(pendingHeightRafRef.current);
      pendingHeightRafRef.current = null;
    }
    pendingHeightUpdatesRef.current.clear();
    cycleRef.current = null;
    previousHistoryRef.current = { length: 0, firstKey: '', virtualized: false };
  }, [chatHistory.length]);

  useEffect(() => {
    const pendingHeightUpdates = pendingHeightUpdatesRef.current;
    return () => {
      if (pendingHeightRafRef.current !== null) {
        cancelAnimationFrame(pendingHeightRafRef.current);
      }
      pendingHeightRafRef.current = null;
      pendingHeightUpdates.clear();
    };
  }, []);

  useEffect(() => {
    if (!virtualizationEnabled) {
      return;
    }

    const container = containerRef.current;
    if (!container) {
      return;
    }

    const updateViewport = () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }

      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        setViewportState((previous) => {
          const next = {
            scrollTop: container.scrollTop,
            height: container.clientHeight,
            width: container.clientWidth,
          };

          if (
            previous.scrollTop === next.scrollTop
            && previous.height === next.height
            && previous.width === next.width
          ) {
            return previous;
          }

          return next;
        });
      });
    };

    updateViewport();
    container.addEventListener('scroll', updateViewport, { passive: true });

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => updateViewport());
      resizeObserver.observe(container);
    }

    return () => {
      container.removeEventListener('scroll', updateViewport);
      resizeObserver?.disconnect();
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [containerRef, virtualizationEnabled]);

  const estimatedInnerWidth = useMemo(() => {
    const fallback = containerRef.current?.clientWidth ?? 420;
    const width = viewportState.width > 0 ? viewportState.width : fallback;
    return Math.max(160, width - 28);
  }, [containerRef, viewportState.width]);

  useEffect(() => {
    if (!virtualizationEnabled) {
      previousWidthRef.current = estimatedInnerWidth;
      return;
    }

    const previous = previousWidthRef.current;
    previousWidthRef.current = estimatedInnerWidth;
    if (previous === 0 || Math.abs(previous - estimatedInnerWidth) < 24) {
      return;
    }

    if (heightOverridesRef.current.size > 0) {
      heightOverridesRef.current.clear();
      heightOverrideSignaturesRef.current.clear();
      setHeightVersion((current) => current + 1);
    }
  }, [estimatedInnerWidth, virtualizationEnabled]);

  useEffect(() => {
    if (!virtualizationEnabled || chatHistory.length === 0) {
      return;
    }

    const firstKey = messageKey(chatHistory[0], 0);
    const previousFirstKey = previousHistoryRef.current.firstKey;
    if (previousFirstKey === '' || previousFirstKey === firstKey) {
      return;
    }

    if (heightOverridesRef.current.size > 0) {
      heightOverridesRef.current.clear();
      heightOverrideSignaturesRef.current.clear();
      setHeightVersion((current) => current + 1);
    }
  }, [chatHistory, virtualizationEnabled]);

  const rowSignatures = useMemo(() => {
    return chatHistory.map((message, index) => (
      messageLayoutSignature(message, index, generatingModel)
    ));
  }, [chatHistory, generatingModel]);

  const estimation = useMemo(() => {
    const startedAt = nowMs();
    const overrides = heightOverridesRef.current;
    const overrideSignatures = heightOverrideSignaturesRef.current;

    const heights = chatHistory.map((message, index) => {
      const expectedSignature = rowSignatures[index];
      const measured = overrides.get(index);
      const measuredSignature = overrideSignatures.get(index);
      if (typeof measured === 'number' && measuredSignature === expectedSignature) {
        return measured;
      }

      if (typeof measured === 'number' || measuredSignature !== undefined) {
        overrides.delete(index);
        overrideSignatures.delete(index);
      }

      const estimated = estimateChatMessageHeight(message, estimatedInnerWidth);
      if (!Number.isFinite(estimated) || estimated <= 0) {
        return DEFAULT_ESTIMATED_MESSAGE_HEIGHT;
      }
      return estimated;
    });

    return {
      heights,
      estimatePassMs: Math.round(nowMs() - startedAt),
      versionMarker: heightVersion,
    };
  }, [chatHistory, estimatedInnerWidth, heightVersion, rowSignatures]);

  const estimatedHeights = estimation.heights;

  const positions = useMemo(() => {
    const next: number[] = new Array(estimatedHeights.length);
    let running = 0;

    for (let index = 0; index < estimatedHeights.length; index += 1) {
      next[index] = running;
      running += estimatedHeights[index];
    }

    return next;
  }, [estimatedHeights]);

  const totalHeight = useMemo(() => {
    if (estimatedHeights.length === 0) {
      return 0;
    }

    const last = estimatedHeights.length - 1;
    return positions[last] + estimatedHeights[last];
  }, [estimatedHeights, positions]);

  const range = useMemo(() => {
    if (!virtualizationEnabled || chatHistory.length === 0) {
      return { start: 0, end: Math.max(0, chatHistory.length - 1) };
    }

    const viewportTop = Math.max(0, viewportState.scrollTop - OVERSCAN_PX);
    const viewportBottom = viewportState.scrollTop
      + Math.max(MIN_VIEWPORT_HEIGHT, viewportState.height)
      + OVERSCAN_PX;

    const start = findStartIndex(positions, viewportTop);
    const end = findEndIndex(positions, estimatedHeights, viewportBottom);

    return {
      start: Math.max(0, Math.min(start, chatHistory.length - 1)),
      end: Math.max(0, Math.min(end, chatHistory.length - 1)),
    };
  }, [chatHistory.length, estimatedHeights, positions, viewportState.height, viewportState.scrollTop, virtualizationEnabled]);

  const visibleItems = useMemo(() => {
    if (!virtualizationEnabled || chatHistory.length === 0) {
      return [];
    }

    const rows: Array<{ index: number; message: ChatMessageType }> = [];
    for (let index = range.start; index <= range.end; index += 1) {
      rows.push({
        index,
        message: chatHistory[index],
      });
    }
    return rows;
  }, [chatHistory, range.end, range.start, virtualizationEnabled]);

  const topSpacer = virtualizationEnabled && chatHistory.length > 0 ? positions[range.start] : 0;
  const bottomSpacer = virtualizationEnabled && chatHistory.length > 0
    ? Math.max(0, totalHeight - (positions[range.end] + estimatedHeights[range.end]))
    : 0;

  const measuredCount = heightOverridesRef.current.size;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const previousScrollBehavior = container.style.scrollBehavior;
    container.style.scrollBehavior = virtualizationEnabled ? 'auto' : 'smooth';
    return () => {
      container.style.scrollBehavior = previousScrollBehavior;
    };
  }, [containerRef, virtualizationEnabled]);

  useEffect(() => {
    activeVisibleRangeRef.current = { start: range.start, end: range.end };
  }, [range.end, range.start]);

  const handleMeasuredHeight = useCallback((index: number, height: number, signature: string) => {
    const visible = activeVisibleRangeRef.current;
    if (index < visible.start || index > visible.end) {
      return;
    }

    const visibleCount = visible.end - visible.start + 1;
    if (visible.end !== Number.MAX_SAFE_INTEGER && visibleCount > MAX_VISIBLE_ROW_MEASURES) {
      const stride = Math.ceil(visibleCount / MAX_VISIBLE_ROW_MEASURES);
      const relativeIndex = index - visible.start;
      const distanceFromEnd = visible.end - index;
      const shouldAlwaysMeasure = relativeIndex <= 1 || distanceFromEnd <= 1;
      const isStrideSample = relativeIndex % stride === 0;
      if (!shouldAlwaysMeasure && !isStrideSample) {
        return;
      }
    }

    const pendingValue = pendingHeightUpdatesRef.current.get(index);
    if (
      pendingValue
      && pendingValue.signature === signature
      && Math.abs(pendingValue.height - height) <= 1
    ) {
      return;
    }

    const previous = heightOverridesRef.current.get(index);
    const previousSignature = heightOverrideSignaturesRef.current.get(index);
    if (
      typeof previous === 'number'
      && previousSignature === signature
      && Math.abs(previous - height) <= 1
      && pendingValue === undefined
    ) {
      return;
    }

    pendingHeightUpdatesRef.current.set(index, { height, signature });
    if (pendingHeightRafRef.current !== null) {
      return;
    }

    pendingHeightRafRef.current = requestAnimationFrame(() => {
      pendingHeightRafRef.current = null;
      if (pendingHeightUpdatesRef.current.size === 0) {
        return;
      }

      let hasChanges = false;
      for (const [pendingIndex, pendingUpdate] of pendingHeightUpdatesRef.current) {
        const current = heightOverridesRef.current.get(pendingIndex);
        const currentSignature = heightOverrideSignaturesRef.current.get(pendingIndex);
        if (
          typeof current === 'number'
          && currentSignature === pendingUpdate.signature
          && Math.abs(current - pendingUpdate.height) <= 1
        ) {
          continue;
        }
        heightOverridesRef.current.set(pendingIndex, pendingUpdate.height);
        heightOverrideSignaturesRef.current.set(pendingIndex, pendingUpdate.signature);
        hasChanges = true;
      }

      pendingHeightUpdatesRef.current.clear();
      if (hasChanges) {
        setHeightVersion((current) => current + 1);
      }
    });
  }, []);

  useEffect(() => {
    if (chatHistory.length === 0 && !virtualizationEnabled) {
      return;
    }

    const signature = [
      chatHistory.length,
      virtualizationEnabled ? 1 : 0,
      virtualizationDecision.reason,
      virtualizationDecision.totalContentChars,
      virtualizationDecision.maxRowChars,
    ].join('|');
    if (signature === previousDecisionSignatureRef.current) {
      return;
    }
    previousDecisionSignatureRef.current = signature;

    logPerf(
      `[chat-performance] event=virtualization_mode enabled=${virtualizationEnabled ? 'true' : 'false'} `
      + `reason=${virtualizationDecision.reason} rows=${chatHistory.length} `
      + `total_content_chars=${virtualizationDecision.totalContentChars} max_row_chars=${virtualizationDecision.maxRowChars} `
      + `by_row_count=${virtualizationDecision.byRowCount ? 'true' : 'false'} `
      + `by_total_chars=${virtualizationDecision.byTotalChars ? 'true' : 'false'} `
      + `by_single_row_chars=${virtualizationDecision.bySingleRowChars ? 'true' : 'false'} `
      + `blocked_by_stability_floor=${virtualizationDecision.blockedByStabilityFloor ? 'true' : 'false'} `
      + `row_count_threshold=${VIRTUALIZATION_MESSAGE_THRESHOLD} `
      + `stability_row_floor=${VIRTUALIZATION_STABILITY_ROW_FLOOR} `
      + `total_chars_threshold=${VIRTUALIZATION_TOTAL_CHARS_THRESHOLD} `
      + `single_row_chars_threshold=${VIRTUALIZATION_SINGLE_MESSAGE_CHARS_THRESHOLD}`,
    );
  }, [
    chatHistory.length,
    virtualizationDecision.byRowCount,
    virtualizationDecision.bySingleRowChars,
    virtualizationDecision.byTotalChars,
    virtualizationDecision.blockedByStabilityFloor,
    virtualizationDecision.maxRowChars,
    virtualizationDecision.reason,
    virtualizationDecision.totalContentChars,
    virtualizationEnabled,
  ]);

  useEffect(() => {
    const nextLength = chatHistory.length;
    const nextFirstKey = nextLength > 0 ? messageKey(chatHistory[0], 0) : '';
    const previous = previousHistoryRef.current;

    let reason: VirtualizationCycle['reason'] | null = null;
    if (virtualizationEnabled) {
      const openedVirtualizedChat = !previous.virtualized;
      const largeHistoryJump = previous.length > 0
        && Math.abs(nextLength - previous.length) >= LARGE_JUMP_DELTA;
      const switchedVirtualizedChat = previous.virtualized
        && previous.firstKey !== ''
        && previous.firstKey !== nextFirstKey;

      if (openedVirtualizedChat) {
        reason = 'opened-virtualized-chat';
      } else if (switchedVirtualizedChat) {
        reason = 'switched-virtualized-chat';
      } else if (largeHistoryJump) {
        reason = 'large-history-jump';
      }
    }

    if (reason !== null) {
      const viewportHeight = Math.max(viewportState.height, containerRef.current?.clientHeight ?? 0);

      cycleRef.current = {
        reason,
        startedAt: nowMs(),
        totalRows: nextLength,
        totalChars: virtualizationDecision.totalContentChars,
        maxRowChars: virtualizationDecision.maxRowChars,
        decisionReason: virtualizationDecision.reason,
        estimatePassMs: estimation.estimatePassMs,
        startHeightVersion: heightVersion,
        containerWidth: estimatedInnerWidth,
        viewportHeight,
      };

      logPerf(
        `[chat-performance] event=virtualization_cycle_start reason=${reason} total_rows=${nextLength} `
        + `decision_reason=${virtualizationDecision.reason} total_content_chars=${virtualizationDecision.totalContentChars} `
        + `max_row_chars=${virtualizationDecision.maxRowChars} `
        + `baseline_rows=${nextLength} container_width=${estimatedInnerWidth} viewport_height=${viewportHeight} `
        + `estimate_pass_ms=${estimation.estimatePassMs}`,
      );
    }

    previousHistoryRef.current = {
      length: nextLength,
      firstKey: nextFirstKey,
      virtualized: virtualizationEnabled,
    };
  }, [
    chatHistory,
    containerRef,
    estimatedInnerWidth,
    estimation.estimatePassMs,
    heightVersion,
    virtualizationDecision.maxRowChars,
    virtualizationDecision.reason,
    virtualizationDecision.totalContentChars,
    viewportState.height,
    virtualizationEnabled,
  ]);

  useEffect(() => {
    const cycle = cycleRef.current;
    if (!cycle || !virtualizationEnabled || chatHistory.length === 0) {
      return;
    }

    if (heightVersion <= cycle.startHeightVersion || visibleItems.length === 0) {
      return;
    }

    const renderedRows = visibleItems.length;
    const hiddenRows = Math.max(0, cycle.totalRows - renderedRows);
    const reductionPct = cycle.totalRows > 0
      ? Math.round((hiddenRows / cycle.totalRows) * 100)
      : 0;
    const domWorkRatio = renderedRows > 0
      ? (cycle.totalRows / renderedRows).toFixed(2)
      : '0.00';
    const firstVisibleMeasureMs = Math.round(nowMs() - cycle.startedAt);

    logPerf(
      `[chat-performance] event=virtualization_cycle_complete reason=${cycle.reason} total_rows=${cycle.totalRows} `
      + `decision_reason=${cycle.decisionReason} total_content_chars=${cycle.totalChars} max_row_chars=${cycle.maxRowChars} `
      + `rendered_rows=${renderedRows} hidden_rows=${hiddenRows} dom_reduction_pct=${reductionPct} `
      + `dom_work_ratio=${domWorkRatio}x `
      + `estimate_pass_ms=${cycle.estimatePassMs} first_visible_measure_ms=${firstVisibleMeasureMs} `
      + `measured_rows=${measuredCount} virtual_height_px=${Math.round(totalHeight)} `
      + `container_width=${cycle.containerWidth} viewport_height=${cycle.viewportHeight}`,
    );

    cycleRef.current = null;
  }, [chatHistory.length, heightVersion, measuredCount, totalHeight, visibleItems.length, virtualizationEnabled]);

  if (!virtualizationEnabled) {
    return (
      <>
        {chatHistory.map((message, index) => (
          <ChatMessage
            key={message.messageId ?? `${message.role}-${index}`}
            message={message}
            selectedModel={generatingModel}
            actionsDisabled={!canSubmit}
            onRetryMessage={onRetryMessage}
            onEditMessage={onEditMessage}
            onSetActiveResponse={onSetActiveResponse}
            onArtifactUpdated={onArtifactUpdated}
            onArtifactDeleted={onArtifactDeleted}
          />
        ))}
      </>
    );
  }

  return (
    <>
      {topSpacer > 0 && (
        <div
          data-virtual-spacer="top"
          style={{ height: `${topSpacer}px`, flex: '0 0 auto' }}
          aria-hidden="true"
        />
      )}

      {visibleItems.map(({ index, message }) => (
        <MeasuredChatMessage
          key={message.messageId ?? `${message.role}-${index}`}
          index={index}
          message={message}
          selectedModel={generatingModel}
            actionsDisabled={!canSubmit}
            onRetryMessage={onRetryMessage}
            onEditMessage={onEditMessage}
            onSetActiveResponse={onSetActiveResponse}
            onArtifactUpdated={onArtifactUpdated}
            onArtifactDeleted={onArtifactDeleted}
            onHeight={handleMeasuredHeight}
          />
      ))}

      {bottomSpacer > 0 && (
        <div
          data-virtual-spacer="bottom"
          style={{ height: `${bottomSpacer}px`, flex: '0 0 auto' }}
          aria-hidden="true"
        />
      )}
    </>
  );
}
