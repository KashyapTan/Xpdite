import { layout } from '@chenglou/pretext';
import { describe, expect, test, vi } from 'vitest';

import type { ChatMessage } from '../../types';
import {
  estimateChatMessageHeight,
  estimateTextHeight,
} from '../../utils/pretextMessageLayout';

vi.mock('@chenglou/pretext', () => ({
  layout: vi.fn((prepared: { text: string }, width: number, lineHeight: number) => ({
    height: Math.max(lineHeight, Math.ceil(prepared.text.length / Math.max(20, Math.floor(width / 8))) * lineHeight),
  })),
  prepare: vi.fn((text: string) => ({ text })),
}));

describe('pretextMessageLayout', () => {
  test('returns a single line for whitespace-only text', () => {
    expect(estimateTextHeight('   ', '400 16px Montserrat', 240, 24)).toBe(24);
  });

  test('falls back to hard-break counts when layout measurement throws', () => {
    vi.mocked(layout).mockImplementationOnce(() => {
      throw new Error('measurement failed');
    });

    expect(
      estimateTextHeight('alpha\nbeta\ncharlie', '400 16px Montserrat', 240, 20, 'pre-wrap'),
    ).toBe(60);
  });

  test('adds image chip height to user messages', () => {
    const plainUserMessage: ChatMessage = {
      role: 'user',
      content: 'Describe this screenshot',
    };
    const imageUserMessage: ChatMessage = {
      ...plainUserMessage,
      images: [{ name: 'screen.png', thumbnail: 'data:image/png;base64,abc' }],
    };

    expect(estimateChatMessageHeight(imageUserMessage, 280)).toBeGreaterThan(
      estimateChatMessageHeight(plainUserMessage, 280),
    );
  });

  test('uses the deleted-artifact compact height for removed assistant artifacts', () => {
    const deletedArtifactMessage: ChatMessage = {
      role: 'assistant',
      content: '',
      contentBlocks: [
        {
          type: 'artifact',
          artifact: {
            artifactId: 'artifact-1',
            artifactType: 'markdown',
            title: 'spec.md',
            sizeBytes: 0,
            lineCount: 0,
            status: 'deleted',
          },
        },
      ],
    };

    expect(estimateChatMessageHeight(deletedArtifactMessage, 320)).toBe(214);
  });

  test('expands assistant messages that include a thinking chain', () => {
    const plainAssistantMessage: ChatMessage = {
      role: 'assistant',
      content: 'Final answer',
      contentBlocks: [{ type: 'text', content: 'Final answer' }],
    };
    const thinkingAssistantMessage: ChatMessage = {
      role: 'assistant',
      content: '',
      contentBlocks: [{ type: 'thinking', content: 'Inspect logs before answering.' }],
    };

    expect(estimateChatMessageHeight(thinkingAssistantMessage, 320)).toBeGreaterThan(
      estimateChatMessageHeight(plainAssistantMessage, 320),
    );
  });
});
