/**
 * Chat state management hook.
 * 
 * Manages chat history, current query/response, and conversation state.
 */
import { useState, useRef, useCallback } from 'react';
import type { ChatMessage, ToolCall, ContentBlock } from '../types';

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
  setCanSubmit: (canSubmit: boolean) => void;
  setStatus: (status: string) => void;
  setError: (error: string) => void;
  setThinkingCollapsed: (collapsed: boolean) => void;
  setIsThinking: (isThinking: boolean) => void;
  appendThinking: (chunk: string) => void;
  appendResponse: (chunk: string) => void;
  addToolCall: (toolCall: ToolCall) => void;
  updateToolCall: (toolCall: ToolCall) => void;
  startQuery: (query: string) => void;
  completeResponse: (attachedImages?: Array<{name: string; thumbnail: string}>, model?: string) => void;
  resetForNewChat: () => void;
  loadConversation: (id: string, messages: ChatMessage[]) => void;
  setConversationId: (id: string | null) => void;
}

const DEFAULT_TOKEN_LIMIT = 128000;

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

  const completeResponse = useCallback((attachedImages?: Array<{name: string; thumbnail: string}>, model?: string) => {
    const completedQuery = currentQueryRef.current;
    const completedResponse = responseRef.current;
    const completedThinking = thinkingRef.current;
    const completedToolCalls = toolCallsRef.current.length > 0 ? [...toolCallsRef.current] : undefined;
    const completedContentBlocks = contentBlocksRef.current.length > 0 ? [...contentBlocksRef.current] : undefined;

    // Add to chat history
    setChatHistory(prev => [
      ...prev,
      { 
        role: 'user', 
        content: completedQuery, 
        images: attachedImages && attachedImages.length > 0 ? attachedImages : undefined 
      },
      { 
        role: 'assistant', 
        content: completedResponse, 
        thinking: completedThinking || undefined, 
        toolCalls: completedToolCalls,
        contentBlocks: completedContentBlocks,
        model: model
      }
    ]);

    // Reset current state
    setResponse('');
    setThinking('');
    setCurrentQuery('');
    setToolCalls([]);
    setContentBlocks([]);
    
    // Reset refs
    currentQueryRef.current = '';
    responseRef.current = '';
    thinkingRef.current = '';
    toolCallsRef.current = [];
    contentBlocksRef.current = [];
    
    setStatus('Ready for follow-up question.');
    setCanSubmit(true);
  }, []);

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
    setCanSubmit,
    setStatus,
    setError,
    setThinkingCollapsed,
    setIsThinking,
    appendThinking,
    appendResponse,
    addToolCall,
    updateToolCall,
    startQuery,
    completeResponse,
    resetForNewChat,
    loadConversation,
    setConversationId,
  };
}
