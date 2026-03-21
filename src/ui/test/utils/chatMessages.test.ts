import { describe, expect, test } from 'vitest';

import type { ChatMessage, ContentBlock, ToolCall } from '../../types';
import {
  applyResponseVariant,
  applySavedTurnToHistory,
  buildRenderableContentBlocks,
  formatMessageTimestamp,
  mapConversationContentBlock,
  mapConversationMessagePayload,
  mergeMessageMetadata,
  normalizeTimestamp,
  serializeMessageForCopy,
} from '../../utils/chatMessages';

// ============================================
// normalizeTimestamp Tests
// ============================================
describe('normalizeTimestamp', () => {
  test('returns undefined for undefined input', () => {
    expect(normalizeTimestamp(undefined)).toBeUndefined();
  });

  test('returns undefined for NaN input', () => {
    expect(normalizeTimestamp(NaN)).toBeUndefined();
  });

  test('converts seconds-based timestamp to milliseconds', () => {
    const secondsTimestamp = 1700000000;
    expect(normalizeTimestamp(secondsTimestamp)).toBe(1700000000000);
  });

  test('keeps milliseconds-based timestamp unchanged', () => {
    const msTimestamp = 1700000000000;
    expect(normalizeTimestamp(msTimestamp)).toBe(1700000000000);
  });

  test('handles boundary value correctly', () => {
    // Exactly 1_000_000_000_000 is already ms
    expect(normalizeTimestamp(1_000_000_000_000)).toBe(1_000_000_000_000);
    // Just below threshold is seconds
    expect(normalizeTimestamp(999_999_999_999)).toBe(999_999_999_999_000);
  });
});

// ============================================
// formatMessageTimestamp Tests
// ============================================
describe('formatMessageTimestamp', () => {
  test('returns empty string for undefined timestamp', () => {
    expect(formatMessageTimestamp(undefined)).toBe('');
  });

  test('returns empty string for NaN timestamp', () => {
    expect(formatMessageTimestamp(NaN)).toBe('');
  });

  test('formats valid timestamp correctly', () => {
    const timestamp = 1700000000000;
    const result = formatMessageTimestamp(timestamp);
    // Should return a time string in format like "12:34 AM/PM"
    expect(result).toMatch(/^\d{1,2}:\d{2}\s?(AM|PM)$/i);
  });

  test('normalizes seconds timestamp before formatting', () => {
    const secondsTimestamp = 1700000000;
    const result = formatMessageTimestamp(secondsTimestamp);
    expect(result).toMatch(/^\d{1,2}:\d{2}\s?(AM|PM)$/i);
  });
});

