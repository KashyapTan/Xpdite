/**
 * Chat state management hook.
 * 
 * Manages chat history, current query/response, and conversation state.
 */
import { useState, useRef, useCallback } from 'react';
import type { ChatMessage, ToolCall, ContentBlock, TerminalCommandBlock, ChatStateSnapshot } from '../types';

interface UseChatStateReturn {
  // State
  chatHistory: ChatMessage[];
  currentQuery: string;
  response: string;
  thinking: string;
  isThinking: boolean;
  thinkingCollapsed: boolean;
  toolCalls: ToolCall[];
  contentBlocks: ContentBlock[];
  conversationId: string | null;
  query: string;
  canSubmit: boolean;
  status: string;
  error: string;
  
  // Refs for WebSocket callbacks
  currentQueryRef: React.RefObject<string>;
  responseRef: React.RefObject<string>;
  thinkingRef: React.RefObject<string>;
  toolCallsRef: React.RefObject<ToolCall[]>;
  contentBlocksRef: React.RefObject<ContentBlock[]>;
  
  // Actions
  setQuery: React.Dispatch<React.SetStateAction<string>>;
  setChatHistory: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setCanSubmit: (canSubmit: boolean) => void;
  setStatus: (status: string) => void;
  setError: (error: string) => void;
  setThinkingCollapsed: (collapsed: boolean) => void;
  setIsThinking: (isThinking: boolean) => void;
  appendThinking: (chunk: string) => void;
  appendResponse: (chunk: string) => void;
  addToolCall: (toolCall: ToolCall) => void;
  updateToolCall: (toolCall: ToolCall) => void;
  addTerminalBlock: (terminal: TerminalCommandBlock) => void;
  updateTerminalBlock: (requestId: string, updates: Partial<TerminalCommandBlock>) => void;
  appendTerminalOutput: (requestId: string, text: string, raw?: boolean) => void;
  startQuery: (query: string) => void;
  completeResponse: (attachedImages?: Array<{name: string; thumbnail: string}>, model?: string) => void;
  clearStreamingState: (status?: string) => void;
  resetForNewChat: () => void;
  loadConversation: (id: string, messages: ChatMessage[]) => void;
  setConversationId: (id: string | null) => void;

  // Snapshot / restore for tab switching
  getSnapshot: () => ChatStateSnapshot;
  restoreSnapshot: (snapshot: ChatStateSnapshot) => void;
}

