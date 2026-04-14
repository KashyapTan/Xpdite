import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { InlineContentBlocks, ToolCallsDisplay } from '../../../components/chat/ToolCallsDisplay';
import type { ContentBlock, ToolCall } from '../../../types';

vi.mock('../../../components/chat/SubAgentTranscript', () => ({
  SubAgentTranscript: ({ stepsJson }: { stepsJson?: string }) => <div>sub-agent:{stepsJson}</div>,
}));

vi.mock('../../../components/chat/InlineTerminalBlock', () => ({
  InlineTerminalBlock: ({ terminal }: { terminal: { command: string } }) => <div>terminal:{terminal.command}</div>,
}));

vi.mock('../../../components/chat/InlineYouTubeApprovalBlock', () => ({
  InlineYouTubeApprovalBlock: ({ approval }: { approval: { title: string } }) => <div>youtube:{approval.title}</div>,
}));

vi.mock('../../../components/chat/toolCallUtils', () => ({
  getHumanReadableDescription: (toolCall: ToolCall) => ({
    badge: toolCall.server.toUpperCase(),
    text: `${toolCall.name} description`,
  }),
  getServerSummaryFragment: (server: string, count: number) => `${count} ${server} tools`,
}));

describe('ToolCallsDisplay', () => {
  test('returns null for empty tool calls', () => {
    const { container } = render(<ToolCallsDisplay toolCalls={[]} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders summary for legacy tool call array', () => {
    const toolCalls: ToolCall[] = [
      {
        name: 'search_docs',
        args: { q: 'token limits' },
        result: 'Found docs result',
        server: 'skills',
        status: 'complete',
      },
    ];

    render(<ToolCallsDisplay toolCalls={toolCalls} />);

    expect(screen.getByText('search_docs description')).toBeInTheDocument();
  });

  test('summarizes grouped completed tools by server', () => {
    const toolCalls: ToolCall[] = [
      {
        name: 'fetch_docs',
        args: {},
        result: 'ok',
        server: 'skills',
        status: 'complete',
      },
      {
        name: 'search_docs',
        args: {},
        result: 'ok',
        server: 'skills',
        status: 'complete',
      },
      {
        name: 'run_terminal_command',
        args: {},
        result: 'ok',
        server: 'terminal',
        status: 'complete',
      },
    ];

    const { container } = render(<ToolCallsDisplay toolCalls={toolCalls} />);

    expect(screen.getByText('2 skills tools and 1 terminal tools')).toBeInTheDocument();
    fireEvent.click(container.querySelector('.tool-chain-header') as HTMLElement);
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  test('uses running tool summary while chain is active', () => {
    const toolCalls: ToolCall[] = [
      {
        name: 'fetch_context',
        args: {},
        result: 'done',
        server: 'skills',
        status: 'complete',
      },
      {
        name: 'search_docs',
        args: {},
        server: 'skills',
        status: 'calling',
      },
    ];

    render(<ToolCallsDisplay toolCalls={toolCalls} />);

    expect(screen.getAllByText('search_docs description').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Done')).not.toBeInTheDocument();
  });
});

describe('InlineContentBlocks', () => {
  test('renders plain text blocks when no timeline blocks exist', () => {
    const blocks: ContentBlock[] = [{ type: 'text', content: 'Hello markdown block' }];
    render(<InlineContentBlocks blocks={blocks} />);
    expect(screen.getByText('Hello markdown block')).toBeInTheDocument();
  });

  test('renders timeline blocks for terminal and youtube approvals', async () => {
    const blocks: ContentBlock[] = [
      {
        type: 'terminal_command',
        terminal: {
          requestId: 'req-1',
          command: 'pwd',
          cwd: '.',
          status: 'running',
          output: '',
          outputChunks: [],
          isPty: false,
        },
      },
      {
        type: 'youtube_transcription_approval',
        approval: {
          requestId: 'yt-1',
          title: 'Video Title',
          channel: 'Channel',
          duration: '10:00',
          url: 'https://youtube.com/watch?v=abc',
          noCaptionsReason: 'none',
          audioSizeEstimate: '1 MB',
          downloadTimeEstimate: '1m',
          transcriptionTimeEstimate: '2m',
          totalTimeEstimate: '3m',
          whisperModel: 'base',
          computeBackend: 'cpu',
          status: 'pending',
        },
      },
    ];

    const { container } = render(<InlineContentBlocks blocks={blocks} expanded={true} />);

    // Terminal and youtube blocks are rendered
    expect(container.textContent).toContain('terminal:pwd');
    expect(container.textContent).toContain('youtube:Video Title');
  });

  test('renders thinking blocks in a collapsible chain group', () => {
    // For thinking-only chains, content is rendered directly (no extra nested collapsible)
    // since the outer header already indicates it's thinking
    const blocks: ContentBlock[] = [{ type: 'thinking', content: 'I should check `tool` output.' }];
    const { container } = render(<InlineContentBlocks blocks={blocks} isThinking={false} />);

    // Chain header should be present with "Thought process" summary
    const chainHeader = container.querySelector('.tool-chain-header');
    expect(chainHeader).not.toBeNull();
    expect(chainHeader).toHaveTextContent('Thought process');

    // Thinking content should be visible directly (thinking-only chains auto-expand)
    const thoughtContent = container.querySelector('.chain-thought-content');
    expect(thoughtContent).not.toBeNull();
    expect(thoughtContent).toHaveTextContent('I should check tool output.');

    // No nested "Thinking..." label for thinking-only chains
    const thinkingLabel = container.querySelector('.chain-thought-label');
    expect(thinkingLabel).toBeNull();
  });

  test('renders blocks in interleaved sequence (text, tools, thinking in order)', () => {
    const blocks: ContentBlock[] = [
      { type: 'text', content: 'Preamble before tool call' },
      {
        type: 'tool_call',
        toolCall: {
          name: 'search_docs',
          args: {},
          result: 'done',
          server: 'skills',
          status: 'complete',
        },
      },
      { type: 'text', content: 'Final answer after tools' },
    ];

    const { container } = render(<InlineContentBlocks blocks={blocks} />);

    // All text should be visible in the document (rendered in sequence)
    expect(screen.getByText('Preamble before tool call')).toBeInTheDocument();
    expect(screen.getByText('Final answer after tools')).toBeInTheDocument();

    // Tool call is inside a collapsed chain - expand it first
    const chainHeader = container.querySelector('.tool-chain-header');
    expect(chainHeader).not.toBeNull();
    fireEvent.click(chainHeader as HTMLElement);

    // Now the tool badge should be visible
    expect(screen.getByText('SKILLS')).toBeInTheDocument();
  });

  test('renders all blocks in their actual sequence', () => {
    // Blocks should render in order: tool1, text, tool2, text
    // With new behavior: text blocks separate chain groups
    const blocks: ContentBlock[] = [
      {
        type: 'tool_call',
        toolCall: {
          name: 'search_docs',
          args: {},
          result: 'done',
          server: 'skills',
          status: 'complete',
        },
      },
      { type: 'text', content: 'Let me call another tool' },
      {
        type: 'tool_call',
        toolCall: {
          name: 'read_file',
          args: {},
          result: 'content',
          server: 'filesystem',
          status: 'complete',
        },
      },
      { type: 'text', content: 'Final answer' },
    ];

    const { container } = render(<InlineContentBlocks blocks={blocks} />);

    // All text content should be visible
    expect(screen.getByText('Let me call another tool')).toBeInTheDocument();
    expect(screen.getByText('Final answer')).toBeInTheDocument();

    // We have two chain groups (one before each text block) - expand both
    const chainHeaders = container.querySelectorAll('.tool-chain-header');
    expect(chainHeaders.length).toBe(2);

    // Expand first chain group
    fireEvent.click(chainHeaders[0] as HTMLElement);
    expect(screen.getByText('SKILLS')).toBeInTheDocument();

    // Expand second chain group
    fireEvent.click(chainHeaders[1] as HTMLElement);
    expect(screen.getByText('FILESYSTEM')).toBeInTheDocument();
  });

  test('renders sub-agent running branch from partial result and complete branch from result', () => {
    const runningBlocks: ContentBlock[] = [
      {
        type: 'tool_call',
        toolCall: {
          name: 'delegate_task',
          args: {},
          server: 'sub_agent',
          status: 'progress',
          partialResult: '{"steps":["streaming"]}',
        },
      },
    ];

    const runningView = render(<InlineContentBlocks blocks={runningBlocks} />);
    // Chain is auto-expanded when tool is running - click the tool item header to show result
    const runningToolHeader = runningView.container.querySelector('.chain-item .chain-tool-header');
    expect(runningToolHeader).not.toBeNull();
    fireEvent.click(runningToolHeader as HTMLElement);
    expect(screen.getByText('sub-agent:{"steps":["streaming"]}')).toBeInTheDocument();
    runningView.unmount();

    const completeBlocks: ContentBlock[] = [
      {
        type: 'tool_call',
        toolCall: {
          name: 'delegate_task',
          args: {},
          server: 'sub_agent',
          status: 'complete',
          result: '{"steps":["done"]}',
          partialResult: '{"steps":["stale"]}',
        },
      },
    ];

    const completeView = render(<InlineContentBlocks blocks={completeBlocks} />);
    // Expand the chain first
    const chainHeader = completeView.container.querySelector('.tool-chain-header');
    expect(chainHeader).not.toBeNull();
    fireEvent.click(chainHeader as HTMLElement);
    // Then expand the tool item
    const completeToolHeader = completeView.container.querySelector('.chain-item .chain-tool-header');
    expect(completeToolHeader).not.toBeNull();
    fireEvent.click(completeToolHeader as HTMLElement);
    expect(screen.getByText('sub-agent:{"steps":["stale"]}')).toBeInTheDocument();
    expect(screen.queryByText('sub-agent:{"steps":["done"]}')).not.toBeInTheDocument();
  });

  test('renders non-sub-agent result branch with markdown rendering', () => {
    const blocks: ContentBlock[] = [
      {
        type: 'tool_call',
        toolCall: {
          name: 'search_docs',
          args: {},
          server: 'skills',
          status: 'complete',
          result: 'tool output lines',
        },
      },
    ];

    const { container } = render(<InlineContentBlocks blocks={blocks} />);

    // Expand the chain first
    const chainHeader = container.querySelector('.tool-chain-header');
    expect(chainHeader).not.toBeNull();
    fireEvent.click(chainHeader as HTMLElement);

    // Then expand the tool item to see result
    const toolHeader = container.querySelector('.chain-item .chain-tool-header');
    expect(toolHeader).not.toBeNull();
    fireEvent.click(toolHeader as HTMLElement);

    const result = container.querySelector('.chain-tool-result');
    expect(result).not.toBeNull();
    expect(result?.textContent).toContain('tool output lines');
  });
});
