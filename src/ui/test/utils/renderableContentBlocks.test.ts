import { describe, expect, test } from 'vitest';

import { buildRenderableContentBlocks } from '../../utils/renderableContentBlocks';

describe('buildRenderableContentBlocks', () => {
  test('returns existing content blocks when provided', () => {
    const existing = [{ type: 'text', content: 'Persisted' }] as const;

    expect(
      buildRenderableContentBlocks({
        content: 'Ignored',
        contentBlocks: [...existing],
      }),
    ).toEqual(existing);
  });

  test('builds fallback blocks in thinking, tool, text order', () => {
    expect(
      buildRenderableContentBlocks({
        content: 'Final answer',
        thinking: 'Plan first',
        toolCalls: [{ name: 'search', args: { q: 'x' }, server: 'web', status: 'complete' }],
      }),
    ).toEqual([
      { type: 'thinking', content: 'Plan first' },
      {
        type: 'tool_call',
        toolCall: { name: 'search', args: { q: 'x' }, server: 'web', status: 'complete' },
      },
      { type: 'text', content: 'Final answer' },
    ]);
  });

  test('returns undefined for whitespace-only fallback state', () => {
    expect(
      buildRenderableContentBlocks({
        content: '   ',
        thinking: '\n',
      }),
    ).toBeUndefined();
  });
});
