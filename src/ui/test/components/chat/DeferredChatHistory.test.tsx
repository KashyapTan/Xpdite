import type { RefObject } from 'react';
import { describe, expect, test, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

import DeferredChatHistory from '../../../components/chat/DeferredChatHistory';
import type { ChatMessage } from '../../../types';

const { logPerfMock } = vi.hoisted(() => ({
  logPerfMock: vi.fn(),
}));

vi.mock('../../../components/chat/ChatMessage', () => ({
  ChatMessage: ({ message }: { message: ChatMessage }) => (
    <div data-testid="chat-message">{message.content}</div>
  ),
}));

vi.mock('../../../utils/pretextMessageLayout', () => ({
  estimateChatMessageHeight: vi.fn(() => 110),
}));

vi.mock('../../../utils/perfLogger', () => ({
  logPerf: logPerfMock,
}));

function createContainerRef({ width = 420, height = 620 }: { width?: number; height?: number } = {}): RefObject<HTMLDivElement> {
  const container = document.createElement('div');
  Object.defineProperty(container, 'clientWidth', {
    configurable: true,
    get: () => width,
  });
  Object.defineProperty(container, 'clientHeight', {
    configurable: true,
    get: () => height,
  });
  Object.defineProperty(container, 'scrollTop', {
    configurable: true,
    writable: true,
    value: 0,
  });

  return { current: container } as unknown as RefObject<HTMLDivElement>;
}

function buildHistory(count: number): ChatMessage[] {
  const items: ChatMessage[] = [];
  for (let index = 0; index < count; index += 1) {
    items.push({
      role: index % 2 === 0 ? 'user' : 'assistant',
      content: `message-${index + 1}`,
      messageId: `msg-${index + 1}`,
      timestamp: 1000 + index,
    });
  }
  return items;
}

function makeProps(history: ChatMessage[], containerRef: RefObject<HTMLDivElement>) {
  return {
    chatHistory: history,
    generatingModel: 'gpt-5',
    canSubmit: true,
    onRetryMessage: vi.fn(),
    onEditMessage: vi.fn(),
    onSetActiveResponse: vi.fn(),
    containerRef,
  };
}

describe('DeferredChatHistory', () => {
  test('keeps virtualization disabled below stability floor even for huge single message', async () => {
    const containerRef = createContainerRef({ height: 480 });
    const history: ChatMessage[] = [
      {
        role: 'user',
        content: 'x'.repeat(6200),
        messageId: 'huge-user',
        timestamp: 1000,
      },
      {
        role: 'assistant',
        content: 'short response',
        messageId: 'assistant-1',
        timestamp: 1001,
      },
    ];

    const { container } = render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    await waitFor(() => {
      expect(logPerfMock).toHaveBeenCalledWith(
        expect.stringContaining('event=virtualization_mode enabled=false reason=stability-row-floor'),
      );
    });

    expect(container.querySelectorAll('[data-virtual-row-index]')).toHaveLength(0);
  });

  test('uses virtualization for large content once row floor is met', async () => {
    const containerRef = createContainerRef({ height: 500 });
    const history: ChatMessage[] = Array.from({ length: 10 }, (_, index) => ({
      role: index % 2 === 0 ? 'user' : 'assistant',
      content: index === 0 ? 'x'.repeat(6200) : `message-${index + 1}`,
      messageId: `msg-${index + 1}`,
      timestamp: 1000 + index,
    }));

    const { container } = render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    await waitFor(() => {
      expect(container.querySelectorAll('[data-virtual-row-index]').length).toBeGreaterThan(0);
    });

    expect(logPerfMock).toHaveBeenCalledWith(
      expect.stringContaining('event=virtualization_mode enabled=true reason=single-message-chars-threshold'),
    );
  });

  test('renders all rows when history is below virtualization threshold', () => {
    const history = buildHistory(8);
    const containerRef = createContainerRef();

    render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    expect(screen.getAllByTestId('chat-message')).toHaveLength(8);
  });

  test('virtualizes large histories and renders fewer rows than total', async () => {
    const history = buildHistory(60);
    const containerRef = createContainerRef({ height: 500 });

    render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    await waitFor(() => {
      const rendered = screen.getAllByTestId('chat-message').length;
      expect(rendered).toBeGreaterThan(0);
      expect(rendered).toBeLessThan(history.length);
    });
  });

  test('updates rendered window when container scrolls', async () => {
    const history = buildHistory(80);
    const containerRef = createContainerRef({ height: 450 });

    render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    expect(await screen.findByText('message-1')).toBeInTheDocument();

    act(() => {
      if (containerRef.current) {
        containerRef.current.scrollTop = 7000;
        containerRef.current.dispatchEvent(new Event('scroll'));
      }
    });

    await waitFor(() => {
      expect(screen.getByText('message-80')).toBeInTheDocument();
    });
  });

  test('keeps virtualization spacers as non-shrinking flex items', async () => {
    const history = buildHistory(80);
    const containerRef = createContainerRef({ height: 450 });

    const { container } = render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    act(() => {
      if (containerRef.current) {
        containerRef.current.scrollTop = 6500;
        containerRef.current.dispatchEvent(new Event('scroll'));
      }
    });

    await waitFor(() => {
      const topSpacer = container.querySelector('[data-virtual-spacer="top"]');
      expect(topSpacer).toBeInTheDocument();
      expect(topSpacer).toHaveStyle({ flex: '0 0 auto' });
    });

    const bottomSpacer = container.querySelector('[data-virtual-spacer="bottom"]');
    if (bottomSpacer) {
      expect(bottomSpacer).toHaveStyle({ flex: '0 0 auto' });
    }

    const row = container.querySelector('[data-virtual-row-index]');
    expect(row).toHaveStyle({ flex: '0 0 auto' });
  });

  test('resets virtualization estimate cache when container width changes', async () => {
    const { estimateChatMessageHeight } = await import('../../../utils/pretextMessageLayout');
    const estimateMock = vi.mocked(estimateChatMessageHeight);

    const history = buildHistory(40);
    let width = 420;
    const containerRef = createContainerRef({ width });
    if (containerRef.current) {
      Object.defineProperty(containerRef.current, 'clientWidth', {
        configurable: true,
        get: () => width,
      });
    }

    render(<DeferredChatHistory {...makeProps(history, containerRef)} />);

    await waitFor(() => {
      expect(estimateMock).toHaveBeenCalled();
    });
    const beforeResizeCalls = estimateMock.mock.calls.length;

    act(() => {
      width = 760;
      if (containerRef.current) {
        containerRef.current.dispatchEvent(new Event('scroll'));
      }
    });

    await waitFor(() => {
      expect(estimateMock.mock.calls.length).toBeGreaterThan(beforeResizeCalls);
    });
  });
});