// ============================================
// mapConversationContentBlock Tests
// ============================================
describe('mapConversationContentBlock', () => {
  test('maps text block correctly', () => {
    expect(
      mapConversationContentBlock({
        type: 'text',
        content: 'Hello world',
      }),
    ).toEqual({
      type: 'text',
      content: 'Hello world',
    });
  });

  test('maps text block with missing content to empty string', () => {
    expect(
      mapConversationContentBlock({
        type: 'text',
      }),
    ).toEqual({
      type: 'text',
      content: '',
    });
  });

  test('maps thinking block correctly', () => {
    expect(
      mapConversationContentBlock({
        type: 'thinking',
        content: 'Plan the answer first.',
      }),
    ).toEqual({
      type: 'thinking',
      content: 'Plan the answer first.',
    });
  });

  test('maps thinking block with missing content to empty string', () => {
    expect(
      mapConversationContentBlock({
        type: 'thinking',
      }),
    ).toEqual({
      type: 'thinking',
      content: '',
    });
  });

  test('maps tool_call block correctly', () => {
    expect(
      mapConversationContentBlock({
        type: 'tool_call',
        name: 'read_file',
        args: { path: '/test.txt' },
        result: 'File contents here',
        server: 'filesystem',
      }),
    ).toEqual({
      type: 'tool_call',
      toolCall: {
        name: 'read_file',
        args: { path: '/test.txt' },
        result: 'File contents here',
        server: 'filesystem',
        status: 'complete',
      },
    });
  });

  test('maps tool_call block with missing fields to defaults', () => {
    expect(
      mapConversationContentBlock({
        type: 'tool_call',
      }),
    ).toEqual({
      type: 'tool_call',
      toolCall: {
        name: '',
        args: {},
        result: undefined,
        server: '',
        status: 'complete',
      },
    });
  });

  test('maps terminal_command block with snake_case fields', () => {
    expect(
      mapConversationContentBlock({
        type: 'terminal_command',
        request_id: 'req-123',
        command: 'ls -la',
        cwd: '/home/user',
        status: 'completed',
        output: 'file1.txt\nfile2.txt',
        output_chunks: [{ text: 'file1.txt', raw: false }],
        is_pty: true,
        exit_code: 0,
        duration_ms: 150,
        timed_out: false,
      }),
    ).toEqual({
      type: 'terminal_command',
      terminal: {
        requestId: 'req-123',
        command: 'ls -la',
        cwd: '/home/user',
        status: 'completed',
        output: 'file1.txt\nfile2.txt',
        outputChunks: [{ text: 'file1.txt', raw: false }],
        isPty: true,
        exitCode: 0,
        durationMs: 150,
        timedOut: false,
      },
    });
  });

  test('maps terminal_command block with camelCase fields', () => {
    expect(
      mapConversationContentBlock({
        type: 'terminal_command',
        requestId: 'req-456',
        command: 'echo hello',
        cwd: '/tmp',
        status: 'running',
        output: 'hello',
        outputChunks: [],
        isPty: false,
        exitCode: undefined,
        durationMs: undefined,
        timedOut: undefined,
      }),
    ).toEqual({
      type: 'terminal_command',
      terminal: {
        requestId: 'req-456',
        command: 'echo hello',
        cwd: '/tmp',
        status: 'running',
        output: 'hello',
        outputChunks: [],
        isPty: false,
        exitCode: undefined,
        durationMs: undefined,
        timedOut: undefined,
      },
    });
  });

  test('maps terminal_command block with minimal fields', () => {
    expect(
      mapConversationContentBlock({
        type: 'terminal_command',
      }),
    ).toEqual({
      type: 'terminal_command',
      terminal: {
        requestId: '',
        command: '',
        cwd: '',
        status: 'completed',
        output: '',
        outputChunks: [],
        isPty: false,
        exitCode: undefined,
        durationMs: undefined,
        timedOut: undefined,
      },
    });
  });

  test('maps youtube_transcription_approval block correctly', () => {
    expect(
      mapConversationContentBlock({
        type: 'youtube_transcription_approval',
        request_id: 'yt-req-123',
        title: 'Test Video',
        channel: 'Test Channel',
        duration: '10:30',
        duration_seconds: 630,
        url: 'https://youtube.com/watch?v=abc123',
        no_captions_reason: 'No auto-generated captions',
        audio_size_estimate: '15MB',
        audio_size_bytes: 15728640,
        download_time_estimate: '2 minutes',
        transcription_time_estimate: '5 minutes',
        total_time_estimate: '7 minutes',
        whisper_model: 'base',
        compute_backend: 'cpu',
        playlist_note: 'Part of playlist',
        status: 'pending',
      }),
    ).toEqual({
      type: 'youtube_transcription_approval',
      approval: {
        requestId: 'yt-req-123',
        title: 'Test Video',
        channel: 'Test Channel',
        duration: '10:30',
        durationSeconds: 630,
        url: 'https://youtube.com/watch?v=abc123',
        noCaptionsReason: 'No auto-generated captions',
        audioSizeEstimate: '15MB',
        audioSizeBytes: 15728640,
        downloadTimeEstimate: '2 minutes',
        transcriptionTimeEstimate: '5 minutes',
        totalTimeEstimate: '7 minutes',
        whisperModel: 'base',
        computeBackend: 'cpu',
        playlistNote: 'Part of playlist',
        status: 'pending',
      },
    });
  });

  test('maps youtube_transcription_approval with approved status', () => {
    const result = mapConversationContentBlock({
      type: 'youtube_transcription_approval',
      status: 'approved',
    });
    expect(result.type).toBe('youtube_transcription_approval');
    if (result.type === 'youtube_transcription_approval') {
      expect(result.approval.status).toBe('approved');
    }
  });

  test('maps youtube_transcription_approval with denied status', () => {
    const result = mapConversationContentBlock({
      type: 'youtube_transcription_approval',
      status: 'denied',
    });
    expect(result.type).toBe('youtube_transcription_approval');
    if (result.type === 'youtube_transcription_approval') {
      expect(result.approval.status).toBe('denied');
    }
  });

  test('maps unknown type to text block', () => {
    expect(
      mapConversationContentBlock({
        type: 'unknown_type',
        content: 'Some content',
      }),
    ).toEqual({
      type: 'text',
      content: 'Some content',
    });
  });
});

