import { useState, useEffect, useRef } from 'react';
import type { FormEvent } from 'react';
import { useOutletContext, useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import '../CSS/App.css';
import TitleBar from '../components/TitleBar';
// import plusSignSvg from '../assets/plus-icon.svg';
import micSignSvg from '../assets/mic-icon.svg';
import fullscreenSSIcon from '../assets/entire-screen-shot-icon.svg';
import regionSSIcon from '../assets/region-screen-shot-icon.svg';
import meetingRecordingIcon from '../assets/meeting-record-icon.svg';
import contextWindowInsightsIcon from '../assets/context-window-icon.svg';
import scrollDownIcon from '../assets/scroll-down-icon.svg';
import { CameraIcon, ChevronRightIcon, XIcon } from '../components/icons/AppIcons';
// Extend the Window interface to include electronAPI
declare global {
  interface Window {
    electronAPI?: {
      focusWindow: () => Promise<void>;
      setMiniMode: (mini: boolean) => Promise<void>;
    };
  }
}

function App() {
  const [query, setQuery] = useState<string>('');
  const [response, setResponse] = useState<string>('');
  const [thinking, setThinking] = useState<string>('');
  const [isThinking, setIsThinking] = useState<boolean>(false);
  const [thinkingCollapsed, setThinkingCollapsed] = useState<boolean>(true);
  const [, setStatus] = useState<string>('Connecting to server...');
  const [error, setError] = useState<string>('');
  const [canSubmit, setCanSubmit] = useState<boolean>(false);
  const { setMini, setIsHidden } = useOutletContext<{ 
    setMini: (val: boolean) => void, 
    setIsHidden: (val: boolean) => void,
    isHidden: boolean
  }>();
  const [selectedModel, setSelectedModel] = useState<string>('QWEN 3 VL:8B');
  // Multiple screenshots support
  const [screenshots, setScreenshots] = useState<Array<{id: string, name: string, thumbnail: string}>>([]);
  // Capture mode: 'fullscreen' | 'precision' | 'none'
  const [captureMode, setCaptureMode] = useState<'fullscreen' | 'precision' | 'none'>('precision');
  const [meetingRecordingMode, setMeetingRecordingMode] = useState<boolean>(false);
  // Chat history for multi-turn conversations
  const [chatHistory, setChatHistory] = useState<Array<{role: 'user' | 'assistant', content: string, thinking?: string, images?: Array<{name: string, thumbnail: string}>, toolCalls?: Array<{name: string, args: Record<string, unknown>, result: string, server: string}>}>>([]);
  const [currentQuery, setCurrentQuery] = useState<string>('');
  const [, setConversationId] = useState<string | null>(null);
  
  const location = useLocation();
  
  // Token usage states
  const [tokenUsage, setTokenUsage] = useState({
    total: 0,
    input: 0,
    output: 0,
    limit: 128000
  });
  const [showTokenPopup, setShowTokenPopup] = useState(false);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const responseAreaRef = useRef<HTMLDivElement | null>(null);
  // Refs to track current values for WebSocket handler
  const currentQueryRef = useRef<string>('');
  const responseRef = useRef<string>('');
  const thinkingRef = useRef<string>('');
  // Ref to capture current screenshots at response_complete time
  const screenshotsRef = useRef<Array<{id: string, name: string, thumbnail: string}>>([]);
  // Ref to capture tool calls during the current response
  const toolCallsRef = useRef<Array<{name: string, args: Record<string, unknown>, result: string, server: string}>>([]);
  // Ref to hold a pending conversation ID to resume once WS is ready
  const pendingConversationRef = useRef<string | null>(null);
  // Ref to flag that a new chat was requested before WS was ready
  const pendingNewChatRef = useRef<boolean>(false);

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      console.error('Failed to copy text: ', err);
      // Fallback for older browsers
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
      } catch (fallbackErr) {
        console.error('Fallback copy failed: ', fallbackErr);
      }
      document.body.removeChild(textArea);
    }
  };

  useEffect(() => {
  let ws: WebSocket | null = null;

    const connect = () => {
  ws = new WebSocket('ws://localhost:8000/ws');
  wsRef.current = ws;

      ws.onopen = () => {
        setStatus('Connected to server');
        setError('');
        // Send initial capture mode to backend
        ws?.send(JSON.stringify({ type: 'set_capture_mode', mode: captureMode }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            case 'ready':
              // Server is ready - enable input immediately (no screenshot required)
              setStatus(data.content || 'Ready to chat. Take a screenshot (Alt+.) or just type.');
              setCanSubmit(true);
              setError('');
              // If there's a pending conversation to resume (navigated from ChatHistory), send it now
              if (pendingConversationRef.current) {
                ws?.send(JSON.stringify({
                  type: 'resume_conversation',
                  conversation_id: pendingConversationRef.current
                }));
                pendingConversationRef.current = null;
                window.history.replaceState({}, '');
              } else if (pendingNewChatRef.current) {
                // New chat was requested before WS was ready — send clear_context now
                ws?.send(JSON.stringify({ type: 'clear_context' }));
                pendingNewChatRef.current = false;
                window.history.replaceState({}, '');
              }
              break;
            case 'screenshot_start':
              setIsHidden(true);
              break;
            case 'screenshot_ready':
              setStatus('Screenshot captured! Ask about it or continue chatting.');
              setError('');
              setIsHidden(false);
              // Don't reset chat history - allow continuing conversation with new screenshot context
              break;
            case 'screenshot_added': {
              // New screenshot added to context
              try {
                const ssData = typeof data.content === 'string' ? JSON.parse(data.content) : data.content;
                setScreenshots(prev => {
                  const updated = [...prev, {
                    id: ssData.id,
                    name: ssData.name,
                    thumbnail: ssData.thumbnail
                  }];
                  screenshotsRef.current = updated;
                  return updated;
                });
                setStatus('Screenshot added to context.');
                setIsHidden(false);
              } catch (e) {
                console.error('Error parsing screenshot data:', e);
              }
              break;
            }
            case 'screenshot_removed': {
              // Screenshot removed from context
              try {
                const removeData = typeof data.content === 'string' ? JSON.parse(data.content) : data.content;
                setScreenshots(prev => prev.filter(ss => ss.id !== removeData.id));
              } catch (e) {
                console.error('Error parsing screenshot removal:', e);
              }
              break;
            }
            case 'screenshots_cleared':
              // Only clear screenshots, preserve chat history (used in fullscreen mode)
              setScreenshots([]);
              screenshotsRef.current = [];
              break;
            case 'context_cleared':
              setStatus(data.content || 'Context cleared. Ready for new conversation.');
              setResponse('');
              setThinking('');
              setIsThinking(false);
              setThinkingCollapsed(true);
              setError('');
              setQuery('');
              setCurrentQuery('');
              setChatHistory([]);
              setScreenshots([]);
              setCanSubmit(true);
              setConversationId(null);
              // Reset token usage for new conversation
              setTokenUsage({ total: 0, input: 0, output: 0, limit: 128000 });
              // Reset refs
              currentQueryRef.current = '';
              responseRef.current = '';
              thinkingRef.current = '';
              screenshotsRef.current = [];
              break;
            case 'query':
              // Server echoes the submitted query
              setCurrentQuery(data.content);
              currentQueryRef.current = data.content;
              setError('');
              setStatus('Thinking...');
              setIsThinking(true);
              setCanSubmit(false);
              // Reset tool calls for this new query
              toolCallsRef.current = [];
              break;
            case 'tool_call': {
              // MCP tool call event — accumulate completed calls
              try {
                const tc = typeof data.content === 'string' ? JSON.parse(data.content) : data.content;
                if (tc.status === 'calling') {
                  setStatus(`Calling tool: ${tc.name}...`);
                } else if (tc.status === 'complete') {
                  toolCallsRef.current = [...toolCallsRef.current, {
                    name: tc.name,
                    args: tc.args,
                    result: tc.result,
                    server: tc.server
                  }];
                  setStatus('Tool call complete. Generating response...');
                }
              } catch (e) {
                console.error('Error parsing tool_call:', e);
              }
              break;
            }
            case 'tool_calls_summary': {
              // Full summary of all tool calls (backup in case individual events were missed)
              try {
                const calls = typeof data.content === 'string' ? JSON.parse(data.content) : data.content;
                if (Array.isArray(calls) && calls.length > 0) {
                  toolCallsRef.current = calls;
                }
              } catch (e) {
                console.error('Error parsing tool_calls_summary:', e);
              }
              break;
            }
            case 'thinking_chunk':
              setThinking(prev => prev + data.content);
              thinkingRef.current += data.content;
              break;
            case 'thinking_complete':
              setIsThinking(false);
              setStatus('Receiving response...');
              break;
            case 'response_chunk':
              setResponse(prev => prev + data.content);
              responseRef.current += data.content;
              break;
            case 'response_complete': {
              // Capture values BEFORE resetting - React's setState callback runs async!
              const completedQuery = currentQueryRef.current;
              const completedResponse = responseRef.current;
              const completedThinking = thinkingRef.current;
              // Capture screenshots that were attached to this query
              const attachedImages = screenshotsRef.current.map(ss => ({
                name: ss.name,
                thumbnail: ss.thumbnail
              }));
              // Capture tool calls made during this response
              const completedToolCalls = toolCallsRef.current.length > 0 ? [...toolCallsRef.current] : undefined;
              
              // Add the completed exchange to chat history
              setChatHistory(prev => [
                ...prev,
                { role: 'user', content: completedQuery, images: attachedImages.length > 0 ? attachedImages : undefined },
                { role: 'assistant', content: completedResponse, thinking: completedThinking || undefined, toolCalls: completedToolCalls }
              ]);
              // Clear current response/thinking for next turn
              setResponse('');
              setThinking('');
              setCurrentQuery('');
              // Note: query input is already cleared in handleSubmit
              // Reset refs
              currentQueryRef.current = '';
              responseRef.current = '';
              thinkingRef.current = '';
              toolCallsRef.current = [];
              setStatus('Ready for follow-up question.');
              setCanSubmit(true); // Allow follow-up questions
              break;
            }
            case 'token_usage': {
              const stats = JSON.parse(data.content);
              const input = stats.prompt_eval_count || 0;
              const output = stats.eval_count || 0;
              
              setTokenUsage(prev => ({
                ...prev,
                total: prev.total + input + output,
                input: prev.input + input,
                output: prev.output + output
              }));
              break;
            }
            case 'conversation_saved': {
              try {
                const saveData = JSON.parse(data.content);
                setConversationId(saveData.conversation_id);
              } catch (e) {
                console.error('Error parsing conversation_saved:', e);
              }
              break;
            }
            case 'conversation_resumed': {
              try {
                const resumeData = JSON.parse(data.content);
                setConversationId(resumeData.conversation_id);
                // Load the conversation messages into chat history
                const msgs = resumeData.messages.map((m: {
                  role: 'user' | 'assistant';
                  content: string;
                  images?: Array<{ name: string; thumbnail: string }>;
                }) => ({
                  role: m.role as 'user' | 'assistant',
                  content: m.content,
                  images: m.images && m.images.length > 0 ? m.images : undefined,
                }));
                setChatHistory(msgs);
                // Restore token usage from database
                if (resumeData.token_usage) {
                  setTokenUsage(prev => ({
                    ...prev,
                    total: resumeData.token_usage.total || 0,
                    input: resumeData.token_usage.input || 0,
                    output: resumeData.token_usage.output || 0
                  }));
                }
                setResponse('');
                setThinking('');
                setCurrentQuery('');
                setScreenshots([]);
                screenshotsRef.current = [];
                currentQueryRef.current = '';
                responseRef.current = '';
                thinkingRef.current = '';
                setStatus('Conversation loaded. Ask a follow-up question.');
                setCanSubmit(true);
              } catch (e) {
                console.error('Error parsing conversation_resumed:', e);
              }
              break;
            }
            case 'error':
              setError(data.content);
              setResponse('');
              setStatus('An error occurred.');
              setCanSubmit(true); // Allow retry
              break;
          }
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e);
          setError('Failed to parse message from server.');
          setStatus('An error occurred.');
        }
      };

      ws.onclose = () => {
        setStatus('Disconnected. Retrying connection...');
        // Don't clear query/response here to preserve state during brief disconnects
        setTimeout(connect, 2000); // Attempt to reconnect after 2 seconds
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        // The onclose event will be fired next, which will handle the retry.
      };
    };

    connect(); // Initial connection attempt

    return () => {
      // Cleanly close the WebSocket connection when the component unmounts
    if (ws) {
          ws.onclose = null; // Prevent automatic reconnection on component unmount
          ws.close();
        }
      };
    }, []);

  // Handle resuming a conversation or starting new chat when navigating
  useEffect(() => {
    const state = location.state as { conversationId?: string; newChat?: boolean } | null;
    if (state?.conversationId) {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // WS already open — send immediately
        wsRef.current.send(JSON.stringify({
          type: 'resume_conversation',
          conversation_id: state.conversationId
        }));
        window.history.replaceState({}, '');
      } else {
        // WS not open yet — stash the ID so the 'ready' handler picks it up
        pendingConversationRef.current = state.conversationId;
      }
    } else if (state?.newChat) {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // WS already open — send clear_context immediately
        wsRef.current.send(JSON.stringify({ type: 'clear_context' }));
        window.history.replaceState({}, '');
      } else {
        // WS not open yet — stash the flag so the 'ready' handler picks it up
        pendingNewChatRef.current = true;
      }
    }
  }, [location.state]);

  // Focus the input field whenever canSubmit becomes true (new screenshot taken)
  useEffect(() => {
    if (canSubmit && inputRef.current) {
      // For Electron apps, use the electronAPI to focus the window
      const focusInput = async () => {
        try {
          console.log('Attempting to focus window...', { electronAPI: window.electronAPI });
          if (window.electronAPI) {
            console.log('Calling electronAPI.focusWindow()');
            await window.electronAPI.focusWindow();
            console.log('electronAPI.focusWindow() completed');
          } else {
            console.log('electronAPI not available, using fallback');
            window.focus();
          }
          // Small delay to ensure window focus happens first
          setTimeout(() => {
            if (inputRef.current) {
              inputRef.current.focus();
              console.log('Input focused');
            }
          }, 50);
        } catch (error) {
          console.error('Failed to focus window:', error);
          // Fallback to just focusing the input
          if (inputRef.current) {
            inputRef.current.focus();
          }
        }
      };
      
      focusInput();
    }
  }, [canSubmit]);

  const scrollToBottom = () => {
    if (responseAreaRef.current) {
      responseAreaRef.current.scrollTo({
        top: responseAreaRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  };

  const handleScroll = () => {
    if (responseAreaRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = responseAreaRef.current;
      // Show button if we are more than 50px from the bottom
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
      setShowScrollBottom(!isNearBottom);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (!query.trim()) return; // Don't submit empty queries

    setResponse('');
    setThinking('');
    setThinkingCollapsed(true);
    setQuery(''); // Clear input immediately

    // Scroll to bottom when user submits
    setTimeout(scrollToBottom, 50);
    
    // Send query with capture mode
    wsRef.current.send(JSON.stringify({ 
      type: 'submit_query', 
      content: query.trim(),
      capture_mode: captureMode
    }));
  };

  const handleStopStreaming = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'stop_streaming' }));
  };

  const handleClearContext = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'clear_context' }));
  };

  const handleRemoveScreenshot = (id: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'remove_screenshot', id }));
  };

  // Helper to get appropriate placeholder text
  const getPlaceholder = () => {
    if (chatHistory.length > 0) {
      return screenshots.length > 0 ? "Ask a follow-up about the screenshot(s)..." : "Ask a follow-up question...";
    }
    if (captureMode === 'fullscreen') {
      return "Ask Xpdite anything on your screen...";
    }
    if (captureMode === 'precision') {
      return screenshots.length > 0 ? "Ask about the screenshot(s)..." : "Ask Xpdite about a region on your screen (Alt+.)";
    }
    return "Ask Xpdite anything...";
  };
  
  const sendCaptureMode = (mode: 'fullscreen' | 'precision' | 'none') => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'set_capture_mode', mode }));
    }
  };
  
  const fullscreenModeEnabled = () => {
    setCaptureMode('fullscreen');
    setMeetingRecordingMode(false);
    sendCaptureMode('fullscreen');
  };
  
  const precisionModeEnabled = () => {
    setCaptureMode('precision');
    setMeetingRecordingMode(false);
    sendCaptureMode('precision');
  };
  
  const meetingRecordingModeEnabled = () => {
    setCaptureMode('none');
    setMeetingRecordingMode(true);
    sendCaptureMode('none');
  }
  return (
    <>
      <div className="content-container" style={{ width: '100%', height: '100%', position: 'relative' }}>
        <TitleBar onClearContext={handleClearContext} setMini={setMini} />
        <div 
          className="response-area" 
          ref={responseAreaRef}
          onScroll={handleScroll}
        >
          {error && <div className="error"><strong>Error:</strong> {error}</div>}

          {/* Display chat history */}
          {!error && chatHistory.map((msg, idx) => (
            <div key={idx} className={msg.role === 'user' ? 'chat-user' : 'chat-assistant'}>
              {msg.role === 'user' ? (
                <div className="query">
                  {/* <div className="user-header">You</div> */}
                  <p>{msg.content}</p>
                  {msg.images && msg.images.length > 0 && (
                    <div className="message-image-chips">
                      {msg.images.map((img, imgIdx) => (
                        <div key={imgIdx} className="message-image-chip">
                          {img.thumbnail ? (
                            <img 
                              src={`data:image/png;base64,${img.thumbnail}`} 
                              alt={img.name || `Image ${imgIdx + 1}`}
                              className="message-chip-thumb"
                            />
                          ) : (
                            <CameraIcon size={12} className="message-chip-icon" />
                          )}
                          <span className="message-chip-name">{img.name || `Image ${imgIdx + 1}`}</span>
                          {/* Hover preview popup */}
                          {img.thumbnail && (
                            <div className="message-chip-hover-preview">
                              <img 
                                src={`data:image/png;base64,${img.thumbnail}`} 
                                alt={img.name || `Image ${imgIdx + 1}`}
                              />
                              <span>{img.name || `Image ${imgIdx + 1}`}</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="response">
                  <div className="assistant-header">Xpdite • {selectedModel}</div>
                  {/* Tool calls display */}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="tool-calls-section">
                      <div className="tool-calls-header">
                        <span className="tool-calls-icon">&#9881;</span>
                        <span>Used {msg.toolCalls.length} tool{msg.toolCalls.length > 1 ? 's' : ''}</span>
                      </div>
                      <div className="tool-calls-list">
                        {msg.toolCalls.map((tc, tcIdx) => (
                          <div key={tcIdx} className="tool-call-item">
                            <div className="tool-call-name">
                              <span className="tool-call-badge">{tc.server}</span>
                              <code>{tc.name}({Object.entries(tc.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(', ')})</code>
                            </div>
                            <div className="tool-call-result">
                              <span className="tool-result-label">Result:</span> <code>{tc.result.slice(0, 100)}{tc.result.length > 100 ? '...' : ''}</code>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <ReactMarkdown
                    components={{
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      code({ inline, className, children, ...props }: any) {
                        const match = /language-(\w+)/.exec(className || '');
                        const codeContent = String(children).replace(/\n$/, '');

                        if (!inline && match) {
                          return (
                            <div className="code-block-container">
                              <button
                                onClick={() => copyToClipboard(codeContent)}
                                className="copy-button"
                                title="Copy code"
                              >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                </svg>
                              </button>
                              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                              <SyntaxHighlighter style={vscDarkPlus as any} language={match[1]} PreTag="div" {...props}>
                                {codeContent}
                              </SyntaxHighlighter>
                            </div>
                          );
                        }
                        return <code className={className} {...props}>{children}</code>;
                      },
                    }}
                  >{msg.content}</ReactMarkdown>
                </div>
              )}
            </div>
          ))}

          {/* Current query being processed */}
          {!error && currentQuery && !canSubmit && (
            <div className="query">
              {/* <div className="user-header">You</div> */}
              <p>{currentQuery}</p>
            </div>
          )}

          {/* Current thinking process */}
          {!error && thinking && (
            <div className="thinking-section">
              <div
                className="thinking-header"
                onClick={() => setThinkingCollapsed(!thinkingCollapsed)}
              >
                <ChevronRightIcon
                  size={12}
                  className={`thinking-arrow ${thinkingCollapsed ? '' : 'expanded'}`}
                />
                <span className="thinking-label">
                  {isThinking ? 'Thinking...' : 'Thought process'}
                </span>
              </div>
              {!thinkingCollapsed && (
                <div className="thinking-content">
                  <ReactMarkdown>{thinking}</ReactMarkdown>
                </div>
              )}
            </div>
          )}

          {/* Current response being streamed */}
          {!error && response && (
            <div className="response">
              <div className="assistant-header">Xpdite • {selectedModel}</div>
              <ReactMarkdown
                components={{
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  code({ inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '');
                    const codeContent = String(children).replace(/\n$/, '');

                    if (!inline && match) {
                      return (
                        <div className="code-block-container">
                          <button
                            onClick={() => copyToClipboard(codeContent)}
                            className="copy-button"
                            title="Copy code"
                          >
                            <svg
                              width="14"
                              height="14"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                          </button>
                          <SyntaxHighlighter
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            style={vscDarkPlus as any}
                            language={match[1]}
                            PreTag="div"
                            {...props}
                          >
                            {codeContent}
                          </SyntaxHighlighter>
                        </div>
                      );
                    }
                    return <code className={className} {...props}>{children}</code>;
                  },
                }}
              >{response}</ReactMarkdown>
            </div>
          )}
          {/* <div className="status">{status}</div> */}
        </div>

        {showScrollBottom && (
          <button 
            className="scroll-bottom-button" 
            onClick={scrollToBottom}
            title="Scroll to bottom"
          >
            <img src={scrollDownIcon} alt="Scroll down" className="scroll-down-icon" />
          </button>
        )}

        <div className="main-interaction-section">
          <div className="query-input-section">
            <div className="query-input-text-box-section">
              <form onSubmit={handleSubmit} style={{ marginTop: '0.5rem' }} className='query-input-form'>
                <input
                  ref={inputRef}
                  className="query-input"
                  type="text"
                  placeholder={getPlaceholder()}
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                />
              </form>
              {!canSubmit && (
                <button className="stop-streaming-button" onClick={handleStopStreaming} title="Stop generating">
                  <div className="stop-icon" />
                </button>
              )}
            </div>

            <div className="input-options-section">
              {/* <div className="add-attachments-section">
                <img src={plusSignSvg} alt="Add attachment" className='plus-sign-svg' />
              </div> */}
              
              {/* Fixed container for context chips - maintains layout stability */}
              <div 
                className="chips-container-wrapper"
                onWheel={(e) => {
                  if (e.deltaY !== 0) {
                    e.currentTarget.scrollLeft += e.deltaY;
                    e.preventDefault();
                  }
                }}
              >
                {screenshots.length > 0 && (
                  <div className="context-chips">
                    {screenshots.map((ss, index) => (
                      <div key={ss.id} className="context-chip">
                        <div className="chip-preview">
                          {ss.thumbnail ? (
                            <img 
                              src={`data:image/png;base64,${ss.thumbnail}`} 
                              alt={ss.name}
                              className="chip-thumb"
                            />
                          ) : (
                            <CameraIcon size={12} className="chip-icon" />
                          )}
                        </div>
                        <span className="chip-name">SS{index + 1}</span>
                        <button 
                          className="chip-remove" 
                          onClick={() => handleRemoveScreenshot(ss.id)}
                          title="Remove"
                        >
                          <XIcon size={12} />
                        </button>
                        {/* Hover preview popup */}
                        <div className="chip-hover-preview">
                          {ss.thumbnail && (
                            <img 
                              src={`data:image/png;base64,${ss.thumbnail}`} 
                              alt={ss.name}
                              className="hover-preview-img"
                            />
                          )}
                          <span className="hover-preview-name">{ss.name}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="additional-inputs-section">
                <div className="model-selection-section">
                  <select 
                    name="model-selector" 
                    className='model-select' 
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                  >
                    <option value="qwen3-vl:8b-instruct">Qwen 3 VL:8B</option>
                    <option value="GPT-5">GPT-5</option>
                    <option value="GPT-3.5">GPT-3.5</option>
                    <option value="Claude Opus 4.6">Claude Opus 4.6</option>
                  </select>
                </div>
                <div 
                  className="context-window-insights-icon"
                  onMouseEnter={() => setShowTokenPopup(true)}
                  onMouseLeave={() => setShowTokenPopup(false)}
                  onClick={() => setShowTokenPopup(!showTokenPopup)}
                >
                  <img src={contextWindowInsightsIcon} alt="Context Window Insights" className='context-window-insights-svg' title="Context Window Insights" />
                  
                  {showTokenPopup && (
                    <div className="token-usage-popup">
                      <div className="token-popup-header">
                        <span className="token-popup-title">Context Window</span>
                        <span className="token-popup-subtitle">
                          {((tokenUsage.total / 1000)).toFixed(1)}K / {(tokenUsage.limit / 1000)}K tokens • {Math.round((tokenUsage.total / tokenUsage.limit) * 100)}%
                        </span>
                      </div>
                      
                      <div className="token-progress-bar-container">
                        <div 
                          className="token-progress-bar-fill" 
                          style={{ width: `${Math.min(100, (tokenUsage.total / tokenUsage.limit) * 100)}%` }}
                        ></div>
                      </div>

                      <div className="token-usage-section">
                        <div className="token-usage-row">
                          <span className="token-usage-label">Total Tokens</span>
                          <span className="token-usage-value">{tokenUsage.total.toLocaleString()} ({Math.round((tokenUsage.total / tokenUsage.limit) * 100)}%)</span>
                        </div>
                        <div className="token-usage-row">
                          <span className="token-usage-label">Input Tokens</span>
                          <span className="token-usage-value">{tokenUsage.input.toLocaleString()} ({Math.round((tokenUsage.input / tokenUsage.total || 0) * 100)}%)</span>
                        </div>
                        <div className="token-usage-row">
                          <span className="token-usage-label">Output Tokens</span>
                          <span className="token-usage-value">{tokenUsage.output.toLocaleString()} ({Math.round((tokenUsage.output / tokenUsage.total || 0) * 100)}%)</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="mic-input-section">
                  <img src={micSignSvg} alt="Voice input" className='mic-icon' />
                </div>
              </div>
            </div>
          </div>
          <div className="mode-selection-section">
            <div className={`regionssmode${captureMode === 'precision' ? '-active' : ''}`} onClick={precisionModeEnabled} title="Talk to a specific region of your screen">
              <img src={regionSSIcon} alt="Region Screenshot Mode" className='region-ss-icon' />
            </div>
            <div className={`fullscreenssmode${captureMode === 'fullscreen' ? '-active' : ''}`} onClick={fullscreenModeEnabled} title="Talk to anything on your screen">
              <img src={fullscreenSSIcon} alt="Full Screen Screenshot Mode" className='fullscreen-ss-icon' />
            </div>
            <div className={`meetingrecordermode${meetingRecordingMode ? '-active' : ''}`} onClick={meetingRecordingModeEnabled} title="Meeting recorder mode">
              <img src={meetingRecordingIcon} alt="Meeting Recorder Mode" className='meeting-recording-icon' />
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default App
