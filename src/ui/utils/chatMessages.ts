import type {
  ChatMessage,
  TerminalCommandBlock,
  ToolCall,
  YouTubeTranscriptionApprovalBlock,
} from '../types';
import {
  applyResponseVariant,
  applySavedTurnToHistory,
  mapConversationContentBlock,
  mapConversationMessagePayload,
  mergeMessageMetadata,
  normalizeTimestamp,
} from './conversationMessageTransforms';
import { buildRenderableContentBlocks } from './renderableContentBlocks';

export type { LocalTurnPatch } from './conversationMessageTransforms';
export {
  applyResponseVariant,
  applySavedTurnToHistory,
  buildRenderableContentBlocks,
  mapConversationContentBlock,
  mapConversationMessagePayload,
  mergeMessageMetadata,
  normalizeTimestamp,
};

export function formatMessageTimestamp(timestamp?: number): string {
  const normalized = normalizeTimestamp(timestamp);
  if (!normalized) {
    return '';
  }
  return new Date(normalized).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}

function serializeToolCall(toolCall: ToolCall): string {
  const header = `[Tool: ${toolCall.name}]`;
  if (toolCall.result) {
    return `${header}\n${toolCall.result}`;
  }
  return header;
}

function serializeTerminalBlock(terminal: TerminalCommandBlock): string {
  const parts = [`$ ${terminal.command}`];
  if (terminal.output.trim()) {
    parts.push(terminal.output.trim());
  }
  return parts.join('\n');
}

function serializeYouTubeApprovalBlock(approval: YouTubeTranscriptionApprovalBlock): string {
  const status =
    approval.status === 'approved'
      ? 'Approved'
      : approval.status === 'denied'
        ? 'Denied'
        : 'Pending';

  return [
    `[YouTube transcription approval: ${status}]`,
    `Title: ${approval.title}`,
    `Channel: ${approval.channel}`,
    `Duration: ${approval.duration}`,
    `Estimated total: ${approval.totalTimeEstimate}`,
    `Model: ${approval.whisperModel}`,
    `URL: ${approval.url}`,
  ].join('\n');
}

function serializeArtifactBlock(messageArtifact: {
  title: string;
  status: 'streaming' | 'ready' | 'deleted';
  content?: string;
}): string {
  const prefix = `[Artifact: ${messageArtifact.title}]`;
  if (messageArtifact.status === 'deleted') {
    return `${prefix}\n[Deleted]`;
  }
  if (messageArtifact.content?.trim()) {
    return `${prefix}\n${messageArtifact.content}`;
  }
  if (messageArtifact.status === 'streaming') {
    return `${prefix}\n[Streaming]`;
  }
  return prefix;
}

export function serializeMessageForCopy(message: ChatMessage): string {
  if (message.contentBlocks && message.contentBlocks.length > 0) {
    return message.contentBlocks
      .map((block) => {
        if (block.type === 'text' || block.type === 'thinking') {
          return block.content;
        }
        if (block.type === 'artifact') {
          return serializeArtifactBlock(block.artifact);
        }
        if (block.type === 'tool_call') {
          return serializeToolCall(block.toolCall);
        }
        if (block.type === 'terminal_command') {
          return serializeTerminalBlock(block.terminal);
        }
        if (block.type === 'youtube_transcription_approval') {
          return serializeYouTubeApprovalBlock(block.approval);
        }
        return '';
      })
      .filter(Boolean)
      .join('\n\n')
      .trim();
  }
  return message.content.trim();
}

