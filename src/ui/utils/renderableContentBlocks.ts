import type { ChatMessage, ContentBlock } from '../types';

export function buildRenderableContentBlocks(
  message: Pick<ChatMessage, 'content' | 'thinking' | 'toolCalls' | 'contentBlocks'>,
): ContentBlock[] | undefined {
  if (message.contentBlocks && message.contentBlocks.length > 0) {
    return message.contentBlocks;
  }

  const blocks: ContentBlock[] = [];

  if (message.thinking?.trim()) {
    blocks.push({ type: 'thinking', content: message.thinking });
  }

  if (message.toolCalls && message.toolCalls.length > 0) {
    blocks.push(
      ...message.toolCalls.map((toolCall) => ({
        type: 'tool_call' as const,
        toolCall,
      })),
    );
  }

  if (message.content.trim()) {
    blocks.push({ type: 'text', content: message.content });
  }

  return blocks.length > 0 ? blocks : undefined;
}
