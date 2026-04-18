import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import DeferredInlineContentBlocks from '../../../components/chat/DeferredInlineContentBlocks';

const inlineContentBlocksMock = vi.fn(() => <div data-testid="inline-content-blocks">inline blocks</div>);

vi.mock('../../../components/chat/ToolCallsDisplay', () => ({
  InlineContentBlocks: (props: unknown) => inlineContentBlocksMock(props),
}));

describe('DeferredInlineContentBlocks', () => {
  test('forwards props directly to InlineContentBlocks', () => {
    const onToggleExpanded = vi.fn();

    render(
      <DeferredInlineContentBlocks
        blocks={[{ type: 'text', content: 'Hello world' }]}
        isThinking
        isStreaming
        expanded
        onToggleExpanded={onToggleExpanded}
      />,
    );

    expect(screen.getByTestId('inline-content-blocks')).toBeInTheDocument();
    expect(inlineContentBlocksMock).toHaveBeenCalledWith(expect.objectContaining({
      blocks: [{ type: 'text', content: 'Hello world' }],
      isThinking: true,
      isStreaming: true,
      expanded: true,
      onToggleExpanded,
    }));
  });
});
