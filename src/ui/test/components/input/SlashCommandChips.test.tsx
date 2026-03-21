import { describe, expect, test, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SlashCommandChips from '../../../components/input/SlashCommandChips';

describe('SlashCommandChips', () => {
  test('returns null when query has no slash commands', () => {
    const { container } = render(
      <SlashCommandChips query="hello world" onRemoveCommand={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  test('renders unique command chips from query', () => {
    render(
      <SlashCommandChips
        query="run /terminal then /fs and /terminal again"
        onRemoveCommand={() => {}}
      />,
    );

    expect(screen.getByText('/terminal')).toBeInTheDocument();
    expect(screen.getByText('/fs')).toBeInTheDocument();
    expect(screen.getAllByText('/terminal')).toHaveLength(1);
  });

  test('calls onRemoveCommand with selected command when remove is clicked', () => {
    const onRemove = vi.fn();
    render(
      <SlashCommandChips query="/terminal /fs" onRemoveCommand={onRemove} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Remove /terminal' }));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith('/terminal');
  });
});
