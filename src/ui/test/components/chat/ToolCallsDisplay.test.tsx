import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

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

    expect(screen.getByText('Running terminal command')).toBeInTheDocument();
    expect(container.textContent).toContain('terminal:pwd');
    expect(container.textContent).toContain('youtube:Video Title');
  });

  test('renders thinking token blocks and expandable markdown content', () => {
    const blocks: ContentBlock[] = [{ type: 'thinking', content: 'I should check `tool` output.' }];
    render(<InlineContentBlocks blocks={blocks} isThinking={false} expanded={true} />);

    const thoughtHeader = document.querySelector('.chain-thought-label');
    expect(thoughtHeader).not.toBeNull();
    expect(screen.queryByText('I should check')).not.toBeInTheDocument();

    fireEvent.click(thoughtHeader as HTMLElement);
    const thoughtContent = document.querySelector('.chain-thought-content');
    expect(thoughtContent).not.toBeNull();
    expect(thoughtContent).toHaveTextContent('I should check tool output.');
  });

  test('renders preamble text inside timeline and trailing text after chain', () => {
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

    const { container } = render(<InlineContentBlocks blocks={blocks} expanded={true} />);

    const timeline = container.querySelector('.tool-chain-timeline');
    expect(timeline).not.toBeNull();
    expect(within(timeline as HTMLElement).getByText('Preamble before tool call')).toBeInTheDocument();
    expect(screen.getByText('Final answer after tools')).toBeInTheDocument();
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

    const runningView = render(<InlineContentBlocks blocks={runningBlocks} expanded={true} />);
    fireEvent.click(runningView.container.querySelector('.chain-tool-header') as HTMLElement);
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

    const completeView = render(<InlineContentBlocks blocks={completeBlocks} expanded={true} />);
    fireEvent.click(completeView.container.querySelector('.chain-tool-header') as HTMLElement);
    expect(screen.getByText('sub-agent:{"steps":["done"]}')).toBeInTheDocument();
    expect(screen.queryByText('sub-agent:{"steps":["stale"]}')).not.toBeInTheDocument();
  });

  test('renders non-sub-agent result branch in preformatted block', () => {
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

    const { container } = render(<InlineContentBlocks blocks={blocks} expanded={true} />);
    fireEvent.click(container.querySelector('.chain-tool-header') as HTMLElement);

    const pre = container.querySelector('pre.chain-tool-result');
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toBe('tool output lines');
  });
});
