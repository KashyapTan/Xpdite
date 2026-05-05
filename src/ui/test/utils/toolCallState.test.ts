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

  test('collapses a single anonymous pending sub-agent row when stream adds an agentId', () => {
    const genericToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        instruction: 'Research TurboTax',
      },
      server: 'sub_agent',
      status: 'calling',
    };

    const nextState = applyToolCallChange(
      [genericToolCall],
      [{ type: 'tool_call', toolCall: genericToolCall }],
      {
        name: 'spawn_agent',
        args: {
          agent_name: 'Sub-agent',
          model_tier: '',
        },
        server: 'sub_agent',
        status: 'complete',
        agentId: 'agent-1',
        result: 'Finished report',
        partialResult: 'Finished report',
      },
      true,
    );

    expect(nextState.toolCalls).toHaveLength(1);
    expect(nextState.contentBlocks).toHaveLength(1);
    expect(nextState.toolCalls[0]?.agentId).toBe('agent-1');
    expect(nextState.toolCalls[0]?.status).toBe('complete');
    expect(nextState.toolCalls[0]?.result).toBe('Finished report');
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

  test('keeps a completed streamed sub-agent row when late parent events omit model_tier', () => {
    const streamedToolCall: ToolCall = {
      name: 'spawn_agent',
      args: {
        agent_name: 'QuickBooks Researcher',
        model_tier: 'fast',
      },
      server: 'sub_agent',
      status: 'complete',
      agentId: 'agent-1',
      description: 'QuickBooks Researcher (fast)',
      result: 'Streamed report',
      startedAt: 1_000,
      completedAt: 4_000,
      durationMs: 3_000,
    };

    const afterLateCalling = applyToolCallChange(
      [streamedToolCall],
      [{ type: 'tool_call', toolCall: streamedToolCall }],
      {
        name: 'spawn_agent',
        args: {
          instruction: 'Research QuickBooks',
          agent_name: 'QuickBooks Researcher',
        },
        server: 'sub_agent',
        status: 'calling',
      },
      true,
    );

    expect(afterLateCalling.toolCalls).toHaveLength(1);
    expect(afterLateCalling.contentBlocks).toHaveLength(1);
    expect(afterLateCalling.toolCalls[0]?.agentId).toBe('agent-1');
    expect(afterLateCalling.toolCalls[0]?.status).toBe('complete');
    expect(afterLateCalling.toolCalls[0]?.durationMs).toBe(3_000);

    const afterLateComplete = applyToolCallChange(
      afterLateCalling.toolCalls,
      afterLateCalling.contentBlocks,
      {
        name: 'spawn_agent',
        args: {
          instruction: 'Research QuickBooks',
          agent_name: 'QuickBooks Researcher',
        },
        result: 'Parent result',
        server: 'sub_agent',
        status: 'complete',
      },
      true,
    );

    expect(afterLateComplete.toolCalls).toHaveLength(1);
    expect(afterLateComplete.contentBlocks).toHaveLength(1);
    expect(afterLateComplete.toolCalls[0]?.agentId).toBe('agent-1');
    expect(afterLateComplete.toolCalls[0]?.status).toBe('complete');
    expect(afterLateComplete.toolCalls[0]?.result).toBe('Parent result');
    expect(afterLateComplete.contentBlocks[0]?.type).toBe('tool_call');
    if (afterLateComplete.contentBlocks[0]?.type === 'tool_call') {
      expect(afterLateComplete.contentBlocks[0].toolCall.agentId).toBe('agent-1');
      expect(afterLateComplete.contentBlocks[0].toolCall.result).toBe('Parent result');
    }
  });
});
