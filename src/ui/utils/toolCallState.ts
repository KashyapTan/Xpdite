import type { ContentBlock, ToolCall } from '../types';

function isSubAgentToolCall(toolCall: ToolCall): boolean {
  return toolCall.server === 'sub_agent' && toolCall.name === 'spawn_agent';
}

function getSubAgentIdentity(toolCall: ToolCall): { agentName: string; modelTier: string } | null {
  if (!isSubAgentToolCall(toolCall)) {
    return null;
  }

  const agentNameRaw = toolCall.args['agent_name'];
  const modelTierRaw = toolCall.args['model_tier'];

  const agentName = typeof agentNameRaw === 'string'
    ? agentNameRaw.trim()
    : '';
  const modelTier = typeof modelTierRaw === 'string'
    ? modelTierRaw.trim()
    : '';

  if (!agentName || !modelTier) {
    return null;
  }

  return { agentName, modelTier };
}

function hasOwnProperty<K extends PropertyKey>(value: object, key: K): value is Record<K, unknown> {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function hasMeaningfulArgs(args: Record<string, unknown>): boolean {
  return Object.keys(args).length > 0;
}

export function toolCallsMatch(existing: ToolCall, incoming: ToolCall): boolean {
  if (existing.agentId && incoming.agentId) {
    return existing.agentId === incoming.agentId;
  }

  if (isSubAgentToolCall(existing) && isSubAgentToolCall(incoming)) {
    const existingIdentity = getSubAgentIdentity(existing);
    const incomingIdentity = getSubAgentIdentity(incoming);

    if (
      existingIdentity
      && incomingIdentity
      && existingIdentity.agentName === incomingIdentity.agentName
      && existingIdentity.modelTier === incomingIdentity.modelTier
      && (!!existing.agentId !== !!incoming.agentId)
    ) {
      return true;
    }
  }

  return (
    existing.server === incoming.server
    && existing.name === incoming.name
    && JSON.stringify(existing.args) === JSON.stringify(incoming.args)
  );
}

export function mergeToolCalls(existing: ToolCall, incoming: ToolCall): ToolCall {
  const merged: ToolCall = {
    ...existing,
    name: incoming.name || existing.name,
    server: incoming.server || existing.server,
    status: incoming.status ?? existing.status,
  };

  if (hasMeaningfulArgs(incoming.args)) {
    merged.args = incoming.args;
  }

  if (incoming.agentId) {
    merged.agentId = incoming.agentId;
  }

  if (hasOwnProperty(incoming, 'result')) {
    merged.result = incoming.result;
  }

  if (incoming.description !== undefined) {
    merged.description = incoming.description;
  }

  if (hasOwnProperty(incoming, 'partialResult')) {
    merged.partialResult = incoming.partialResult as string | undefined;
  }

  return merged;
}

export function applyToolCallChange(
  toolCalls: ToolCall[],
  contentBlocks: ContentBlock[],
  incoming: ToolCall,
  insertIfMissing: boolean,
): { toolCalls: ToolCall[]; contentBlocks: ContentBlock[] } {
  let canonicalToolCall = incoming;
  let foundMatch = false;

  const nextToolCalls = toolCalls.reduce<ToolCall[]>((acc, existingToolCall) => {
    if (!toolCallsMatch(existingToolCall, incoming)) {
      acc.push(existingToolCall);
      return acc;
    }

    if (!foundMatch) {
      canonicalToolCall = mergeToolCalls(existingToolCall, incoming);
      acc.push(canonicalToolCall);
      foundMatch = true;
    }

    return acc;
  }, []);

  if (!foundMatch && insertIfMissing) {
    nextToolCalls.push(canonicalToolCall);
  }

  let contentBlockMatched = false;
  const nextContentBlocks = contentBlocks.reduce<ContentBlock[]>((acc, block) => {
    if (block.type !== 'tool_call' || !toolCallsMatch(block.toolCall, incoming)) {
      acc.push(block);
      return acc;
    }

    if (!contentBlockMatched) {
      acc.push({ type: 'tool_call', toolCall: canonicalToolCall });
      contentBlockMatched = true;
    }

    return acc;
  }, []);

  if ((foundMatch || insertIfMissing) && !contentBlockMatched) {
    nextContentBlocks.push({ type: 'tool_call', toolCall: canonicalToolCall });
  }

  return {
    toolCalls: nextToolCalls,
    contentBlocks: nextContentBlocks,
  };
}