// ============================================
// buildRenderableContentBlocks Tests
// ============================================
describe('buildRenderableContentBlocks', () => {
  test('returns existing contentBlocks if present', () => {
    const existingBlocks: ContentBlock[] = [
      { type: 'text', content: 'Existing block' },
    ];
    expect(
      buildRenderableContentBlocks({
        content: 'This should be ignored',
        contentBlocks: existingBlocks,
      }),
    ).toBe(existingBlocks);
  });

  test('returns undefined for empty existing contentBlocks', () => {
    expect(
      buildRenderableContentBlocks({
        content: '',
        contentBlocks: [],
      }),
    ).toBeUndefined();
  });

  test('builds fallback blocks with thinking before text', () => {
    expect(
      buildRenderableContentBlocks({
        content: 'Final answer.',
        thinking: 'Inspect the request.',
        toolCalls: [],
      }),
    ).toEqual([
      { type: 'thinking', content: 'Inspect the request.' },
      { type: 'text', content: 'Final answer.' },
    ]);
  });

  test('builds fallback blocks with tool calls', () => {
    const toolCalls: ToolCall[] = [
      { name: 'read_file', args: { path: '/test.txt' }, server: 'filesystem', status: 'complete' },
    ];
    expect(
      buildRenderableContentBlocks({
        content: 'Here is the file content.',
        toolCalls,
      }),
    ).toEqual([
      { type: 'tool_call', toolCall: toolCalls[0] },
      { type: 'text', content: 'Here is the file content.' },
    ]);
  });

  test('builds fallback blocks with thinking, tool calls, and text', () => {
    const toolCalls: ToolCall[] = [
      { name: 'search', args: { query: 'test' }, server: 'websearch', status: 'complete' },
    ];
    expect(
      buildRenderableContentBlocks({
        content: 'Search results.',
        thinking: 'Let me search for that.',
        toolCalls,
      }),
    ).toEqual([
      { type: 'thinking', content: 'Let me search for that.' },
      { type: 'tool_call', toolCall: toolCalls[0] },
      { type: 'text', content: 'Search results.' },
    ]);
  });

  test('builds fallback blocks with multiple tool calls', () => {
    const toolCalls: ToolCall[] = [
      { name: 'read_file', args: { path: '/a.txt' }, server: 'filesystem', status: 'complete' },
      { name: 'read_file', args: { path: '/b.txt' }, server: 'filesystem', status: 'complete' },
    ];
    expect(
      buildRenderableContentBlocks({
        content: 'Both files read.',
        toolCalls,
      }),
    ).toEqual([
      { type: 'tool_call', toolCall: toolCalls[0] },
      { type: 'tool_call', toolCall: toolCalls[1] },
      { type: 'text', content: 'Both files read.' },
    ]);
  });

  test('returns undefined for empty message', () => {
    expect(
      buildRenderableContentBlocks({
        content: '',
      }),
    ).toBeUndefined();
  });

  test('returns undefined for whitespace-only message', () => {
    expect(
      buildRenderableContentBlocks({
        content: '   \n\t  ',
      }),
    ).toBeUndefined();
  });

  test('ignores whitespace-only thinking', () => {
    expect(
      buildRenderableContentBlocks({
        content: 'Answer',
        thinking: '   ',
      }),
    ).toEqual([{ type: 'text', content: 'Answer' }]);
  });

  test('handles only thinking with no content', () => {
    expect(
      buildRenderableContentBlocks({
        content: '',
        thinking: 'Thinking only',
      }),
    ).toEqual([{ type: 'thinking', content: 'Thinking only' }]);
  });

  test('handles only tool calls with no content', () => {
    const toolCalls: ToolCall[] = [
      { name: 'test', args: {}, server: 'demo', status: 'complete' },
    ];
    expect(
      buildRenderableContentBlocks({
        content: '',
        toolCalls,
      }),
    ).toEqual([{ type: 'tool_call', toolCall: toolCalls[0] }]);
  });
});

