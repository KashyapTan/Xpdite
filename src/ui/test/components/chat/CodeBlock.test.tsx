import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ReactNode } from 'react';
import { CodeBlock } from '../../../components/chat/CodeBlock';
import { copyToClipboard } from '../../../utils/clipboard';

vi.mock('react-syntax-highlighter', () => ({
  Prism: ({ children }: { children?: ReactNode }) => (
    <pre data-testid="syntax-highlighter">{children}</pre>
  ),
}));

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  vscDarkPlus: {},
}));

vi.mock('../../../utils/clipboard', () => ({
  copyToClipboard: vi.fn(),
}));

describe('CodeBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders inline code element when inline is true', () => {
    render(
      <CodeBlock inline className="language-ts">
        const x = 1
      </CodeBlock>,
    );

    const code = screen.getByText('const x = 1');
    expect(code.tagName.toLowerCase()).toBe('code');
    expect(screen.queryByTitle('Copy code')).not.toBeInTheDocument();
  });

  test('renders plain code when no language class is present', () => {
    render(<CodeBlock>plain text</CodeBlock>);

    expect(screen.getByText('plain text').tagName.toLowerCase()).toBe('code');
    expect(screen.queryByTestId('syntax-highlighter')).not.toBeInTheDocument();
  });

  test('renders syntax highlighter and copy button for fenced code block', () => {
    render(<CodeBlock className="language-ts">{'const value = 42;\n'}</CodeBlock>);

    expect(screen.getByTestId('syntax-highlighter')).toHaveTextContent(
      'const value = 42;',
    );
    expect(screen.getByTitle('Copy code')).toBeInTheDocument();
  });

  test('copy button sends trimmed code content to clipboard', () => {
    render(<CodeBlock className="language-ts">{'line one\nline two\n'}</CodeBlock>);

    fireEvent.click(screen.getByTitle('Copy code'));

    expect(copyToClipboard).toHaveBeenCalledTimes(1);
    expect(copyToClipboard).toHaveBeenCalledWith('line one\nline two');
  });
});
