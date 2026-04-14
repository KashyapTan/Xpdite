import { describe, expect, test } from 'vitest';

import type { ContentBlock, ToolCall } from '../../types';
import { applyToolCallChange, toolCallsMatch } from '../../utils/toolCallState';

describe('toolCallState', () => {
  test('matches sub-agent tool calls when runtime updates add an agentId', () => {
    const genericToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        instruction: 'Research TurboTax',
        agent_name: 'TurboTax Researcher',
        model_tier: 'smart',
      },
      server: 'sub_agent',
      status: 'calling',
    };

    const runtimeToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        agent_name: 'TurboTax Researcher',
        model_tier: 'smart',
      },
      server: 'sub_agent',
      status: 'calling',
      agentId: 'agent-1',
      description: 'TurboTax Researcher (smart)',
    };

    expect(toolCallsMatch(genericToolCall, runtimeToolCall)).toBe(true);
  });

  test('collapses generic and runtime sub-agent rows into one canonical entry', () => {
    const genericToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        instruction: 'Research TurboTax',
        agent_name: 'TurboTax Researcher',
        model_tier: 'smart',
      },
      server: 'sub_agent',
      status: 'calling',
    };

    const existingBlocks: ContentBlock[] = [
      { type: 'tool_call', toolCall: genericToolCall },
    ];

    const nextState = applyToolCallChange(
      [genericToolCall],
      existingBlocks,
      {
        name: 'spawn_agent',
        args: {
          agent_name: 'TurboTax Researcher',
          model_tier: 'smart',
        },
        server: 'sub_agent',
        status: 'calling',
        agentId: 'agent-1',
        description: 'TurboTax Researcher (smart)',
      },
      true,
    );

    expect(nextState.toolCalls).toHaveLength(1);
    expect(nextState.contentBlocks).toHaveLength(1);

    const toolCall = nextState.toolCalls[0];
    expect(toolCall.agentId).toBe('agent-1');
    expect(toolCall.description).toBe('TurboTax Researcher (smart)');
    expect(toolCall.args).toEqual({
      agent_name: 'TurboTax Researcher',
      model_tier: 'smart',
    });
  });

  test('updates the canonical sub-agent row when the generic completion payload arrives', () => {
    const runtimeToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        agent_name: 'TurboTax Researcher',
        model_tier: 'smart',
      },
      server: 'sub_agent',
      status: 'calling',
      agentId: 'agent-1',
      description: 'TurboTax Researcher (smart)',
      partialResult: 'Working...',
    };

    const nextState = applyToolCallChange(
      [runtimeToolCall],
      [{ type: 'tool_call', toolCall: runtimeToolCall }],
      {
        name: 'spawn_agent',
        args: {
          instruction: 'Research TurboTax',
          agent_name: 'TurboTax Researcher',
          model_tier: 'smart',
        },
        result: 'Finished report',
        server: 'sub_agent',
        status: 'complete',
        partialResult: undefined,
      },
      false,
    );

    expect(nextState.toolCalls).toHaveLength(1);
    expect(nextState.contentBlocks).toHaveLength(1);

    const toolCall = nextState.toolCalls[0];
    expect(toolCall.agentId).toBe('agent-1');
    expect(toolCall.status).toBe('complete');
    expect(toolCall.result).toBe('Finished report');
    expect(toolCall.partialResult).toBeUndefined();
  });
});
