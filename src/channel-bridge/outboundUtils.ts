export const DISCORD_OUTBOUND_CHUNK_LIMIT = 1900;

function findPreferredSplitPoint(content: string, maxLength: number): number {
  const minPreferred = Math.floor(maxLength * 0.6);
  const paragraphBoundary = content.lastIndexOf('\n\n', maxLength);
  if (paragraphBoundary >= 0) {
    return Math.min(paragraphBoundary + 2, maxLength);
  }

  const candidates = [
    content.lastIndexOf('\n', maxLength),
    content.lastIndexOf(' ', maxLength),
  ];

  for (const candidate of candidates) {
    if (candidate >= minPreferred) {
      return Math.min(candidate + 1, maxLength);
    }
  }

  return maxLength;
}

export function splitDiscordOutboundContent(
  content: string,
  maxLength: number = DISCORD_OUTBOUND_CHUNK_LIMIT,
): string[] {
  if (content.length <= maxLength) {
    return [content];
  }

  const chunks: string[] = [];
  let remaining = content;

  while (remaining.length > maxLength) {
    const splitAt = findPreferredSplitPoint(remaining, maxLength);
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt);
  }

  if (remaining) {
    chunks.push(remaining);
  }

  return chunks;
}
