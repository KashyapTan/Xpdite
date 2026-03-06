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
import { useState, useEffect, useRef, useCallback } from 'react';
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
import { ResponseArea } from '../components/chat/ResponseArea';
import { QueryInput } from '../components/input/QueryInput';
import { QueueDropdown } from '../components/input/QueueDropdown';
import { ModeSelector } from '../components/input/ModeSelector';
import { TokenUsagePopup } from '../components/input/TokenUsagePopup';
import { ScreenshotChips } from '../components/input/ScreenshotChips';
import '../CSS/QueueDropdown.css';

// Types
import type {
  WebSocketMessage,
  TabSnapshot,
  Screenshot,
  ScreenshotAddedContent,
  ScreenshotRemovedContent,
  ConversationSavedContent,
  ConversationResumedContent,
  ConversationTurnPayload,
  ToolCallContent,
  TokenUsageContent,
  ChatMessage,
  TerminalApprovalRequest,
  TerminalSessionRequest,
  TerminalOutput,
  TerminalCommandComplete,
} from '../types';
import {
  applySavedTurnToHistory,
  mapConversationMessagePayload,
  type LocalTurnPatch,
} from '../utils/chatMessages';

// Assets
import '../CSS/App.css';
import micSignSvg from '../assets/mic-icon.svg';
import fullscreenSSIcon from '../assets/entire-screen-shot-icon.svg';
import regionSSIcon from '../assets/region-screen-shot-icon.svg';
import meetingRecordingIcon from '../assets/meeting-record-icon.svg';
import contextWindowInsightsIcon from '../assets/context-window-icon.svg';
import scrollDownIcon from '../assets/scroll-down-icon.svg';

// API
import { api } from '../services/api';

