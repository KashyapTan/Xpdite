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
import { useOutletContext, useLocation } from 'react-router-dom';

// Hooks
import { useChatState } from '../hooks/useChatState';
import { useScreenshots } from '../hooks/useScreenshots';
import { useTokenUsage } from '../hooks/useTokenUsage';

// Components
import TitleBar from '../components/TitleBar';
import { ResponseArea } from '../components/chat/ResponseArea';
import { QueryInput } from '../components/input/QueryInput';
import { ModeSelector } from '../components/input/ModeSelector';
import { TokenUsagePopup } from '../components/input/TokenUsagePopup';
import { ScreenshotChips } from '../components/input/ScreenshotChips';

// Types
import type {
  WebSocketMessage,
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
  // Context from Layout
  // ============================================
  const { setMini, setIsHidden } = useOutletContext<{
    setMini: (val: boolean) => void;
    setIsHidden: (val: boolean) => void;
    isHidden: boolean;
  }>();

  const location = useLocation();

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
  // WebSocket Message Handler
  // ============================================
  const handleWebSocketMessage = useCallback((data: WebSocketMessage) => {
    switch (data.type) {
      case 'ready':
        chatState.setStatus(String(data.content) || 'Ready to chat.');
        chatState.setCanSubmit(true);
        chatState.setError('');

        // Handle pending operations
        if (pendingConversationRef.current) {
          wsRef.current?.send(JSON.stringify({
            type: 'resume_conversation',
            conversation_id: pendingConversationRef.current,
          }));
          pendingConversationRef.current = null;
          window.history.replaceState({}, '');
        } else if (pendingNewChatRef.current) {
          wsRef.current?.send(JSON.stringify({ type: 'clear_context' }));
          pendingNewChatRef.current = false;
          window.history.replaceState({}, '');
        }
        break;

      case 'screenshot_start':
        setIsHidden(true);
        break;

      case 'screenshot_ready':
        chatState.setStatus('Screenshot captured!');
        chatState.setError('');
        setIsHidden(false);
        break;

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

      case 'context_cleared':
        chatState.resetForNewChat();
        screenshotState.clearScreenshots();
        tokenState.resetTokens();
        setTerminalSessionRequest(null);
        setTerminalSessionActive(false);
        break;

      case 'query':
        chatState.startQuery(String(data.content));
        break;

      case 'tool_call': {
        const tc = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as ToolCallContent;

        // Terminal run_command: use inline terminal blocks instead of generic tool cards
        if (tc.server === 'terminal' && tc.name === 'run_command') {
          if (tc.status === 'calling') {
            chatState.setStatus(`Running command: ${tc.args.command}...`);
            // Stash command info — the actual terminal block is created when the real
            // request_id arrives (via terminal_approval_request or terminal_output)
            pendingTerminalCommandRef.current = {
              command: String(tc.args.command || ''),
              cwd: String(tc.args.cwd || ''),
            };
          }
          // For 'complete' status, the terminal_command_complete message handles it
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

      case 'transcription_result':
        chatState.setQuery((prev) => prev + (prev ? ' ' : '') + String(data.content));
        setIsRecording(false);
        chatState.setStatus('Transcription complete.');
        break;

      // ── Terminal messages ──────────────────────────────
      case 'terminal_approval_request': {
        const approvalData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalApprovalRequest;
        // Create an inline terminal block in pending_approval state
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
        // Find existing terminal block by request_id
        const hasBlock = chatState.contentBlocksRef.current.some(
          b => b.type === 'terminal_command' && b.terminal.requestId === outputData.request_id
        );
        if (!hasBlock) {
          // Auto-approved command: create terminal block now using stashed info
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
          // Update status to running if still pending (approval flow)
          chatState.updateTerminalBlock(outputData.request_id, { status: 'running' });
        }
        chatState.appendTerminalOutput(outputData.request_id, outputData.text, !!outputData.raw);
        break;
      }

      case 'terminal_command_complete': {
        const completeData = (typeof data.content === 'string'
          ? JSON.parse(data.content)
          : data.content) as unknown as TerminalCommandComplete;
        // Update the inline terminal block to completed state
        chatState.updateTerminalBlock(completeData.request_id, {
          status: 'completed',
          exitCode: completeData.exit_code,
          durationMs: completeData.duration_ms,
        });
        break;
      }

      case 'terminal_running_notice': {
        // Running notice is now implicit in the inline terminal block's 'running' status
        // No separate state needed — the block already shows a spinner
        break;
      }
    }
  }, [chatState, screenshotState, tokenState, setIsHidden]);

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
        ws?.send(JSON.stringify({ type: 'set_capture_mode', mode: screenshotState.captureMode }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
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
        wsRef.current.send(JSON.stringify({
          type: 'resume_conversation',
          conversation_id: state.conversationId,
        }));
        window.history.replaceState({}, '');
      } else {
        pendingConversationRef.current = state.conversationId;
      }
    } else if (state?.newChat) {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'clear_context' }));
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
    if (!chatState.query.trim()) return;

    chatState.setQuery('');
    setTimeout(scrollToBottom, 50);

    generatingModelRef.current = selectedModel;

    wsRef.current.send(JSON.stringify({
      type: 'submit_query',
      content: chatState.query.trim(),
      capture_mode: screenshotState.captureMode,
      model: selectedModel,
    }));
  };

  const handleStopStreaming = () => {
    wsRef.current?.send(JSON.stringify({ type: 'stop_streaming' }));
  };

  const handleClearContext = () => {
    wsRef.current?.send(JSON.stringify({ type: 'clear_context' }));
  };

  const handleRemoveScreenshot = (id: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'remove_screenshot', id }));
  };

  const sendCaptureMode = (mode: 'fullscreen' | 'precision' | 'none') => {
    wsRef.current?.send(JSON.stringify({ type: 'set_capture_mode', mode }));
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
      // Stop recording
      wsRef.current.send(JSON.stringify({ type: 'stop_recording' }));
      chatState.setStatus('Transcribing...');
    } else {
      // Start recording
      wsRef.current.send(JSON.stringify({ type: 'start_recording' }));
      setIsRecording(true);
      chatState.setStatus('Listening...');
    }
  };

  // ── Terminal Action Handlers ────────────────────────────────
  const handleTerminalApprovalResponse = useCallback((requestId: string, approved: boolean, remember: boolean) => {
    wsRef.current?.send(JSON.stringify({
      type: 'terminal_approval_response',
      request_id: requestId,
      approved,
      remember,
    }));

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
    wsRef.current?.send(JSON.stringify({
      type: 'terminal_session_response',
      approved,
    }));
    setTerminalSessionRequest(null);
  };

  const handleStopSession = () => {
    wsRef.current?.send(JSON.stringify({
      type: 'terminal_stop_session',
    }));
    setTerminalSessionActive(false);
  };

  const handleKillCommand = useCallback((_requestId: string) => {
    wsRef.current?.send(JSON.stringify({
      type: 'terminal_kill_command',
    }));
  }, []);

  const handleTerminalResize = useCallback((cols: number, rows: number) => {
    wsRef.current?.send(JSON.stringify({
      type: 'terminal_resize',
      cols,
      rows,
    }));
  }, []);

  // ============================================
  // Render
  // ============================================
  return (
    <div className="content-container" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <TitleBar onClearContext={handleClearContext} setMini={setMini} />

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