// ============================================
// serializeMessageForCopy Tests
// ============================================
describe('serializeMessageForCopy', () => {
  test('serializes text content blocks', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: 'Fallback content',
        contentBlocks: [
          { type: 'text', content: 'First paragraph.' },
          { type: 'text', content: 'Second paragraph.' },
        ],
      }),
    ).toBe('First paragraph.\n\nSecond paragraph.');
  });

  test('serializes thinking blocks', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: 'Final answer.',
        contentBlocks: [
          { type: 'thinking', content: 'Inspect the request.' },
          { type: 'text', content: 'Final answer.' },
        ],
      }),
    ).toBe('Inspect the request.\n\nFinal answer.');
  });

  test('serializes tool call blocks without result', () => {
    const toolCall: ToolCall = {
      name: 'read_file',
      args: { path: '/test.txt' },
      server: 'filesystem',
      status: 'complete',
    };
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [{ type: 'tool_call', toolCall }],
      }),
    ).toBe('[Tool: read_file]');
  });

  test('serializes tool call blocks with result', () => {
    const toolCall: ToolCall = {
      name: 'read_file',
      args: { path: '/test.txt' },
      result: 'File contents here',
      server: 'filesystem',
      status: 'complete',
    };
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [{ type: 'tool_call', toolCall }],
      }),
    ).toBe('[Tool: read_file]\nFile contents here');
  });

  test('serializes terminal command blocks', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [
          {
            type: 'terminal_command',
            terminal: {
              requestId: 'req-1',
              command: 'ls -la',
              cwd: '/home',
              status: 'completed',
              output: 'file1.txt\nfile2.txt',
              outputChunks: [],
              isPty: false,
            },
          },
        ],
      }),
    ).toBe('$ ls -la\nfile1.txt\nfile2.txt');
  });

  test('serializes terminal command blocks with empty output', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [
          {
            type: 'terminal_command',
            terminal: {
              requestId: 'req-1',
              command: 'touch newfile.txt',
              cwd: '/home',
              status: 'completed',
              output: '',
              outputChunks: [],
              isPty: false,
            },
          },
        ],
      }),
    ).toBe('$ touch newfile.txt');
  });

  test('serializes terminal command blocks with whitespace-only output', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [
          {
            type: 'terminal_command',
            terminal: {
              requestId: 'req-1',
              command: 'echo',
              cwd: '/home',
              status: 'completed',
              output: '   \n\t  ',
              outputChunks: [],
              isPty: false,
            },
          },
        ],
      }),
    ).toBe('$ echo');
  });

  test('serializes youtube transcription approval - pending', () => {
    const result = serializeMessageForCopy({
      role: 'assistant',
      content: '',
      contentBlocks: [
        {
          type: 'youtube_transcription_approval',
          approval: {
            requestId: 'yt-1',
            title: 'Test Video',
            channel: 'Test Channel',
            duration: '10:30',
            url: 'https://youtube.com/watch?v=abc',
            noCaptionsReason: '',
            audioSizeEstimate: '15MB',
            downloadTimeEstimate: '2 min',
            transcriptionTimeEstimate: '5 min',
            totalTimeEstimate: '7 min',
            whisperModel: 'base',
            computeBackend: 'cpu',
            status: 'pending',
          },
        },
      ],
    });
    expect(result).toContain('[YouTube transcription approval: Pending]');
    expect(result).toContain('Title: Test Video');
    expect(result).toContain('Channel: Test Channel');
    expect(result).toContain('Duration: 10:30');
  });

  test('serializes youtube transcription approval - approved', () => {
    const result = serializeMessageForCopy({
      role: 'assistant',
      content: '',
      contentBlocks: [
        {
          type: 'youtube_transcription_approval',
          approval: {
            requestId: 'yt-1',
            title: 'Test',
            channel: 'Channel',
            duration: '5:00',
            url: 'https://youtube.com/watch?v=xyz',
            noCaptionsReason: '',
            audioSizeEstimate: '10MB',
            downloadTimeEstimate: '1 min',
            transcriptionTimeEstimate: '3 min',
            totalTimeEstimate: '4 min',
            whisperModel: 'tiny',
            computeBackend: 'gpu',
            status: 'approved',
          },
        },
      ],
    });
    expect(result).toContain('[YouTube transcription approval: Approved]');
  });

  test('serializes youtube transcription approval - denied', () => {
    const result = serializeMessageForCopy({
      role: 'assistant',
      content: '',
      contentBlocks: [
        {
          type: 'youtube_transcription_approval',
          approval: {
            requestId: 'yt-1',
            title: 'Test',
            channel: 'Channel',
            duration: '5:00',
            url: 'https://youtube.com/watch?v=xyz',
            noCaptionsReason: '',
            audioSizeEstimate: '10MB',
            downloadTimeEstimate: '1 min',
            transcriptionTimeEstimate: '3 min',
            totalTimeEstimate: '4 min',
            whisperModel: 'tiny',
            computeBackend: 'gpu',
            status: 'denied',
          },
        },
      ],
    });
    expect(result).toContain('[YouTube transcription approval: Denied]');
  });

  test('serializes mixed content blocks', () => {
    const result = serializeMessageForCopy({
      role: 'assistant',
      content: '',
      contentBlocks: [
        { type: 'thinking', content: 'Let me check the file.' },
        {
          type: 'tool_call',
          toolCall: {
            name: 'read_file',
            args: { path: '/test.txt' },
            result: 'Hello World',
            server: 'filesystem',
            status: 'complete',
          },
        },
        { type: 'text', content: 'The file contains "Hello World".' },
      ],
    });
    expect(result).toBe(
      'Let me check the file.\n\n[Tool: read_file]\nHello World\n\nThe file contains "Hello World".',
    );
  });

  test('filters out empty blocks', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '',
        contentBlocks: [
          { type: 'text', content: '' },
          { type: 'text', content: 'Valid content' },
          { type: 'thinking', content: '' },
        ],
      }),
    ).toBe('Valid content');
  });

  test('ignores unknown content block types during serialization', () => {
    const result = serializeMessageForCopy({
      role: 'assistant',
      content: '',
      contentBlocks: [
        { type: 'text', content: 'Visible' },
        { type: 'unknown' as never },
      ] as unknown as ContentBlock[],
    });

    expect(result).toBe('Visible');
  });

  test('falls back to content when no contentBlocks', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: 'Simple content',
      }),
    ).toBe('Simple content');
  });

  test('falls back to content when contentBlocks is empty', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: 'Fallback content',
        contentBlocks: [],
      }),
    ).toBe('Fallback content');
  });

  test('trims whitespace from fallback content', () => {
    expect(
      serializeMessageForCopy({
        role: 'assistant',
        content: '  Padded content  ',
      }),
    ).toBe('Padded content');
  });
});

