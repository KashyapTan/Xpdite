/**
 * Tests for useChatState hook.
 */
import { describe, expect, test } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useChatState } from '../../hooks/useChatState';
import type {
  ArtifactBlockData,
  ToolCall,
  TerminalCommandBlock,
  YouTubeTranscriptionApprovalBlock,
  ChatStateSnapshot,
} from '../../types';

describe('useChatState', () => {
  describe('initial state', () => {
    test('should have correct initial values', () => {
      const { result } = renderHook(() => useChatState());

      expect(result.current.chatHistory).toEqual([]);
      expect(result.current.currentQuery).toBe('');
      expect(result.current.response).toBe('');
      expect(result.current.thinking).toBe('');
      expect(result.current.isThinking).toBe(false);
      expect(result.current.thinkingCollapsed).toBe(true);
      expect(result.current.toolCalls).toEqual([]);
      expect(result.current.contentBlocks).toEqual([]);
      expect(result.current.conversationId).toBeNull();
      expect(result.current.query).toBe('');
      expect(result.current.canSubmit).toBe(false);
      expect(result.current.status).toBe('Connecting to server...');
      expect(result.current.error).toBe('');
    });

    test('should initialize refs with empty values', () => {
      const { result } = renderHook(() => useChatState());

      expect(result.current.currentQueryRef.current).toBe('');
      expect(result.current.responseRef.current).toBe('');
      expect(result.current.thinkingRef.current).toBe('');
      expect(result.current.toolCallsRef.current).toEqual([]);
      expect(result.current.contentBlocksRef.current).toEqual([]);
    });
  });

  describe('startQuery', () => {
    test('should set up streaming state correctly', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('What is TypeScript?');
      });

      expect(result.current.currentQuery).toBe('What is TypeScript?');
      expect(result.current.currentQueryRef.current).toBe('What is TypeScript?');
      expect(result.current.error).toBe('');
      expect(result.current.status).toBe('Thinking...');
      expect(result.current.isThinking).toBe(true);
      expect(result.current.canSubmit).toBe(false);
      expect(result.current.toolCalls).toEqual([]);
      expect(result.current.contentBlocks).toEqual([]);
    });

    test('should reset previous tool calls and content blocks', () => {
      const { result } = renderHook(() => useChatState());

      // Add some data first
      act(() => {
        const toolCall: ToolCall = {
          name: 'test_tool',
          args: { arg1: 'value1' },
          server: 'test-server',
          status: 'complete',
        };
        result.current.addToolCall(toolCall);
      });

      expect(result.current.toolCalls).toHaveLength(1);
      expect(result.current.contentBlocks).toHaveLength(1);

      // Start new query
      act(() => {
        result.current.startQuery('New question');
      });

      expect(result.current.toolCalls).toEqual([]);
      expect(result.current.toolCallsRef.current).toEqual([]);
      expect(result.current.contentBlocks).toEqual([]);
      expect(result.current.contentBlocksRef.current).toEqual([]);
    });
  });

  describe('appendResponse', () => {
    test('should accumulate response text', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendResponse('Hello');
      });
      expect(result.current.response).toBe('Hello');
      expect(result.current.responseRef.current).toBe('Hello');

      act(() => {
        result.current.appendResponse(' World');
      });
      expect(result.current.response).toBe('Hello World');
      expect(result.current.responseRef.current).toBe('Hello World');
    });

    test('should create text content block on first append', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendResponse('First chunk');
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'text',
        content: 'First chunk',
      });
    });

    test('should append to existing text block', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendResponse('Hello');
      });
      act(() => {
        result.current.appendResponse(' World');
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'text',
        content: 'Hello World',
      });
    });

    test('should create new text block after tool call', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendResponse('Before');
      });

      act(() => {
        result.current.addToolCall({
          name: 'test_tool',
          args: {},
          server: 'test-server',
        });
      });

      act(() => {
        result.current.appendResponse('After');
      });

      expect(result.current.contentBlocks).toHaveLength(3);
      expect(result.current.contentBlocks[0]).toEqual({ type: 'text', content: 'Before' });
      expect(result.current.contentBlocks[1].type).toBe('tool_call');
      expect(result.current.contentBlocks[2]).toEqual({ type: 'text', content: 'After' });
    });

    test('should keep a single text block under high chunk counts', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        for (let i = 0; i < 500; i += 1) {
          result.current.appendResponse(`chunk-${i};`);
        }
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'text',
        content: Array.from({ length: 500 }, (_unused, idx) => `chunk-${idx};`).join(''),
      });
    });
  });

  describe('appendThinking', () => {
    test('should accumulate thinking text', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendThinking('Let me think...');
      });
      expect(result.current.thinking).toBe('Let me think...');
      expect(result.current.thinkingRef.current).toBe('Let me think...');

      act(() => {
        result.current.appendThinking(' More thoughts.');
      });
      expect(result.current.thinking).toBe('Let me think... More thoughts.');
      expect(result.current.thinkingRef.current).toBe('Let me think... More thoughts.');
    });

    test('should create thinking content block', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendThinking('Thinking...');
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'thinking',
        content: 'Thinking...',
      });
    });

    test('should append to existing thinking block', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendThinking('First');
      });
      act(() => {
        result.current.appendThinking(' Second');
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'thinking',
        content: 'First Second',
      });
    });
  });

  describe('addToolCall', () => {
    test('should add tool call to state and ref', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall: ToolCall = {
        name: 'search',
        args: { query: 'test' },
        server: 'mcp-server',
        status: 'calling',
      };

      act(() => {
        result.current.addToolCall(toolCall);
      });

      expect(result.current.toolCalls).toHaveLength(1);
      expect(result.current.toolCalls[0]).toEqual(toolCall);
      expect(result.current.toolCallsRef.current).toHaveLength(1);
      expect(result.current.toolCallsRef.current[0]).toEqual(toolCall);
    });

    test('should add tool call content block', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall: ToolCall = {
        name: 'search',
        args: { query: 'test' },
        server: 'mcp-server',
      };

      act(() => {
        result.current.addToolCall(toolCall);
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'tool_call',
        toolCall,
      });
    });

    test('should support multiple tool calls', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall1: ToolCall = {
        name: 'search',
        args: { query: 'test1' },
        server: 'server1',
      };
      const toolCall2: ToolCall = {
        name: 'fetch',
        args: { url: 'https://example.com' },
        server: 'server2',
      };

      act(() => {
        result.current.addToolCall(toolCall1);
        result.current.addToolCall(toolCall2);
      });

      expect(result.current.toolCalls).toHaveLength(2);
      expect(result.current.contentBlocks).toHaveLength(2);
    });
  });

  describe('updateToolCall', () => {
    test('should update existing tool call by name and args', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall: ToolCall = {
        name: 'search',
        args: { query: 'test' },
        server: 'mcp-server',
        status: 'calling',
      };

      act(() => {
        result.current.addToolCall(toolCall);
      });

      act(() => {
        result.current.updateToolCall({
          ...toolCall,
          status: 'complete',
          result: 'Search results',
        });
      });

      expect(result.current.toolCalls[0].status).toBe('complete');
      expect(result.current.toolCalls[0].result).toBe('Search results');
      expect(result.current.toolCallsRef.current[0].status).toBe('complete');
    });

    test('should update tool call by agentId for sub-agents', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall: ToolCall = {
        name: 'sub_agent',
        args: { task: 'analyze' },
        server: 'mcp-server',
        status: 'calling',
        agentId: 'agent-123',
      };

      act(() => {
        result.current.addToolCall(toolCall);
      });

      act(() => {
        result.current.updateToolCall({
          name: 'sub_agent',
          args: {},
          server: 'mcp-server',
          status: 'progress',
          agentId: 'agent-123',
          partialResult: 'Working...',
        });
      });

      expect(result.current.toolCalls[0].status).toBe('progress');
      expect(result.current.toolCalls[0].partialResult).toBe('Working...');
    });

    test('should update tool call in content blocks', () => {
      const { result } = renderHook(() => useChatState());

      const toolCall: ToolCall = {
        name: 'search',
        args: { query: 'test' },
        server: 'mcp-server',
        status: 'calling',
      };

      act(() => {
        result.current.addToolCall(toolCall);
      });

      act(() => {
        result.current.updateToolCall({
          ...toolCall,
          status: 'complete',
        });
      });

      const block = result.current.contentBlocks[0];
      expect(block.type).toBe('tool_call');
      if (block.type === 'tool_call') {
        expect(block.toolCall.status).toBe('complete');
      }
    });
  });

  describe('artifact block management', () => {
    const streamingArtifact: ArtifactBlockData = {
      artifactId: 'artifact-1',
      artifactType: 'code',
      title: 'demo.py',
      language: 'python',
      sizeBytes: 0,
      lineCount: 0,
      status: 'streaming',
    };

    test('should add artifact block', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.addArtifactBlock(streamingArtifact);
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0]).toEqual({
        type: 'artifact',
        artifact: streamingArtifact,
      });
    });

    test('should upsert streaming artifact chunks through addArtifactBlock', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.addArtifactBlock(streamingArtifact);
        result.current.addArtifactBlock({
          ...streamingArtifact,
          sizeBytes: 11,
          lineCount: 1,
          content: 'print("hi")',
        });
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      const block = result.current.contentBlocks[0];
      expect(block.type).toBe('artifact');
      if (block.type === 'artifact') {
        expect(block.artifact.status).toBe('streaming');
        expect(block.artifact.content).toBe('print("hi")');
        expect(block.artifact.sizeBytes).toBe(11);
      }
    });

    test('should complete artifact block in place', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.addArtifactBlock(streamingArtifact);
        result.current.completeArtifactBlock({
          ...streamingArtifact,
          status: 'ready',
          sizeBytes: 11,
          lineCount: 1,
          content: 'print("hi")',
        });
      });

      const block = result.current.contentBlocks[0];
      expect(block.type).toBe('artifact');
      if (block.type === 'artifact') {
        expect(block.artifact.status).toBe('ready');
        expect(block.artifact.content).toBe('print("hi")');
      }
    });

    test('should update existing artifact block without appending a new one', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.updateArtifactBlock({
          ...streamingArtifact,
          status: 'ready',
          sizeBytes: 11,
          lineCount: 1,
          content: 'print("hi")',
        });
      });

      expect(result.current.contentBlocks).toEqual([]);

      act(() => {
        result.current.addArtifactBlock(streamingArtifact);
        result.current.updateArtifactBlock({
          ...streamingArtifact,
          status: 'ready',
          sizeBytes: 11,
          lineCount: 1,
          content: 'print("hi")',
        });
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      const block = result.current.contentBlocks[0];
      expect(block.type).toBe('artifact');
      if (block.type === 'artifact') {
        expect(block.artifact.status).toBe('ready');
        expect(block.artifact.content).toBe('print("hi")');
      }
    });

    test('should mark artifact as deleted', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.addArtifactBlock({
          ...streamingArtifact,
          status: 'ready',
          sizeBytes: 11,
          lineCount: 1,
          content: 'print("hi")',
        });
        result.current.markArtifactDeleted('artifact-1');
      });

      const block = result.current.contentBlocks[0];
      expect(block.type).toBe('artifact');
      if (block.type === 'artifact') {
        expect(block.artifact.status).toBe('deleted');
        expect(block.artifact.content).toBeUndefined();
      }
    });
  });

  describe('terminal block management', () => {
    test('should add terminal block', () => {
      const { result } = renderHook(() => useChatState());

      const terminal: TerminalCommandBlock = {
        requestId: 'req-1',
        command: 'ls -la',
        cwd: '/home/user',
        status: 'running',
        output: '',
        outputChunks: [],
        isPty: false,
      };

      act(() => {
        result.current.addTerminalBlock(terminal);
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0].type).toBe('terminal_command');
    });

    test('should update terminal block', () => {
      const { result } = renderHook(() => useChatState());

      const terminal: TerminalCommandBlock = {
        requestId: 'req-1',
        command: 'ls -la',
        cwd: '/home/user',
        status: 'running',
        output: '',
        outputChunks: [],
        isPty: false,
      };

      act(() => {
        result.current.addTerminalBlock(terminal);
      });

      act(() => {
        result.current.updateTerminalBlock('req-1', { status: 'completed', exitCode: 0 });
      });

      const block = result.current.contentBlocks[0];
      if (block.type === 'terminal_command') {
        expect(block.terminal.status).toBe('completed');
        expect(block.terminal.exitCode).toBe(0);
      }
    });

    test('should append terminal output', () => {
      const { result } = renderHook(() => useChatState());

      const terminal: TerminalCommandBlock = {
        requestId: 'req-1',
        command: 'ls -la',
        cwd: '/home/user',
        status: 'running',
        output: '',
        outputChunks: [],
        isPty: false,
      };

      act(() => {
        result.current.addTerminalBlock(terminal);
      });

      act(() => {
        result.current.appendTerminalOutput('req-1', 'file1.txt');
        result.current.appendTerminalOutput('req-1', 'file2.txt');
      });

      const block = result.current.contentBlocks[0];
      if (block.type === 'terminal_command') {
        expect(block.terminal.output).toBe('file1.txt\nfile2.txt\n');
        expect(block.terminal.outputChunks).toHaveLength(2);
      }
    });

    test('should mark terminal as PTY on raw output', () => {
      const { result } = renderHook(() => useChatState());

      const terminal: TerminalCommandBlock = {
        requestId: 'req-1',
        command: 'vim',
        cwd: '/home/user',
        status: 'running',
        output: '',
        outputChunks: [],
        isPty: false,
      };

      act(() => {
        result.current.addTerminalBlock(terminal);
      });

      act(() => {
        result.current.appendTerminalOutput('req-1', '\x1b[2J', true); // raw ANSI escape
      });

      const block = result.current.contentBlocks[0];
      if (block.type === 'terminal_command') {
        expect(block.terminal.isPty).toBe(true);
      }
    });
  });

  describe('YouTube approval block management', () => {
    test('should add YouTube approval block', () => {
      const { result } = renderHook(() => useChatState());

      const approval: YouTubeTranscriptionApprovalBlock = {
        requestId: 'yt-req-1',
        title: 'Test Video',
        channel: 'Test Channel',
        duration: '10:00',
        url: 'https://youtube.com/watch?v=123',
        noCaptionsReason: 'No captions available',
        audioSizeEstimate: '15 MB',
        downloadTimeEstimate: '30s',
        transcriptionTimeEstimate: '2min',
        totalTimeEstimate: '2min 30s',
        whisperModel: 'base',
        computeBackend: 'cpu',
        status: 'pending',
      };

      act(() => {
        result.current.addYouTubeApprovalBlock(approval);
      });

      expect(result.current.contentBlocks).toHaveLength(1);
      expect(result.current.contentBlocks[0].type).toBe('youtube_transcription_approval');
    });

    test('should update YouTube approval block', () => {
      const { result } = renderHook(() => useChatState());

      const approval: YouTubeTranscriptionApprovalBlock = {
        requestId: 'yt-req-1',
        title: 'Test Video',
        channel: 'Test Channel',
        duration: '10:00',
        url: 'https://youtube.com/watch?v=123',
        noCaptionsReason: 'No captions',
        audioSizeEstimate: '15 MB',
        downloadTimeEstimate: '30s',
        transcriptionTimeEstimate: '2min',
        totalTimeEstimate: '2min 30s',
        whisperModel: 'base',
        computeBackend: 'cpu',
        status: 'pending',
      };

      act(() => {
        result.current.addYouTubeApprovalBlock(approval);
      });

      act(() => {
        result.current.updateYouTubeApprovalBlock('yt-req-1', { status: 'approved' });
      });

      const block = result.current.contentBlocks[0];
      if (block.type === 'youtube_transcription_approval') {
        expect(block.approval.status).toBe('approved');
      }
    });
  });

  describe('completeResponse', () => {
    test('should finalize streaming and add to chat history', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('What is TypeScript?');
      });

      act(() => {
        result.current.appendResponse('TypeScript is a typed superset of JavaScript.');
      });

      act(() => {
        result.current.completeResponse();
      });

      expect(result.current.chatHistory).toHaveLength(2);
      expect(result.current.chatHistory[0].role).toBe('user');
      expect(result.current.chatHistory[0].content).toBe('What is TypeScript?');
      expect(result.current.chatHistory[1].role).toBe('assistant');
      expect(result.current.chatHistory[1].content).toBe('TypeScript is a typed superset of JavaScript.');
    });

    test('should clear streaming state after completion', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
        result.current.completeResponse();
      });

      expect(result.current.response).toBe('');
      expect(result.current.responseRef.current).toBe('');
      expect(result.current.currentQuery).toBe('');
      expect(result.current.isThinking).toBe(false);
      expect(result.current.canSubmit).toBe(true);
      expect(result.current.status).toBe('Ready for follow-up question.');
    });

    test('should include attached images in user message', () => {
      const { result } = renderHook(() => useChatState());

      const images = [
        { name: 'screenshot.png', thumbnail: 'data:image/png;base64,abc' },
      ];

      act(() => {
        result.current.startQuery('Analyze this image');
        result.current.appendResponse('I see an image');
        result.current.completeResponse(images);
      });

      expect(result.current.chatHistory[0].images).toEqual(images);
    });

    test('should include model in assistant message', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
        result.current.completeResponse(undefined, 'gpt-4');
      });

      expect(result.current.chatHistory[1].model).toBe('gpt-4');
    });

    test('should include tool calls in assistant message', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Search for something');
      });

      const toolCall: ToolCall = {
        name: 'search',
        args: { query: 'test' },
        server: 'mcp-server',
        status: 'complete',
        result: 'Found results',
      };

      act(() => {
        result.current.addToolCall(toolCall);
        result.current.appendResponse('Based on the search...');
        result.current.completeResponse();
      });

      expect(result.current.chatHistory[1].toolCalls).toHaveLength(1);
      expect(result.current.chatHistory[1].contentBlocks).toBeDefined();
    });

    test('should not add empty messages if nothing was generated', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        // No response, thinking, or tool calls
        result.current.completeResponse();
      });

      expect(result.current.chatHistory).toHaveLength(0);
    });

    test('should persist artifact-only responses into chat history', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Build a file');
        result.current.addArtifactBlock({
          artifactId: 'artifact-1',
          artifactType: 'code',
          title: 'demo.py',
          language: 'python',
          sizeBytes: 0,
          lineCount: 0,
          status: 'streaming',
        });
        result.current.completeArtifactBlock({
          artifactId: 'artifact-1',
          artifactType: 'code',
          title: 'demo.py',
          language: 'python',
          sizeBytes: 11,
          lineCount: 1,
          status: 'ready',
          content: 'print("hi")',
        });
        result.current.completeResponse(undefined, 'gpt-4.1');
      });

      expect(result.current.chatHistory).toHaveLength(2);
      expect(result.current.chatHistory[0].content).toBe('Build a file');
      expect(result.current.chatHistory[1].content).toBe('');
      expect(result.current.chatHistory[1].contentBlocks?.[0]).toEqual({
        type: 'artifact',
        artifact: {
          artifactId: 'artifact-1',
          artifactType: 'code',
          title: 'demo.py',
          language: 'python',
          sizeBytes: 11,
          lineCount: 1,
          status: 'ready',
          content: 'print("hi")',
        },
      });
      expect(result.current.chatHistory[1].responseVersions?.[0].contentBlocks?.[0]).toEqual({
        type: 'artifact',
        artifact: {
          artifactId: 'artifact-1',
          artifactType: 'code',
          title: 'demo.py',
          language: 'python',
          sizeBytes: 11,
          lineCount: 1,
          status: 'ready',
          content: 'print("hi")',
        },
      });
    });

    test('should include response versions', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
        result.current.completeResponse(undefined, 'claude-3');
      });

      const assistantMessage = result.current.chatHistory[1];
      expect(assistantMessage.responseVersions).toBeDefined();
      expect(assistantMessage.responseVersions).toHaveLength(1);
      expect(assistantMessage.responseVersions![0].responseIndex).toBe(0);
      expect(assistantMessage.responseVersions![0].model).toBe('claude-3');
    });
  });

  describe('clearStreamingState', () => {
    test('should reset streaming state with default status', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
        result.current.appendThinking('Thinking');
      });

      act(() => {
        result.current.clearStreamingState();
      });

      expect(result.current.response).toBe('');
      expect(result.current.thinking).toBe('');
      expect(result.current.currentQuery).toBe('');
      expect(result.current.isThinking).toBe(false);
      expect(result.current.toolCalls).toEqual([]);
      expect(result.current.contentBlocks).toEqual([]);
      expect(result.current.canSubmit).toBe(true);
      expect(result.current.status).toBe('Ready for follow-up question.');
    });

    test('should accept custom status message', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.clearStreamingState('Custom status');
      });

      expect(result.current.status).toBe('Custom status');
    });

    test('should reset refs as well', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
      });

      act(() => {
        result.current.clearStreamingState();
      });

      expect(result.current.currentQueryRef.current).toBe('');
      expect(result.current.responseRef.current).toBe('');
      expect(result.current.thinkingRef.current).toBe('');
      expect(result.current.toolCallsRef.current).toEqual([]);
      expect(result.current.contentBlocksRef.current).toEqual([]);
    });
  });

  describe('resetForNewChat', () => {
    test('should reset all state for new conversation', () => {
      const { result } = renderHook(() => useChatState());

      // Set up some state
      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
        result.current.completeResponse();
        result.current.setConversationId('conv-123');
        result.current.setError('Some error');
      });

      // Reset
      act(() => {
        result.current.resetForNewChat();
      });

      expect(result.current.chatHistory).toEqual([]);
      expect(result.current.response).toBe('');
      expect(result.current.thinking).toBe('');
      expect(result.current.isThinking).toBe(false);
      expect(result.current.thinkingCollapsed).toBe(true);
      expect(result.current.toolCalls).toEqual([]);
      expect(result.current.contentBlocks).toEqual([]);
      expect(result.current.error).toBe('');
      expect(result.current.query).toBe('');
      expect(result.current.currentQuery).toBe('');
      expect(result.current.canSubmit).toBe(true);
      expect(result.current.conversationId).toBeNull();
      expect(result.current.status).toBe('Context cleared. Ready for new conversation.');
    });

    test('should reset all refs', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
      });

      act(() => {
        result.current.resetForNewChat();
      });

      expect(result.current.currentQueryRef.current).toBe('');
      expect(result.current.responseRef.current).toBe('');
      expect(result.current.thinkingRef.current).toBe('');
      expect(result.current.toolCallsRef.current).toEqual([]);
      expect(result.current.contentBlocksRef.current).toEqual([]);
    });
  });

  describe('loadConversation', () => {
    test('should load conversation with messages', () => {
      const { result } = renderHook(() => useChatState());

      const messages = [
        { role: 'user' as const, content: 'Hello', timestamp: Date.now() },
        { role: 'assistant' as const, content: 'Hi there!', timestamp: Date.now() },
      ];

      act(() => {
        result.current.loadConversation('conv-456', messages);
      });

      expect(result.current.conversationId).toBe('conv-456');
      expect(result.current.chatHistory).toEqual(messages);
      expect(result.current.response).toBe('');
      expect(result.current.thinking).toBe('');
      expect(result.current.currentQuery).toBe('');
      expect(result.current.status).toBe('Conversation loaded. Ask a follow-up question.');
      expect(result.current.canSubmit).toBe(true);
    });

    test('should reset refs when loading conversation', () => {
      const { result } = renderHook(() => useChatState());

      // Set some streaming state
      act(() => {
        result.current.startQuery('Test');
        result.current.appendResponse('Response');
      });

      // Load conversation
      act(() => {
        result.current.loadConversation('conv-789', []);
      });

      expect(result.current.currentQueryRef.current).toBe('');
      expect(result.current.responseRef.current).toBe('');
      expect(result.current.thinkingRef.current).toBe('');
    });
  });

  describe('getSnapshot / restoreSnapshot', () => {
    test('should capture current state as snapshot', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Test query');
        result.current.appendResponse('Test response');
        result.current.appendThinking('Test thinking');
        result.current.setStatus('Processing...');
        result.current.setError('Test error');
        result.current.setConversationId('conv-123');
      });

      let snapshot: ChatStateSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      expect(snapshot!.currentQuery).toBe('Test query');
      expect(snapshot!.response).toBe('Test response');
      expect(snapshot!.thinking).toBe('Test thinking');
      expect(snapshot!.isThinking).toBe(true);
      expect(snapshot!.status).toBe('Processing...');
      expect(snapshot!.error).toBe('Test error');
      expect(snapshot!.conversationId).toBe('conv-123');
      expect(snapshot!.contentBlocks.length).toBeGreaterThan(0);
    });

    test('should restore state from snapshot', () => {
      const { result } = renderHook(() => useChatState());

      const snapshot: ChatStateSnapshot = {
        chatHistory: [
          { role: 'user', content: 'Hello', timestamp: Date.now() },
          { role: 'assistant', content: 'Hi!', timestamp: Date.now() },
        ],
        currentQuery: 'Restored query',
        response: 'Restored response',
        thinking: 'Restored thinking',
        isThinking: true,
        thinkingCollapsed: false,
        toolCalls: [{ name: 'tool', args: {}, server: 'server' }],
        contentBlocks: [{ type: 'text', content: 'Restored content' }],
        conversationId: 'restored-conv',
        query: 'Restored input',
        canSubmit: false,
        status: 'Restored status',
        error: 'Restored error',
      };

      act(() => {
        result.current.restoreSnapshot(snapshot);
      });

      expect(result.current.chatHistory).toEqual(snapshot.chatHistory);
      expect(result.current.currentQuery).toBe('Restored query');
      expect(result.current.response).toBe('Restored response');
      expect(result.current.thinking).toBe('Restored thinking');
      expect(result.current.isThinking).toBe(true);
      expect(result.current.thinkingCollapsed).toBe(false);
      expect(result.current.toolCalls).toEqual(snapshot.toolCalls);
      expect(result.current.contentBlocks).toEqual(snapshot.contentBlocks);
      expect(result.current.conversationId).toBe('restored-conv');
      expect(result.current.query).toBe('Restored input');
      expect(result.current.canSubmit).toBe(false);
      expect(result.current.status).toBe('Restored status');
      expect(result.current.error).toBe('Restored error');
    });

    test('should restore refs as well as state', () => {
      const { result } = renderHook(() => useChatState());

      const snapshot: ChatStateSnapshot = {
        chatHistory: [],
        currentQuery: 'Ref query',
        response: 'Ref response',
        thinking: 'Ref thinking',
        isThinking: false,
        thinkingCollapsed: true,
        toolCalls: [{ name: 'ref_tool', args: {}, server: 'server' }],
        contentBlocks: [{ type: 'text', content: 'Ref content' }],
        conversationId: null,
        query: '',
        canSubmit: true,
        status: 'Ready',
        error: '',
      };

      act(() => {
        result.current.restoreSnapshot(snapshot);
      });

      expect(result.current.currentQueryRef.current).toBe('Ref query');
      expect(result.current.responseRef.current).toBe('Ref response');
      expect(result.current.thinkingRef.current).toBe('Ref thinking');
      expect(result.current.toolCallsRef.current).toEqual(snapshot.toolCalls);
      expect(result.current.contentBlocksRef.current).toEqual(snapshot.contentBlocks);
    });

    test('snapshot and restore should be symmetric', () => {
      const { result } = renderHook(() => useChatState());

      // Set up some state
      act(() => {
        result.current.startQuery('Original query');
        result.current.appendResponse('Original response');
        result.current.addToolCall({ name: 'tool1', args: { a: 1 }, server: 'srv' });
        result.current.setConversationId('conv-sym');
      });

      // Take snapshot
      let snapshot: ChatStateSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      // Reset state
      act(() => {
        result.current.resetForNewChat();
      });

      // Verify reset
      expect(result.current.currentQuery).toBe('');
      expect(result.current.response).toBe('');

      // Restore snapshot
      act(() => {
        result.current.restoreSnapshot(snapshot!);
      });

      // Verify restoration
      expect(result.current.currentQuery).toBe('Original query');
      expect(result.current.response).toBe('Original response');
      expect(result.current.conversationId).toBe('conv-sym');
      expect(result.current.toolCalls).toHaveLength(1);
    });
  });

  describe('state setters', () => {
    test('setQuery should update query state', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.setQuery('New query text');
      });

      expect(result.current.query).toBe('New query text');
    });

    test('setCanSubmit should update canSubmit state', () => {
      const { result } = renderHook(() => useChatState());

      expect(result.current.canSubmit).toBe(false);

      act(() => {
        result.current.setCanSubmit(true);
      });

      expect(result.current.canSubmit).toBe(true);
    });

    test('setStatus should update status', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.setStatus('New status message');
      });

      expect(result.current.status).toBe('New status message');
    });

    test('setError should update error', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.setError('Something went wrong');
      });

      expect(result.current.error).toBe('Something went wrong');
    });

    test('setThinkingCollapsed should update thinking collapsed state', () => {
      const { result } = renderHook(() => useChatState());

      expect(result.current.thinkingCollapsed).toBe(true);

      act(() => {
        result.current.setThinkingCollapsed(false);
      });

      expect(result.current.thinkingCollapsed).toBe(false);
    });

    test('setIsThinking should update isThinking state', () => {
      const { result } = renderHook(() => useChatState());

      expect(result.current.isThinking).toBe(false);

      act(() => {
        result.current.setIsThinking(true);
      });

      expect(result.current.isThinking).toBe(true);
    });

    test('setChatHistory should update chat history', () => {
      const { result } = renderHook(() => useChatState());

      const newHistory = [
        { role: 'user' as const, content: 'Direct set', timestamp: Date.now() },
      ];

      act(() => {
        result.current.setChatHistory(newHistory);
      });

      expect(result.current.chatHistory).toEqual(newHistory);
    });

    test('setConversationId should update conversation ID', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.setConversationId('new-conv-id');
      });

      expect(result.current.conversationId).toBe('new-conv-id');
    });
  });

  describe('dual ref+state pattern', () => {
    test('refs should stay in sync with state during streaming', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.startQuery('Query');
      });

      // Simulate streaming chunks
      act(() => {
        result.current.appendResponse('Chunk 1 ');
      });

      expect(result.current.response).toBe('Chunk 1 ');
      expect(result.current.responseRef.current).toBe('Chunk 1 ');

      act(() => {
        result.current.appendResponse('Chunk 2');
      });

      expect(result.current.response).toBe('Chunk 1 Chunk 2');
      expect(result.current.responseRef.current).toBe('Chunk 1 Chunk 2');
    });

    test('refs should be accessible synchronously without re-render', () => {
      const { result } = renderHook(() => useChatState());

      // Refs should be accessible immediately
      expect(result.current.responseRef.current).toBe('');

      act(() => {
        result.current.appendResponse('Test');
        // Within the same act, ref should be updated
        expect(result.current.responseRef.current).toBe('Test');
      });
    });

    test('tool calls ref should track all additions', () => {
      const { result } = renderHook(() => useChatState());

      const tc1: ToolCall = { name: 't1', args: {}, server: 's' };
      const tc2: ToolCall = { name: 't2', args: {}, server: 's' };

      act(() => {
        result.current.addToolCall(tc1);
      });

      expect(result.current.toolCallsRef.current).toHaveLength(1);

      act(() => {
        result.current.addToolCall(tc2);
      });

      expect(result.current.toolCallsRef.current).toHaveLength(2);
      expect(result.current.toolCalls).toHaveLength(2);
    });
  });

  describe('content block interleaving', () => {
    test('should correctly interleave thinking, text, and tool calls', () => {
      const { result } = renderHook(() => useChatState());

      act(() => {
        result.current.appendThinking('Let me analyze...');
      });

      act(() => {
        result.current.addToolCall({
          name: 'search',
          args: { q: 'test' },
          server: 'srv',
        });
      });

      act(() => {
        result.current.appendResponse('Based on search results...');
      });

      act(() => {
        result.current.addToolCall({
          name: 'fetch',
          args: { url: 'test' },
          server: 'srv',
        });
      });

      act(() => {
        result.current.appendResponse(' Final conclusion.');
      });

      const blocks = result.current.contentBlocks;
      expect(blocks).toHaveLength(5);
      expect(blocks[0].type).toBe('thinking');
      expect(blocks[1].type).toBe('tool_call');
      expect(blocks[2].type).toBe('text');
      expect(blocks[3].type).toBe('tool_call');
      expect(blocks[4].type).toBe('text');

      // Text is grouped contiguously; adding a tool call starts a new text block.
      if (blocks[2].type === 'text') {
        expect(blocks[2].content).toBe('Based on search results...');
      }
      if (blocks[4].type === 'text') {
        expect(blocks[4].content).toBe(' Final conclusion.');
      }
    });
  });
});
