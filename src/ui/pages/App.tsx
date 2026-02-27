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
  ToolCallContent,
  TokenUsageContent,
  ChatMessage,
  TerminalApprovalRequest,
  TerminalSessionRequest,
  TerminalOutput,
  TerminalCommandComplete,
} from '../types';

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
  const wsRef = useRef<WebSocket | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const responseAreaRef = useRef<HTMLDivElement | null>(null);
  const pendingConversationRef = useRef<string | null>(null);
  const pendingNewChatRef = useRef<boolean>(false);
  const generatingModelRef = useRef<string>('');
  // Stash run_command args so we can create terminal blocks when output arrives (auto-approved)
  const pendingTerminalCommandRef = useRef<{ command: string; cwd: string } | null>(null);

  // ============================================
  // Tab Management
  // ============================================
  const {
    activeTabId, createTab, switchTab, updateTabTitle,
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
  // Tab-scoped WS send helper
  // ============================================
  const wsSend = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ tab_id: activeTabIdRef.current, ...msg }));
    }
  }, []);

  // Expose wsSend globally so non-App pages (MeetingAlbum, etc.) can send messages
  useEffect(() => {
    (window as any).__xpditeWsSend = wsSend;
    return () => { delete (window as any).__xpditeWsSend; };
  }, [wsSend]);

  // ============================================
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
      // Notify the backend so hotkey-captured screenshots route to the correct tab
      wsSend({ type: 'tab_activated', tab_id: newTabId });
    });
    registerOnTabClosed((closedTabId: string) => {
      tabRegistryRef.current.delete(closedTabId);
    });
  }, [registerBeforeSwitch, registerAfterSwitch, registerOnTabClosed, saveTabState, restoreTabState]);

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
        if (chat.response || chat.thinking || chat.toolCalls.length > 0) {
          chat.chatHistory = [
            ...chat.chatHistory,
            { role: 'user', content: chat.currentQuery },
            {
              role: 'assistant',
              content: chat.response,
              thinking: chat.thinking || undefined,
              toolCalls: chat.toolCalls.length > 0 ? [...chat.toolCalls] : undefined,
              contentBlocks: chat.contentBlocks.length > 0 ? [...chat.contentBlocks] : undefined,
              model: snap.generatingModel || undefined,
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
        break;
      }

      case 'error':
        chat.error = String(data.content);
        chat.status = 'An error occurred.';
        chat.canSubmit = true;
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

      // ── Meeting Recording messages (global, not tab-scoped) ──
      case 'meeting_recording_started':
      case 'meeting_recording_stopped':
      case 'meeting_transcript_chunk':
      case 'meeting_recording_error':
      case 'meeting_recording_status': {
        // Route to MeetingRecorderContext handlers
        const handlers = (window as any).__meetingRecorderHandlers;
        if (handlers) {
          const content = typeof data.content === 'string' ? JSON.parse(data.content) : data.content;
          if (data.type === 'meeting_recording_started') handlers.handleRecordingStarted(content);
          else if (data.type === 'meeting_recording_stopped') handlers.handleRecordingStopped(content);
          else if (data.type === 'meeting_transcript_chunk') handlers.handleTranscriptChunk(content);
        }
        return true;
      }

      case 'meeting_recordings_list':
      case 'meeting_recording_loaded':
      case 'meeting_recording_deleted':
      case 'meeting_processing_progress':
      case 'meeting_analysis_started':
      case 'meeting_analysis_complete':
      case 'meeting_analysis_error':
      case 'meeting_action_result': {
        // Route to MeetingAlbum and MeetingRecordingDetail page handlers
        const albumHandler = (window as any).__meetingAlbumHandler;
        if (albumHandler) albumHandler(data);
        const detailHandler = (window as any).__meetingDetailHandler;
        if (detailHandler) detailHandler(data);
        return true;
      }

      case 'meeting_compute_info':
      case 'meeting_settings': {
        // Route to MeetingRecorderSettings handler
        const settingsHandler = (window as any).__meetingSettingsHandler;
        if (settingsHandler) settingsHandler(data);
        return true;
      }

      default:
        return false; // Not a global message
    }
  }, [chatState, setIsHidden, wsSend, setQueueItems]);

  /** Handle tab-scoped messages for the active tab. */
  const handleActiveTabMessage = useCallback((data: WebSocketMessage) => {
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
        chatState.completeResponse(screenshotState.getImageData(), generatingModelRef.current);
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
        // Use first user message as tab title
        if (chatState.chatHistory.length === 0 && chatState.currentQueryRef.current) {
          const title = chatState.currentQueryRef.current.slice(0, 30) || 'Chat';
          updateTabTitle(activeTabIdRef.current, title);
        }
        break;
      }

      case 'conversation_resumed': {
        const resumeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ConversationResumedContent;

        const msgs: ChatMessage[] = resumeData.messages.map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          images: m.images && m.images.length > 0 ? m.images : undefined,
          model: m.model,
          contentBlocks: m.content_blocks
            ? m.content_blocks.map((b) =>
              b.type === 'tool_call'
                ? { type: 'tool_call' as const, toolCall: { name: b.name!, args: b.args ?? {}, server: b.server ?? '', status: 'complete' as const } }
                : { type: 'text' as const, content: b.content ?? '' }
            )
            : undefined,
        }));

        chatState.loadConversation(resumeData.conversation_id, msgs);
        screenshotState.clearScreenshots();

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
  }, [chatState, screenshotState, tokenState, setIsHidden, updateTabTitle]);

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

  // Keep WS handler in a ref so the WS effect always calls the latest version
  // without needing to reconnect when callbacks change.
  const handleWebSocketMessageRef = useRef(handleWebSocketMessage);
  handleWebSocketMessageRef.current = handleWebSocketMessage;

  // ============================================
  // WebSocket Connection
  // ============================================
  useEffect(() => {
    let ws: WebSocket | null = null;

    const connect = () => {
      ws = new WebSocket('ws://localhost:8000/ws');
      wsRef.current = ws;

      ws.onopen = () => {
        chatState.setStatus('Connected to server');
        chatState.setError('');
        wsSend({ type: 'set_capture_mode', mode: screenshotState.captureMode });
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessageRef.current(data);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      ws.onclose = () => {
        chatState.setStatus('Disconnected. Retrying...');
        setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
      };
    };

    connect();

    return () => {
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, []);

  // ============================================
  // Navigation Handler
  // ============================================
  useEffect(() => {
    const state = location.state as { conversationId?: string; newChat?: boolean } | null;

    if (state?.conversationId) {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsSend({
          type: 'resume_conversation',
          conversation_id: state.conversationId,
        });
        window.history.replaceState({}, '');
      } else {
        pendingConversationRef.current = state.conversationId;
      }
    } else if (state?.newChat) {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsSend({ type: 'clear_context' });
        window.history.replaceState({}, '');
      } else {
        pendingNewChatRef.current = true;
      }
    }
  }, [location.state]);

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
  const scrollToBottom = () => {
    responseAreaRef.current?.scrollTo({
      top: responseAreaRef.current.scrollHeight,
      behavior: 'smooth',
    });
  };

  const handleScroll = () => {
    if (responseAreaRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = responseAreaRef.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
      setShowScrollBottom(!isNearBottom);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

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

  const handleStopStreaming = () => {
    wsSend({ type: 'stop_streaming' });
  };

  const handleClearContext = () => {
    wsSend({ type: 'clear_context' });
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
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

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
  }, [chatState]);

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

  const handleKillCommand = useCallback((_requestId: string) => {
    wsSend({
      type: 'terminal_kill_command',
    });
  }, []);

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
        response={chatState.response}
        thinking={chatState.thinking}
        isThinking={chatState.isThinking}
        thinkingCollapsed={chatState.thinkingCollapsed}
        contentBlocks={chatState.contentBlocks}
        generatingModel={generatingModelRef.current || selectedModel}
        canSubmit={chatState.canSubmit}
        error={chatState.error}
        showScrollBottom={showScrollBottom}
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