// ============================================
// mapConversationMessagePayload Tests
// ============================================
describe('mapConversationMessagePayload', () => {
  test('maps basic user message', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-1',
      turn_id: 'turn-1',
      role: 'user',
      content: 'Hello',
      timestamp: 1700000000,
    });

    expect(result.role).toBe('user');
    expect(result.content).toBe('Hello');
    expect(result.messageId).toBe('msg-1');
    expect(result.turnId).toBe('turn-1');
    expect(result.timestamp).toBe(1700000000000);
  });

  test('maps assistant message with model', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-2',
      turn_id: 'turn-1',
      role: 'assistant',
      content: 'Hi there',
      timestamp: 1700000001000,
      model: 'gpt-4',
    });

    expect(result.role).toBe('assistant');
    expect(result.model).toBe('gpt-4');
  });

  test('maps message with string images', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-3',
      turn_id: 'turn-2',
      role: 'user',
      content: 'Look at this image',
      timestamp: 1700000002000,
      images: ['/path/to/image.png'],
    });

    expect(result.images).toEqual([{ name: 'image.png', thumbnail: '' }]);
  });

  test('maps message with object images', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-4',
      turn_id: 'turn-2',
      role: 'user',
      content: 'Look at this image',
      timestamp: 1700000002000,
      images: [{ name: 'screenshot.png', thumbnail: 'data:image/png;base64,abc123' }],
    });

    expect(result.images).toEqual([{ name: 'screenshot.png', thumbnail: 'data:image/png;base64,abc123' }]);
  });

  test('maps message with object image missing thumbnail to empty string', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-4b',
      turn_id: 'turn-2',
      role: 'user',
      content: 'Look at this image',
      timestamp: 1700000002000,
      images: [{ name: 'screenshot.png', thumbnail: null }],
    });

    expect(result.images).toEqual([{ name: 'screenshot.png', thumbnail: '' }]);
  });

  test('maps message with content_blocks', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-5',
      turn_id: 'turn-3',
      role: 'assistant',
      content: 'Response',
      timestamp: 1700000003000,
      content_blocks: [
        { type: 'thinking', content: 'Planning...' },
        { type: 'text', content: 'Response' },
      ],
    });

    expect(result.contentBlocks).toHaveLength(2);
    expect(result.contentBlocks?.[0]).toEqual({ type: 'thinking', content: 'Planning...' });
    expect(result.contentBlocks?.[1]).toEqual({ type: 'text', content: 'Response' });
  });

  test('maps message timestamp fallback when normalizeTimestamp returns undefined', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-ts',
      turn_id: 'turn-ts',
      role: 'assistant',
      content: 'NaN timestamp',
      timestamp: Number.NaN,
    });

    expect(Number.isNaN(result.timestamp)).toBe(true);
  });

  test('maps message with response_variants', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-6',
      turn_id: 'turn-4',
      role: 'assistant',
      content: 'Active response',
      timestamp: 1700000004000,
      active_response_index: 1,
      response_variants: [
        { response_index: 0, content: 'First response', timestamp: 1700000004000 },
        { response_index: 1, content: 'Second response', timestamp: 1700000005000, model: 'gpt-4' },
      ],
    });

    expect(result.activeResponseIndex).toBe(1);
    expect(result.responseVersions).toHaveLength(2);
    expect(result.responseVersions?.[0]).toEqual({
      responseIndex: 0,
      content: 'First response',
      model: undefined,
      timestamp: 1700000004000,
      contentBlocks: undefined,
    });
    expect(result.responseVersions?.[1].model).toBe('gpt-4');
  });

  test('handles empty images array', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-7',
      turn_id: 'turn-5',
      role: 'user',
      content: 'No images',
      timestamp: 1700000005000,
      images: [],
    });

    expect(result.images).toBeUndefined();
  });
});

