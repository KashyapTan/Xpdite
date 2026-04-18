import { describe, expect, test } from 'vitest';

import type { ChatMessage } from '../../types';
import {
  applyResponseVariant,
  applySavedTurnToHistory,
  mapConversationContentBlock,
  mapConversationMessagePayload,
  mergeMessageMetadata,
  normalizeTimestamp,
} from '../../utils/conversationMessageTransforms';

describe('conversationMessageTransforms', () => {
  test('normalizes second-based timestamps to milliseconds', () => {
    expect(normalizeTimestamp(1_700_000_000)).toBe(1_700_000_000_000);
    expect(normalizeTimestamp(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(normalizeTimestamp(undefined)).toBeUndefined();
  });

  test('maps persisted artifact and mobile-origin payloads into chat messages', () => {
    const result = mapConversationMessagePayload({
      message_id: 'msg-1',
      turn_id: 'turn-1',
      role: 'assistant',
      content: 'Artifact ready',
      timestamp: 1_700_000_000,
      images: ['/tmp/screenshot.png'],
      content_blocks: [
        {
          type: 'artifact',
          artifact_id: 'artifact-1',
          artifact_type: 'code',
          title: 'demo.py',
          language: 'python',
          size_bytes: 11,
          line_count: 1,
          status: 'ready',
          content: 'print("hi")',
        },
      ],
      mobile_origin: {
        platform: 'telegram',
        display_name: 'Alex',
      },
    });

    expect(result).toMatchObject({
      role: 'assistant',
      messageId: 'msg-1',
      turnId: 'turn-1',
      timestamp: 1_700_000_000_000,
      images: [{ name: 'screenshot.png', thumbnail: '' }],
      mobileOrigin: {
        platform: 'telegram',
        displayName: 'Alex',
      },
    });
    expect(result.contentBlocks).toEqual([
      {
        type: 'artifact',
        artifact: expect.objectContaining({
          artifactId: 'artifact-1',
          title: 'demo.py',
          content: 'print("hi")',
        }),
      },
    ]);
  });

  test('maps terminal command blocks from snake_case payloads', () => {
    expect(
      mapConversationContentBlock({
        type: 'terminal_command',
        request_id: 'req-1',
        command: 'dir',
        cwd: 'C:/tmp',
        status: 'completed',
        output_chunks: [{ text: 'done', raw: false }],
        is_pty: true,
        exit_code: 0,
        duration_ms: 15,
        timed_out: false,
      }),
    ).toEqual({
      type: 'terminal_command',
      terminal: {
        requestId: 'req-1',
        command: 'dir',
        cwd: 'C:/tmp',
        status: 'completed',
        output: '',
        outputChunks: [{ text: 'done', raw: false }],
        isPty: true,
        exitCode: 0,
        durationMs: 15,
        timedOut: false,
      },
    });
  });

  test('merges local assistant content into the active persisted response variant', () => {
    const persisted: ChatMessage = {
      role: 'assistant',
      content: 'Server response',
      responseVersions: [
        { responseIndex: 0, content: 'Server response', timestamp: 1000 },
      ],
      activeResponseIndex: 0,
      messageId: 'msg-1',
    };
    const local: ChatMessage = {
      role: 'assistant',
      content: 'Local stream',
      contentBlocks: [{ type: 'text', content: 'Local stream' }],
      model: 'gpt-4.1',
      timestamp: 2000,
    };

    const result = mergeMessageMetadata(local, persisted);

    expect(result.content).toBe('Local stream');
    expect(result.responseVersions?.[0]).toEqual({
      responseIndex: 0,
      content: 'Local stream',
      model: 'gpt-4.1',
      timestamp: 2000,
      contentBlocks: [{ type: 'text', content: 'Local stream' }],
    });
  });

  test('applies response variants with content blocks and clears legacy tool state', () => {
    const result = applyResponseVariant(
      {
        role: 'assistant',
        content: 'Original',
        toolCalls: [{ name: 'search', args: {}, server: 'web', status: 'complete' }],
        responseVersions: [
          {
            responseIndex: 0,
            content: 'Updated',
            contentBlocks: [{ type: 'text', content: 'Updated' }],
            timestamp: 1000,
          },
        ],
      },
      0,
    );

    expect(result).toEqual({
      role: 'assistant',
      content: 'Updated',
      toolCalls: undefined,
      responseVersions: [
        {
          responseIndex: 0,
          content: 'Updated',
          contentBlocks: [{ type: 'text', content: 'Updated' }],
          timestamp: 1000,
        },
      ],
      contentBlocks: [{ type: 'text', content: 'Updated' }],
      model: undefined,
      timestamp: 1000,
      thinking: undefined,
      activeResponseIndex: 0,
    });
  });

  test('rebuilds edited turns from the matched history boundary', () => {
    const history: ChatMessage[] = [
      { role: 'user', content: 'Old user', turnId: 'turn-1' },
      { role: 'assistant', content: 'Old assistant', turnId: 'turn-1' },
      { role: 'user', content: 'Later user', turnId: 'turn-2' },
      { role: 'assistant', content: 'Later assistant', turnId: 'turn-2' },
    ];

    const result = applySavedTurnToHistory(
      history,
      {
        turn_id: 'turn-1',
        user: {
          message_id: 'turn-1-user',
          turn_id: 'turn-1',
          role: 'user',
          content: 'Persisted user',
          timestamp: 1_700_000_000,
        },
        assistant: {
          message_id: 'turn-1-assistant',
          turn_id: 'turn-1',
          role: 'assistant',
          content: 'Persisted assistant',
          timestamp: 1_700_000_001,
        },
      },
      'edit',
    );

    expect(result).toEqual([
      expect.objectContaining({
        role: 'user',
        content: 'Old user',
        messageId: 'turn-1-user',
      }),
      expect.objectContaining({
        role: 'assistant',
        content: 'Old assistant',
        messageId: 'turn-1-assistant',
      }),
    ]);
  });
});
