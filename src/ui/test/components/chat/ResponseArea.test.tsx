import { createRef } from 'react';
import { describe, expect, test, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ResponseArea } from '../../../components/chat/ResponseArea';
import type { ChatMessage, ContentBlock } from '../../../types';

const { buildRenderableContentBlocksMock } = vi.hoisted(() => ({
  buildRenderableContentBlocksMock: vi.fn(
    ({ thinking, contentBlocks }: { thinking?: string; contentBlocks?: ContentBlock[] }) => {
      if (contentBlocks && contentBlocks.length > 0) {
        return contentBlocks;
      }
      if (thinking) {
        return [{ type: 'thinking', content: thinking } as ContentBlock];
      }
      return [];
    },
  ),
}));

vi.mock('../../../components/chat/DeferredChatHistory', () => ({
  default: ({ chatHistory }: { chatHistory: ChatMessage[] }) => (
    <>
      {chatHistory.map((message) => (
        <div key={message.messageId ?? message.content} data-testid="chat-message">
          {message.content}
        </div>
      ))}
    </>
  ),
}));

vi.mock('../../../components/chat/LoadingDots', () => ({
  LoadingDots: ({ isVisible }: { isVisible?: boolean }) => (
    <div data-testid="loading-dots">{String(Boolean(isVisible))}</div>
  ),
}));

vi.mock('../../../components/chat/DeferredInlineContentBlocks', () => ({
  default: ({ blocks }: { blocks: ContentBlock[] }) => (
    <div data-testid="inline-content-blocks">{blocks.length}</div>
  ),
}));

vi.mock('../../../components/chat/ChatMessage', () => ({
  ChatMessage: ({ message }: { message: ChatMessage }) => (
    <div data-testid="error-chat-message">{message.content}</div>
  ),
}));

vi.mock('../../../utils/renderableContentBlocks', () => ({
  buildRenderableContentBlocks: buildRenderableContentBlocksMock,
}));

function makeProps(overrides: Partial<React.ComponentProps<typeof ResponseArea>> = {}) {
  return {
    chatHistory: [] as ChatMessage[],
    currentQuery: '',
    thinking: '',
    isThinking: false,
    thinkingCollapsed: false,
    contentBlocks: undefined,
    generatingModel: 'gpt-5',
    canSubmit: true,
    error: '',
    errorMessage: null,
    showScrollBottom: false,
    onRetryMessage: vi.fn(),
    onEditMessage: vi.fn(),
    onSetActiveResponse: vi.fn(),
    onToggleThinking: vi.fn(),
    onScroll: vi.fn(),
    onScrollToBottom: vi.fn(),
    responseAreaRef: createRef<HTMLDivElement>(),
    scrollDownIcon: '/scroll.svg',
    onTerminalApprove: vi.fn(),
    onTerminalDeny: vi.fn(),
    onTerminalApproveRemember: vi.fn(),
    onTerminalKill: vi.fn(),
    onTerminalResize: vi.fn(),
    onYouTubeApprovalResponse: vi.fn(),
    hasTabBar: true,
    topInset: 20,
    bottomInset: 30,
    scrollButtonBottom: 14,
    ...overrides,
  };
}

