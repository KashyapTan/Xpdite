import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { QueryInput } from '../../../components/input/QueryInput';

vi.mock('../../../services/api', () => ({
  api: {
    skillsApi: {
      getAll: vi.fn().mockResolvedValue([
        {
          name: 'Terminal',
          description: 'Run terminal commands',
          slash_command: 'terminal',
          trigger_servers: ['terminal'],
          version: '1.0.0',
          source: 'builtin',
          enabled: true,
          overridden_by_user: false,
          folder_path: '/skills/terminal',
        },
        {
          name: 'Planner',
          description: 'Plan tasks',
          slash_command: 'plan',
          trigger_servers: ['skills'],
          version: '1.0.0',
          source: 'builtin',
          enabled: true,
          overridden_by_user: false,
          folder_path: '/skills/plan',
        },
      ]),
    },
  },
}));

describe('QueryInput', () => {
  const props = {
    query: '',
    placeholder: 'Ask something',
    canSubmit: true,
    enabledModels: ['ollama/llama3', 'anthropic/claude-3-sonnet', 'openai/gpt-4'],
    onQueryChange: vi.fn(),
    onSubmit: vi.fn(),
    onStopStreaming: vi.fn(),
    onSelectModel: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('submits non-empty query on Enter', () => {
    const onSubmit = vi.fn();

    render(
      <QueryInput
        {...props}
        query="hello"
        onSubmit={onSubmit}
      />,
    );

    const textbox = screen.getByRole('textbox', { name: 'Query input' });
    fireEvent.keyDown(textbox, { key: 'Enter' });

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  test('does not submit whitespace-only query', () => {
    const onSubmit = vi.fn();

    render(
      <QueryInput
        {...props}
        query="   "
        onSubmit={onSubmit}
      />,
    );

    const textbox = screen.getByRole('textbox', { name: 'Query input' });
    fireEvent.keyDown(textbox, { key: 'Enter' });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('shows stop button when cannot submit and triggers stop callback', () => {
    const onStopStreaming = vi.fn();

    render(
      <QueryInput
        {...props}
        canSubmit={false}
        onStopStreaming={onStopStreaming}
      />,
    );

    const stopButton = screen.getByTitle('Stop generating');
    fireEvent.click(stopButton);

    expect(onStopStreaming).toHaveBeenCalledTimes(1);
  });

  test('updates query when editor input changes', () => {
    const onQueryChange = vi.fn();

    render(
      <QueryInput
        {...props}
        onQueryChange={onQueryChange}
      />,
    );

    const textbox = screen.getByRole('textbox', { name: 'Query input' });
    fireEvent.input(textbox, { target: { textContent: 'hello world' } });

    expect(onQueryChange).toHaveBeenCalledWith('hello world');
  });

  test('shows slash menu and inserts selected slash command', async () => {
    const onQueryChange = vi.fn();

    render(
      <QueryInput
        {...props}
        query="/te"
        onQueryChange={onQueryChange}
      />,
    );

    const textbox = screen.getByRole('textbox', { name: 'Query input' });
    fireEvent.focus(textbox);
    fireEvent.keyUp(textbox, { key: 'e' });

    const menuItem = await screen.findByRole('button', { name: /terminal/i });
    fireEvent.click(menuItem);

    expect(onQueryChange).toHaveBeenCalledWith('/terminal ');
  });
});
