import { layout, prepare } from '@chenglou/pretext';
import type { ChatMessage, ContentBlock } from '../types';
import { buildRenderableContentBlocks } from './renderableContentBlocks';

const PREPARED_CACHE_LIMIT = 900;

const USER_FONT = '400 16px Montserrat';
const ASSISTANT_FONT = '400 16px Montserrat';
const THINKING_FONT = '400 13px Montserrat';

const USER_LINE_HEIGHT = 24;
const ASSISTANT_LINE_HEIGHT = 24;
const THINKING_LINE_HEIGHT = 20;

const USER_BASE_CHROME_HEIGHT = 72;
const ASSISTANT_BASE_CHROME_HEIGHT = 88;
const IMAGE_CHIPS_HEIGHT = 46;
const CHAIN_GROUP_COLLAPSED_HEIGHT = 44;
const THINKING_GROUP_BODY_PADDING = 14;
const TEXT_BLOCK_GAP_HEIGHT = 8;
const ARTIFACT_CARD_BASE_HEIGHT = 136;
const ARTIFACT_CARD_STREAMING_HEIGHT = 116;
const ARTIFACT_CARD_DELETED_HEIGHT = 92;

const preparedCache = new Map<string, ReturnType<typeof prepare>>();

function cachePreparedText(
  text: string,
  font: string,
  whiteSpace: 'normal' | 'pre-wrap',
): ReturnType<typeof prepare> {
  const normalized = text.length > 6000 ? text.slice(0, 6000) : text;
  const key = `${font}|${whiteSpace}|${normalized}`;
  const hit = preparedCache.get(key);
  if (hit) {
    preparedCache.delete(key);
    preparedCache.set(key, hit);
    return hit;
  }

  const prepared = prepare(normalized, font, { whiteSpace });
  preparedCache.set(key, prepared);

  if (preparedCache.size > PREPARED_CACHE_LIMIT) {
    const oldestKey = preparedCache.keys().next().value;
    if (typeof oldestKey === 'string') {
      preparedCache.delete(oldestKey);
    }
  }

  return prepared;
}

function countHardBreakLines(text: string): number {
  if (!text) {
    return 0;
  }
  return text.split('\n').length;
}

export function estimateTextHeight(
  text: string,
  font: string,
  maxWidth: number,
  lineHeight: number,
  whiteSpace: 'normal' | 'pre-wrap' = 'normal',
): number {
  const hardBreakLines = countHardBreakLines(text);
  const hasOnlyWhitespace = text.trim().length === 0;
  if (hasOnlyWhitespace && hardBreakLines <= 1) {
    return lineHeight;
  }

  const safeWidth = Math.max(80, Math.floor(maxWidth));

  try {
    const prepared = cachePreparedText(text.replace(/\r/g, ''), font, whiteSpace);
    const measured = layout(prepared, safeWidth, lineHeight);
    if (Number.isFinite(measured.height) && measured.height > 0) {
      return Math.ceil(measured.height);
    }
  } catch {
    // Fall through to conservative fallback.
  }

  return Math.max(lineHeight, hardBreakLines * lineHeight);
}

function isChainBlock(block: ContentBlock): boolean {
  return (
    block.type === 'thinking'
    || block.type === 'tool_call'
    || block.type === 'terminal_command'
    || block.type === 'youtube_transcription_approval'
  );
}

type BlockGroup =
  | { kind: 'text'; block: ContentBlock & { type: 'text' } }
  | { kind: 'artifact'; block: ContentBlock & { type: 'artifact' } }
  | { kind: 'chain'; blocks: ContentBlock[] };

