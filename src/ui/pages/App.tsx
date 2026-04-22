/**
 * Main Chat Application Component (Refactored)
 * 
 * This is the refactored version of App.tsx that uses modular hooks and components.
 * It demonstrates how to compose the application from smaller, reusable pieces.
 * 
 * Architecture:
 * - State management via custom hooks (useChatState, useScreenshots, useTokenUsage)
 * - WebSocket communication via useWebSocket hook
 * - UI components from src/ui/components/
 * - Type definitions from src/ui/types/
 * - API abstraction via src/ui/services/api.ts
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { FormEvent } from 'react';
import { useOutletContext, useLocation, useNavigate } from 'react-router-dom';

// Hooks
import { useChatState } from '../hooks/useChatState';
import { useScreenshots } from '../hooks/useScreenshots';
import { useTokenUsage } from '../hooks/useTokenUsage';
import { useTabs } from '../contexts/TabContext';
import { useWebSocket } from '../contexts/WebSocketContext';

// Components
import TitleBar from '../components/TitleBar';
import TabBar from '../components/TabBar';
import { BoltIcon } from '../components/icons/AppIcons';
import { ResponseArea } from '../components/chat/ResponseArea.tsx';
import { QueryInput } from '../components/input/QueryInput';
import type { QueryInputAttachedFile } from '../components/input/QueryInput';
import { QueueDropdown } from '../components/input/QueueDropdown';
import { ModeSelector } from '../components/input/ModeSelector';
import { TokenUsagePopup } from '../components/input/TokenUsagePopup';
import { ScreenshotChips } from '../components/input/ScreenshotChips';
import '../CSS/input/QueueDropdown.css';

// Types
import type {
  ArtifactBlockData,
  WebSocketMessage,
  TabSnapshot,
  Screenshot,
  ScreenshotAddedContent,
  ScreenshotRemovedContent,
  ConversationSavedContent,
  ConversationResumedContent,
  ConversationTurnPayload,
  ArtifactContentPayload,
  ToolCallContent,
  SubAgentStreamContent,
  TokenUsageContent,
  ChatMessage,
  ContentBlock,
  TerminalApprovalRequest,
  TerminalSessionRequest,
  TerminalOutput,
  TerminalCommandComplete,
  YouTubeTranscriptionApprovalRequest,
} from '../types';
import type { LocalTurnPatch } from '../utils/conversationMessageTransforms';
import { formatModelLabel, getModelProviderKey, getProviderLabel } from '../utils/modelDisplay';
import { ProviderLogo } from '../components/icons/ProviderLogos';
import { hasProviderLogo } from '../utils/providerLogos';
import { applyToolCallChange } from '../utils/toolCallState';

// Assets
import '../CSS/pages/App.css';
import micSignSvg from '../assets/mic-icon.svg';
import fullscreenSSIcon from '../assets/entire-screen-shot-icon.svg';
import regionSSIcon from '../assets/region-screen-shot-icon.svg';
import contextWindowInsightsIcon from '../assets/context-window-icon.svg';
import scrollDownIcon from '../assets/scroll-down-icon.svg';

type PendingTurnAction = {
  type: 'retry' | 'edit';
  messageId: string;
  editedContent?: string;
};

type StreamPerfStats = {
  submitAtMs: number;
  firstChunkAtMs: number | null;
  lastChunkAtMs: number | null;
  chunkCount: number;
  chunkChars: number;
  maxChunkIntervalMs: number;
  model: string;
  queryChars: number;
};

const STREAM_PERF_DEBUG_FLAG = 'xpdite_stream_debug';

function nowMs(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
}

function isStreamPerfDebugEnabled(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  try {
    return window.localStorage.getItem(STREAM_PERF_DEBUG_FLAG) === '1';
  } catch {
    return false;
  }
}

type ConversationMessageTransforms = typeof import('../utils/conversationMessageTransforms');
let conversationMessageTransformsPromise: Promise<ConversationMessageTransforms> | null = null;

function loadConversationMessageTransforms() {
  if (!conversationMessageTransformsPromise) {
    conversationMessageTransformsPromise = import('../utils/conversationMessageTransforms');
  }

  return conversationMessageTransformsPromise;
}

function hasTurnInHistory(
  history: ChatMessage[],
  turn: ConversationTurnPayload,
): boolean {
  return history.some(
    (message) =>
      message.turnId === turn.turn_id ||
      message.messageId === turn.user.message_id ||
      (turn.assistant !== undefined && message.messageId === turn.assistant.message_id),
  );
}

function buildPendingTurnLocalPatch(
  history: ChatMessage[],
  turn: ConversationTurnPayload,
  pendingAction: PendingTurnAction | undefined,
  assistantMessage?: ChatMessage,
): LocalTurnPatch | undefined {
  if (!pendingAction) {
    return undefined;
  }

  const localUserMessage =
    pendingAction.type === 'edit'
      ? history.find(
          (message) =>
            message.messageId === pendingAction.messageId && message.role === 'user',
        )
      : history.find(
          (message) => message.turnId === turn.turn_id && message.role === 'user',
        );

  return {
    user:
      pendingAction.type === 'edit'
        ? {
            ...(localUserMessage ?? { role: 'user' as const, content: turn.user.content }),
            role: 'user',
            content: pendingAction.editedContent ?? turn.user.content,
          }
        : localUserMessage,
    assistant: assistantMessage,
  };
}

function mapYouTubeApprovalToBlock(approvalData: YouTubeTranscriptionApprovalRequest) {
  return {
    requestId: approvalData.request_id,
    title: approvalData.title,
    channel: approvalData.channel,
    duration: approvalData.duration,
    durationSeconds: approvalData.duration_seconds,
    url: approvalData.url,
    noCaptionsReason: approvalData.no_captions_reason,
    audioSizeEstimate: approvalData.audio_size_estimate,
    audioSizeBytes: approvalData.audio_size_bytes,
    downloadTimeEstimate: approvalData.download_time_estimate,
    transcriptionTimeEstimate: approvalData.transcription_time_estimate,
    totalTimeEstimate: approvalData.total_time_estimate,
    whisperModel: approvalData.whisper_model,
    computeBackend: approvalData.compute_backend,
    playlistNote: approvalData.playlist_note,
    status: 'pending' as const,
  };
}

function mapArtifactPayloadToBlock(
  artifactData: ArtifactContentPayload,
): ContentBlock & { type: 'artifact' } {
  return {
    type: 'artifact',
    artifact: {
      artifactId: artifactData.artifact_id,
      artifactType: artifactData.artifact_type,
      title: artifactData.title,
      language: artifactData.language ?? undefined,
      sizeBytes: artifactData.size_bytes ?? 0,
      lineCount: artifactData.line_count ?? 0,
      status: artifactData.status,
      content: artifactData.content,
      conversationId: artifactData.conversation_id,
      messageId: artifactData.message_id,
      createdAt: artifactData.created_at,
      updatedAt: artifactData.updated_at,
    },
  };
}

function upsertArtifactBlock(
  blocks: ContentBlock[],
  artifactBlock: ContentBlock & { type: 'artifact' },
): ContentBlock[] {
  const nextBlocks = [...blocks];
  const existingIndex = nextBlocks.findIndex(
    (block) =>
      block.type === 'artifact'
      && block.artifact.artifactId === artifactBlock.artifact.artifactId,
  );

  if (existingIndex >= 0) {
    const existingBlock = nextBlocks[existingIndex];
    if (existingBlock.type === 'artifact') {
      nextBlocks[existingIndex] = {
        type: 'artifact',
        artifact: {
          ...existingBlock.artifact,
          ...artifactBlock.artifact,
        },
      };
    }
  } else {
    nextBlocks.push(artifactBlock);
  }

  return nextBlocks;
}

type ArtifactDeletedPayload = {
  artifact_id: string;
  conversation_id?: string | null;
  message_id?: string | null;
  reason?: string;
};

function updateArtifactInBlocks(
  blocks: ContentBlock[],
  artifact: ArtifactBlockData,
  appendIfMissing: boolean = true,
): ContentBlock[] {
  const nextBlocks = [...blocks];
  const existingIndex = nextBlocks.findIndex(
    (block) => block.type === 'artifact' && block.artifact.artifactId === artifact.artifactId,
  );

  if (existingIndex >= 0) {
    const existingBlock = nextBlocks[existingIndex];
    if (existingBlock.type === 'artifact') {
      nextBlocks[existingIndex] = {
        type: 'artifact',
        artifact: {
          ...existingBlock.artifact,
          ...artifact,
        },
      };
    }
  } else if (appendIfMissing) {
    nextBlocks.push({ type: 'artifact', artifact });
  }

  return nextBlocks;
}

function updateArtifactInMessage(
  message: ChatMessage,
  artifact: ArtifactBlockData,
): ChatMessage {
  const shouldUpdateMessageBlocks = !!message.contentBlocks && (
    blocksContainArtifact(message.contentBlocks, artifact.artifactId, artifact.messageId)
    || (artifact.messageId != null && message.messageId === artifact.messageId)
  );
  const nextContentBlocks = shouldUpdateMessageBlocks && message.contentBlocks
    ? updateArtifactInBlocks(
        message.contentBlocks,
        artifact,
        artifact.messageId != null && message.messageId === artifact.messageId,
      )
    : message.contentBlocks;

  const nextResponseVersions = message.responseVersions?.map((variant) => ({
    ...variant,
    contentBlocks: variant.contentBlocks
      ? updateArtifactInBlocks(
          variant.contentBlocks,
          artifact,
          false,
        )
      : variant.contentBlocks,
  }));

  return {
    ...message,
    contentBlocks: nextContentBlocks,
    responseVersions: nextResponseVersions,
  };
}

function updateArtifactInHistory(
  history: ChatMessage[],
  artifact: ArtifactBlockData,
): ChatMessage[] {
  return history.map((message) => updateArtifactInMessage(message, artifact));
}

function markArtifactDeletedInBlocks(
  blocks: ContentBlock[],
  artifactId: string,
): ContentBlock[] {
  return blocks.map((block) => {
    if (block.type !== 'artifact' || block.artifact.artifactId !== artifactId) {
      return block;
    }

    return {
      type: 'artifact',
      artifact: {
        ...block.artifact,
        status: 'deleted',
        content: undefined,
      },
    };
  });
}

function markArtifactDeletedInMessage(
  message: ChatMessage,
  artifactId: string,
): ChatMessage {
  const nextContentBlocks = message.contentBlocks
    ? markArtifactDeletedInBlocks(message.contentBlocks, artifactId)
    : message.contentBlocks;

  const nextResponseVersions = message.responseVersions?.map((variant) => ({
    ...variant,
    contentBlocks: variant.contentBlocks
      ? markArtifactDeletedInBlocks(variant.contentBlocks, artifactId)
      : variant.contentBlocks,
  }));

  return {
    ...message,
    contentBlocks: nextContentBlocks,
    responseVersions: nextResponseVersions,
  };
}

function markArtifactDeletedInHistory(
  history: ChatMessage[],
  artifactId: string,
): ChatMessage[] {
  return history.map((message) => markArtifactDeletedInMessage(message, artifactId));
}

function blocksContainArtifact(
  blocks: ContentBlock[],
  artifactId: string,
  messageId?: string | null,
): boolean {
  return blocks.some((block) => (
    block.type === 'artifact'
    && (
      block.artifact.artifactId === artifactId
      || (!!messageId && block.artifact.messageId === messageId)
    )
  ));
}

function messageContainsArtifactContext(
  message: ChatMessage,
  payload: ArtifactDeletedPayload,
): boolean {
  if (payload.message_id && message.messageId === payload.message_id) {
    return true;
  }

  if (blocksContainArtifact(message.contentBlocks ?? [], payload.artifact_id, payload.message_id)) {
    return true;
  }

  return message.responseVersions?.some((variant) =>
    blocksContainArtifact(variant.contentBlocks ?? [], payload.artifact_id, payload.message_id),
  ) ?? false;
}

function chatMatchesArtifactContext(
  chat: TabSnapshot['chat'],
  payload: ArtifactDeletedPayload,
): boolean {
  if (payload.conversation_id && chat.conversationId !== payload.conversation_id) {
    return false;
  }

  if (payload.message_id) {
    if (blocksContainArtifact(chat.contentBlocks, payload.artifact_id, payload.message_id)) {
      return true;
    }

    return chat.chatHistory.some((message) => messageContainsArtifactContext(message, payload));
  }

  return true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isQueueUpdatedPayload(
  payload: unknown,
): payload is { tab_id: string; items: { item_id: string; preview: string; position: number }[] } {
  if (!isRecord(payload) || typeof payload.tab_id !== 'string' || !Array.isArray(payload.items)) {
    return false;
  }

  return payload.items.every((item) => (
    isRecord(item)
    && typeof item.item_id === 'string'
    && typeof item.preview === 'string'
    && typeof item.position === 'number'
  ));
}

function isConversationResumedPayload(payload: unknown): payload is ConversationResumedContent {
  return isRecord(payload)
    && typeof payload.conversation_id === 'string'
    && Array.isArray(payload.messages);
}

function parseWsPayload<T>(
  data: WebSocketMessage,
  context: string,
): T | null {
  if (typeof data.content !== 'string') {
    if (data.content !== null && typeof data.content === 'object') {
      return data.content as T;
    }

    console.warn(`[ws] Ignoring malformed payload for ${context}`);
    return null;
  }

  try {
    const parsed: unknown = JSON.parse(data.content);
    if (parsed !== null && typeof parsed === 'object') {
      return parsed as T;
    }

    console.warn(`[ws] Ignoring malformed payload for ${context}`);
    return null;
  } catch (error) {
    console.warn(`[ws] Ignoring malformed payload for ${context}`, error);
    return null;
  }
}

function parseWsPayloadWithGuard<T>(
  data: WebSocketMessage,
  context: string,
  isPayload: (payload: unknown) => payload is T,
): T | null {
  const payload = parseWsPayload<unknown>(data, context);
  if (!isPayload(payload)) {
    console.warn(`[ws] Ignoring malformed payload for ${context}`);
    return null;
  }
  return payload;
}


function App() {
  // ============================================
  // State Management Hooks
  // ============================================
  const chatState = useChatState();
  const screenshotState = useScreenshots();
  const tokenState = useTokenUsage();

  // ============================================
  // Local UI State
  // ============================================
  const [selectedModel, setSelectedModel] = useState('');
  const [enabledModels, setEnabledModels] = useState<string[]>([]);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [interactionSectionHeight, setInteractionSectionHeight] = useState(115);

  // Terminal state (minimal — most state is now in chatState.contentBlocks)
  const [terminalSessionActive, setTerminalSessionActive] = useState(false);
  const [terminalSessionRequest, setTerminalSessionRequest] = useState<TerminalSessionRequest | null>(null);

  // ============================================
  // Refs
  // ============================================
  const inputRef = useRef<HTMLDivElement | null>(null);
  const responseAreaRef = useRef<HTMLDivElement | null>(null);
  const mainInteractionRef = useRef<HTMLDivElement | null>(null);
  const pendingConversationRef = useRef<string | null>(null);
  const pendingNewChatRef = useRef<boolean>(false);
  const pendingCreatedTabIdRef = useRef<string | null>(null);
  const generatingModelRef = useRef<string>('');
  const pendingTurnActionsRef = useRef<Map<string, PendingTurnAction>>(new Map());
  const hasNormalizedCaptureModeRef = useRef(false);
  // Stash run_command args so we can create terminal blocks when output arrives (auto-approved)
  const pendingTerminalCommandRef = useRef<{ command: string; cwd: string } | null>(null);
  const attachedFilesRef = useRef<QueryInputAttachedFile[]>([]);
  const streamPerfStatsRef = useRef<StreamPerfStats | null>(null);
  const streamPerfEnabledRef = useRef(false);

  useEffect(() => {
    streamPerfEnabledRef.current = isStreamPerfDebugEnabled();
  }, []);

  const startStreamPerfCycle = useCallback((queryText: string, modelName: string) => {
    if (!streamPerfEnabledRef.current) {
      return;
    }

    streamPerfStatsRef.current = {
      submitAtMs: nowMs(),
      firstChunkAtMs: null,
      lastChunkAtMs: null,
      chunkCount: 0,
      chunkChars: 0,
      maxChunkIntervalMs: 0,
      model: modelName,
      queryChars: queryText.length,
    };
  }, []);

  const markStreamPerfChunk = useCallback((chunk: string) => {
    if (!streamPerfEnabledRef.current || !chunk) {
      return;
    }

    const stats = streamPerfStatsRef.current;
    if (!stats) {
      return;
    }

    const ts = nowMs();
    if (stats.firstChunkAtMs === null) {
      stats.firstChunkAtMs = ts;
    }
    if (stats.lastChunkAtMs !== null) {
      const interval = ts - stats.lastChunkAtMs;
      if (interval > stats.maxChunkIntervalMs) {
        stats.maxChunkIntervalMs = interval;
      }
    }
    stats.lastChunkAtMs = ts;
    stats.chunkCount += 1;
    stats.chunkChars += chunk.length;
  }, []);

  const finishStreamPerfCycle = useCallback((reason: string) => {
    if (!streamPerfEnabledRef.current) {
      return;
    }

    const stats = streamPerfStatsRef.current;
    if (!stats) {
      return;
    }

    const finishedAt = nowMs();
    const submitToFirstChunk = stats.firstChunkAtMs === null
      ? null
      : Math.round(stats.firstChunkAtMs - stats.submitAtMs);
    const streamDuration = stats.firstChunkAtMs === null
      ? null
      : Math.round(finishedAt - stats.firstChunkAtMs);

    console.debug(
      `[stream-perf] ${reason}: model=${stats.model} submit_to_first_chunk_ms=${submitToFirstChunk ?? 'n/a'} stream_duration_ms=${streamDuration ?? 'n/a'} chunks=${stats.chunkCount} chars=${stats.chunkChars} max_chunk_interval_ms=${Math.round(stats.maxChunkIntervalMs)} query_chars=${stats.queryChars}`,
    );

    streamPerfStatsRef.current = null;
  }, []);

  // ============================================
  // Tab Management
  // ============================================
  const {
    tabs, activeTabId, updateTabTitle, createTab,
    queueMap, setQueueItems, getTabSnapshot, setTabSnapshot, deleteTabSnapshot,
    registerBeforeSwitch, registerAfterSwitch, registerOnTabClosed,
  } = useTabs();
  const tabsRef = useRef(tabs);
  const captureModeRef = useRef(screenshotState.captureMode);
  const activeTabIdRef = useRef(activeTabId);
  const saveTabStateRef = useRef<(tabId: string) => void>(() => {});
  const hasRestoredInitialTabRef = useRef(false);
  const syncedTabIdsRef = useRef<Set<string>>(new Set(tabs.map((tab) => tab.id)));

  // ============================================
  // Context from Layout
  // ============================================
  const { setMini, setIsHidden } = useOutletContext<{
    setMini: (val: boolean) => void;
    setIsHidden: (val: boolean) => void;
    isHidden: boolean;
  }>();

  const location = useLocation();
  const navigate = useNavigate();

  // ============================================
  // WebSocket (from Layout-level provider)
  // ============================================
  const { send: wsSendRaw, subscribe: wsSubscribe, isConnected } = useWebSocket();

  // Tab-scoped WS send helper — injects active tab_id into every message.
  const wsSend = useCallback((msg: Record<string, unknown>) => {
    wsSendRaw({ tab_id: activeTabIdRef.current, ...msg });
  }, [wsSendRaw]);

  useEffect(() => {
    const node = mainInteractionRef.current;
    if (!node) {
      return undefined;
    }

    let frameId: number | null = null;

    const updateHeight = () => {
      if (!node.isConnected) {
        return;
      }
      const nextHeight = Math.ceil(node.getBoundingClientRect().height);
      setInteractionSectionHeight((previousHeight) => (
        previousHeight === nextHeight ? previousHeight : nextHeight
      ));
    };

    const scheduleHeightUpdate = () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(() => {
        frameId = null;
        updateHeight();
      });
    };

    updateHeight();

    if (typeof ResizeObserver === 'undefined') {
      return undefined;
    }

    const observer = new ResizeObserver(() => scheduleHeightUpdate());
    observer.observe(node);

    return () => {
      observer.disconnect();
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
    };
  }, []);
  // Tab switch: snapshot / restore state registry
  // ============================================

  /** Create a fresh TabSnapshot with default values. */
  const freshSnapshot = useCallback((): TabSnapshot => ({
    chat: {
      chatHistory: [],
      currentQuery: '',
      response: '',
      thinking: '',
      isThinking: false,
      thinkingCollapsed: true,
      toolCalls: [],
      contentBlocks: [],
      conversationId: null,
      query: '',
      canSubmit: true,
      status: 'Ready to chat.',
      error: '',
    },
    screenshots: {
      screenshots: [],
      captureMode: 'precision',
      meetingRecordingMode: false,
    },
    tokens: {
      tokenUsage: { total: 0, input: 0, output: 0, limit: 128000 },
    },
    terminal: {
      terminalSessionActive: false,
      terminalSessionRequest: null,
    },
    generatingModel: '',
  }), []);

  /** Save current React state into the registry for the given tab. */
  const saveTabState = useCallback((tabId: string) => {
    setTabSnapshot(tabId, {
      chat: chatState.getSnapshot(),
      screenshots: screenshotState.getSnapshot(),
      tokens: tokenState.getSnapshot(),
      terminal: {
        terminalSessionActive,
        terminalSessionRequest,
      },
      generatingModel: generatingModelRef.current,
    });
  }, [chatState, screenshotState, tokenState, terminalSessionActive, terminalSessionRequest, setTabSnapshot]);

  /** Restore React state from the registry for the given tab. */
  const restoreTabState = useCallback((tabId: string) => {
    const snap = getTabSnapshot(tabId) ?? freshSnapshot();
    chatState.restoreSnapshot(snap.chat);
    screenshotState.restoreSnapshot(snap.screenshots);
    tokenState.restoreSnapshot(snap.tokens);
    setTerminalSessionActive(snap.terminal.terminalSessionActive);
    setTerminalSessionRequest(snap.terminal.terminalSessionRequest);
    generatingModelRef.current = snap.generatingModel;
  }, [chatState, screenshotState, tokenState, freshSnapshot, getTabSnapshot]);

  saveTabStateRef.current = saveTabState;

  // Register tab switch callbacks with TabContext
  useEffect(() => {
    const unregisterBeforeSwitch = registerBeforeSwitch((oldTabId: string) => {
      saveTabState(oldTabId);
    });
    const unregisterAfterSwitch = registerAfterSwitch((newTabId: string) => {
      const nextTabSnapshot = getTabSnapshot(newTabId) ?? freshSnapshot();
      const nextCaptureMode = nextTabSnapshot.screenshots.meetingRecordingMode
        ? 'none'
        : nextTabSnapshot.screenshots.captureMode;

      activeTabIdRef.current = newTabId;
      restoreTabState(newTabId);
      captureModeRef.current = nextTabSnapshot.screenshots.captureMode;
      setShowScrollBottom(false);
      // Notify the backend so hotkey-captured screenshots route to the correct tab
      // and use the restored tab's capture mode.
      wsSend({ type: 'tab_activated', tab_id: newTabId });
      wsSend({ type: 'set_capture_mode', tab_id: newTabId, mode: nextCaptureMode });
    });
    const unregisterOnTabClosed = registerOnTabClosed((closedTabId: string) => {
      deleteTabSnapshot(closedTabId);
      pendingTurnActionsRef.current.delete(closedTabId);
    });
    return () => {
      unregisterBeforeSwitch();
      unregisterAfterSwitch();
      unregisterOnTabClosed();
    };
  }, [
    deleteTabSnapshot,
    freshSnapshot,
    getTabSnapshot,
    registerBeforeSwitch,
    registerAfterSwitch,
    registerOnTabClosed,
    restoreTabState,
    saveTabState,
    wsSend,
  ]);

  // Keep activeTabIdRef in sync when activeTabId changes (e.g. from external triggers)
  useEffect(() => {
    activeTabIdRef.current = activeTabId;
  }, [activeTabId]);

  useEffect(() => {
    tabsRef.current = tabs;
  }, [tabs]);

  useEffect(() => {
    const previousTabIds = syncedTabIdsRef.current;
    const nextTabIds = new Set(tabs.map((tab) => tab.id));

    for (const tab of tabs) {
      if (!previousTabIds.has(tab.id)) {
        wsSend({ type: 'tab_created', tab_id: tab.id });
      }
    }

    for (const tabId of previousTabIds) {
      if (!nextTabIds.has(tabId)) {
        wsSend({ type: 'tab_closed', tab_id: tabId });
      }
    }

    syncedTabIdsRef.current = nextTabIds;
  }, [tabs, wsSend]);

  useEffect(() => {
    captureModeRef.current = screenshotState.captureMode;
  }, [screenshotState.captureMode]);

  useEffect(() => {
    if (hasRestoredInitialTabRef.current) {
      return;
    }

    hasRestoredInitialTabRef.current = true;
    activeTabIdRef.current = activeTabId;
    restoreTabState(activeTabId);
    setShowScrollBottom(false);
  }, [activeTabId, restoreTabState]);

  useEffect(() => {
    const state = location.state as { tabId?: string } | null;

    if (!isConnected || state?.tabId) {
      return;
    }

    wsSend({ type: 'tab_activated', tab_id: activeTabIdRef.current });
  }, [isConnected, location.state, wsSend]);

  useEffect(() => {
    return () => {
      saveTabStateRef.current(activeTabIdRef.current);
    };
  }, []);

  // ============================================
  // Background tab message handler
  // ============================================
  /**
   * Apply a WS message to a background tab's snapshot in the registry.
   * Only the subset of message types that affect persistent state are handled;
   * UI-only messages (screenshot_start, terminal_running_notice, etc.) are ignored.
   */
  useEffect(() => {
    const warm = () => {
      void loadConversationMessageTransforms();
    };

    if (typeof window.requestIdleCallback === 'function') {
      const idleId = window.requestIdleCallback(warm, { timeout: 4000 });
      return () => {
        window.cancelIdleCallback?.(idleId);
      };
    }

    const timeoutId = window.setTimeout(warm, 2000);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, []);

  const applyToBackgroundTab = useCallback(async (tabId: string, data: WebSocketMessage) => {
    const snap = getTabSnapshot(tabId) ?? freshSnapshot();
    const chat = { ...snap.chat };
    const pendingTurnAction = pendingTurnActionsRef.current.get(tabId);

    switch (data.type) {
      case 'query':
        chat.currentQuery = String(data.content);
        if (tabId === activeTabIdRef.current) {
          startStreamPerfCycle(chat.currentQuery, snap.generatingModel || selectedModel);
        }
        chat.error = '';
        chat.status = 'Thinking...';
        chat.isThinking = true;
        chat.canSubmit = false;
        chat.toolCalls = [];
        chat.contentBlocks = [];
        break;

      case 'thinking_chunk': {
        const tChunk = String(data.content);
        chat.thinking += tChunk;
        // Also interleave into contentBlocks so thinking appears positionally in the chain
        const tBlocks = [...chat.contentBlocks];
        if (tBlocks.length > 0 && tBlocks[tBlocks.length - 1].type === 'thinking') {
          tBlocks[tBlocks.length - 1] = {
            type: 'thinking',
            content: (tBlocks[tBlocks.length - 1] as { type: 'thinking'; content: string }).content + tChunk,
          };
        } else {
          tBlocks.push({ type: 'thinking', content: tChunk });
        }
        chat.contentBlocks = tBlocks;
        break;
      }

      case 'thinking_complete':
        chat.isThinking = false;
        chat.status = 'Receiving response...';
        break;

      case 'response_chunk': {
        const chunk = String(data.content);
        if (tabId === activeTabIdRef.current) {
          markStreamPerfChunk(chunk);
        }
        chat.response += chunk;
        const blocks = [...chat.contentBlocks];
        if (blocks.length > 0 && blocks[blocks.length - 1].type === 'text') {
          blocks[blocks.length - 1] = {
            type: 'text',
            content: (blocks[blocks.length - 1] as { type: 'text'; content: string }).content + chunk,
          };
        } else {
          blocks.push({ type: 'text', content: chunk });
        }
        chat.contentBlocks = blocks;
        break;
      }

      case 'artifact_start': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'background:artifact_start');
        if (!artifactData) {
          return;
        }
        chat.contentBlocks = upsertArtifactBlock(
          chat.contentBlocks,
          mapArtifactPayloadToBlock(artifactData),
        );
        break;
      }

      case 'artifact_chunk': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'background:artifact_chunk');
        if (!artifactData) {
          return;
        }
        chat.contentBlocks = upsertArtifactBlock(
          chat.contentBlocks,
          mapArtifactPayloadToBlock(artifactData),
        );
        break;
      }

      case 'artifact_complete': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'background:artifact_complete');
        if (!artifactData) {
          return;
        }
        chat.contentBlocks = upsertArtifactBlock(
          chat.contentBlocks,
          mapArtifactPayloadToBlock(artifactData),
        );
        break;
      }

      case 'response_complete': {
        if (tabId === activeTabIdRef.current) {
          finishStreamPerfCycle('background-response-complete');
        }
        if (pendingTurnAction) {
          chat.isThinking = false;
          chat.status = 'Saving updated turn...';
          break;
        }

        if (chat.response || chat.thinking || chat.toolCalls.length > 0 || chat.contentBlocks.length > 0) {
          const timestamp = Date.now();
          chat.chatHistory = [
            ...chat.chatHistory,
            { role: 'user', content: chat.currentQuery, timestamp },
            {
              role: 'assistant',
              content: chat.response,
              thinking: chat.thinking || undefined,
              toolCalls: chat.toolCalls.length > 0 ? [...chat.toolCalls] : undefined,
              contentBlocks: chat.contentBlocks.length > 0 ? [...chat.contentBlocks] : undefined,
              model: snap.generatingModel || undefined,
              timestamp,
              activeResponseIndex: 0,
              responseVersions: [{
                responseIndex: 0,
                content: chat.response,
                model: snap.generatingModel || undefined,
                timestamp,
                contentBlocks: chat.contentBlocks.length > 0 ? [...chat.contentBlocks] : undefined,
              }],
            },
          ];
        }
        chat.response = '';
        chat.thinking = '';
        chat.currentQuery = '';
        chat.isThinking = false;
        chat.toolCalls = [];
        chat.contentBlocks = [];
        chat.canSubmit = true;
        chat.status = 'Ready for follow-up question.';
        break;
      }

      case 'context_cleared':
        chat.chatHistory = [];
        chat.currentQuery = '';
        chat.response = '';
        chat.thinking = '';
        chat.isThinking = false;
        chat.toolCalls = [];
        chat.contentBlocks = [];
        chat.conversationId = null;
        chat.canSubmit = true;
        chat.status = 'Context cleared.';
        chat.error = '';
        chat.query = '';
        break;

      case 'conversation_saved': {
        const { applySavedTurnToHistory } = await loadConversationMessageTransforms();
        const sd = parseWsPayload<ConversationSavedContent>(data, 'background:conversation_saved');
        if (!sd) {
          return;
        }

        const latestSnap = getTabSnapshot(tabId) ?? freshSnapshot();
        const latestChat = { ...latestSnap.chat };
        const latestPendingTurnAction = pendingTurnActionsRef.current.get(tabId);

        latestChat.conversationId = sd.conversation_id;
        if (latestPendingTurnAction && !sd.turn) {
          latestChat.response = '';
          latestChat.thinking = '';
          latestChat.currentQuery = '';
          latestChat.isThinking = false;
          latestChat.toolCalls = [];
          latestChat.contentBlocks = [];
          latestChat.canSubmit = true;
          latestChat.status = 'Ready for follow-up question.';
          pendingTurnActionsRef.current.delete(tabId);
          setTabSnapshot(tabId, { ...latestSnap, chat: latestChat });
          return;
        }

        if (sd.turn) {
          latestChat.chatHistory = applySavedTurnToHistory(
            latestChat.chatHistory,
            sd.turn,
            sd.operation ?? latestPendingTurnAction?.type ?? 'submit',
            buildPendingTurnLocalPatch(
              latestChat.chatHistory,
              sd.turn,
              latestPendingTurnAction,
              latestPendingTurnAction
                ? {
                    role: 'assistant',
                    content: latestChat.response,
                    thinking: latestChat.thinking || undefined,
                    toolCalls: latestChat.toolCalls.length > 0 ? [...latestChat.toolCalls] : undefined,
                    contentBlocks: latestChat.contentBlocks.length > 0 ? [...latestChat.contentBlocks] : undefined,
                    model: latestSnap.generatingModel || undefined,
                    timestamp: Date.now(),
                  }
                : undefined,
            ),
          );
        }

        if (latestPendingTurnAction) {
          latestChat.response = '';
          latestChat.thinking = '';
          latestChat.currentQuery = '';
          latestChat.isThinking = false;
          latestChat.toolCalls = [];
          latestChat.contentBlocks = [];
          latestChat.canSubmit = true;
          latestChat.status = 'Ready for follow-up question.';
          pendingTurnActionsRef.current.delete(tabId);
        }

        setTabSnapshot(tabId, { ...latestSnap, chat: latestChat });
        return;
      }

      case 'conversation_resumed': {
        const { mapConversationMessagePayload } = await loadConversationMessageTransforms();
        const resumeData = parseWsPayloadWithGuard<ConversationResumedContent>(
          data,
          'background:conversation_resumed',
          isConversationResumedPayload,
        );
        if (!resumeData) {
          return;
        }

        const latestSnap = getTabSnapshot(tabId) ?? freshSnapshot();
        const latestChat = { ...latestSnap.chat };

        latestChat.chatHistory = resumeData.messages.map(mapConversationMessagePayload);
        latestChat.conversationId = resumeData.conversation_id;
        latestChat.response = '';
        latestChat.thinking = '';
        latestChat.currentQuery = '';
        latestChat.isThinking = false;
        latestChat.toolCalls = [];
        latestChat.contentBlocks = [];
        latestChat.canSubmit = true;
        latestChat.status = 'Conversation loaded. Ask a follow-up question.';
        pendingTurnActionsRef.current.delete(tabId);
        setTabSnapshot(tabId, { ...latestSnap, chat: latestChat });
        return;
      }

      case 'error':
        if (tabId === activeTabIdRef.current) {
          finishStreamPerfCycle('background-error');
        }
        chat.error = String(data.content);
        chat.status = 'An error occurred.';
        chat.canSubmit = true;
        if (pendingTurnAction) {
          chat.response = '';
          chat.thinking = '';
          chat.currentQuery = '';
          chat.isThinking = false;
          chat.toolCalls = [];
          chat.contentBlocks = [];
          pendingTurnActionsRef.current.delete(tabId);
        }
        break;

      case 'tool_call': {
        const tc = parseWsPayload<ToolCallContent>(data, 'background:tool_call');
        if (!tc) {
          return;
        }
        // Terminal tool calls: create/update inline terminal blocks
        if (tc.server === 'terminal' && tc.name === 'run_command') {
          if (tc.status === 'calling') {
            chat.contentBlocks = [...chat.contentBlocks, {
              type: 'terminal_command',
              terminal: {
                requestId: '', command: String(tc.args.command || ''), cwd: String(tc.args.cwd || ''),
                status: 'running', output: '', outputChunks: [], isPty: false,
              },
            }];
          }
          break;
        }
        const safeAgentId = typeof tc.agent_id === 'string' && tc.agent_id ? tc.agent_id : undefined;
        const safeDesc = typeof tc.description === 'string' ? tc.description.slice(0, 500) : undefined;
        const safePartial = typeof tc.partial_result === 'string' ? tc.partial_result : undefined;
        if (tc.status === 'calling') {
          const nextState = applyToolCallChange(
            chat.toolCalls,
            chat.contentBlocks,
            {
              name: tc.name,
              args: tc.args,
              server: tc.server,
              status: 'calling',
              agentId: safeAgentId,
              description: safeDesc,
            },
            true,
          );
          chat.toolCalls = nextState.toolCalls;
          chat.contentBlocks = nextState.contentBlocks;
        } else if (tc.status === 'progress' && safeAgentId) {
          const nextState = applyToolCallChange(
            chat.toolCalls,
            chat.contentBlocks,
            {
              name: tc.name,
              args: tc.args,
              server: tc.server,
              status: 'calling',
              agentId: safeAgentId,
              description: safeDesc,
              partialResult: safePartial,
            },
            false,
          );
          chat.toolCalls = nextState.toolCalls;
          chat.contentBlocks = nextState.contentBlocks;
        } else if (tc.status === 'complete') {
          const nextState = applyToolCallChange(
            chat.toolCalls,
            chat.contentBlocks,
            {
              name: tc.name,
              args: tc.args,
              result: tc.result,
              server: tc.server,
              status: 'complete',
              agentId: safeAgentId,
              description: safeDesc,
              partialResult: undefined,
            },
            false,
          );
          chat.toolCalls = nextState.toolCalls;
          chat.contentBlocks = nextState.contentBlocks;
        }
        break;
      }

      case 'terminal_output': {
        const to = parseWsPayload<TerminalOutput>(data, 'background:terminal_output');
        if (!to) {
          return;
        }

        let linkedUnassignedTerminalBlock = false;
        chat.contentBlocks = chat.contentBlocks.map(b => {
          if (b.type === 'terminal_command' && b.terminal.requestId === to.request_id) {
            return { ...b, terminal: { ...b.terminal, output: b.terminal.output + to.text + (to.raw ? '' : '\n'), outputChunks: [...b.terminal.outputChunks, { text: to.text, raw: !!to.raw }], isPty: b.terminal.isPty || !!to.raw } };
          }
          // Also match by empty requestId (created from tool_call before real id arrived)
          if (b.type === 'terminal_command' && !b.terminal.requestId && !linkedUnassignedTerminalBlock) {
            linkedUnassignedTerminalBlock = true;
            return { ...b, terminal: { ...b.terminal, requestId: to.request_id, output: b.terminal.output + to.text + (to.raw ? '' : '\n'), outputChunks: [...b.terminal.outputChunks, { text: to.text, raw: !!to.raw }], isPty: b.terminal.isPty || !!to.raw } };
          }
          return b;
        });
        break;
      }

      case 'terminal_command_complete': {
        const tc2 = parseWsPayload<TerminalCommandComplete>(data, 'background:terminal_command_complete');
        if (!tc2) {
          return;
        }
        chat.contentBlocks = chat.contentBlocks.map(b =>
          b.type === 'terminal_command' && b.terminal.requestId === tc2.request_id
            ? { ...b, terminal: { ...b.terminal, status: 'completed', exitCode: tc2.exit_code, durationMs: tc2.duration_ms } }
            : b
        );
        break;
      }

      case 'terminal_approval_request': {
        const ar = parseWsPayload<TerminalApprovalRequest>(data, 'background:terminal_approval_request');
        if (!ar) {
          return;
        }
        chat.contentBlocks = [...chat.contentBlocks, {
          type: 'terminal_command',
          terminal: {
            requestId: ar.request_id,
            command: ar.command,
            shell: ar.shell,
            warning: ar.warning,
            cwd: ar.cwd,
            status: 'pending_approval',
            output: '',
            outputChunks: [],
            isPty: false,
          },
        }];
        break;
      }

      case 'youtube_transcription_approval': {
        const approvalData = parseWsPayload<YouTubeTranscriptionApprovalRequest>(
          data,
          'background:youtube_transcription_approval',
        );
        if (!approvalData) {
          return;
        }
        chat.contentBlocks = [
          ...chat.contentBlocks,
          {
            type: 'youtube_transcription_approval',
            approval: mapYouTubeApprovalToBlock(approvalData),
          },
        ];
        break;
      }

      case 'artifact_deleted': {
        const artifactDeleted = parseWsPayload<ArtifactDeletedPayload>(data, 'background:artifact_deleted');
        if (!artifactDeleted?.artifact_id) {
          return;
        }
        if (!chatMatchesArtifactContext(chat, artifactDeleted)) {
          break;
        }
        chat.contentBlocks = markArtifactDeletedInBlocks(
          chat.contentBlocks,
          artifactDeleted.artifact_id,
        );
        chat.chatHistory = markArtifactDeletedInHistory(
          chat.chatHistory,
          artifactDeleted.artifact_id,
        );
        break;
      }

      case 'token_usage': {
        const stats = parseWsPayload<TokenUsageContent>(data, 'background:token_usage');
        if (!stats) {
          return;
        }
        const input = stats.prompt_eval_count || 0;
        const output = stats.eval_count || 0;
        const tu = { ...snap.tokens.tokenUsage };
        tu.total = (tu.total || 0) + input + output;
        tu.input = (tu.input || 0) + input;
        tu.output = (tu.output || 0) + output;
        setTabSnapshot(tabId, { ...snap, chat, tokens: { tokenUsage: tu } });
        return;
      }

      case 'queue_updated': {
        const qData = parseWsPayloadWithGuard<{ tab_id: string; items: { item_id: string; preview: string; position: number }[] }>(
          data,
          'background:queue_updated',
          isQueueUpdatedPayload,
        );
        if (!qData) {
          return;
        }
        setQueueItems(qData.tab_id, qData.items);
        return; // Don't update chat snapshot
      }

      // ── Screenshot messages for background tabs ──────────────
      case 'screenshot_added': {
        const ssData = parseWsPayload<ScreenshotAddedContent>(data, 'background:screenshot_added');
        if (!ssData) {
          return;
        }
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = [...screenshots.screenshots, ssData as unknown as Screenshot];
        setTabSnapshot(tabId, { ...snap, chat, screenshots });
        return;
      }

      case 'screenshot_removed': {
        const removeData = parseWsPayload<ScreenshotRemovedContent>(data, 'background:screenshot_removed');
        if (!removeData) {
          return;
        }
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = screenshots.screenshots.filter(ss => ss.id !== removeData.id);
        setTabSnapshot(tabId, { ...snap, chat, screenshots });
        return;
      }

      case 'screenshots_cleared': {
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = [];
        setTabSnapshot(tabId, { ...snap, chat, screenshots });
        return;
      }

      default:
        return; // Ignore other types for background tabs
    }

    setTabSnapshot(tabId, { ...snap, chat });
  }, [
    finishStreamPerfCycle,
    freshSnapshot,
    getTabSnapshot,
    markStreamPerfChunk,
    selectedModel,
    setQueueItems,
    setTabSnapshot,
    startStreamPerfCycle,
  ]);

  // ============================================
  // Fetch enabled models on mount & when returning from Settings
  // ============================================
  useEffect(() => {
    const fetchEnabledModels = async () => {
      const { api } = await import('../services/api');
      const models = await api.getEnabledModels();
      setEnabledModels(models);
      // Auto-select first model if current selection is empty or no longer enabled
      if (models.length > 0 && (!selectedModel || !models.includes(selectedModel))) {
        setSelectedModel(models[0]);
      }
    };

    void fetchEnabledModels().catch((error) => {
      console.warn('[models] Failed to fetch enabled models', error);
      setEnabledModels([]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]); // re-fetch when user navigates back from Settings

  // ============================================
  // WebSocket Message Handler (tab-aware)
  // ============================================

  const conversationTitle = useCallback((messages: ChatMessage[]) => {
    const firstUserMessage = messages.find((message) => message.role === 'user');
    return firstUserMessage?.content.slice(0, 30) || 'Chat';
  }, []);

  const buildStreamingAssistantMessage = useCallback((): ChatMessage => ({
    role: 'assistant',
    content: chatState.responseRef.current,
    thinking: chatState.thinkingRef.current || undefined,
    toolCalls:
      chatState.toolCallsRef.current.length > 0
        ? [...chatState.toolCallsRef.current]
        : undefined,
    contentBlocks:
      chatState.contentBlocksRef.current.length > 0
        ? [...chatState.contentBlocksRef.current]
        : undefined,
    model: generatingModelRef.current || selectedModel,
    timestamp: Date.now(),
  }), [chatState, selectedModel]);

  /** Handle messages that apply globally (not tab-scoped). */
  const handleGlobalMessage = useCallback((data: WebSocketMessage): boolean => {
    switch (data.type) {
      case 'ready':
        chatState.setStatus(String(data.content) || 'Ready to chat.');
        chatState.setCanSubmit(true);
        chatState.setError('');

        if (pendingCreatedTabIdRef.current) {
          wsSend({ type: 'tab_created', tab_id: pendingCreatedTabIdRef.current });
          wsSend({ type: 'tab_activated', tab_id: pendingCreatedTabIdRef.current });
          pendingCreatedTabIdRef.current = null;
        }

        // Handle pending operations
        if (pendingConversationRef.current) {
          wsSend({
            type: 'resume_conversation',
            conversation_id: pendingConversationRef.current,
          });
          pendingConversationRef.current = null;
          window.history.replaceState({}, '');
        } else if (pendingNewChatRef.current) {
          wsSend({ type: 'clear_context' });
          pendingNewChatRef.current = false;
          window.history.replaceState({}, '');
        }
        return true;

      case 'screenshot_start':
        setIsHidden(true);
        return true;

      case 'screenshot_ready':
        chatState.setStatus('Screenshot captured!');
        chatState.setError('');
        setIsHidden(false);
        return true;

      case 'screenshot_cancelled':
        chatState.setStatus(String(data.content) || 'Screenshot cancelled.');
        chatState.setError('');
        setIsHidden(false);
        return true;

      case 'transcription_result':
        chatState.setQuery((prev) => prev + (prev ? ' ' : '') + String(data.content));
        setIsRecording(false);
        chatState.setStatus('Transcription complete.');
        return true;

      case 'queue_updated': {
        const qData = parseWsPayloadWithGuard<{ tab_id: string; items: { item_id: string; preview: string; position: number }[] }>(
          data,
          'global:queue_updated',
          isQueueUpdatedPayload,
        );
        if (!qData) {
          return true;
        }
        setQueueItems(qData.tab_id, qData.items);
        return true;
      }

      case 'artifact_deleted': {
        const artifactDeleted = parseWsPayload<ArtifactDeletedPayload>(data, 'global:artifact_deleted');
        if (!artifactDeleted?.artifact_id) {
          return true;
        }

        for (const tab of tabsRef.current) {
          const snapshot = getTabSnapshot(tab.id) ?? freshSnapshot();
          if (!chatMatchesArtifactContext(snapshot.chat, artifactDeleted)) {
            continue;
          }
          setTabSnapshot(tab.id, {
            ...snapshot,
            chat: {
              ...snapshot.chat,
              contentBlocks: markArtifactDeletedInBlocks(
                snapshot.chat.contentBlocks,
                artifactDeleted.artifact_id,
              ),
              chatHistory: markArtifactDeletedInHistory(
                snapshot.chat.chatHistory,
                artifactDeleted.artifact_id,
              ),
            },
          });
        }

        if (chatMatchesArtifactContext(chatState.getSnapshot(), artifactDeleted)) {
          chatState.markArtifactDeleted(artifactDeleted.artifact_id);
          chatState.setChatHistory((previousHistory) =>
            markArtifactDeletedInHistory(previousHistory, artifactDeleted.artifact_id),
          );
        }

        return true;
      }

      case 'ollama_queue_status':
        // TODO: display Ollama serialization status in UI
        return true;

      case 'queue_full':
        chatState.setError('Queue is full. Please wait for current queries to finish.');
        return true;

      // ── Meeting messages are handled directly by their respective
      // components via WebSocketContext subscriptions — no routing needed here. ──
      case 'meeting_recording_started':
      case 'meeting_recording_stopped':
      case 'meeting_transcript_chunk':
      case 'meeting_recording_error':
      case 'meeting_recording_status':
      case 'meeting_recordings_list':
      case 'meeting_recording_loaded':
      case 'meeting_recording_deleted':
      case 'meeting_processing_progress':
      case 'meeting_analysis_started':
      case 'meeting_analysis_complete':
      case 'meeting_analysis_error':
      case 'meeting_action_result':
      case 'meeting_compute_info':
      case 'meeting_settings':
        return true;

      default:
        return false; // Not a global message
    }
  }, [chatState, freshSnapshot, getTabSnapshot, setIsHidden, setQueueItems, setTabSnapshot, wsSend]);

  /** Handle tab-scoped messages for the active tab. */
  const handleActiveTabMessage = useCallback(async (data: WebSocketMessage) => {
    const activePendingTurnAction = pendingTurnActionsRef.current.get(activeTabIdRef.current);

    switch (data.type) {
      case 'context_cleared':
        chatState.resetForNewChat();
        screenshotState.clearScreenshots();
        tokenState.resetTokens();
        setTerminalSessionRequest(null);
        setTerminalSessionActive(false);
        break;

      // ── Screenshot messages (tab-scoped) ──────────────────
      case 'screenshot_added': {
        const ssData = parseWsPayload<ScreenshotAddedContent>(data, 'active:screenshot_added');
        if (!ssData) {
          break;
        }
        screenshotState.addScreenshot(ssData);
        chatState.setStatus('Screenshot added to context.');
        setIsHidden(false);
        break;
      }

      case 'screenshot_removed': {
        const removeData = parseWsPayload<ScreenshotRemovedContent>(data, 'active:screenshot_removed');
        if (!removeData) {
          break;
        }
        screenshotState.removeScreenshot(removeData.id);
        break;
      }

      case 'screenshots_cleared':
        screenshotState.clearScreenshots();
        break;

      case 'query': {
        // Guard: skip if we already started this query via optimistic update
        // (prevents resetting toolCalls/contentBlocks that may have arrived).
        const echoText = String(data.content);
        startStreamPerfCycle(echoText, generatingModelRef.current || selectedModel);
        if (chatState.currentQueryRef.current !== echoText) {
          chatState.startQuery(echoText);
        }
        break;
      }

      case 'tool_call': {
        const tc = parseWsPayload<ToolCallContent>(data, 'active:tool_call');
        if (!tc) {
          break;
        }

        if (tc.server === 'terminal' && tc.name === 'run_command') {
          if (tc.status === 'calling') {
            chatState.setStatus(`Running command: ${tc.args.command}...`);
            pendingTerminalCommandRef.current = {
              command: String(tc.args.command || ''),
              cwd: String(tc.args.cwd || ''),
            };
          }
          break;
        }

        const safeAgentId2 = typeof tc.agent_id === 'string' && tc.agent_id ? tc.agent_id : undefined;
        const safeDesc2 = typeof tc.description === 'string' ? tc.description.slice(0, 500) : undefined;
        const safePartial2 = typeof tc.partial_result === 'string' ? tc.partial_result : undefined;
        if (tc.status === 'calling') {
          chatState.setStatus(`Calling tool: ${tc.name}...`);
          const existingSubAgent =
            tc.server === 'sub_agent'
            && !!safeAgentId2
            && chatState.toolCallsRef.current.some((toolCall) => toolCall.agentId === safeAgentId2);
          if (existingSubAgent) {
            chatState.updateToolCall({
              name: tc.name, args: tc.args, server: tc.server,
              status: 'calling', agentId: safeAgentId2, description: safeDesc2,
            });
          } else {
            chatState.addToolCall({
              name: tc.name, args: tc.args, server: tc.server,
              status: 'calling', agentId: safeAgentId2, description: safeDesc2,
            });
          }
        } else if (tc.status === 'progress' && safeAgentId2) {
          chatState.updateToolCall({
            name: tc.name, args: tc.args, server: tc.server,
            status: 'calling', agentId: safeAgentId2, description: safeDesc2, partialResult: safePartial2,
          });
        } else if (tc.status === 'complete') {
          chatState.updateToolCall({
            name: tc.name, args: tc.args, result: tc.result, server: tc.server,
            status: 'complete', agentId: safeAgentId2, description: safeDesc2,
            ...(tc.server === 'sub_agent' ? {} : { partialResult: undefined }),
          });
          chatState.setStatus('Tool call complete.');
        }
        break;
      }

      case 'sub_agent_stream': {
        const stream = parseWsPayload<SubAgentStreamContent & { accumulated?: string }>(
          data,
          'active:sub_agent_stream',
        );
        if (!stream) {
          break;
        }

        const safeAgentId = typeof stream.agent_id === 'string' && stream.agent_id ? stream.agent_id : undefined;
        if (!safeAgentId) {
          break;
        }

        const safeAgentName = typeof stream.agent_name === 'string' && stream.agent_name
          ? stream.agent_name
          : 'Sub-agent';
        const safeModelTier = typeof stream.model_tier === 'string' ? stream.model_tier : '';
        const safeDescription = safeModelTier
          ? `${safeAgentName} (${safeModelTier})`
          : safeAgentName;
        const safeTranscript = Array.isArray(stream.transcript) ? stream.transcript : undefined;
        const safeAccumulated = typeof stream.accumulated === 'string' ? stream.accumulated : undefined;
        const safeContent = typeof stream.content === 'string' ? stream.content : undefined;

        let partialResult = 'Sub-agent is working...';
        if (safeTranscript && safeTranscript.length > 0) {
          partialResult = JSON.stringify(safeTranscript);
        } else if (safeAccumulated && safeAccumulated.trim().length > 0) {
          partialResult = safeAccumulated;
        } else if (safeContent && safeContent.trim().length > 0) {
          partialResult = safeContent;
        }

        const isKnownToolCall = chatState.toolCallsRef.current.some(
          (toolCall) => toolCall.agentId === safeAgentId,
        );
        if (!isKnownToolCall) {
          chatState.addToolCall({
            name: 'spawn_agent',
            args: { agent_name: safeAgentName, model_tier: safeModelTier },
            server: 'sub_agent',
            status: 'calling',
            agentId: safeAgentId,
            description: safeDescription,
          });
        }

        switch (stream.stream_type) {
          case 'thinking':
          case 'thinking_complete':
          case 'final':
          case 'instruction':
          case 'tool_call':
          case 'tool_result':
          case 'tool_error':
          case 'tool_blocked':
            chatState.updateToolCall({
              name: 'spawn_agent',
              args: { agent_name: safeAgentName, model_tier: safeModelTier },
              server: 'sub_agent',
              status: 'calling',
              agentId: safeAgentId,
              description: safeDescription,
              partialResult,
            });
            break;
          default:
            break;
        }
        break;
      }

      case 'tool_calls_summary': {
        const calls = parseWsPayload<unknown>(data, 'active:tool_calls_summary');
        if (!calls) {
          break;
        }
        if (Array.isArray(calls) && calls.length > 0) {
          let mergedToolCalls = chatState.toolCallsRef.current;
          let mergedContentBlocks = chatState.contentBlocksRef.current;

          for (const rawCall of calls) {
            if (!rawCall || typeof rawCall !== 'object') {
              continue;
            }

            const nextState = applyToolCallChange(
              mergedToolCalls,
              mergedContentBlocks,
              rawCall as ToolCall,
              true,
            );
            mergedToolCalls = nextState.toolCalls;
            mergedContentBlocks = nextState.contentBlocks;
          }

          chatState.toolCallsRef.current = mergedToolCalls;
          chatState.contentBlocksRef.current = mergedContentBlocks;
        }
        break;
      }

      case 'thinking_chunk':
        chatState.appendThinking(String(data.content));
        break;

      case 'thinking_complete':
        chatState.setIsThinking(false);
        chatState.setStatus('Receiving response...');
        break;

      case 'artifact_start': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'active:artifact_start');
        if (!artifactData) {
          break;
        }
        chatState.addArtifactBlock(mapArtifactPayloadToBlock(artifactData).artifact);
        break;
      }

      case 'artifact_chunk': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'active:artifact_chunk');
        if (!artifactData) {
          break;
        }
        chatState.addArtifactBlock(mapArtifactPayloadToBlock(artifactData).artifact);
        break;
      }

      case 'artifact_complete': {
        const artifactData = parseWsPayload<ArtifactContentPayload>(data, 'active:artifact_complete');
        if (!artifactData) {
          break;
        }
        chatState.completeArtifactBlock(mapArtifactPayloadToBlock(artifactData).artifact);
        break;
      }

      case 'response_chunk':
        {
          const chunk = String(data.content);
          markStreamPerfChunk(chunk);
          chatState.appendResponse(chunk);
        }
        break;

      case 'response_complete':
        finishStreamPerfCycle('response-complete');
        if (activePendingTurnAction) {
          chatState.setIsThinking(false);
          chatState.setStatus('Saving updated turn...');
        } else {
          chatState.completeResponse(screenshotState.getImageData(), generatingModelRef.current);
        }
        break;

      case 'token_usage': {
        const stats = parseWsPayload<TokenUsageContent>(data, 'active:token_usage');
        if (!stats) {
          break;
        }
        const input = stats.prompt_eval_count || 0;
        const output = stats.eval_count || 0;
        tokenState.addTokens(input, output);
        break;
      }

      case 'conversation_saved': {
        const { applySavedTurnToHistory } = await loadConversationMessageTransforms();
        const saveData = parseWsPayload<ConversationSavedContent>(data, 'active:conversation_saved');
        if (!saveData) {
          break;
        }
        chatState.setConversationId(saveData.conversation_id);

        if (activePendingTurnAction && !saveData.turn) {
          chatState.clearStreamingState('Updated turn saved. Reloading conversation...');
          pendingTurnActionsRef.current.delete(activeTabIdRef.current);
          wsSend({
            type: 'resume_conversation',
            conversation_id: saveData.conversation_id,
          });
          break;
        }

        let nextHistory: ChatMessage[] | null = null;
        if (saveData.turn) {
          if (
            activePendingTurnAction &&
            !hasTurnInHistory(chatState.chatHistory, saveData.turn)
          ) {
            chatState.clearStreamingState('Updated turn saved. Reloading conversation...');
            pendingTurnActionsRef.current.delete(activeTabIdRef.current);
            wsSend({
              type: 'resume_conversation',
              conversation_id: saveData.conversation_id,
            });
            break;
          }

          nextHistory = applySavedTurnToHistory(
            chatState.chatHistory,
            saveData.turn,
            saveData.operation ?? activePendingTurnAction?.type ?? 'submit',
            buildPendingTurnLocalPatch(
              chatState.chatHistory,
              saveData.turn,
              activePendingTurnAction,
              activePendingTurnAction ? buildStreamingAssistantMessage() : undefined,
            ),
          );
          chatState.setChatHistory(nextHistory);
        }

        if (activePendingTurnAction) {
          chatState.clearStreamingState();
          pendingTurnActionsRef.current.delete(activeTabIdRef.current);
        }

        const titleHistory = nextHistory ?? chatState.chatHistory;
        if (titleHistory.length > 0) {
          updateTabTitle(activeTabIdRef.current, conversationTitle(titleHistory));
        }
        break;
      }

      case 'conversation_resumed': {
        const { mapConversationMessagePayload } = await loadConversationMessageTransforms();
        const resumeData = parseWsPayloadWithGuard<ConversationResumedContent>(
          data,
          'active:conversation_resumed',
          isConversationResumedPayload,
        );
        if (!resumeData) {
          break;
        }

        const msgs: ChatMessage[] = resumeData.messages.map(mapConversationMessagePayload);

        chatState.loadConversation(resumeData.conversation_id, msgs);
        screenshotState.clearScreenshots();
        pendingTurnActionsRef.current.delete(activeTabIdRef.current);
        if (msgs.length > 0) {
          updateTabTitle(activeTabIdRef.current, conversationTitle(msgs));
        }

        if (resumeData.token_usage) {
          tokenState.setTokenUsage({
            total: resumeData.token_usage.total || 0,
            input: resumeData.token_usage.input || 0,
            output: resumeData.token_usage.output || 0,
          });
        }
        break;
      }

      case 'error':
        finishStreamPerfCycle('error');
        if (activePendingTurnAction) {
          pendingTurnActionsRef.current.delete(activeTabIdRef.current);
          chatState.clearStreamingState('An error occurred.');
        }
        chatState.setError(String(data.content));
        chatState.setStatus('An error occurred.');
        chatState.setCanSubmit(true);
        break;

      // ── Terminal messages ──────────────────────────────
      case 'terminal_approval_request': {
        const approvalData = parseWsPayload<TerminalApprovalRequest>(data, 'active:terminal_approval_request');
        if (!approvalData) {
          break;
        }
        chatState.addTerminalBlock({
          requestId: approvalData.request_id,
          command: approvalData.command,
          cwd: approvalData.cwd,
          status: 'pending_approval',
          output: '',
          outputChunks: [],
          isPty: false,
        });
        break;
      }

      case 'youtube_transcription_approval': {
        const approvalData = parseWsPayload<YouTubeTranscriptionApprovalRequest>(
          data,
          'active:youtube_transcription_approval',
        );
        if (!approvalData) {
          break;
        }
        chatState.addYouTubeApprovalBlock(mapYouTubeApprovalToBlock(approvalData));
        break;
      }

      case 'artifact_deleted': {
        const artifactDeleted = parseWsPayload<ArtifactDeletedPayload>(data, 'active:artifact_deleted');
        if (!artifactDeleted?.artifact_id) {
          break;
        }
        if (!chatMatchesArtifactContext(chatState.getSnapshot(), artifactDeleted)) {
          break;
        }
        chatState.markArtifactDeleted(artifactDeleted.artifact_id);
        chatState.setChatHistory((previousHistory) =>
          markArtifactDeletedInHistory(previousHistory, artifactDeleted.artifact_id),
        );
        break;
      }

      case 'terminal_session_request': {
        const sessionData = parseWsPayload<TerminalSessionRequest>(data, 'active:terminal_session_request');
        if (!sessionData) {
          break;
        }
        setTerminalSessionRequest(sessionData);
        break;
      }

      case 'terminal_session_started':
        setTerminalSessionActive(true);
        setTerminalSessionRequest(null);
        break;

      case 'terminal_session_ended':
        setTerminalSessionActive(false);
        break;

      case 'terminal_output': {
        const outputData = parseWsPayload<TerminalOutput>(data, 'active:terminal_output');
        if (!outputData) {
          break;
        }
        const hasBlock = chatState.contentBlocksRef.current.some(
          b => b.type === 'terminal_command' && b.terminal.requestId === outputData.request_id
        );
        if (!hasBlock) {
          const pending = pendingTerminalCommandRef.current;
          chatState.addTerminalBlock({
            requestId: outputData.request_id,
            command: pending?.command || '',
            cwd: pending?.cwd || '',
            status: 'running',
            output: '',
            outputChunks: [],
            isPty: !!outputData.raw,
          });
          pendingTerminalCommandRef.current = null;
        } else {
          chatState.updateTerminalBlock(outputData.request_id, { status: 'running' });
        }
        chatState.appendTerminalOutput(outputData.request_id, outputData.text, !!outputData.raw);
        break;
      }

      case 'terminal_command_complete': {
        const completeData = parseWsPayload<TerminalCommandComplete>(
          data,
          'active:terminal_command_complete',
        );
        if (!completeData) {
          break;
        }
        chatState.updateTerminalBlock(completeData.request_id, {
          status: 'completed',
          exitCode: completeData.exit_code,
          durationMs: completeData.duration_ms,
        });
        break;
      }

      case 'terminal_running_notice':
        break;
    }
  }, [
    buildStreamingAssistantMessage,
    chatState,
    conversationTitle,
    finishStreamPerfCycle,
    markStreamPerfChunk,
    screenshotState,
    selectedModel,
    setIsHidden,
    startStreamPerfCycle,
    tokenState,
    updateTabTitle,
    wsSend,
  ]);

  /** Top-level WS message router: global → active tab → background tab. */
  const handleWebSocketMessage = useCallback((data: WebSocketMessage) => {
    // Global messages are handled first regardless of tab_id
    if (handleGlobalMessage(data)) return;

    // Determine which tab this message is for
    const messageTabId = 'tab_id' in data && typeof data.tab_id === 'string'
      ? data.tab_id
      : 'default';

    if (messageTabId === activeTabIdRef.current) {
      void handleActiveTabMessage(data).catch((error) => {
        console.warn('[ws] Active tab message handling failed', error);
      });
    } else {
      void applyToBackgroundTab(messageTabId, data).catch((error) => {
        console.warn('[ws] Background tab message handling failed', error);
      });
    }
  }, [handleGlobalMessage, handleActiveTabMessage, applyToBackgroundTab]);

  // Keep WS handler in a ref so the subscription callback always calls
  // the latest version without needing to re-subscribe.
  const handleWebSocketMessageRef = useRef(handleWebSocketMessage);
  handleWebSocketMessageRef.current = handleWebSocketMessage;

  // ============================================
  // WebSocket Subscription (connection managed by WebSocketProvider)
  // ============================================
  useEffect(() => {
    return wsSubscribe((data) => {
      if (data.type === '__ws_connected') {
        // Connection (re-)established — run onopen logic
        chatState.setStatus('Connected to server');
        chatState.setError('');
        for (const tab of tabsRef.current) {
          wsSend({ type: 'tab_created', tab_id: tab.id });
        }
        wsSend({ type: 'tab_activated', tab_id: activeTabIdRef.current });
        wsSend({ type: 'set_capture_mode', mode: captureModeRef.current });
        return;
      }
      if (data.type === '__ws_disconnected') {
        chatState.setStatus('Disconnected. Retrying...');
        return;
      }
      // Route all real messages through the existing handler
      handleWebSocketMessageRef.current(data as unknown as WebSocketMessage);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsSubscribe]);

  // ============================================
  // Navigation Handler
  // ============================================
  useEffect(() => {
    const state = location.state as { conversationId?: string; newChat?: boolean; tabId?: string } | null;

    if (state?.conversationId) {
      setShowScrollBottom(false);
      if (isConnected) {
        if (state.tabId) {
          wsSend({ type: 'tab_created', tab_id: state.tabId });
          wsSend({ type: 'tab_activated', tab_id: state.tabId });
        }
        wsSend({
          type: 'resume_conversation',
          conversation_id: state.conversationId,
        });
        window.history.replaceState({}, '');
      } else {
        pendingCreatedTabIdRef.current = state.tabId ?? null;
        pendingConversationRef.current = state.conversationId;
      }
    } else if (state?.newChat) {
      setShowScrollBottom(false);
      if (isConnected) {
        if (state.tabId) {
          wsSend({ type: 'tab_created', tab_id: state.tabId });
          wsSend({ type: 'tab_activated', tab_id: state.tabId });
        }
        wsSend({ type: 'clear_context' });
        window.history.replaceState({}, '');
      } else {
        pendingCreatedTabIdRef.current = state.tabId ?? null;
        pendingNewChatRef.current = true;
      }
    }
  }, [isConnected, location.state, wsSend]);

  // ============================================
  // Focus Handler
  // ============================================
  useEffect(() => {
    if (chatState.canSubmit && inputRef.current) {
      const focusInput = async () => {
        try {
          if (window.electronAPI) {
            await window.electronAPI.focusWindow();
          } else {
            window.focus();
          }
          setTimeout(() => inputRef.current?.focus(), 50);
        } catch (error) {
          console.error('Failed to focus window:', error);
          inputRef.current?.focus();
        }
      };
      focusInput();
    }
  }, [chatState.canSubmit]);

  // ============================================
  // Event Handlers
  // ============================================
  const scrollToBottom = useCallback(() => {
    responseAreaRef.current?.scrollTo({
      top: responseAreaRef.current.scrollHeight,
      behavior: 'auto',
    });
  }, []);

  const updateScrollBottomVisibility = useCallback(() => {
    if (responseAreaRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = responseAreaRef.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
      setShowScrollBottom(!isNearBottom);
    }
  }, []);

  const handleScroll = useCallback(() => {
    updateScrollBottomVisibility();
  }, [updateScrollBottomVisibility]);

  useEffect(() => {
    const container = responseAreaRef.current;
    if (!container) {
      return;
    }

    let frameId: number | null = null;
    const scheduleVisibilityUpdate = () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(() => {
        frameId = null;
        updateScrollBottomVisibility();
      });
    };

    scheduleVisibilityUpdate();

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => scheduleVisibilityUpdate());
      resizeObserver.observe(container);
    }

    let mutationObserver: MutationObserver | null = null;
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver(() => scheduleVisibilityUpdate());
      mutationObserver.observe(container, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['style'],
      });
    }

    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
    };
  }, [updateScrollBottomVisibility]);

  const thinkingCollapsed = chatState.thinkingCollapsed;
  const setThinkingCollapsed = chatState.setThinkingCollapsed;

  const handleToggleThinking = useCallback(() => {
    setThinkingCollapsed(!thinkingCollapsed);
  }, [setThinkingCollapsed, thinkingCollapsed]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!isConnected) return;

    const queryText = chatState.query.trim();
    if (!queryText) return;

    const attachedFiles = attachedFilesRef.current;

    // Handle /new command - create a new tab
    if (queryText === '/new' || queryText.startsWith('/new ')) {
      // Clear query state and the input DOM immediately
      chatState.setQuery('');
      if (inputRef.current) {
        inputRef.current.textContent = '';
      }

      // Manually save the current tab state with query cleared before switching
      // This is needed because React state updates are async, but createTab()
      // triggers beforeSwitch which snapshots state immediately
      const oldTabId = activeTabIdRef.current;
      const chatSnapshot = chatState.getSnapshot();
      setTabSnapshot(oldTabId, {
        chat: { ...chatSnapshot, query: '' },
        screenshots: screenshotState.getSnapshot(),
        tokens: tokenState.getSnapshot(),
        terminal: {
          terminalSessionActive,
          terminalSessionRequest,
        },
        generatingModel: generatingModelRef.current,
      });

      const newTabId = createTab();

      // If there's a message after /new, submit it in the new tab
      if (newTabId && queryText.startsWith('/new ')) {
        const initialMessage = queryText.slice(5).trim();
        if (initialMessage) {
          // Start the query in the new tab's chat state (will be initialized by afterSwitch)
          // Use a short delay to ensure tab state is initialized
          setTimeout(() => {
            chatState.startQuery(initialMessage);
            setTimeout(scrollToBottom, 50);
            generatingModelRef.current = selectedModel;
            wsSendRaw({
              tab_id: newTabId,
              type: 'submit_query',
              content: initialMessage,
              capture_mode: screenshotState.captureMode,
              model: selectedModel,
              attached_files: attachedFiles,
            });
          }, 0);
        }
      }
      return;
    }

    chatState.setQuery('');

    // Optimistic update: show the query immediately instead of waiting
    // for the server echo.  Only for non-queued queries (canSubmit===true)
    // to avoid overwriting in-flight state for queued messages.
    startStreamPerfCycle(queryText, selectedModel);
    if (chatState.canSubmit) {
      chatState.startQuery(queryText);
    }

    setTimeout(scrollToBottom, 50);

    generatingModelRef.current = selectedModel;

    wsSend({
      type: 'submit_query',
      content: queryText,
      capture_mode: screenshotState.captureMode,
      model: selectedModel,
      attached_files: attachedFiles,
    });
  };

  const handleRetryMessage = useCallback((message: ChatMessage) => {
    if (!isConnected || !message.messageId || !chatState.canSubmit) {
      return;
    }

    pendingTurnActionsRef.current.set(activeTabIdRef.current, {
      type: 'retry',
      messageId: message.messageId,
    });
    generatingModelRef.current = selectedModel;
    setTimeout(scrollToBottom, 50);
    wsSend({
      type: 'retry_message',
      message_id: message.messageId,
      model: selectedModel,
    });
  }, [chatState.canSubmit, isConnected, scrollToBottom, selectedModel, wsSend]);

  const handleEditMessage = useCallback((message: ChatMessage, content: string) => {
    if (!isConnected || !message.messageId || !chatState.canSubmit) {
      return;
    }

    pendingTurnActionsRef.current.set(activeTabIdRef.current, {
      type: 'edit',
      messageId: message.messageId,
      editedContent: content,
    });
    generatingModelRef.current = selectedModel;
    setTimeout(scrollToBottom, 50);
    wsSend({
      type: 'edit_message',
      message_id: message.messageId,
      content,
      model: selectedModel,
    });
  }, [chatState.canSubmit, isConnected, scrollToBottom, selectedModel, wsSend]);

  const setChatHistory = chatState.setChatHistory;

  const syncActiveTabArtifactSnapshot = useCallback((
    nextContentBlocks: ContentBlock[],
    nextHistory: ChatMessage[],
  ) => {
    const activeTabId = activeTabIdRef.current;
    if (!activeTabId) {
      return;
    }

    const snapshot = getTabSnapshot(activeTabId) ?? freshSnapshot();
    setTabSnapshot(activeTabId, {
      ...snapshot,
      chat: {
        ...chatState.getSnapshot(),
        contentBlocks: nextContentBlocks,
        chatHistory: nextHistory,
      },
    });
  }, [chatState, freshSnapshot, getTabSnapshot, setTabSnapshot]);

  const handleArtifactUpdated = useCallback((artifact: ArtifactBlockData) => {
    const nextContentBlocks = updateArtifactInBlocks(
      chatState.contentBlocksRef.current,
      artifact,
      false,
    );
    const nextHistory = updateArtifactInHistory(chatState.chatHistory, artifact);

    chatState.updateArtifactBlock(artifact);
    chatState.setChatHistory(nextHistory);
    syncActiveTabArtifactSnapshot(nextContentBlocks, nextHistory);
  }, [chatState, syncActiveTabArtifactSnapshot]);

  const handleArtifactDeleted = useCallback((artifactId: string) => {
    const nextContentBlocks = markArtifactDeletedInBlocks(
      chatState.contentBlocksRef.current,
      artifactId,
    );
    const nextHistory = markArtifactDeletedInHistory(chatState.chatHistory, artifactId);

    chatState.markArtifactDeleted(artifactId);
    chatState.setChatHistory(nextHistory);
    syncActiveTabArtifactSnapshot(nextContentBlocks, nextHistory);
  }, [chatState, syncActiveTabArtifactSnapshot]);

  const handleSetActiveResponse = useCallback(async (message: ChatMessage, responseIndex: number) => {
    if (!message.messageId || !message.responseVersions) {
      return;
    }

    const { applyResponseVariant } = await loadConversationMessageTransforms();
    const nextMessage = applyResponseVariant(message, responseIndex);
    if (!nextMessage) {
      return;
    }

    setChatHistory((prev) =>
      prev.map((entry) =>
        entry.messageId === message.messageId
          ? nextMessage
          : entry,
      ),
    );

    wsSend({
      type: 'set_active_response',
      message_id: message.messageId,
      response_index: responseIndex,
    });
  }, [setChatHistory, wsSend]);

  const handleStopStreaming = () => {
    wsSend({ type: 'stop_streaming' });
  };

  const handleRemoveScreenshot = (id: string) => {
    wsSend({ type: 'remove_screenshot', id });
  };

  const sendCaptureMode = useCallback((mode: 'fullscreen' | 'precision' | 'none') => {
    wsSend({ type: 'set_capture_mode', mode });
  }, [wsSend]);

  useEffect(() => {
    if (hasNormalizedCaptureModeRef.current) {
      return;
    }

    hasNormalizedCaptureModeRef.current = true;

    const state = location.state as { selectedCaptureMode?: 'fullscreen' | 'precision' } | null;
    const selectedCaptureMode = state?.selectedCaptureMode;

    if (selectedCaptureMode) {
      screenshotState.setMeetingRecordingMode(false);
      screenshotState.setCaptureMode(selectedCaptureMode);
      sendCaptureMode(selectedCaptureMode);
      return;
    }

    if (screenshotState.meetingRecordingMode) {
      const fallbackCaptureMode = screenshotState.captureMode === 'none'
        ? 'precision'
        : screenshotState.captureMode;

      screenshotState.setMeetingRecordingMode(false);
      if (screenshotState.captureMode === 'none') {
        screenshotState.setCaptureMode(fallbackCaptureMode);
      }
      sendCaptureMode(fallbackCaptureMode);
    }
  }, [location.state, screenshotState, sendCaptureMode]);

  const fullscreenModeEnabled = () => {
    screenshotState.setCaptureMode('fullscreen');
    screenshotState.setMeetingRecordingMode(false);
    sendCaptureMode('fullscreen');
  };

  const precisionModeEnabled = () => {
    screenshotState.setCaptureMode('precision');
    screenshotState.setMeetingRecordingMode(false);
    sendCaptureMode('precision');
  };

  const meetingRecordingModeEnabled = () => {
    screenshotState.setMeetingRecordingMode(true);
    sendCaptureMode('none');
    navigate('/recorder');
  };

  const getPlaceholder = () => {
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const hotkeyText = isMac ? "Control+." : "Alt+.";

    if (chatState.chatHistory.length > 0) {
      return screenshotState.screenshots.length > 0
        ? "Ask a follow-up about the screenshot(s)..."
        : "Ask a follow-up question...";
    }
    if (screenshotState.captureMode === 'fullscreen') {
      return "Ask Xpdite anything on your screen...";
    }
    if (screenshotState.captureMode === 'precision') {
      return screenshotState.screenshots.length > 0
        ? "Ask about the screenshot(s)..."
        : "Ask Xpdite about a region on your screen (" + hotkeyText + ")";
    }
    return "Ask Xpdite anything...";
  };

  const handleMicClick = () => {
    if (!isConnected) return;

    if (isRecording) {
      wsSend({ type: 'stop_recording' });
      chatState.setStatus('Transcribing...');
    } else {
      wsSend({ type: 'start_recording' });
      setIsRecording(true);
      chatState.setStatus('Listening...');
    }
  };

  // ── Terminal Action Handlers ────────────────────────────────
  const handleTerminalApprovalResponse = useCallback((requestId: string, approved: boolean, remember: boolean) => {
    wsSend({
      type: 'terminal_approval_response',
      request_id: requestId,
      approved,
      remember,
    });

    if (approved) {
      // Transition inline block to running state
      chatState.updateTerminalBlock(requestId, { status: 'running' });
    } else {
      // Transition inline block to denied state
      chatState.updateTerminalBlock(requestId, { status: 'denied' });
    }
  }, [chatState, wsSend]);

  const handleTerminalApprove = useCallback((requestId: string) => {
    handleTerminalApprovalResponse(requestId, true, false);
  }, [handleTerminalApprovalResponse]);

  const handleTerminalDeny = useCallback((requestId: string) => {
    handleTerminalApprovalResponse(requestId, false, false);
  }, [handleTerminalApprovalResponse]);

  const handleTerminalApproveRemember = useCallback((requestId: string) => {
    handleTerminalApprovalResponse(requestId, true, true);
  }, [handleTerminalApprovalResponse]);

  const handleYouTubeApprovalResponse = useCallback((requestId: string, approved: boolean) => {
    wsSend({
      type: 'youtube_transcription_approval_response',
      request_id: requestId,
      approved,
    });
    chatState.updateYouTubeApprovalBlock(requestId, {
      status: approved ? 'approved' : 'denied',
    });
  }, [chatState, wsSend]);

  const handleTerminalSessionResponse = (approved: boolean) => {
    wsSend({
      type: 'terminal_session_response',
      approved,
    });
    setTerminalSessionRequest(null);
  };

  const handleStopSession = () => {
    wsSend({
      type: 'terminal_stop_session',
    });
    setTerminalSessionActive(false);
  };

  const handleKillCommand = useCallback((requestId: string) => {
    void requestId;
    wsSend({
      type: 'terminal_kill_command',
    });
  }, [wsSend]);

  const handleTerminalResize = useCallback((cols: number, rows: number) => {
    wsSend({
      type: 'terminal_resize',
      cols,
      rows,
    });
  }, [wsSend]);

  // ============================================
  // Render
  // ============================================
  const hasTabBar = tabs.length > 1;
  const responseAreaTopInset = hasTabBar ? 58 : 30;
  const responseAreaBottomInset = interactionSectionHeight + 15;
  const scrollButtonBottom = interactionSectionHeight + 10;

  const selectedModelProvider = selectedModel ? getModelProviderKey(selectedModel) : '';
  const showProviderLogo = hasProviderLogo(selectedModelProvider);
  const modelLabelCounts = useMemo(() => {
    const counts = new Map<string, number>();
    enabledModels.forEach((modelId) => {
      const label = formatModelLabel(modelId);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    });
    return counts;
  }, [enabledModels]);

  return (
    <div className="content-container" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <TitleBar setMini={setMini} />
      <TabBar wsSend={wsSend} />

      <ResponseArea
        chatHistory={chatState.chatHistory}
        currentQuery={chatState.currentQuery}
        thinking={chatState.thinking}
        isThinking={chatState.isThinking}
        thinkingCollapsed={chatState.thinkingCollapsed}
        contentBlocks={chatState.contentBlocks}
        generatingModel={generatingModelRef.current || selectedModel}
        canSubmit={chatState.canSubmit}
        error={chatState.error}
        showScrollBottom={showScrollBottom}
        onRetryMessage={handleRetryMessage}
        onEditMessage={handleEditMessage}
        onSetActiveResponse={handleSetActiveResponse}
        onArtifactUpdated={handleArtifactUpdated}
        onArtifactDeleted={handleArtifactDeleted}
        onToggleThinking={handleToggleThinking}
        onScroll={handleScroll}
        onScrollToBottom={scrollToBottom}
        responseAreaRef={responseAreaRef}
        scrollDownIcon={scrollDownIcon}
        onTerminalApprove={handleTerminalApprove}
        onTerminalDeny={handleTerminalDeny}
        onTerminalApproveRemember={handleTerminalApproveRemember}
        onTerminalKill={handleKillCommand}
        onTerminalResize={handleTerminalResize}
        onYouTubeApprovalResponse={handleYouTubeApprovalResponse}
        hasTabBar={hasTabBar}
        topInset={responseAreaTopInset}
        bottomInset={responseAreaBottomInset}
        scrollButtonBottom={scrollButtonBottom}
      />

      <div className="main-interaction-section" ref={mainInteractionRef}>
        {/* Session mode indicators */}
        {terminalSessionRequest && (
          <div className="terminal-session-chip terminal-session-chip--request">
            <span className="terminal-session-chip-label">
              <BoltIcon size={12} className="terminal-session-chip-icon" />
              <span>Autonomous mode requested</span>
            </span>
            <button
              className="terminal-session-chip-button terminal-session-chip-button--allow"
              onClick={() => handleTerminalSessionResponse(true)}
            >
              Allow
            </button>
            <button
              className="terminal-session-chip-button terminal-session-chip-button--deny"
              onClick={() => handleTerminalSessionResponse(false)}
            >
              Deny
            </button>
          </div>
        )}
        {terminalSessionActive && (
          <div className="terminal-session-chip terminal-session-chip--active">
            <span className="terminal-session-chip-label">
              <BoltIcon size={12} className="terminal-session-chip-icon" />
              <span>Autonomous mode active</span>
            </span>
            <button
              className="terminal-session-chip-button terminal-session-chip-button--stop"
              onClick={handleStopSession}
            >
              Stop
            </button>
          </div>
        )}

        <QueueDropdown
          items={queueMap[activeTabId] ?? []}
          onCancel={(itemId) => wsSend({ type: 'cancel_queued_item', item_id: itemId })}
        />

        <div className="query-input-section">
          <QueryInput
            ref={inputRef}
            query={chatState.query}
            placeholder={getPlaceholder()}
            canSubmit={chatState.canSubmit}
            enabledModels={enabledModels}
            onAttachedFilesChange={(files) => {
              attachedFilesRef.current = files;
            }}
            onQueryChange={chatState.setQuery}
            onSubmit={handleSubmit}
            onStopStreaming={handleStopStreaming}
            onSelectModel={setSelectedModel}
          />

          <div className="input-options-section">
            <div
              className="chips-container-wrapper"
              onWheel={(e) => {
                if (e.deltaY !== 0) {
                  e.currentTarget.scrollLeft += e.deltaY;
                  e.preventDefault();
                }
              }}
            >
              <ScreenshotChips
                screenshots={screenshotState.screenshots}
                onRemove={handleRemoveScreenshot}
              />
            </div>

            <div className="additional-inputs-section">
              <div className="model-selection-section">
                <div className="model-select-wrapper">
                  {showProviderLogo && (
                    <span
                      className="model-provider-badge"
                      title={`${getProviderLabel(selectedModelProvider)} model`}
                    >
                      <ProviderLogo
                        provider={selectedModelProvider}
                        className="model-provider-badge-icon"
                      />
                    </span>
                  )}
                  <select
                    name="model-selector"
                    className="model-select"
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                  >
                    {enabledModels.length === 0 && (
                      <option value="" disabled>No models enabled</option>
                    )}
                    {enabledModels.map((model) => {
                      const modelLabel = formatModelLabel(model);
                      const isLabelDuplicate = (modelLabelCounts.get(modelLabel) ?? 0) > 1;
                      const optionLabel = isLabelDuplicate
                        ? `${modelLabel} · ${getProviderLabel(getModelProviderKey(model))}`
                        : modelLabel;

                      return (
                        <option key={model} value={model}>
                          {optionLabel}
                        </option>
                      );
                    })}
                  </select>
                </div>
              </div>

              <TokenUsagePopup
                tokenUsage={tokenState.tokenUsage}
                show={tokenState.showTokenPopup}
                onMouseEnter={() => tokenState.setShowTokenPopup(true)}
                onMouseLeave={() => tokenState.setShowTokenPopup(false)}
                onClick={() => tokenState.setShowTokenPopup(!tokenState.showTokenPopup)}
                contextWindowIcon={contextWindowInsightsIcon}
              />

              <div
                className={`mic-input-section ${isRecording ? 'recording' : ''}`}
                onClick={handleMicClick}
                title={isRecording ? "Stop recording" : "Start voice input"}
              >
                <img src={micSignSvg} alt="Voice input" className="mic-icon" />
              </div>
            </div>
          </div>
        </div>

        <ModeSelector
          captureMode={screenshotState.captureMode}
          meetingRecordingMode={screenshotState.meetingRecordingMode}
          onFullscreenMode={fullscreenModeEnabled}
          onPrecisionMode={precisionModeEnabled}
          onMeetingMode={meetingRecordingModeEnabled}
          regionSSIcon={regionSSIcon}
          fullscreenSSIcon={fullscreenSSIcon}
        />
      </div>
    </div>
  );
}

export default App;
