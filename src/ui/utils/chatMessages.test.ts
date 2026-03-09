import { describe, expect, test } from 'bun:test';

import {
  buildRenderableContentBlocks,
  mapConversationContentBlock,
  serializeMessageForCopy,
} from './chatMessages';

describe('chatMessages timeline helpers', () => {
  test('preserves thinking content blocks from persisted conversations', () => {
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

  test('builds fallback render blocks with thinking before the final response', () => {
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

  test('serializes thinking blocks without treating them as terminal output', () => {
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
});