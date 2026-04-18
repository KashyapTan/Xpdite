import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import ModelCommandMenu from '../../../components/chat/ModelCommandMenu';

describe('ModelCommandMenu', () => {
  test('renders model labels, highlights the selected option, and forwards hover/select events', () => {
    const onHover = vi.fn();
    const onSelect = vi.fn();

    render(
      <ModelCommandMenu
        models={['openai/gpt-4o-mini', 'anthropic/claude-3-5-sonnet']}
        selectedIndex={1}
        onHover={onHover}
        onSelect={onSelect}
        position={{ top: 20, left: 44 }}
      />,
    );

    expect(screen.getByText('Models')).toBeInTheDocument();
    expect(screen.getByText('GPT 4o Mini')).toBeInTheDocument();
    expect(screen.getByText('OpenAI')).toBeInTheDocument();
    expect(screen.getByText('Claude 3.5 Sonnet')).toBeInTheDocument();

    const selectedButton = screen.getByRole('button', { name: /Claude 3\.5 Sonnet/i });
    expect(selectedButton.className).toContain('selected');

    fireEvent.mouseEnter(screen.getByRole('button', { name: /GPT 4o Mini/i }));
    expect(onHover).toHaveBeenCalledWith(0);

    fireEvent.click(selectedButton);
    expect(onSelect).toHaveBeenCalledWith('anthropic/claude-3-5-sonnet');
  });

  test('returns null when no models are available', () => {
    const { container } = render(
      <ModelCommandMenu
        models={[]}
        selectedIndex={0}
        onHover={vi.fn()}
        onSelect={vi.fn()}
        position={{ top: 0, left: 0 }}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
