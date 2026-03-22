import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { SubAgentTranscript } from '../../../components/chat/SubAgentTranscript';

describe('SubAgentTranscript', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders waiting state when no steps are available', () => {
    render(<SubAgentTranscript stepsJson={undefined} isRunning={false} />);

    expect(screen.getByText('Waiting for response...')).toBeInTheDocument();
  });

  test('renders valid JSON text and tool call blocks', () => {
    const stepsJson = JSON.stringify([
      { type: 'text', content: 'Agent says hello' },
      {
        type: 'tool_call',
        name: 'search_docs',
        args: { query: 'retry strategy' },
        status: 'complete',
        result: 'Found 3 matching docs',
      },
    ]);

    render(<SubAgentTranscript stepsJson={stepsJson} isRunning={false} />);

    expect(screen.getByText('Agent says hello')).toBeInTheDocument();
    expect(screen.getByText('search_docs')).toBeInTheDocument();
  });

  test('expands and collapses tool step details', () => {
    const stepsJson = JSON.stringify([
      {
        type: 'tool_call',
        name: 'fetch_context',
        args: { topic: 'mcp' },
        status: 'complete',
        result: 'context loaded',
      },
    ]);

    render(<SubAgentTranscript stepsJson={stepsJson} isRunning={false} />);

    expect(screen.queryByText('Arguments')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('fetch_context'));
    expect(screen.getByText('Arguments')).toBeInTheDocument();
    expect(screen.getByText('Result')).toBeInTheDocument();

    fireEvent.click(screen.getByText('fetch_context'));
    expect(screen.queryByText('Arguments')).not.toBeInTheDocument();
  });

  test('falls back to legacy plain text for invalid JSON', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    render(<SubAgentTranscript stepsJson={'legacy plain transcript text'} isRunning={false} />);

    expect(screen.getByText('legacy plain transcript text')).toBeInTheDocument();
    expect(warnSpy).toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  test('truncates long args preview and long result content', () => {
    const longArg = 'a'.repeat(700);
    const longResult = 'r'.repeat(2300);
    const stepsJson = JSON.stringify([
      {
        type: 'tool_call',
        name: 'big_payload_tool',
        args: { blob: longArg },
        status: 'complete',
        result: longResult,
      },
    ]);

    const { container } = render(<SubAgentTranscript stepsJson={stepsJson} isRunning={false} />);
    fireEvent.click(screen.getByText('big_payload_tool'));

    const preBlocks = container.querySelectorAll('pre');
    expect(preBlocks).toHaveLength(2);
    expect(preBlocks[0].textContent?.length ?? 0).toBeLessThanOrEqual(520);
    expect(preBlocks[1].textContent).toContain('...(truncated)');
  });

  test('shows running indicator while transcript is streaming', () => {
    const stepsJson = JSON.stringify([{ type: 'text', content: 'still working' }]);
    const { container } = render(<SubAgentTranscript stepsJson={stepsJson} isRunning={true} />);

    expect(container.querySelector('.chain-subagent-streaming-indicator')).toBeInTheDocument();
  });
});
