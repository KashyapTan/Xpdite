import { describe, expect, test } from 'vitest';

import { DISCORD_OUTBOUND_CHUNK_LIMIT, splitDiscordOutboundContent } from './outboundUtils';

describe('splitDiscordOutboundContent', () => {
  test('returns a single chunk when content fits', () => {
    expect(splitDiscordOutboundContent('short message')).toEqual(['short message']);
  });

  test('prefers splitting on paragraph boundaries', () => {
    const content = `First paragraph.\n\n${'A'.repeat(DISCORD_OUTBOUND_CHUNK_LIMIT)}`;
    const chunks = splitDiscordOutboundContent(content);

    expect(chunks).toHaveLength(2);
    expect(chunks[0]).toBe('First paragraph.\n\n');
    expect(chunks.join('')).toBe(content);
  });

  test('falls back to a hard split when there is no separator', () => {
    const content = 'A'.repeat(DISCORD_OUTBOUND_CHUNK_LIMIT + 125);
    const chunks = splitDiscordOutboundContent(content);

    expect(chunks).toHaveLength(2);
    expect(chunks[0]).toHaveLength(DISCORD_OUTBOUND_CHUNK_LIMIT);
    expect(chunks.join('')).toBe(content);
  });

  test('never emits a chunk beyond the Discord limit at a boundary separator', () => {
    const content = `${'A'.repeat(DISCORD_OUTBOUND_CHUNK_LIMIT)}\n\nTail`;
    const chunks = splitDiscordOutboundContent(content);

    expect(chunks[0]).toHaveLength(DISCORD_OUTBOUND_CHUNK_LIMIT);
    expect(chunks.join('')).toBe(content);
  });
});
