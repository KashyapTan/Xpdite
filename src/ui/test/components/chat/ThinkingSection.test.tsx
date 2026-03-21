import { describe, expect, test, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThinkingSection } from '../../../components/chat/ThinkingSection';

vi.mock('react-markdown', () => ({
  default: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="markdown">{children}</div>
  ),
}));

vi.mock('../../../components/chat/LoadingDots', () => ({
  LoadingDots: () => <div data-testid="loading-dots">loading</div>,
}));

describe('ThinkingSection', () => {
  test('returns null when thinking text is empty', () => {
    const { container } = render(
      <ThinkingSection
        thinking=""
        isThinking={false}
        collapsed={false}
        onToggle={() => {}}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  test('renders thought process label when not actively thinking', () => {
    render(
      <ThinkingSection
        thinking="Reasoning output"
        isThinking={false}
        collapsed={false}
        onToggle={() => {}}
      />,
    );

    expect(screen.getByText('Thought process')).toBeInTheDocument();
    expect(screen.queryByTestId('loading-dots')).not.toBeInTheDocument();
  });

  test('renders thinking label and loading dots while thinking', () => {
    render(
      <ThinkingSection
        thinking="Reasoning output"
        isThinking={true}
        collapsed={false}
        onToggle={() => {}}
      />,
    );

    expect(screen.getByText('Thinking...')).toBeInTheDocument();
    expect(screen.getByTestId('loading-dots')).toBeInTheDocument();
  });

  test('toggles content visibility based on collapsed state', () => {
    const { rerender } = render(
      <ThinkingSection
        thinking="Visible markdown"
        isThinking={false}
        collapsed={false}
        onToggle={() => {}}
      />,
    );

    expect(screen.getByTestId('markdown')).toHaveTextContent('Visible markdown');

    rerender(
      <ThinkingSection
        thinking="Visible markdown"
        isThinking={false}
        collapsed={true}
        onToggle={() => {}}
      />,
    );

    expect(screen.queryByTestId('markdown')).not.toBeInTheDocument();
  });

  test('calls onToggle when header is clicked', () => {
    const onToggle = vi.fn();
    const { container } = render(
      <ThinkingSection
        thinking="Reasoning"
        isThinking={false}
        collapsed={true}
        onToggle={onToggle}
      />,
    );

    const header = container.querySelector('.thinking-header');
    expect(header).toBeTruthy();
    fireEvent.click(header!);

    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
