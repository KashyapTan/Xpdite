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
  YouTubeTranscriptionApprovalBlock,
} from '../types';

export interface LocalTurnPatch {
  user?: ChatMessage;
  assistant?: ChatMessage;
}

export function normalizeTimestamp(timestamp?: number): number | undefined {
  if (timestamp === undefined || Number.isNaN(timestamp)) {
    return undefined;
  }
  return timestamp >= 1_000_000_000_000 ? timestamp : timestamp * 1000;
}

export function mapConversationContentBlock(
  block: ConversationContentBlockPayload,
): ContentBlock {
  if (block.type === 'artifact') {
    return {
      type: 'artifact',
      artifact: {
        artifactId: block.artifact_id ?? '',
        artifactType: (block.artifact_type ?? 'code') as 'code' | 'markdown' | 'html',
        title: block.title ?? 'Untitled artifact',
        language: block.language ?? undefined,
        sizeBytes: block.size_bytes ?? block.sizeBytes ?? 0,
        lineCount: block.line_count ?? block.lineCount ?? 0,
        status: (block.status as 'streaming' | 'ready' | 'deleted') ?? 'ready',
        content: block.content,
        conversationId: block.conversation_id,
        messageId: block.message_id,
        createdAt: normalizeTimestamp(block.created_at) ?? block.created_at,
        updatedAt: normalizeTimestamp(block.updated_at) ?? block.updated_at,
      },
    };
  }

  if (block.type === 'thinking') {
    const thinkingBlock: Extract<ContentBlock, { type: 'thinking' }> = {
      type: 'thinking',
      content: block.content ?? '',
    };
    const startedAt = normalizeTimestamp(block.started_at) ?? block.startedAt;
    const completedAt = normalizeTimestamp(block.completed_at) ?? block.completedAt;
    const durationMs = block.duration_ms ?? block.durationMs;
    if (startedAt !== undefined) thinkingBlock.startedAt = startedAt;
    if (completedAt !== undefined) thinkingBlock.completedAt = completedAt;
    if (durationMs !== undefined) thinkingBlock.durationMs = durationMs;
    return thinkingBlock;
  }

  if (block.type === 'tool_call') {
    const toolCall: ToolCall = {
      name: block.name ?? '',
      args: block.args ?? {},
      result: block.result,
      server: block.server ?? '',
      status: 'complete' as const,
    };
    const startedAt = normalizeTimestamp(block.started_at) ?? block.startedAt;
    const completedAt = normalizeTimestamp(block.completed_at) ?? block.completedAt;
    const durationMs = block.duration_ms ?? block.durationMs;
    if (startedAt !== undefined) toolCall.startedAt = startedAt;
    if (completedAt !== undefined) toolCall.completedAt = completedAt;
    if (durationMs !== undefined) toolCall.durationMs = durationMs;
    return {
      type: 'tool_call',
      toolCall,
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

  if (block.type === 'youtube_transcription_approval') {
    return {
      type: 'youtube_transcription_approval',
      approval: {
        requestId: block.request_id ?? block.requestId ?? '',
        title: block.title ?? '',
        channel: block.channel ?? '',
        duration: block.duration ?? '',
        durationSeconds: block.duration_seconds,
        url: block.url ?? '',
        noCaptionsReason: block.no_captions_reason ?? '',
        audioSizeEstimate: block.audio_size_estimate ?? 'Unknown',
        audioSizeBytes: block.audio_size_bytes,
        downloadTimeEstimate: block.download_time_estimate ?? 'Unknown',
        transcriptionTimeEstimate: block.transcription_time_estimate ?? 'Unknown',
        totalTimeEstimate: block.total_time_estimate ?? 'Unknown',
        whisperModel: block.whisper_model ?? '',
        computeBackend: block.compute_backend ?? '',
        playlistNote: block.playlist_note,
        status: (block.status as YouTubeTranscriptionApprovalBlock['status']) ?? 'pending',
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
  const mapped: ResponseVariant = {
    responseIndex: variant.response_index,
    content: variant.content,
    model: variant.model,
    timestamp: normalizeTimestamp(variant.timestamp) ?? variant.timestamp,
    contentBlocks: variant.content_blocks?.map(mapConversationContentBlock),
  };
  const durationMs = variant.duration_ms ?? variant.durationMs;
  if (durationMs !== undefined) mapped.durationMs = durationMs;
  return mapped;
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

  const mobileOrigin = message.mobile_origin
    ? {
        platform: message.mobile_origin.platform,
        displayName: message.mobile_origin.display_name,
      }
    : undefined;

  const mapped: ChatMessage = {
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
    mobileOrigin,
  };
  const durationMs = message.duration_ms ?? message.durationMs;
  if (durationMs !== undefined) mapped.durationMs = durationMs;
  return mapped;
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
            durationMs: localMessage.durationMs ?? variant.durationMs,
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
    durationMs: localMessage.durationMs ?? persistedMessage.durationMs,
    activeResponseIndex,
    responseVersions,
  };
}

export function applyResponseVariant(
  message: ChatMessage,
  responseIndex: number,
): ChatMessage | undefined {
  const nextVariant = message.responseVersions?.[responseIndex];
  if (!nextVariant) {
    return undefined;
  }
  const hasContentBlocks =
    !!nextVariant.contentBlocks && nextVariant.contentBlocks.length > 0;

  return {
    ...message,
    content: nextVariant.content,
    model: nextVariant.model ?? message.model,
    timestamp: nextVariant.timestamp ?? message.timestamp,
    durationMs: nextVariant.durationMs ?? message.durationMs,
    contentBlocks: hasContentBlocks ? nextVariant.contentBlocks : undefined,
    toolCalls: hasContentBlocks ? undefined : message.toolCalls,
    thinking: undefined,
    activeResponseIndex: responseIndex,
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