// ============================================
// mergeMessageMetadata Tests
// ============================================
describe('mergeMessageMetadata', () => {
  test('returns persisted message when local is undefined', () => {
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Hello',
      messageId: 'msg-1',
    };
    expect(mergeMessageMetadata(undefined, persisted)).toBe(persisted);
  });

  test('merges local content into persisted', () => {
    const local: ChatMessage = {
      role: 'assistant',
      content: 'Updated content',
    };
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Original content',
      messageId: 'msg-1',
    };

    const result = mergeMessageMetadata(local, persisted);
    expect(result.content).toBe('Updated content');
    expect(result.messageId).toBe('msg-1');
  });

  test('merges local thinking into persisted', () => {
    const local: ChatMessage = {
      role: 'assistant',
      content: 'Response',
      thinking: 'Local thinking',
    };
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Response',
      messageId: 'msg-1',
    };

    const result = mergeMessageMetadata(local, persisted);
    expect(result.thinking).toBe('Local thinking');
  });

  test('prefers local images over persisted', () => {
    const local: ChatMessage = {
      role: 'user',
      content: 'Message',
      images: [{ name: 'local.png', thumbnail: 'thumb1' }],
    };
    const persisted: ChatMessage = {
      role: 'user',
      content: 'Message',
      images: [{ name: 'persisted.png', thumbnail: 'thumb2' }],
    };

    const result = mergeMessageMetadata(local, persisted);
    expect(result.images).toEqual([{ name: 'local.png', thumbnail: 'thumb1' }]);
  });

  test('merges response versions for assistant messages', () => {
    const local: ChatMessage = {
      role: 'assistant',
      content: 'Updated variant content',
      model: 'gpt-4-updated',
      timestamp: 1700000002000,
      contentBlocks: [{ type: 'text', content: 'Updated variant content' }],
    };
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      messageId: 'msg-1',
      activeResponseIndex: 0,
      responseVersions: [
        { responseIndex: 0, content: 'Original variant', timestamp: 1700000001000 },
      ],
    };

    const result = mergeMessageMetadata(local, persisted);
    expect(result.responseVersions?.[0].content).toBe('Updated variant content');
    expect(result.responseVersions?.[0].model).toBe('gpt-4-updated');
    expect(result.responseVersions?.[0].contentBlocks).toEqual([
      { type: 'text', content: 'Updated variant content' },
    ]);
  });

  test('uses persisted model when local model is empty', () => {
    const local: ChatMessage = {
      role: 'assistant',
      content: 'Response',
      model: '',
    };
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Response',
      model: 'gpt-4',
    };

    const result = mergeMessageMetadata(local, persisted);
    expect(result.model).toBe('gpt-4');
  });
});