type PendingTurnAction = {
  type: 'retry' | 'edit';
  messageId: string;
  editedContent?: string;
};

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

  // Terminal state (minimal — most state is now in chatState.contentBlocks)
  const [terminalSessionActive, setTerminalSessionActive] = useState(false);
  const [terminalSessionRequest, setTerminalSessionRequest] = useState<TerminalSessionRequest | null>(null);

  // ============================================
  // Refs
  // ============================================
  const inputRef = useRef<HTMLInputElement | null>(null);
  const responseAreaRef = useRef<HTMLDivElement | null>(null);
  const pendingConversationRef = useRef<string | null>(null);
  const pendingNewChatRef = useRef<boolean>(false);
  const generatingModelRef = useRef<string>('');
  const pendingTurnActionsRef = useRef<Map<string, PendingTurnAction>>(new Map());
  // Stash run_command args so we can create terminal blocks when output arrives (auto-approved)
  const pendingTerminalCommandRef = useRef<{ command: string; cwd: string } | null>(null);

  // ============================================
  // Tab Management
  // ============================================
  const {
    activeTabId, createTab, updateTabTitle,
    queueMap, setQueueItems, registerBeforeSwitch, registerAfterSwitch, registerOnTabClosed,
  } = useTabs();
  const activeTabIdRef = useRef(activeTabId);
  const tabRegistryRef = useRef<Map<string, TabSnapshot>>(new Map());

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
    tabRegistryRef.current.set(tabId, {
      chat: chatState.getSnapshot(),
      screenshots: screenshotState.getSnapshot(),
      tokens: tokenState.getSnapshot(),
      terminal: {
        terminalSessionActive,
        terminalSessionRequest,
      },
      generatingModel: generatingModelRef.current,
    });
  }, [chatState, screenshotState, tokenState, terminalSessionActive, terminalSessionRequest]);

  /** Restore React state from the registry for the given tab. */
  const restoreTabState = useCallback((tabId: string) => {
    const snap = tabRegistryRef.current.get(tabId) ?? freshSnapshot();
    chatState.restoreSnapshot(snap.chat);
    screenshotState.restoreSnapshot(snap.screenshots);
    tokenState.restoreSnapshot(snap.tokens);
    setTerminalSessionActive(snap.terminal.terminalSessionActive);
    setTerminalSessionRequest(snap.terminal.terminalSessionRequest);
    generatingModelRef.current = snap.generatingModel;
  }, [chatState, screenshotState, tokenState, freshSnapshot]);

  // Register tab switch callbacks with TabContext
  useEffect(() => {
    registerBeforeSwitch((oldTabId: string) => {
      saveTabState(oldTabId);
    });
    registerAfterSwitch((newTabId: string) => {
      activeTabIdRef.current = newTabId;
      restoreTabState(newTabId);
      setShowScrollBottom(false);
      // Notify the backend so hotkey-captured screenshots route to the correct tab
      wsSend({ type: 'tab_activated', tab_id: newTabId });
    });
    registerOnTabClosed((closedTabId: string) => {
      tabRegistryRef.current.delete(closedTabId);
      pendingTurnActionsRef.current.delete(closedTabId);
    });
  }, [registerBeforeSwitch, registerAfterSwitch, registerOnTabClosed, saveTabState, restoreTabState, wsSend]);

  // Keep activeTabIdRef in sync when activeTabId changes (e.g. from external triggers)
  useEffect(() => {
    activeTabIdRef.current = activeTabId;
  }, [activeTabId]);

  // ============================================
  // Background tab message handler
  // ============================================
  /**
   * Apply a WS message to a background tab's snapshot in the registry.
   * Only the subset of message types that affect persistent state are handled;
   * UI-only messages (screenshot_start, terminal_running_notice, etc.) are ignored.
   */
  const applyToBackgroundTab = useCallback((tabId: string, data: WebSocketMessage) => {
    const snap = tabRegistryRef.current.get(tabId) ?? freshSnapshot();
    const chat = { ...snap.chat };
    const pendingTurnAction = pendingTurnActionsRef.current.get(tabId);

    switch (data.type) {
      case 'query':
        chat.currentQuery = String(data.content);
        chat.error = '';
        chat.status = 'Thinking...';
        chat.isThinking = true;
        chat.canSubmit = false;
        chat.toolCalls = [];
        chat.contentBlocks = [];
        break;

      case 'thinking_chunk':
        chat.thinking += String(data.content);
        break;

      case 'thinking_complete':
        chat.isThinking = false;
        chat.status = 'Receiving response...';
        break;

      case 'response_chunk': {
        const chunk = String(data.content);
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

      case 'response_complete': {
        if (pendingTurnAction) {
          chat.isThinking = false;
          chat.status = 'Saving updated turn...';
          break;
        }

        if (chat.response || chat.thinking || chat.toolCalls.length > 0) {
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
        const sd = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as ConversationSavedContent;
        chat.conversationId = sd.conversation_id;
        if (pendingTurnAction && !sd.turn) {
          chat.response = '';
          chat.thinking = '';
          chat.currentQuery = '';
          chat.isThinking = false;
          chat.toolCalls = [];
          chat.contentBlocks = [];
          chat.canSubmit = true;
          chat.status = 'Ready for follow-up question.';
          pendingTurnActionsRef.current.delete(tabId);
          break;
        }
        if (sd.turn) {
          chat.chatHistory = applySavedTurnToHistory(
            chat.chatHistory,
            sd.turn,
            sd.operation ?? pendingTurnAction?.type ?? 'submit',
            buildPendingTurnLocalPatch(
              chat.chatHistory,
              sd.turn,
              pendingTurnAction,
              pendingTurnAction
                ? {
                    role: 'assistant',
                    content: chat.response,
                    thinking: chat.thinking || undefined,
                    toolCalls: chat.toolCalls.length > 0 ? [...chat.toolCalls] : undefined,
                    contentBlocks: chat.contentBlocks.length > 0 ? [...chat.contentBlocks] : undefined,
                    model: snap.generatingModel || undefined,
                    timestamp: Date.now(),
                  }
                : undefined,
            ),
          );
        }
        if (pendingTurnAction) {
          chat.response = '';
          chat.thinking = '';
          chat.currentQuery = '';
          chat.isThinking = false;
          chat.toolCalls = [];
          chat.contentBlocks = [];
          chat.canSubmit = true;
          chat.status = 'Ready for follow-up question.';
          pendingTurnActionsRef.current.delete(tabId);
        }
        break;
      }

      case 'conversation_resumed': {
        const resumeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as ConversationResumedContent;
        chat.chatHistory = resumeData.messages.map(mapConversationMessagePayload);
        chat.conversationId = resumeData.conversation_id;
        chat.response = '';
        chat.thinking = '';
        chat.currentQuery = '';
        chat.isThinking = false;
        chat.toolCalls = [];
        chat.contentBlocks = [];
        chat.canSubmit = true;
        chat.status = 'Conversation loaded. Ask a follow-up question.';
        pendingTurnActionsRef.current.delete(tabId);
        break;
      }

      case 'error':
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
        const tc = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as unknown as ToolCallContent;
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
        if (tc.status === 'calling') {
          chat.toolCalls = [...chat.toolCalls, { name: tc.name, args: tc.args, server: tc.server, status: 'calling' }];
          chat.contentBlocks = [...chat.contentBlocks, { type: 'tool_call', toolCall: { name: tc.name, args: tc.args, server: tc.server, status: 'calling' } }];
        } else if (tc.status === 'complete' && tc.result) {
          chat.toolCalls = chat.toolCalls.map(t =>
            t.name === tc.name && JSON.stringify(t.args) === JSON.stringify(tc.args)
              ? { ...t, ...tc } : t
          );
          chat.contentBlocks = chat.contentBlocks.map(b =>
            b.type === 'tool_call' && b.toolCall.name === tc.name && JSON.stringify(b.toolCall.args) === JSON.stringify(tc.args)
              ? { ...b, toolCall: { ...b.toolCall, ...tc } } : b
          );
        }
        break;
      }

      case 'terminal_output': {
        const to = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as unknown as TerminalOutput;
        chat.contentBlocks = chat.contentBlocks.map(b => {
          if (b.type === 'terminal_command' && b.terminal.requestId === to.request_id) {
            return { ...b, terminal: { ...b.terminal, output: b.terminal.output + to.text + (to.raw ? '' : '\n'), outputChunks: [...b.terminal.outputChunks, { text: to.text, raw: !!to.raw }], isPty: b.terminal.isPty || !!to.raw } };
          }
          // Also match by empty requestId (created from tool_call before real id arrived)
          if (b.type === 'terminal_command' && !b.terminal.requestId) {
            return { ...b, terminal: { ...b.terminal, requestId: to.request_id, output: b.terminal.output + to.text + (to.raw ? '' : '\n'), outputChunks: [...b.terminal.outputChunks, { text: to.text, raw: !!to.raw }], isPty: b.terminal.isPty || !!to.raw } };
          }
          return b;
        });
        break;
      }

      case 'terminal_command_complete': {
        const tc2 = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as unknown as TerminalCommandComplete;
        chat.contentBlocks = chat.contentBlocks.map(b =>
          b.type === 'terminal_command' && b.terminal.requestId === tc2.request_id
            ? { ...b, terminal: { ...b.terminal, status: 'completed', exitCode: tc2.exit_code, durationMs: tc2.duration_ms } }
            : b
        );
        break;
      }

      case 'terminal_approval_request': {
        const ar = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as unknown as TerminalApprovalRequest;
        chat.contentBlocks = [...chat.contentBlocks, {
          type: 'terminal_command',
          terminal: { requestId: ar.request_id, command: ar.command, cwd: ar.cwd, status: 'pending_approval', output: '', outputChunks: [], isPty: false },
        }];
        break;
      }

      case 'token_usage': {
        const stats = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TokenUsageContent;
        const input = stats.prompt_eval_count || 0;
        const output = stats.eval_count || 0;
        const tu = { ...snap.tokens.tokenUsage };
        tu.total = (tu.total || 0) + input + output;
        tu.input = (tu.input || 0) + input;
        tu.output = (tu.output || 0) + output;
        tabRegistryRef.current.set(tabId, { ...snap, chat, tokens: { tokenUsage: tu } });
        return;
      }

      case 'queue_updated': {
        const qData = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as { tab_id: string; items: { item_id: string; preview: string; position: number }[] };
        setQueueItems(qData.tab_id, qData.items);
        return; // Don't update chat snapshot
      }

      // ── Screenshot messages for background tabs ──────────────
      case 'screenshot_added': {
        const ssData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ScreenshotAddedContent;
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = [...screenshots.screenshots, ssData as unknown as Screenshot];
        tabRegistryRef.current.set(tabId, { ...snap, chat, screenshots });
        return;
      }

      case 'screenshot_removed': {
        const removeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ScreenshotRemovedContent;
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = screenshots.screenshots.filter(ss => ss.id !== removeData.id);
        tabRegistryRef.current.set(tabId, { ...snap, chat, screenshots });
        return;
      }

      case 'screenshots_cleared': {
        const screenshots = { ...snap.screenshots };
        screenshots.screenshots = [];
        tabRegistryRef.current.set(tabId, { ...snap, chat, screenshots });
        return;
      }

      default:
        return; // Ignore other types for background tabs
    }

    tabRegistryRef.current.set(tabId, { ...snap, chat });
  }, [freshSnapshot, setQueueItems]);

  // ============================================
  // Fetch enabled models on mount & when returning from Settings
  // ============================================
  useEffect(() => {
    const fetchEnabledModels = async () => {
      const models = await api.getEnabledModels();
      setEnabledModels(models);
      // Auto-select first model if current selection is empty or no longer enabled
      if (models.length > 0 && (!selectedModel || !models.includes(selectedModel))) {
        setSelectedModel(models[0]);
      }
    };
    fetchEnabledModels();
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

      case 'transcription_result':
        chatState.setQuery((prev) => prev + (prev ? ' ' : '') + String(data.content));
        setIsRecording(false);
        chatState.setStatus('Transcription complete.');
        return true;

      case 'queue_updated': {
        const qData = (typeof data.content === 'string' ? JSON.parse(data.content) : data.content) as { tab_id: string; items: { item_id: string; preview: string; position: number }[] };
        setQueueItems(qData.tab_id, qData.items);
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
  }, [chatState, setIsHidden, wsSend, setQueueItems]);

  /** Handle tab-scoped messages for the active tab. */
  const handleActiveTabMessage = useCallback((data: WebSocketMessage) => {
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
        const ssData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ScreenshotAddedContent;
        screenshotState.addScreenshot(ssData);
        chatState.setStatus('Screenshot added to context.');
        setIsHidden(false);
        break;
      }

      case 'screenshot_removed': {
        const removeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ScreenshotRemovedContent;
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
        if (chatState.currentQueryRef.current !== echoText) {
          chatState.startQuery(echoText);
        }
        break;
      }

      case 'tool_call': {
        const tc = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ToolCallContent;

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

        if (tc.status === 'calling') {
          chatState.setStatus(`Calling tool: ${tc.name}...`);
          chatState.addToolCall({
            name: tc.name,
            args: tc.args,
            server: tc.server,
            status: 'calling'
          });
        } else if (tc.status === 'complete' && tc.result) {
          chatState.updateToolCall({
            name: tc.name,
            args: tc.args,
            result: tc.result,
            server: tc.server,
            status: 'complete'
          });
          chatState.setStatus('Tool call complete.');
        }
        break;
      }

      case 'tool_calls_summary': {
        const calls = typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content;
        if (Array.isArray(calls) && calls.length > 0) {
          chatState.toolCallsRef.current = calls;
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

      case 'response_chunk':
        chatState.appendResponse(String(data.content));
        break;

      case 'response_complete':
        if (activePendingTurnAction) {
          chatState.setIsThinking(false);
          chatState.setStatus('Saving updated turn...');
        } else {
          chatState.completeResponse(screenshotState.getImageData(), generatingModelRef.current);
        }
        break;

      case 'token_usage': {
        const stats = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TokenUsageContent;
        const input = stats.prompt_eval_count || 0;
        const output = stats.eval_count || 0;
        tokenState.addTokens(input, output);
        break;
      }

      case 'conversation_saved': {
        const saveData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ConversationSavedContent;
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
        const resumeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ConversationResumedContent;

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
        const approvalData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalApprovalRequest;
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

      case 'terminal_session_request': {
        const sessionData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalSessionRequest;
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
        const outputData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalOutput;
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
        const completeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalCommandComplete;
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
  }, [buildStreamingAssistantMessage, chatState, conversationTitle, screenshotState, tokenState, setIsHidden, updateTabTitle, wsSend]);

  /** Top-level WS message router: global → active tab → background tab. */
  const handleWebSocketMessage = useCallback((data: WebSocketMessage) => {
    // Global messages are handled first regardless of tab_id
    if (handleGlobalMessage(data)) return;

    // Determine which tab this message is for
    const messageTabId = (data as Record<string, unknown>).tab_id as string | undefined ?? 'default';

    if (messageTabId === activeTabIdRef.current) {
      handleActiveTabMessage(data);
    } else {
      applyToBackgroundTab(messageTabId, data);
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
        wsSend({ type: 'set_capture_mode', mode: screenshotState.captureMode });
        return;
      }
      if (data.type === '__ws_disconnected') {
        chatState.setStatus('Disconnected. Retrying...');
        return;
      }
      // Route all real messages through the existing handler
      handleWebSocketMessageRef.current(data as WebSocketMessage);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsSubscribe]);

  // ============================================
  // Navigation Handler
  // ============================================
  useEffect(() => {
    const state = location.state as { conversationId?: string; newChat?: boolean } | null;

    if (state?.conversationId) {
      setShowScrollBottom(false);
      if (isConnected) {
        wsSend({
          type: 'resume_conversation',
          conversation_id: state.conversationId,
        });
        window.history.replaceState({}, '');
      } else {
        pendingConversationRef.current = state.conversationId;
      }
    } else if (state?.newChat) {
      setShowScrollBottom(false);
      if (isConnected) {
        wsSend({ type: 'clear_context' });
        window.history.replaceState({}, '');
      } else {
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
      behavior: 'smooth',
    });
  }, []);

  const handleScroll = () => {
    if (responseAreaRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = responseAreaRef.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
      setShowScrollBottom(!isNearBottom);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!isConnected) return;

    const queryText = chatState.query.trim();
    if (!queryText) return;

    chatState.setQuery('');

    // Optimistic update: show the query immediately instead of waiting
    // for the server echo.  Only for non-queued queries (canSubmit===true)
    // to avoid overwriting in-flight state for queued messages.
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

  const handleSetActiveResponse = useCallback((message: ChatMessage, responseIndex: number) => {
    if (!message.messageId || !message.responseVersions) {
      return;
    }

    const nextVariant = message.responseVersions[responseIndex];
    if (!nextVariant) {
      return;
    }

    chatState.setChatHistory((prev) =>
      prev.map((entry) =>
        entry.messageId === message.messageId
          ? {
            ...entry,
            content: nextVariant.content,
            model: nextVariant.model ?? entry.model,
            timestamp: nextVariant.timestamp ?? entry.timestamp,
            contentBlocks: nextVariant.contentBlocks ?? entry.contentBlocks,
            activeResponseIndex: responseIndex,
          }
          : entry,
      ),
    );

    wsSend({
      type: 'set_active_response',
      message_id: message.messageId,
      response_index: responseIndex,
    });
  }, [chatState, wsSend]);

  const handleStopStreaming = () => {
    wsSend({ type: 'stop_streaming' });
  };

  /** Create a new tab and notify the backend. */
  const handleNewTab = useCallback(() => {
    const id = createTab();
    if (id) {
      wsSend({ type: 'tab_created', tab_id: id });
    }
  }, [createTab, wsSend]);

  const handleRemoveScreenshot = (id: string) => {
    wsSend({ type: 'remove_screenshot', id });
  };

  const sendCaptureMode = (mode: 'fullscreen' | 'precision' | 'none') => {
    wsSend({ type: 'set_capture_mode', mode });
  };

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
    screenshotState.setCaptureMode('none');
    screenshotState.setMeetingRecordingMode(true);
    sendCaptureMode('none');
    navigate('/recorder');
  };

  const getPlaceholder = () => {
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
        : "Ask Xpdite about a region on your screen (Alt+.)";
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
  return (
    <div className="content-container" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <TitleBar onClearContext={handleNewTab} setMini={setMini} />
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
        onToggleThinking={() => chatState.setThinkingCollapsed(!chatState.thinkingCollapsed)}
        onScroll={handleScroll}
        onScrollToBottom={scrollToBottom}
        responseAreaRef={responseAreaRef}
        scrollDownIcon={scrollDownIcon}
        onTerminalApprove={handleTerminalApprove}
        onTerminalDeny={handleTerminalDeny}
        onTerminalApproveRemember={handleTerminalApproveRemember}
        onTerminalKill={handleKillCommand}
        onTerminalResize={handleTerminalResize}
      />

      <div className="main-interaction-section">
        {/* Session mode indicators */}
        {terminalSessionRequest && (
          <div className="terminal-session-chip">
            <span>⚡ Session mode requested</span>
            <button onClick={() => handleTerminalSessionResponse(true)}>Allow</button>
            <button onClick={() => handleTerminalSessionResponse(false)}>Deny</button>
          </div>
        )}
        {terminalSessionActive && (
          <div className="terminal-session-chip">
            <span>⚡ Session Mode Active</span>
            <button onClick={handleStopSession}>Stop</button>
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
            onQueryChange={chatState.setQuery}
            onSubmit={handleSubmit}
            onStopStreaming={handleStopStreaming}
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
                <select
                  name="model-selector"
                  className="model-select"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                >
                  {enabledModels.length === 0 && (
                    <option value="" disabled>No models enabled</option>
                  )}
                  {enabledModels.map((model) => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
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
          meetingRecordingIcon={meetingRecordingIcon}
        />
      </div>
    </div>
  );
}

export default App;