export function useChatState(): UseChatStateReturn {
  // UI State
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState('');
  const [thinking, setThinking] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingCollapsed, setThinkingCollapsed] = useState(true);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [contentBlocks, setContentBlocks] = useState<ContentBlock[]>([]);
  const [status, setStatus] = useState('Connecting to server...');
  const [error, setError] = useState('');
  const [canSubmit, setCanSubmit] = useState(false);
  
  // Chat State
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [currentQuery, setCurrentQuery] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  
  // Refs for WebSocket callbacks (avoid stale closures)
  const currentQueryRef = useRef('');
  const responseRef = useRef('');
  const thinkingRef = useRef('');
  const toolCallsRef = useRef<ToolCall[]>([]);
  const contentBlocksRef = useRef<ContentBlock[]>([]);

  const appendThinking = useCallback((chunk: string) => {
    setThinking(prev => prev + chunk);
    thinkingRef.current += chunk;
  }, []);

  const appendResponse = useCallback((chunk: string) => {
    setResponse(prev => prev + chunk);
    responseRef.current += chunk;

    // Append to last text block, or create a new one
    const blocks = contentBlocksRef.current;
    if (blocks.length > 0 && blocks[blocks.length - 1].type === 'text') {
      const newBlocks = [...blocks];
      newBlocks[newBlocks.length - 1] = {
        type: 'text',
        content: (newBlocks[newBlocks.length - 1] as { type: 'text'; content: string }).content + chunk,
      };
      contentBlocksRef.current = newBlocks;
      setContentBlocks(newBlocks);
    } else {
      const newBlocks: ContentBlock[] = [...blocks, { type: 'text', content: chunk }];
      contentBlocksRef.current = newBlocks;
      setContentBlocks(newBlocks);
    }
  }, []);

  const addToolCall = useCallback((toolCall: ToolCall) => {
    setToolCalls(prev => [...prev, toolCall]);
    toolCallsRef.current = [...toolCallsRef.current, toolCall];

    // Append a tool_call block to contentBlocks
    const newBlocks: ContentBlock[] = [...contentBlocksRef.current, { type: 'tool_call', toolCall }];
    contentBlocksRef.current = newBlocks;
    setContentBlocks(newBlocks);
  }, []);

  const updateToolCall = useCallback((updatedToolCall: ToolCall) => {
    setToolCalls(prev => prev.map(tc => 
      (tc.name === updatedToolCall.name && JSON.stringify(tc.args) === JSON.stringify(updatedToolCall.args)) 
        ? { ...tc, ...updatedToolCall } 
        : tc
    ));
    
    // Update ref as well
    toolCallsRef.current = toolCallsRef.current.map(tc => 
       (tc.name === updatedToolCall.name && JSON.stringify(tc.args) === JSON.stringify(updatedToolCall.args))
        ? { ...tc, ...updatedToolCall }
        : tc
    );

    // Update the matching tool_call block in contentBlocks
    const newBlocks = contentBlocksRef.current.map(block => {
      if (
        block.type === 'tool_call' &&
        block.toolCall.name === updatedToolCall.name &&
        JSON.stringify(block.toolCall.args) === JSON.stringify(updatedToolCall.args)
      ) {
        return { ...block, toolCall: { ...block.toolCall, ...updatedToolCall } };
      }
      return block;
    });
    contentBlocksRef.current = newBlocks;
    setContentBlocks(newBlocks);
  }, []);

  // ── Terminal block management ─────────────────────────────────

  const addTerminalBlock = useCallback((terminal: TerminalCommandBlock) => {
    // Ensure new fields have defaults
    const block: TerminalCommandBlock = {
      ...terminal,
      outputChunks: terminal.outputChunks || [],
      isPty: terminal.isPty || false,
    };
    const newBlocks: ContentBlock[] = [...contentBlocksRef.current, { type: 'terminal_command', terminal: block }];
    contentBlocksRef.current = newBlocks;
    setContentBlocks(newBlocks);
  }, []);

  const updateTerminalBlock = useCallback((requestId: string, updates: Partial<TerminalCommandBlock>) => {
    const newBlocks = contentBlocksRef.current.map(block => {
      if (block.type === 'terminal_command' && block.terminal.requestId === requestId) {
        return { ...block, terminal: { ...block.terminal, ...updates } };
      }
      return block;
    });
    contentBlocksRef.current = newBlocks;
    setContentBlocks(newBlocks);
  }, []);

  const appendTerminalOutput = useCallback((requestId: string, text: string, raw: boolean = false) => {
    const newBlocks = contentBlocksRef.current.map(block => {
      if (block.type === 'terminal_command' && block.terminal.requestId === requestId) {
        // Mark as PTY if we receive raw output
        const isPty = block.terminal.isPty || raw;
        return {
          ...block,
          terminal: {
            ...block.terminal,
            output: block.terminal.output + text + (raw ? '' : '\n'),
            outputChunks: [...block.terminal.outputChunks, { text, raw }],
            isPty,
          },
        };
      }
      return block;
    });
    contentBlocksRef.current = newBlocks;
    setContentBlocks(newBlocks);
  }, []);

  const startQuery = useCallback((queryText: string) => {
    setCurrentQuery(queryText);
    currentQueryRef.current = queryText;
    setError('');
    setStatus('Thinking...');
    setIsThinking(true);
    setCanSubmit(false);
    // Reset tool calls and content blocks for new query
    setToolCalls([]);
    toolCallsRef.current = [];
    setContentBlocks([]);
    contentBlocksRef.current = [];
  }, []);

  const clearStreamingState = useCallback((nextStatus: string = 'Ready for follow-up question.') => {
    setResponse('');
    setThinking('');
    setCurrentQuery('');
    setIsThinking(false);
    setToolCalls([]);
    setContentBlocks([]);

    currentQueryRef.current = '';
    responseRef.current = '';
    thinkingRef.current = '';
    toolCallsRef.current = [];
    contentBlocksRef.current = [];

    setStatus(nextStatus);
    setCanSubmit(true);
  }, []);

  const completeResponse = useCallback((attachedImages?: Array<{name: string; thumbnail: string}>, model?: string) => {
    const completedQuery = currentQueryRef.current;
    const completedResponse = responseRef.current;
    const completedThinking = thinkingRef.current;
    const completedToolCalls = toolCallsRef.current.length > 0 ? [...toolCallsRef.current] : undefined;
    const completedContentBlocks = contentBlocksRef.current.length > 0 ? [...contentBlocksRef.current] : undefined;
    const timestamp = Date.now();
    const responseVersions = completedResponse || completedToolCalls
      ? [{
        responseIndex: 0,
        content: completedResponse,
        model,
        timestamp,
        contentBlocks: completedContentBlocks,
      }]
      : undefined;

    // Guard: if nothing was generated (cancelled before any output, or duplicate
    // response_complete), just reset state without adding empty messages.
    if (!completedResponse && !completedThinking && !completedToolCalls) {
      clearStreamingState('Ready');
      return;
    }

    // Add to chat history
    setChatHistory(prev => [
      ...prev,
      { 
        role: 'user', 
        content: completedQuery, 
        images: attachedImages && attachedImages.length > 0 ? attachedImages : undefined,
        timestamp,
      },
      { 
        role: 'assistant', 
        content: completedResponse, 
        thinking: completedThinking || undefined, 
        toolCalls: completedToolCalls,
        contentBlocks: completedContentBlocks,
        model,
        timestamp,
        activeResponseIndex: 0,
        responseVersions,
      }
    ]);

    clearStreamingState();
  }, [clearStreamingState]);

  const resetForNewChat = useCallback(() => {
    setStatus('Context cleared. Ready for new conversation.');
    setResponse('');
    setThinking('');
    setIsThinking(false);
    setThinkingCollapsed(true);
    setToolCalls([]);
    setContentBlocks([]);
    setError('');
    setQuery('');
    setCurrentQuery('');
    setChatHistory([]);
    setCanSubmit(true);
    setConversationId(null);
    
    // Reset refs
    currentQueryRef.current = '';
    responseRef.current = '';
    thinkingRef.current = '';
    toolCallsRef.current = [];
    contentBlocksRef.current = [];
  }, []);

  const loadConversation = useCallback((id: string, messages: ChatMessage[]) => {
    setConversationId(id);
    setChatHistory(messages);
    setResponse('');
    setThinking('');
    setCurrentQuery('');
    
    // Reset refs
    currentQueryRef.current = '';
    responseRef.current = '';
    thinkingRef.current = '';
    
    setStatus('Conversation loaded. Ask a follow-up question.');
    setCanSubmit(true);
  }, []);

  // ── Snapshot / restore for tab switching ─────────────────────

  const getSnapshot = useCallback((): ChatStateSnapshot => {
    return {
      chatHistory,
      currentQuery: currentQueryRef.current,
      response: responseRef.current,
      thinking: thinkingRef.current,
      isThinking,
      thinkingCollapsed,
      toolCalls: [...toolCallsRef.current],
      contentBlocks: [...contentBlocksRef.current],
      conversationId,
      query,
      canSubmit,
      status,
      error,
    };
  }, [chatHistory, isThinking, thinkingCollapsed, conversationId, query, canSubmit, status, error]);

  const restoreSnapshot = useCallback((s: ChatStateSnapshot) => {
    setChatHistory(s.chatHistory);
    setCurrentQuery(s.currentQuery);
    currentQueryRef.current = s.currentQuery;
    setResponse(s.response);
    responseRef.current = s.response;
    setThinking(s.thinking);
    thinkingRef.current = s.thinking;
    setIsThinking(s.isThinking);
    setThinkingCollapsed(s.thinkingCollapsed);
    setToolCalls(s.toolCalls);
    toolCallsRef.current = [...s.toolCalls];
    setContentBlocks(s.contentBlocks);
    contentBlocksRef.current = [...s.contentBlocks];
    setConversationId(s.conversationId);
    setQuery(s.query);
    setCanSubmit(s.canSubmit);
    setStatus(s.status);
    setError(s.error);
  }, []);

  return {
    // State
    chatHistory,
    currentQuery,
    response,
    thinking,
    toolCalls,
    contentBlocks,
    isThinking,
    thinkingCollapsed,
    conversationId,
    query,
    canSubmit,
    status,
    error,
    
    // Refs
    currentQueryRef,
    responseRef,
    thinkingRef,
    toolCallsRef,
    contentBlocksRef,
    
    // Actions
    setQuery,
    setChatHistory,
    setCanSubmit,
    setStatus,
    setError,
    setThinkingCollapsed,
    setIsThinking,
    appendThinking,
    appendResponse,
    addToolCall,
    updateToolCall,
    addTerminalBlock,
    updateTerminalBlock,
    appendTerminalOutput,
    startQuery,
    completeResponse,
    clearStreamingState,
    resetForNewChat,
    loadConversation,
    setConversationId,
    getSnapshot,
    restoreSnapshot,
  };
}