// ============================================
// applyResponseVariant Tests
// ============================================
describe('applyResponseVariant', () => {
  test('returns undefined when variant does not exist', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Response',
      responseVersions: [],
    };
    expect(applyResponseVariant(message, 0)).toBeUndefined();
  });

  test('returns undefined when responseVersions is undefined', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Response',
    };
    expect(applyResponseVariant(message, 0)).toBeUndefined();
  });

  test('applies variant with content only', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      model: 'gpt-3.5',
      timestamp: 1700000000000,
      responseVersions: [
        { responseIndex: 0, content: 'Variant 0', timestamp: 1700000001000 },
        { responseIndex: 1, content: 'Variant 1', timestamp: 1700000002000 },
      ],
    };

    const result = applyResponseVariant(message, 1);
    expect(result?.content).toBe('Variant 1');
    expect(result?.activeResponseIndex).toBe(1);
    expect(result?.timestamp).toBe(1700000002000);
  });

  test('applies variant with model', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      model: 'gpt-3.5',
      responseVersions: [
        { responseIndex: 0, content: 'Variant', timestamp: 1700000000000, model: 'gpt-4' },
      ],
    };

    const result = applyResponseVariant(message, 0);
    expect(result?.model).toBe('gpt-4');
  });

  test('keeps original model when variant model is undefined', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      model: 'gpt-3.5',
      responseVersions: [
        { responseIndex: 0, content: 'Variant', timestamp: 1700000000000 },
      ],
    };

    const result = applyResponseVariant(message, 0);
    expect(result?.model).toBe('gpt-3.5');
  });

  test('applies variant with contentBlocks', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      toolCalls: [{ name: 'old_tool', args: {}, server: 'demo', status: 'complete' }],
      responseVersions: [
        {
          responseIndex: 0,
          content: 'Variant with blocks',
          timestamp: 1700000000000,
          contentBlocks: [{ type: 'text', content: 'Block content' }],
        },
      ],
    };

    const result = applyResponseVariant(message, 0);
    expect(result?.contentBlocks).toEqual([{ type: 'text', content: 'Block content' }]);
    expect(result?.toolCalls).toBeUndefined();
    expect(result?.thinking).toBeUndefined();
  });

  test('preserves toolCalls when variant has no contentBlocks', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'Original',
      toolCalls: [{ name: 'tool', args: {}, server: 'demo', status: 'complete' }],
      responseVersions: [
        { responseIndex: 0, content: 'Variant', timestamp: 1700000000000 },
      ],
    };

    const result = applyResponseVariant(message, 0);
    expect(result?.toolCalls).toEqual(message.toolCalls);
  });
});

