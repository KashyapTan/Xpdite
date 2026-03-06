import type {
  ChatMessage,
  ContentBlock,
  ConversationContentBlockPayload,
  ConversationImagePayload,
  ConversationMessagePayload,
  ConversationTurnPayload,
  ResponseVariant,
  TerminalCommandBlock,
  ToolCall,
} from '../types';

export interface LocalTurnPatch {
  user?: ChatMessage;
  assistant?: ChatMessage;
}

export function normalizeTimestamp(timestamp?: number): number | undefined {
  if (timestamp === undefined || Number.isNaN(timestamp)) {
    return undefined;
  }
  return timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000;
}

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

export function serializeMessageForCopy(message: ChatMessage): string {
  if (message.contentBlocks && message.contentBlocks.length > 0) {
    return message.contentBlocks
      .map((block) => {
        if (block.type === 'text') {
          return block.content;
        }
        if (block.type === 'tool_call') {
          return serializeToolCall(block.toolCall);
        }
        return serializeTerminalBlock(block.terminal);
      })
      .filter(Boolean)
      .join('\n\n')
      .trim();
  }
  return message.content.trim();
}

export function mapConversationContentBlock(
  block: ConversationContentBlockPayload,
): ContentBlock {
  if (block.type === 'tool_call') {
    return {
      type: 'tool_call',
      toolCall: {
        name: block.name ?? '',
        args: block.args ?? {},
        result: block.result,
        server: block.server ?? '',
        status: 'complete',
      },
    };
  }

  if (block.type === 'terminal_command') {
    return {
      type: 'terminal_command',
      terminal: {
        requestId: block.request_id ?? block.requestId ?? '',
        command: block.command ?? '',
        cwd: block.cwd ?? '',
        status: (block.status as TerminalCommandBlock['status']) ?? 'completed',
        output: block.output ?? '',
        outputChunks: block.output_chunks ?? block.outputChunks ?? [],
        isPty: block.is_pty ?? block.isPty ?? false,
        exitCode: block.exit_code ?? block.exitCode,
        durationMs: block.duration_ms ?? block.durationMs,
        timedOut: block.timed_out ?? block.timedOut,
      },
    };
  }

  return {
    type: 'text',
    content: block.content ?? '',
  };
}

function mapResponseVariantPayload(
  variant: NonNullable<ConversationMessagePayload['response_variants']>[number],
): ResponseVariant {
  return {
    responseIndex: variant.response_index,
    content: variant.content,
    model: variant.model,
    timestamp: normalizeTimestamp(variant.timestamp) ?? variant.timestamp,
    contentBlocks: variant.content_blocks?.map(mapConversationContentBlock),
  };
}

function imageNameFromPath(imagePath: string): string {
  const parts = imagePath.split(/[\\/]/);
  return parts[parts.length - 1] || imagePath;
}

function mapConversationImagePayload(
  image: ConversationImagePayload,
): { name: string; thumbnail: string } {
  if (typeof image === 'string') {
    return {
      name: imageNameFromPath(image),
      thumbnail: '',
    };
  }

  return {
    name: image.name,
    thumbnail: image.thumbnail ?? '',
  };
}

export function mapConversationMessagePayload(
  message: ConversationMessagePayload,
): ChatMessage {
  const images = Array.isArray(message.images)
    ? message.images.map(mapConversationImagePayload)
    : undefined;

  return {
    role: message.role as 'user' | 'assistant',
    content: message.content,
    images: images && images.length > 0 ? images : undefined,
    model: message.model,
    messageId: message.message_id,
    turnId: message.turn_id,
    timestamp: normalizeTimestamp(message.timestamp) ?? message.timestamp,
    contentBlocks: message.content_blocks?.map(mapConversationContentBlock),
    activeResponseIndex: message.active_response_index ?? 0,
    responseVersions: message.response_variants?.map(mapResponseVariantPayload),
  };
}