describe('ResponseArea', () => {
  test('falls back to role-index key when messageId is missing', async () => {
    render(
      <ResponseArea
        {...makeProps({
          chatHistory: [{ role: 'assistant', content: 'no id' }],
        })}
      />,
    );

    expect(await screen.findByTestId('chat-message')).toHaveTextContent('no id');
  });

  test('renders error through the assistant message component and keeps history visible', async () => {
    render(
      <ResponseArea
        {...makeProps({
          error: 'Something failed',
          chatHistory: [{ role: 'user', content: 'hello' }],
        })}
      />,
    );

    expect(await screen.findByTestId('chat-message')).toHaveTextContent('hello');
    expect(screen.getByTestId('error-chat-message')).toHaveTextContent('Something failed');
  });

  test('renders chat history messages when no error', async () => {
    render(
      <ResponseArea
        {...makeProps({
          chatHistory: [
            { role: 'user', content: 'first', messageId: '1' },
            { role: 'assistant', content: 'second', messageId: '2' },
          ],
        })}
      />,
    );

    const messages = await screen.findAllByTestId('chat-message');
    expect(messages).toHaveLength(2);
    expect(messages[0]).toHaveTextContent('first');
    expect(messages[1]).toHaveTextContent('second');
  });

  test('shows current query while generating', () => {
    render(
      <ResponseArea
        {...makeProps({
          currentQuery: 'What is happening?',
          canSubmit: false,
        })}
      />,
    );

    expect(screen.getByText('What is happening?')).toBeInTheDocument();
  });

  test('keeps the current query visible when an error response is present', () => {
    render(
      <ResponseArea
        {...makeProps({
          currentQuery: 'Why did that fail?',
          canSubmit: true,
          errorMessage: {
            role: 'assistant',
            content: '**Request failed**',
            variant: 'error',
          },
        })}
      />,
    );

    expect(screen.getByText('Why did that fail?')).toBeInTheDocument();
    expect(screen.getByTestId('error-chat-message')).toHaveTextContent('Request failed');
  });

  test('does not render the current query twice when the failed turn is already in history', () => {
    render(
      <ResponseArea
        {...makeProps({
          chatHistory: [{ role: 'user', content: 'Why did that fail?', messageId: 'user-1' }],
          currentQuery: 'Why did that fail?',
          canSubmit: true,
          errorMessage: {
            role: 'assistant',
            content: '**Request failed**',
            variant: 'error',
          },
        })}
      />,
    );

    expect(screen.getAllByText('Why did that fail?')).toHaveLength(1);
    expect(screen.getByTestId('error-chat-message')).toHaveTextContent('Request failed');
  });

  test('renders inline content blocks and assistant header when blocks exist', async () => {
    render(
      <ResponseArea
        {...makeProps({
          contentBlocks: [{ type: 'text', content: 'hello' }],
          generatingModel: 'claude-sonnet',
        })}
      />,
    );

    expect(screen.getByText('Xpdite • claude-sonnet')).toBeInTheDocument();
    expect(await screen.findByTestId('inline-content-blocks')).toHaveTextContent('1');
  });

  test('passes expandable thinking controls when there is only a single thinking block', async () => {
    buildRenderableContentBlocksMock.mockReturnValueOnce([
      { type: 'thinking', content: 'Thinking...' },
    ]);
    const onToggleThinking = vi.fn();
    render(<ResponseArea {...makeProps({ onToggleThinking })} />);

    expect(await screen.findByTestId('inline-content-blocks')).toHaveTextContent('1');
  });

  test('does not pass thinking toggle for mixed content timelines', async () => {
    buildRenderableContentBlocksMock.mockReturnValueOnce([
      { type: 'thinking', content: 'Thinking...' },
      { type: 'text', content: 'Answer' },
    ]);
    render(<ResponseArea {...makeProps()} />);

    expect(await screen.findByTestId('inline-content-blocks')).toHaveTextContent('2');
  });

  test('renders scroll-to-bottom button and triggers callback', () => {
    const onScrollToBottom = vi.fn();
    render(
      <ResponseArea
        {...makeProps({
          showScrollBottom: true,
          onScrollToBottom,
          scrollButtonBottom: 66,
        })}
      />,
    );

    const button = screen.getByTitle('Scroll to bottom');
    expect(button).toBeInTheDocument();
    expect(button).toHaveStyle({ bottom: '66px' });
    fireEvent.click(button);
    expect(onScrollToBottom).toHaveBeenCalledTimes(1);
  });

  test('applies response area style from insets and tab visibility', () => {
    const { container } = render(
      <ResponseArea
        {...makeProps({
          hasTabBar: false,
          topInset: 24,
          bottomInset: 40,
        })}
      />,
    );

    const responseArea = container.querySelector('.response-area');
    expect(responseArea).toHaveStyle({
      marginTop: '24px',
      marginBottom: '40px',
      height: 'calc(100% - 64px)',
    });
  });
});