// ============================================
// applySavedTurnToHistory Tests
// ============================================
describe('applySavedTurnToHistory', () => {
  const createTurn = (
    turnId: string,
    userContent: string,
    assistantContent?: string,
  ) => ({
    turn_id: turnId,
    user: {
      message_id: `${turnId}-user`,
      turn_id: turnId,
      role: 'user',
      content: userContent,
      timestamp: 1700000000000,
    },
    assistant: assistantContent
      ? {
          message_id: `${turnId}-assistant`,
          turn_id: turnId,
          role: 'assistant',
          content: assistantContent,
          timestamp: 1700000001000,
        }
      : undefined,
  });

  describe('submit operation', () => {
    test('appends new turn to empty history', () => {
      const result = applySavedTurnToHistory([], createTurn('turn-1', 'Hello', 'Hi'), 'submit');

      expect(result).toHaveLength(2);
      expect(result[0].content).toBe('Hello');
      expect(result[1].content).toBe('Hi');
    });

    test('preserves local pending content while merging persisted metadata', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'Pending user', turnId: 'turn-1' },
        { role: 'assistant', content: 'Pending assistant', turnId: 'turn-1' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Persisted user', 'Persisted assistant'),
        'submit',
      );

      expect(result).toHaveLength(2);
      expect(result[0].content).toBe('Pending user');
      expect(result[0].messageId).toBe('turn-1-user');
      expect(result[1].content).toBe('Pending assistant');
      expect(result[1].messageId).toBe('turn-1-assistant');
    });

    test('appends assistant when only user exists', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'User message' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'User message', 'Assistant response'),
        'submit',
      );

      expect(result).toHaveLength(2);
      expect(result[1].role).toBe('assistant');
    });

    test('handles turn without assistant', () => {
      const history: ChatMessage[] = [];
      const turn = createTurn('turn-1', 'User only');

      const result = applySavedTurnToHistory(history, turn, 'submit');

      expect(result).toHaveLength(1);
      expect(result[0].role).toBe('user');
    });

    test('applies local patch to user message', () => {
      const localPatch = {
        user: { role: 'user' as const, content: 'Local user content' },
      };

      const result = applySavedTurnToHistory(
        [],
        createTurn('turn-1', 'Persisted', 'Response'),
        'submit',
        localPatch,
      );

      expect(result[0].content).toBe('Local user content');
    });
  });

  describe('retry operation', () => {
    test('finds turn by turn_id and preserves local content', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'First user', turnId: 'turn-1' },
        { role: 'assistant', content: 'First assistant', turnId: 'turn-1' },
        { role: 'user', content: 'Second user', turnId: 'turn-2' },
        { role: 'assistant', content: 'Second assistant', turnId: 'turn-2' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Retry user', 'Retry assistant'),
        'retry',
      );

      expect(result).toHaveLength(2);
      expect(result[0].content).toBe('First user');
      expect(result[0].messageId).toBe('turn-1-user');
      expect(result[1].content).toBe('First assistant');
      expect(result[1].messageId).toBe('turn-1-assistant');
    });

    test('finds turn by message_id and keeps local user text', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'User', messageId: 'turn-1-user' },
        { role: 'assistant', content: 'Assistant' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Updated user', 'Updated assistant'),
        'retry',
      );

      expect(result).toHaveLength(2);
      expect(result[0].content).toBe('User');
      expect(result[1].content).toBe('Updated assistant');
    });

    test('returns original history when turn not found', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'User', turnId: 'other-turn' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Not found', 'Not found'),
        'retry',
      );

      expect(result).toBe(history);
    });

    test('truncates history after the matched turn', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'First', turnId: 'turn-1' },
        { role: 'assistant', content: 'First response', turnId: 'turn-1' },
        { role: 'user', content: 'Second', turnId: 'turn-2' },
        { role: 'assistant', content: 'Second response', turnId: 'turn-2' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Edited first', 'New response'),
        'retry',
      );

      expect(result).toHaveLength(2);
    });
  });

  describe('edit operation', () => {
    test('behaves like retry - preserves local text while updating metadata', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'Original', turnId: 'turn-1' },
        { role: 'assistant', content: 'Response', turnId: 'turn-1' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Edited', 'New response'),
        'edit',
      );

      expect(result).toHaveLength(2);
      expect(result[0].content).toBe('Original');
      expect(result[0].messageId).toBe('turn-1-user');
      expect(result[1].content).toBe('Response');
      expect(result[1].messageId).toBe('turn-1-assistant');
    });

    test('applies local patch during edit', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'Original', turnId: 'turn-1' },
        { role: 'assistant', content: 'Response', turnId: 'turn-1' },
      ];

      const localPatch = {
        assistant: { role: 'assistant' as const, content: 'Patched assistant' },
      };

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'User', 'Persisted'),
        'edit',
        localPatch,
      );

      expect(result[1].content).toBe('Patched assistant');
    });
  });

  describe('edge cases', () => {
    test('handles turn with only user (no assistant) during retry', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'Original', turnId: 'turn-1' },
        { role: 'assistant', content: 'Response', turnId: 'turn-1' },
      ];

      const turn = createTurn('turn-1', 'User only');

      const result = applySavedTurnToHistory(history, turn, 'retry');

      expect(result).toHaveLength(1);
      expect(result[0].content).toBe('Original');
      expect(result[0].messageId).toBe('turn-1-user');
    });

    test('handles matching by assistant message_id', () => {
      const history: ChatMessage[] = [
        { role: 'user', content: 'User' },
        { role: 'assistant', content: 'Assistant', messageId: 'turn-1-assistant' },
      ];

      const result = applySavedTurnToHistory(
        history,
        createTurn('turn-1', 'Updated', 'Updated assistant'),
        'retry',
      );

      expect(result).toHaveLength(3);
      expect(result[0].content).toBe('User');
      expect(result[1].content).toBe('Updated');
      expect(result[2].content).toBe('Updated assistant');
    });
  });
});