export function mergeMessageMetadata(
  localMessage: ChatMessage | undefined,
  persistedMessage: ChatMessage,
): ChatMessage {
  if (!localMessage) {
    return persistedMessage;
  }

  const activeResponseIndex =
    persistedMessage.activeResponseIndex ?? localMessage.activeResponseIndex ?? 0;
  let responseVersions = persistedMessage.responseVersions ?? localMessage.responseVersions;

  if (
    localMessage.role === 'assistant' &&
    responseVersions &&
    responseVersions.length > 0 &&
    activeResponseIndex >= 0 &&
    activeResponseIndex < responseVersions.length
  ) {
    responseVersions = responseVersions.map((variant, index) =>
      index === activeResponseIndex
        ? {
            ...variant,
            content: localMessage.content || variant.content,
            model: localMessage.model || variant.model,
            timestamp: localMessage.timestamp ?? variant.timestamp,
            contentBlocks:
              localMessage.contentBlocks && localMessage.contentBlocks.length > 0
                ? localMessage.contentBlocks
                : variant.contentBlocks,
          }
        : variant,
    );
  }

  return {
    ...persistedMessage,
    content: localMessage.content || persistedMessage.content,
    thinking: localMessage.thinking ?? persistedMessage.thinking,
    images:
      localMessage.images && localMessage.images.length > 0
        ? localMessage.images
        : persistedMessage.images,
    toolCalls: localMessage.toolCalls ?? persistedMessage.toolCalls,
    contentBlocks:
      localMessage.contentBlocks && localMessage.contentBlocks.length > 0
        ? localMessage.contentBlocks
        : persistedMessage.contentBlocks,
    model: localMessage.model || persistedMessage.model,
    timestamp: localMessage.timestamp ?? persistedMessage.timestamp,
    activeResponseIndex,
    responseVersions,
  };
}

export function applySavedTurnToHistory(
  history: ChatMessage[],
  turn: ConversationTurnPayload,
  operation: 'submit' | 'retry' | 'edit',
  localPatch?: LocalTurnPatch,
): ChatMessage[] {
  const persistedUser = mapConversationMessagePayload(turn.user);
  const persistedAssistant = turn.assistant
    ? mapConversationMessagePayload(turn.assistant)
    : undefined;

  if (operation === 'submit') {
    const nextHistory = [...history];
    const assistantIndex =
      persistedAssistant && nextHistory[nextHistory.length - 1]?.role === 'assistant'
        ? nextHistory.length - 1
        : -1;
    const userIndex =
      nextHistory[assistantIndex >= 0 ? assistantIndex - 1 : nextHistory.length - 1]
        ?.role === 'user'
        ? assistantIndex >= 0
          ? assistantIndex - 1
          : nextHistory.length - 1
        : -1;

    if (userIndex >= 0) {
      nextHistory[userIndex] = mergeMessageMetadata(
        localPatch?.user ?? nextHistory[userIndex],
        persistedUser,
      );
    } else {
      nextHistory.push(mergeMessageMetadata(localPatch?.user, persistedUser));
    }

    if (persistedAssistant) {
      if (assistantIndex >= 0) {
        nextHistory[assistantIndex] = mergeMessageMetadata(
          localPatch?.assistant ?? nextHistory[assistantIndex],
          persistedAssistant,
        );
      } else {
        nextHistory.push(
          mergeMessageMetadata(localPatch?.assistant, persistedAssistant),
        );
      }
    }

    return nextHistory;
  }

  const turnStartIndex = history.findIndex(
    (message) =>
      message.turnId === turn.turn_id ||
      message.messageId === turn.user.message_id ||
      (turn.assistant && message.messageId === turn.assistant.message_id),
  );

  if (turnStartIndex === -1) {
    return history;
  }

  const existingUser =
    history[turnStartIndex]?.role === 'user' ? history[turnStartIndex] : undefined;
  const existingAssistant =
    history[turnStartIndex + 1]?.role === 'assistant' &&
    history[turnStartIndex + 1]?.turnId === turn.turn_id
      ? history[turnStartIndex + 1]
      : undefined;

  const nextHistory = history.slice(0, turnStartIndex);
  nextHistory.push(
    mergeMessageMetadata(localPatch?.user ?? existingUser, persistedUser),
  );
  if (persistedAssistant) {
    nextHistory.push(
      mergeMessageMetadata(
        localPatch?.assistant ?? existingAssistant,
        persistedAssistant,
      ),
    );
  }
  return nextHistory;
}