function groupBlocks(blocks: ContentBlock[]): BlockGroup[] {
  const groups: BlockGroup[] = [];
  let chainBlocks: ContentBlock[] = [];

  for (const block of blocks) {
    if (isChainBlock(block)) {
      chainBlocks.push(block);
      continue;
    }

    if (block.type === 'text' && block.content.trim()) {
      if (chainBlocks.length > 0) {
        groups.push({ kind: 'chain', blocks: chainBlocks });
        chainBlocks = [];
      }
      groups.push({ kind: 'text', block });
      continue;
    }

    if (block.type === 'artifact') {
      if (chainBlocks.length > 0) {
        groups.push({ kind: 'chain', blocks: chainBlocks });
        chainBlocks = [];
      }
      groups.push({ kind: 'artifact', block });
    }
  }

  if (chainBlocks.length > 0) {
    groups.push({ kind: 'chain', blocks: chainBlocks });
  }

  return groups;
}

function estimateChainGroupHeight(blocks: ContentBlock[], maxTextWidth: number): number {
  const hasThinking = blocks.some((block) => block.type === 'thinking' && block.content.trim());
  const hasExecutableBlocks = blocks.some(
    (block) =>
      block.type === 'tool_call'
      || block.type === 'terminal_command'
      || block.type === 'youtube_transcription_approval',
  );

  let height = CHAIN_GROUP_COLLAPSED_HEIGHT;

  const isThinkingOnly = hasThinking && !hasExecutableBlocks;
  if (!isThinkingOnly) {
    return height;
  }

  for (const block of blocks) {
    if (block.type !== 'thinking' || !block.content.trim()) {
      continue;
    }
    height += estimateTextHeight(
      block.content,
      THINKING_FONT,
      maxTextWidth,
      THINKING_LINE_HEIGHT,
      'pre-wrap',
    );
  }

  height += THINKING_GROUP_BODY_PADDING;
  return height;
}

function estimateArtifactBlockHeight(block: ContentBlock & { type: 'artifact' }, maxTextWidth: number): number {
  if (block.artifact.status === 'deleted') {
    return ARTIFACT_CARD_DELETED_HEIGHT;
  }

  if (block.artifact.status === 'streaming') {
    return ARTIFACT_CARD_STREAMING_HEIGHT;
  }

  const metadataHeight = block.artifact.language ? 22 : 18;
  const titleHeight = estimateTextHeight(
    block.artifact.title,
    ASSISTANT_FONT,
    maxTextWidth,
    ASSISTANT_LINE_HEIGHT,
    'normal',
  );

  return Math.max(
    ARTIFACT_CARD_BASE_HEIGHT,
    84 + metadataHeight + titleHeight,
  );
}

function estimateAssistantContentHeight(message: ChatMessage, maxTextWidth: number): number {
  const blocks = buildRenderableContentBlocks(message);
  if (!blocks || blocks.length === 0) {
    return estimateTextHeight(message.content, ASSISTANT_FONT, maxTextWidth, ASSISTANT_LINE_HEIGHT, 'normal');
  }

  const groups = groupBlocks(blocks);
  let total = 0;

  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index];
    if (group.kind === 'text') {
      total += estimateTextHeight(
        group.block.content,
        ASSISTANT_FONT,
        maxTextWidth,
        ASSISTANT_LINE_HEIGHT,
        'normal',
      );
    } else if (group.kind === 'artifact') {
      total += estimateArtifactBlockHeight(group.block, maxTextWidth);
    } else {
      total += estimateChainGroupHeight(group.blocks, maxTextWidth);
    }

    if (index < groups.length - 1) {
      total += TEXT_BLOCK_GAP_HEIGHT;
    }
  }

  return Math.max(total, ASSISTANT_LINE_HEIGHT);
}

export function estimateChatMessageHeight(message: ChatMessage, maxTextWidth: number): number {
  const textWidth = Math.max(120, maxTextWidth);

  if (message.role === 'user') {
    let height = USER_BASE_CHROME_HEIGHT;
    height += estimateTextHeight(message.content, USER_FONT, textWidth, USER_LINE_HEIGHT, 'pre-wrap');
    if (message.images && message.images.length > 0) {
      height += IMAGE_CHIPS_HEIGHT;
    }
    return Math.ceil(height);
  }

  const assistantHeight = ASSISTANT_BASE_CHROME_HEIGHT + estimateAssistantContentHeight(message, textWidth);
  return Math.ceil(assistantHeight);
}
